import asyncio, websockets, json, pyupbit, requests, os, time
from datetime import datetime
from keep_alive import keep_alive

# ──────────────── 기본 설정 ────────────────
keep_alive()
BOT_TOKEN = os.environ['BOT_TOKEN']
CHAT_ID = os.environ['CHAT_ID']
TELEGRAM_URL = f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage'

watchlist = ["KRW-BTC", "KRW-ETH", "KRW-XRP", "KRW-DOGE"]
price_queue = asyncio.Queue()
alert_cache = {}
ohlcv_cache = {}
summary_log = {1: [], 2: []}

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

# ──────────────── 알림 중복 방지 ────────────────
def should_alert(key):
    if alert_cache.get(key): return False
    alert_cache[key] = True
    return True

# ──────────────── 요약 기록 ────────────────
def record_summary(day_index, ticker, condition_text, change_str):
    if day_index in summary_log:
        summary_log[day_index].append(f"{ticker} | {condition_text} {change_str}")

# ──────────────── 조건 검사 (초간결 버전) ────────────────
def check_conditions(ticker, price, day_indexes=[0]):
    df, weekly = get_ohlcv_cached(ticker)
    if df is None or weekly is None or len(df) < 125 or len(weekly) < 2:
        return

    # 기술 지표 계산
    close = df['close']
    ma7 = close.rolling(7).mean()
    ma120 = close.rolling(120).mean()
    std120 = close.rolling(120).std()
    bbd = ma120 - 2 * std120
    bbu = ma120 + 2 * std120

    # 주봉 조건
    last_week_open = weekly['open'].iloc[-2]
    last_week_close = weekly['close'].iloc[-2]
    is_weekly_bullish = last_week_close > last_week_open or price > last_week_close

    # 당일 변동률
    open_price = df['open'].iloc[-1]
    change_str = f"{((price - open_price) / open_price) * 100:+.2f}%" if open_price else "N/A"
    link = f"https://upbit.com/exchange?code=CRIX.UPBIT.{ticker}"

    for i in day_indexes:
        try:
            idx = -1 - i
            prev_idx = -2 - i

            pc = close.iloc[prev_idx]
            cc = close.iloc[idx]

            ma7_prev = ma7.iloc[prev_idx]
            ma7_curr = ma7.iloc[idx]
            ma120_prev = ma120.iloc[prev_idx]
            ma120_curr = ma120.iloc[idx]
            bbd_prev = bbd.iloc[prev_idx]
            bbd_curr = bbd.iloc[idx]
            bbu_prev = bbu.iloc[prev_idx]
            bbu_curr = bbu.iloc[idx]
        except:
            continue

        key = f"{ticker}_D{i}_{datetime.now().date()}_"

        # 📉 BBD + MA7 돌파
        if is_weekly_bullish and pc < bbd_prev and pc < ma7_prev and cc > bbd_curr and cc > ma7_curr:
            if i == 0 and should_alert(key + "bbd_ma7"):
                send_message(f"📉 BBD + MA7 돌파 (D-{i})\n{ticker} | 현재가: {price:,} {change_str}\n{link}")
            record_summary(i, ticker, "BBD + MA7 돌파", change_str)

        # ➖ MA120 + MA7 돌파
        if pc < ma120_prev and pc < ma7_prev and cc > ma120_curr and cc > ma7_curr:
            if i == 0 and should_alert(key + "ma120_ma7"):
                send_message(f"➖ MA120 + MA7 돌파 (D-{i})\n{ticker} | 현재가: {price:,} {change_str}\n{link}")
            record_summary(i, ticker, "MA120 + MA7 돌파", change_str)

        # 📈 BBU 상단 돌파
        if pc < bbu_prev and cc > bbu_curr:
            if i == 0 and should_alert(key + "bollinger_upper"):
                send_message(f"📈 BBU 상단 돌파 (D-{i})\n{ticker} | 현재가: {price:,} {change_str}\n{link}")
            record_summary(i, ticker, "BBU 상단 돌파", change_str)
# ──────────────── 실시간 가격 처리 ────────────────
async def process_queue():
    while True:
        if not price_queue.empty():
            ticker, price = await price_queue.get()
            check_conditions(ticker, price, day_indexes=[0])
        await asyncio.sleep(0.5)

# ──────────────── 과거 조건 분석 ────────────────
async def analyze_past_conditions():
    summary_log[1] = []
    summary_log[2] = []
    for ticker in watchlist:
        price = pyupbit.get_current_price(ticker) or 0
        check_conditions(ticker, price, day_indexes=[1, 2])
        await asyncio.sleep(0.2)

# ──────────────── 요약 메시지 전송 ────────────────
def send_past_summary():
    msg = f"📊 과거 조건 요약 ({datetime.now().strftime('%m/%d %H:%M')})\n"
    for i in [2, 1]:
        entries = summary_log[i]
        msg += f"\n📆 D-{i} ({len(entries)}종목)\n"
        msg += "\n".join([f"• {e}" for e in entries]) if entries else "• 해당 없음\n"
    send_message(msg)

# ──────────────── 메인 루프 ────────────────
async def main():
    send_message("📡 감시 시스템 시작")
    asyncio.create_task(run_ws())
    asyncio.create_task(process_queue())
    await analyze_past_conditions()
    send_past_summary()
    while True:
        await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(main())

