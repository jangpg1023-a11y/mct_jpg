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
    df, w = get_ohlcv_cached(ticker)
    if df is None or w is None or len(df) < 125: return

    c = df['close'].tolist()
    o = df['open'].iloc[-1]
    chg = f"{((price - o) / o) * 100:+.2f}%" if o else "N/A"
    ma7 = df['close'].rolling(7).mean().dropna().tolist()
    ma120 = df['close'].rolling(120).mean().dropna().tolist()
    std = df['close'].rolling(120).std().dropna().tolist()
    bbd = [ma120[i] - 2 * std[i] for i in range(len(ma120))]
    bbu = [ma120[i] + 2 * std[i] for i in range(len(ma120))]
    off = len(c) - len(ma7)
    bull = w['close'].iloc[-2] > w['open'].iloc[-2] or price > w['close'].iloc[-2]
    link = f"https://upbit.com/exchange?code=CRIX.UPBIT.{ticker}"

    for i in day_indexes:
        try:
            pc, cc = c[-2 - i], c[-1 - i]
            m7p, m7c = ma7[-2 - i - off], ma7[-1 - i - off]
            m120p, m120c = ma120[-2 - i - off], ma120[-1 - i - off]
            bbp, bbc = bbu[-2 - i], bbu[-1 - i]
            bbdp, bbdc = bbd[-2 - i], bbd[-1 - i]
        except: continue

        k = f"{ticker}_D{i}_{datetime.now().date()}_"

        if bull and pc < bbdp and pc < m7p and cc > bbdc and cc > m7c:
            if i == 0 and should_alert(k + "bbd_ma7"):
                send_message(f"📉 BBD + MA7 돌파 (D-{i})\n{ticker} | 현재가: {price:,} {chg}\n{link}")
            record_summary(i, ticker, "BBD + MA7 돌파", chg)

        if pc < m120p and pc < m7p and cc > m120c and cc > m7c:
            if i == 0 and should_alert(k + "ma120_ma7"):
                send_message(f"➖ MA120 + MA7 돌파 (D-{i})\n{ticker} | 현재가: {price:,} {chg}\n{link}")
            record_summary(i, ticker, "MA120 + MA7 돌파", chg)

        if pc < bbp and cc > bbc:
            if i == 0 and should_alert(k + "bollinger_upper"):
                send_message(f"📈 BBU 상단 돌파 (D-{i})\n{ticker} | 현재가: {price:,} {chg}\n{link}")
            record_summary(i, ticker, "BBU 상단 돌파", chg)

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
