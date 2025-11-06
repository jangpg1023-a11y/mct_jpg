import asyncio, websockets, json, pyupbit, requests, os, time
from datetime import datetime, timezone
from collections import OrderedDict
from keep_alive import keep_alive

# ──────────────── 기본 설정 ────────────────
keep_alive()
BOT_TOKEN = os.environ['BOT_TOKEN']
CHAT_ID = os.environ['CHAT_ID']
TELEGRAM_URL = f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage'

price_queue = asyncio.Queue()
alert_cache = {}
ohlcv_cache = OrderedDict()
summary_log = {0: [], 1: [], 2: []}
watchlist = []

MAX_CACHE_SIZE = 300
TTL_SECONDS = 10800  # 3시간

# ──────────────── 가격 포맷 ────────────────
def format_price(price):
    if price >= 2_000_000:
        return f"{price:,.0f}"
    elif price >= 1_000_000:
        return f"{price:,.0f}"
    elif price >= 500_000:
        return f"{price:,.0f}"
    elif price >= 100_000:
        return f"{price:,.0f}"
    elif price >= 10_000:
        return f"{price:,.0f}"
    elif price >= 1_000:
        return f"{price:,.0f}"
    elif price >= 100:
        return f"{price:,.0f}"
    elif price >= 10:
        return f"{price:,.1f}"
    elif price >= 1:
        return f"{price:,.2f}"
    elif price >= 0.1:
        return f"{price:,.3f}"
    elif price >= 0.01:
        return f"{price:,.4f}"
    else:
        return f"{price:,.5f}"


# ──────────────── 전체 KRW 종목 불러오기 ────────────────
def get_all_krw_tickers():
    return pyupbit.get_tickers(fiat="KRW")

# ──────────────── 텔레그램 메시지 ────────────────
def send_message(text):
    try:
        requests.post(TELEGRAM_URL, data={'chat_id': CHAT_ID, 'text': text})
    except Exception as e:
        print(f"[텔레그램 오류] {e}")

# ──────────────── 웹소켓 가격 수신 ────────────────
async def run_ws(watchlist):
    uri = "wss://api.upbit.com/websocket/v1"
    while True:
        try:
            async with websockets.connect(uri) as ws:
                sub = [{"ticket": "test"}, {"type": "ticker", "codes": watchlist}]
                await ws.send(json.dumps(sub))
                while True:
                    msg = json.loads(await ws.recv())
                    await price_queue.put((msg['code'], msg['trade_price']))
        except Exception as e:
            print(f"[웹소켓 오류] {e}")
            await asyncio.sleep(5)

# ──────────────── OHLCV 캐시 저장 ────────────────
def set_ohlcv_cache(ticker, df, weekly):
    now = time.time()

    expired_keys = [k for k, v in ohlcv_cache.items() if now - v['time'] > TTL_SECONDS]
    for k in expired_keys:
        del ohlcv_cache[k]

    while len(ohlcv_cache) >= MAX_CACHE_SIZE:
        ohlcv_cache.popitem(last=False)

    ohlcv_cache[ticker] = {
        'df': df,
        'weekly': weekly,
        'time': now
    }

# ──────────────── OHLCV 캐시 조회 ────────────────
def get_ohlcv_cached(ticker):
    now = time.time()

    if ticker in ohlcv_cache and now - ohlcv_cache[ticker]['time'] < TTL_SECONDS:
        return ohlcv_cache[ticker]['df'], ohlcv_cache[ticker]['weekly']

    try:
        df = pyupbit.get_ohlcv(ticker, interval="day", count=130)
        weekly = pyupbit.get_ohlcv(ticker, interval="week", count=3)
        set_ohlcv_cache(ticker, df, weekly)
        return df, weekly
    except:
        return None, None

# ──────────────── 기술 지표 계산 ────────────────
def calculate_indicators(df):
    close = df['close']
    df['MA7'] = close.rolling(7).mean()
    df['MA120'] = close.rolling(120).mean()
    df['STD120'] = close.rolling(120).std()
    df['BBU'] = df['MA120'] + 2 * df['STD120']
    df['BBD'] = df['MA120'] - 2 * df['STD120']
    return df

