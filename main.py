import asyncio, websockets, json, pyupbit, requests, os, time
from datetime import datetime, timezone
from keep_alive import keep_alive

# ──────────────── 설정 ────────────────
keep_alive()
BOT_TOKEN = os.environ['BOT_TOKEN']
CHAT_ID = os.environ['CHAT_ID']
TELEGRAM_URL = f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage'

price_queue = asyncio.Queue()
alert_cache = {}
ohlcv_cache = {}
summary_log = {0: [], 1: [], 2: []}
btc_tracker = {"price": None, "open": None}

# ──────────────── 유틸 함수 ────────────────
def format_price(price):
    if price >= 100_000: return f"{price:,.0f}"
    elif price >= 10_000: return f"{price:,.1f}"
    elif price >= 1_000: return f"{price:,.2f}"
    elif price >= 10: return f"{price:,.3f}"
    else: return f"{price:,.4f}"

def send_message(text):
    try:
        requests.post(TELEGRAM_URL, data={'chat_id': CHAT_ID, 'text': text})
    except Exception as e:
        print(f"[텔레그램 오류] {e}")

def should_alert(key, cooldown=300):
    last_time = alert_cache.get(key)
    if last_time and time.time() - last_time < cooldown:
        return False
    alert_cache[key] = time.time()
    return True

def record_summary(day_index, ticker, condition_key, change_str):
    if day_index in summary_log:
        symbol = ticker.replace("KRW-", "")
        change = change_str.replace("(", "").replace(")", "")
        summary_log[day_index].append(f"{symbol} | {condition_key} | {change}")

def get_all_krw_tickers():
    return pyupbit.get_tickers(fiat="KRW")

def get_ohlcv_cached(ticker):
    now = time.time()
    if ticker in ohlcv_cache and now - ohlcv_cache[ticker]['time'] < 1800:
        return ohlcv_cache[ticker]['df'], ohlcv_cache[ticker]['weekly']
    try:
        df = pyupbit.get_ohlcv(ticker, interval="day", count=130)
        weekly = pyupbit.get_ohlcv(ticker, interval="week", count=3)
        ohlcv_cache[ticker] = {'df': df, 'weekly': weekly, 'time': now}
        return df, weekly
    except:
        return None, None

def calculate_indicators(df):
    close = df['close']
    df['MA7'] = close.rolling(7).mean()
    df['MA120'] = close.rolling(120).mean()
    df['STD120'] = close.rolling(120).std()
    df['BBU'] = df['MA120'] + 2 * df['STD120']
    df['BBD'] = df['MA120'] - 2 * df['STD120']
    return df

def is_bbd_condition(df, weekly, pc, cc):
    bbdp, bbdc = df['BBD'].iloc[-2], df['BBD'].iloc[-1]
    ma7p, ma7c = df['MA7'].iloc[-2], df['MA7'].iloc[-1]
    is_weekly_bullish = weekly['close'].iloc[-2] > weekly['open'].iloc[-2] or cc > weekly['close'].iloc[-2]
    return is_weekly_bullish and pc < bbdp and pc < ma7p and cc > bbdc and cc > ma7c

def is_ma_condition(df, pc, cc):
    ma120p, ma120c = df['MA120'].iloc[-2], df['MA120'].iloc[-1]
    ma7p, ma7c = df['MA7'].iloc[-2], df['MA7'].iloc[-1]
    return pc < ma120p and pc < ma7p and cc > ma120c and cc > ma7c

def is_bbu_condition(df, pc, cc):
    bbup, bbuc = df['BBU'].iloc[-2], df['BBU'].iloc[-1]
    return pc < bbup and cc > bbuc

async def run_ws():
    uri = "wss://api.upbit.com/websocket/v1"
    tickers = get_all_krw_tickers()
    subscribe_data = [{"ticket": "summary"}, {"type": "ticker", "codes": tickers}]

    while True:
        try:
            async with websockets.connect(uri) as websocket:
                await websocket.send(json.dumps(subscribe_data))
                while True:
                    data = await websocket.recv()
                    parsed = json.loads(data)
                    ticker = parsed['code']
                    price = parsed['trade_price']
                    await price_queue.put((ticker, price))

                    if ticker == "KRW-BTC":
                        btc_tracker["price"] = price
        except Exception as e:
            print(f"[웹소켓 오류] {e}")
            await asyncio.sleep(5)

