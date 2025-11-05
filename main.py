import asyncio, websockets, json, pyupbit, requests, os, time
from datetime import datetime
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
watchlist = []

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

# ──────────────── 종목 및 데이터 ────────────────
def get_all_krw_tickers():
    return pyupbit.get_tickers(fiat="KRW")

def get_ohlcv_cached(ticker):
    now = time.time()
    if ticker in ohlcv_cache and now - ohlcv_cache[ticker]['time'] < 60:
        return ohlcv_cache[ticker]['df'], ohlcv_cache[ticker]['weekly']
    try:
        df = pyupbit.get_ohlcv(ticker, interval="day", count=130)
        weekly = pyupbit.get_ohlcv(ticker, interval="week", count=3)
        ohlcv_cache[ticker] = {'df': df, 'weekly': weekly, 'time': now}
        return df, weekly
    except:
        return None, None

def cleanup_cache():
    now = time.time()
    for k in list(ohlcv_cache.keys()):
        if now - ohlcv_cache[k]['time'] > 600:
            del ohlcv_cache[k]

def calculate_indicators(df):
    close = df['close']
    df['MA7'] = close.rolling(7).mean()
    df['MA120'] = close.rolling(120).mean()
    df['STD120'] = close.rolling(120).std()
    df['BBU'] = df['MA120'] + 2 * df['STD120']
    df['BBD'] = df['MA120'] - 2 * df['STD120']
    return df

def check_conditions_realtime(ticker, price):
    df, weekly = get_ohlcv_cached(ticker)
    if df is None or weekly is None or len(df) < 125: return
    df = calculate_indicators(df)

    open_price = df['open'].iloc[-1]
    change_str = f"{((price - open_price) / open_price) * 100:+.2f}%" if open_price else "N/A"
    formatted_price = format_price(price)
    link = f"https://upbit.com/exchange?code=CRIX.UPBIT.{ticker}"
    is_weekly_bullish = weekly['close'].iloc[-2] > weekly['open'].iloc[-2] or price > weekly['close'].iloc[-2]

    try:
        pc, cc = df['close'].iloc[-2], df['close'].iloc[-1]
        ma7p, ma7c = df['MA7'].iloc[-2], df['MA7'].iloc[-1]
        ma120p, ma120c = df['MA120'].iloc[-2], df['MA120'].iloc[-1]
        bbdp, bbdc = df['BBD'].iloc[-2], df['BBD'].iloc[-1]
        bbup, bbuc = df['BBU'].iloc[-2], df['BBU'].iloc[-1]
    except: return

    key = f"{ticker}_D0_{datetime.now().date()}_"

    if is_weekly_bullish and pc < bbdp and pc < ma7p and cc > bbdc and cc > ma7c:
        if should_alert(key + "bbd_ma7"):
            send_message(f"📉 BBD 조건 (D-0)\n{ticker} | 현재가: {formatted_price} {change_str}\n{link}")
        record_summary(0, ticker, "BBD 조건", change_str)

    if pc < ma120p and pc < ma7p and cc > ma120c and cc > ma7c:
        if should_alert(key + "ma120_ma7"):
            send_message(f"➖ MA 조건 (D-0)\n{ticker} | 현재가: {formatted_price} {change_str}\n{link}")
        record_summary(0, ticker, "MA 조건", change_str)

    if pc < bbup and cc > bbuc:
        if should_alert(key + "bollinger_upper"):
            send_message(f"📈 BBU 조건 (D-0)\n{ticker} | 현재가: {formatted_price} {change_str}\n{link}")
        record_summary(0, ticker, "BBU 조건", change_str)

def check_conditions_historical(ticker, price, day_indexes=[1, 2]):
    df, weekly = get_ohlcv_cached(ticker)
    if df is None or weekly is None or len(df) < 125: return
    df = calculate_indicators(df)

    open_price = df['open'].iloc[-1]
    change_str = f"{((price - open_price) / open_price) * 100:+.2f}%" if open_price else "N/A"
    is_weekly_bullish = weekly['close'].iloc[-2] > weekly['open'].iloc[-2] or price > weekly['close'].iloc[-2]

    for i in day_indexes:
        try:
            idx, prev = -1 - i, -2 - i
            pc, cc = df['close'].iloc[prev], df['close'].iloc[idx]
            ma7p, ma7c = df['MA7'].iloc[prev], df['MA7'].iloc[idx]
            ma120p, ma120c = df['MA120'].iloc[prev], df['MA120'].iloc[idx]
            bbdp, bbdc = df['BBD'].iloc[prev], df['BBD'].iloc[idx]
            bbup, bbuc = df['BBU'].iloc[prev], df['BBU'].iloc[idx]
        except: continue

        if is_weekly_bullish and pc < bbdp and pc < ma7p and cc > bbdc and cc > ma7c:
            record_summary(i, ticker, "BBD 조건", change_str)

        if pc < ma120p and pc < ma7p and cc > ma120c and cc > ma7c:
            record_summary(i, ticker, "MA 조건", change_str)

        if pc < bbup and cc > bbuc:
            record_summary(i, ticker, "BBU 조건", change_str)

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
        except Exception as e:
            print(f"[웹소켓 오류] 재연결 시도 중... {e}")
            await asyncio.sleep(5)

# 실시간 가격 처리 루프
async def process_realtime():
    while True:
        if not price_queue.empty():
            ticker, price = await price_queue.get()
            check_conditions_realtime(ticker, price)
        await asyncio.sleep(0.5)

# 과거 조건 분석 루프 (D-1, D-2)
async def analyze_historical_conditions():
    summary_log[1] = []
    summary_log[2] = []
    for ticker in watchlist:
        price = pyupbit.get_current_price(ticker) or 0
        check_conditions_historical(ticker, price)
        await asyncio.sleep(0.2)

# 요약 메시지 전송
def send_past_summary():
    msg = f"📊 Summary (UTC {datetime.utcnow().strftime('%m/%d %H:%M')})\n\n"
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
            grouped.setdefault(condition, []).append(f"{symbol} | {change}")

        for condition, items in grouped.items():
            emoji = emoji_map.get(condition, "🔔")
            msg += f"{emoji} {condition}\n"
            for item in dict.fromkeys(items):  # 중복 제거
                msg += f"{indent}{item}\n"
            msg += "\n"

    send_message(msg.strip())

# 3시간마다 과거 조건 분석 및 요약 전송
async def daily_summary_loop():
    while True:
        await analyze_historical_conditions()
        send_past_summary()
        await asyncio.sleep(60 * 60 * 3)

# 캐시 정리 루프
async def cleanup_loop():
    while True:
        cleanup_cache()
        await asyncio.sleep(300)

# 메인 실행 함수
async def main():
    global watchlist
    watchlist = get_all_krw_tickers()
    send_message("📡 실시간 감시 시작")

    # 병렬 작업 실행
    asyncio.create_task(run_ws())
    asyncio.create_task(process_realtime())
    asyncio.create_task(daily_summary_loop())
    asyncio.create_task(cleanup_loop())

    # 시작 시 과거 분석 및 요약 전송
    await analyze_historical_conditions()
    send_past_summary()

    # 메인 루프 유지
    while True:
        await asyncio.sleep(60)

# 실행 시작
if __name__ == "__main__":
    asyncio.run(main())