# ──────────────── 알림 중복 방지 ────────────────
def should_alert(key, cooldown=10800):
    last_time = alert_cache.get(key)
    if last_time and time.time() - last_time < cooldown:
        return False
    alert_cache[key] = time.time()
    return True

def cleanup_alert_cache():
    now = time.time()
    expired_keys = [k for k, t in alert_cache.items() if now - t > 10800]
    for k in expired_keys:
        del alert_cache[k]

# ──────────────── 요약 기록 ────────────────
def record_summary(day_index, ticker, condition_text, change_str):
    if day_index in summary_log:
        summary_log[day_index].append(f"{ticker} | {condition_text} | {change_str}")

# ──────────────── 조건 검사 ────────────────
def check_conditions(ticker, price, day_indexes=[0]):
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

        key = f"{ticker}_D{i}_{datetime.now().date()}_"

        if is_weekly_bullish and pc < bbdp and pc < ma7p and cc > bbdc and cc > ma7c:
            if i == 0 and should_alert(key + "bbd_ma7"):
                send_message(f"📉 BBD + MA7 (D-{i})\n{ticker} | 현재가: {format_price(price)} {change_str}")
            record_summary(i, ticker, "BBD", change_str)

        if pc < ma120p and pc < ma7p and cc > ma120c and cc > ma7c:
            if i == 0 and should_alert(key + "ma120_ma7"):
                send_message(f"➖ MA120 + MA7 (D-{i})\n{ticker} | 현재가: {format_price(price)} {change_str}")
            record_summary(i, ticker, "MA", change_str)

        if pc < bbup and cc > bbuc:
            if i == 0 and should_alert(key + "bollinger_upper"):
                send_message(f"📈 BBU 상단 (D-{i})\n{ticker} | 현재가: {format_price(price)} {change_str}")
            record_summary(i, ticker, "BBU", change_str)

# ──────────────── 실시간 가격 처리 ────────────────
async def process_queue():
    while True:
        while not price_queue.empty():
            ticker, price = await price_queue.get()
            check_conditions(ticker, price, day_indexes=[0])
        await asyncio.sleep(2)

# ──────────────── 과거 조건 분석 ────────────────
async def analyze_past_conditions():
    summary_log[1] = []
    summary_log[2] = []
    for ticker in watchlist:
        price = pyupbit.get_current_price(ticker) or 0
        check_conditions(ticker, price, day_indexes=[1, 2])
        await asyncio.sleep(0.5)

# ──────────────── 요약 메시지 전송 ────────────────
def send_past_summary():
    emoji_map = {"BBD": "📉", "MA": "➖", "BBU": "📈"}
    day_labels = {
        0: "🔥 D-0 ━━",
        1: "⏳ D-1 ━━",
        2: "⌛ D-2 ━━"
    }

    msg = f"📊 Summary (UTC {datetime.now(timezone.utc).strftime('%m/%d %H:%M')})\n\n"

    for i in [0, 1, 2]:
        entries = summary_log.get(i, [])
        msg += f"{day_labels[i]}\n"

        grouped = {"BBD": {}, "MA": {}, "BBU": {}}
        for entry in entries:
            parts = entry.split(" | ")
            if len(parts) == 3:
                symbol, condition, change = parts
                symbol = symbol.replace("KRW-", "")
                if condition in grouped:
                    grouped[condition][symbol] = change

        for condition in ["BBD", "MA", "BBU"]:
            symbols = grouped[condition]
            if symbols:
                line = f"      {emoji_map[condition]} {condition}:\n" + "\n".join(
                    f"        {s} {symbols[s]}" for s in symbols
                )
                msg += line + "\n"

        msg += "\n"

    send_message(msg.strip())
    cleanup_alert_cache()

# ──────────────── 요약 루프 (3시간마다) ────────────────
async def daily_summary_loop():
    while True:
        await analyze_past_conditions()
        send_past_summary()
        await asyncio.sleep(60 * 60 * 3)

# ──────────────── 메인 루프 ────────────────
async def main():
    global watchlist
    watchlist = get_all_krw_tickers()
    send_message("📡 종목 감시 시작")

    asyncio.create_task(run_ws(watchlist))         # D-0 실시간 감시
    asyncio.create_task(process_queue())           # D-0 조건 평가
    asyncio.create_task(daily_summary_loop())      # D-1, D-2 분석 및 요약

    while True:
        await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(main())