def check_conditions_realtime(ticker, price):
    df, weekly = get_ohlcv_cached(ticker)
    if df is None or weekly is None or len(df) < 125: return
    df = calculate_indicators(df)

    pc, cc = df['close'].iloc[-2], df['close'].iloc[-1]
    open_price = df['open'].iloc[-1]
    change_str = f"{((price - open_price) / open_price) * 100:+.2f}%" if open_price else "N/A"
    formatted_price = format_price(price)
    link = f"https://upbit.com/exchange?code=CRIX.UPBIT.{ticker}"
    key = f"{ticker}_D0_{datetime.now().date()}_"

    if is_bbd_condition(df, weekly, pc, cc):
        if should_alert(key + "bbd_ma7"):
            send_message(f"📉 BBD 조건 (D-0)\n{ticker} | 현재가: {formatted_price} {change_str}\n{link}")
        record_summary(0, ticker, "BBD 조건", change_str)

    if is_ma_condition(df, pc, cc):
        if should_alert(key + "ma120_ma7"):
            send_message(f"➖ MA 조건 (D-0)\n{ticker} | 현재가: {formatted_price} {change_str}\n{link}")
        record_summary(0, ticker, "MA 조건", change_str)

    if is_bbu_condition(df, pc, cc):
        if should_alert(key + "bollinger_upper"):
            send_message(f"📈 BBU 조건 (D-0)\n{ticker} | 현재가: {formatted_price} {change_str}\n{link}")
        record_summary(0, ticker, "BBU 조건", change_str)

def get_btc_summary():
    price = btc_tracker.get("price")
    open_price = btc_tracker.get("open")
    if price and open_price:
        change = ((price - open_price) / open_price) * 100
        direction = "상승" if change > 0 else "하락"
        return (
            "🕒 비트코인 동향\n"
            f"   - 현재가: {format_price(price)} KRW\n"
            f"   - 변동폭: {change:+.2f}% {direction}\n\n"
        )
    return ""  # 정보 없을 경우 생략

def send_past_summary():
    msg = f"📊 Summary (UTC {datetime.now(timezone.utc).strftime('%m/%d %H:%M')})\n\n"
    msg += get_btc_summary()

    emoji_map = {
        "BBD 조건": "📉",
        "MA 조건": "➖",
        "BBU 조건": "📈"
    }
    indent = " " * 3

    for day in [0, 1, 2]:
        msg += f"D-{day}\n"
        entries = summary_log[day]
        if not entries:
            msg += "\n"
            continue

        grouped = {}
        for entry in entries:
            parts = entry.split(" | ")
            if len(parts) != 3:
                continue
            symbol, condition, change = parts
            grouped.setdefault(condition, []).append(f"{symbol:<7} {change}")

        for condition, items in grouped.items():
            emoji = emoji_map.get(condition, "🔔")
            msg += f"{indent}{emoji} {condition}\n"
            for item in dict.fromkeys(items):
                msg += f"{indent}{item}\n"
            msg += "\n"

    send_message(msg.strip())

def check_conditions_historical(ticker, price, day_indexes=[1, 2]):
    df, weekly = get_ohlcv_cached(ticker)
    if df is None or weekly is None or len(df) < 125: return
    df = calculate_indicators(df)
    pc, cc = df['close'].iloc[-2], df['close'].iloc[-1]

    for i in day_indexes:
        if is_bbd_condition(df, weekly, pc, cc):
            record_summary(i, ticker, "BBD 조건", f"{((price - df['open'].iloc[-1]) / df['open'].iloc[-1]) * 100:+.2f}%")
        if is_ma_condition(df, pc, cc):
            record_summary(i, ticker, "MA 조건", f"{((price - df['open'].iloc[-1]) / df['open'].iloc[-1]) * 100:+.2f}%")
        if is_bbu_condition(df, pc, cc):
            record_summary(i, ticker, "BBU 조건", f"{((price - df['open'].iloc[-1]) / df['open'].iloc[-1]) * 100:+.2f}%")

async def analyze_historical_conditions():
    tickers = get_all_krw_tickers()
    for ticker in tickers:
        df, weekly = get_ohlcv_cached(ticker)
        if df is None or weekly is None or len(df) < 125:
            continue
        df = calculate_indicators(df)
        pc, cc = df['close'].iloc[-2], df['close'].iloc[-1]
        price = cc
        check_conditions_historical(ticker, price)

        # 비트코인 시가 보완
        if ticker == "KRW-BTC":
            btc_tracker["open"] = df['open'].iloc[-1]

async def price_consumer():
    while True:
        ticker, price = await price_queue.get()
        check_conditions_realtime(ticker, price)

async def daily_summary_loop():
    while True:
        await analyze_historical_conditions()
        send_past_summary()
        await asyncio.sleep(60 * 60 * 3)  # 3시간 대기

async def main():
    send_message("📢 알림 시스템 시작 💰")  # 시작 메시지 전송
    await asyncio.gather(
        run_ws(),              # 웹소켓 실시간 가격 수신
        price_consumer(),      # 가격 큐 소비 및 조건 검사
        daily_summary_loop()   # 요약 메시지 루프
    )

if __name__ == "__main__":
    asyncio.run(main())
