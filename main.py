import asyncio, websockets, json, pyupbit, requests, os, time
from datetime import datetime
from keep_alive import keep_alive

# ──────────────── 기본 설정 ────────────────
keep_alive()
BOT_TOKEN = os.environ['BOT_TOKEN']
CHAT_ID = os.environ['CHAT_ID']
TELEGRAM_URL = f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage'

price_queue = asyncio.Queue()
alert_cache = {}
ohlcv_cache = {}
summary_log = {0: [], 1: [], 2: []}
watchlist = []

# ──────────────── 가격 포맷 ────────────────
def format_price(price):
    if price >= 100_000:
        return f"{price:,.0f}"
    elif price >= 10_000:
        return f"{price:,.1f}"
    elif price >= 1_000:
        return f"{price:,.2f}"
    elif price >= 10:
        return f"{price:,.3f}"
    else:
        return f"{price:,.4f}"

# ──────────────── 1원 이상 KRW 종목 필터링 ────────────────
def get_filtered_krw_tickers(min_price=1):
    all_tickers = pyupbit.get_tickers(fiat="KRW")
    filtered = []
    for ticker in all_tickers:
        price = pyupbit.get_current_price(ticker)
        if price and price >= min_price:
            filtered.append(ticker)
        time.sleep(0.05)
    return filtered

# ──────────────── 텔레그램 메시지 ────────────────
def send_message(text):
    try:
        requests.post(TELEGRAM_URL, data={'chat_id': CHAT_ID, 'text': text})
    except Exception as e:
        print(f"[텔레그램 오류] {e}")

# ──────────────── 웹소켓 가격 수신 ────────────────
async def run_ws():
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

# ──────────────── OHLCV 캐시 ────────────────
def get_ohlcv_cached(ticker):
    if ticker in ohlcv_cache and time.time() - ohlcv_cache[ticker]['time'] < 60:
        return ohlcv_cache[ticker]['df'], ohlcv_cache[ticker]['weekly']
    try:
        df = pyupbit.get_ohlcv(ticker, interval="day", count=130)
        weekly = pyupbit.get_ohlcv(ticker, interval="week", count=3)
        ohlcv_cache[ticker] = {'df': df, 'weekly': weekly, 'time': time.time()}
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
def should_alert(key, cooldown=1800):
    last_time = alert_cache.get(key)
    if last_time and time.time() - last_time < cooldown:
        return False
    alert_cache[key] = time.time()
    return True

# ──────────────── 요약 기록 ────────────────
def record_summary(day_index, ticker, condition_text, change_str):
    if day_index in summary_log:
        summary_log[day_index].append(f"{ticker} | {condition_text} {change_str}")

# ──────────────── 실시간 가격 처리 ────────────────
async def process_realtime():
    while True:
        if not price_queue.empty():
            ticker, price = await price_queue.get()
            check_conditions_realtime(ticker, price)
        await asyncio.sleep(0.5)

# ──────────────── 과거 조건 분석 ────────────────
async def analyze_historical_conditions():
    summary_log[1] = []
    summary_log[2] = []
    for ticker in watchlist:
        price = pyupbit.get_current_price(ticker) or 0
        check_conditions_historical(ticker, price)
        await asyncio.sleep(0.2)

# ──────────────── 요약 메시지 전송 ────────────────
def send_past_summary():
    msg = f"📊 조건 요약 ({datetime.now().strftime('%m/%d %H:%M')})\n"
    for i in [0, 1, 2]:
        entries = summary_log[i]
        unique_entries = list(dict.fromkeys(entries))
        msg += f"\nD-{i} ({len(unique_entries)})\n"
        msg += "\n".join([f"• {e}" for e in unique_entries]) if unique_entries else "•\n"
    send_message(msg)

# ──────────────── 요약 루프 (3시간마다) ────────────────
async def daily_summary_loop():
    while True:
        await analyze_historical_conditions()
        send_past_summary()
        await asyncio.sleep(60 * 60 * 3)

# ──────────────── 메인 루프 ────────────────
async def main():
    global watchlist
    watchlist = get_filtered_krw_tickers()
    send_message("📡 실시간 감시 시작")
    asyncio.create_task(run_ws())
    asyncio.create_task(process_realtime())
    asyncio.create_task(daily_summary_loop())
    await analyze_historical_conditions()
    send_past_summary()
    while True:
        await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(main())
