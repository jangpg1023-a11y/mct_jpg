import asyncio, websockets, json, pyupbit, requests, os, time
from datetime import datetime
from keep_alive import keep_alive

keep_alive()

BOT_TOKEN = os.environ['BOT_TOKEN']
CHAT_ID = os.environ['CHAT_ID']
TELEGRAM_URL = f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage'

alert_cache = {}
summary_log = {0: [], 1: [], 2: []}
ohlcv_cache = {}
last_summary_time = 0
first_summary_sent = False
price_queue = asyncio.Queue()
current_day = datetime.now().date()

def send_message(text):
    try:
        requests.post(TELEGRAM_URL, data={'chat_id': CHAT_ID, 'text': text})
    except:
        pass

def should_alert(key, limit=1800):
    now = time.time()
    last = alert_cache.get(key, 0)
    if now - last > limit:
        alert_cache[key] = now
        return True
    return False

def record_summary(day_index, ticker, condition, change_str):
    summary_log[day_index].append(f"{ticker}: {condition} ({change_str})")

def get_ohlcv_cached(ticker):
    now = time.time()
    if ticker not in ohlcv_cache or now - ohlcv_cache[ticker]['ts'] > 600:
        df = pyupbit.get_ohlcv(ticker, interval="day", count=130)
        weekly = pyupbit.get_ohlcv(ticker, interval="week", count=3)
        ohlcv_cache[ticker] = {'day': df, 'week': weekly, 'ts': now}
    return ohlcv_cache[ticker]['day'], ohlcv_cache[ticker]['week']

def check_conditions(ticker, price, day_indexes=[0]):
    df, weekly = get_ohlcv_cached(ticker)
    if df is None or weekly is None or len(df) < 125 or len(weekly) < 2:
        return

    close = df['close'].tolist()
    open_price = df['open'].iloc[-1]
    change_str = "N/A" if open_price == 0 else f"{((price - open_price) / open_price) * 100:+.2f}%"

    ma7 = df['close'].rolling(window=7).mean().dropna().tolist()
    ma120 = df['close'].rolling(window=120).mean().dropna().tolist()
    std120 = df['close'].rolling(window=120).std().dropna().tolist()

    offset_ma7 = len(close) - len(ma7)
    offset_ma120 = len(close) - len(ma120)
    offset_std120 = len(close) - len(std120)

    bbd = [ma120[i] - 2 * std120[i] for i in range(len(ma120))]
    bbu = [ma120[i] + 2 * std120[i] for i in range(len(ma120))]

    last_week_open = weekly['open'].iloc[-2]
    last_week_close = weekly['close'].iloc[-2]
    is_weekly_bullish = last_week_close > last_week_open or price > last_week_close

    for i in day_indexes:
        try:
            prev_close = close[-2 - i]
            curr_close = close[-1 - i]

            prev_ma7 = ma7[-2 - i - offset_ma7]
            curr_ma7 = ma7[-1 - i - offset_ma7]
            prev_ma120 = ma120[-2 - i - offset_ma120]
            curr_ma120 = ma120[-1 - i - offset_ma120]
            prev_bbd = bbd[-2 - i]
            curr_bbd = bbd[-1 - i]
            prev_bbu = bbu[-2 - i]
            curr_bbu = bbu[-1 - i]
        except:
            continue

        date_str = datetime.now().date()
        key_prefix = f"{ticker}_D{i}_{date_str}_"
        link = f"https://upbit.com/exchange?code=CRIX.UPBIT.{ticker}"

        # 📉 BBD + MA7 돌파
        key_bbd = key_prefix + "bbd_ma7"
        if (
            is_weekly_bullish and
            prev_close < prev_bbd and
            prev_close < prev_ma7 and
            curr_close > curr_bbd and
            curr_close > curr_ma7
        ):
            if i == 0 and should_alert(key_bbd):
                send_message(
                    f"📉 BBD + MA7 돌파 (D-{i})\n"
                    f"{ticker} | 현재가: {price:,} {change_str}\n"
                    f"BBD: {curr_bbd:.2f}, MA7: {curr_ma7:.2f}\n"
                    f"{link}"
                )
            record_summary(i, ticker, f"BBD + MA7 돌파 | BBD: {curr_bbd:.2f}, MA7: {curr_ma7:.2f}", change_str)

        # ➖ MA120 + MA7 돌파
        key_ma120 = key_prefix + "ma120_ma7"
        if (
            prev_close < prev_ma120 and
            prev_close < prev_ma7 and
            curr_close > curr_ma120 and
            curr_close > curr_ma7
        ):
            if i == 0 and should_alert(key_ma120):
                send_message(
                    f"➖ MA120 + MA7 돌파 (D-{i})\n"
                    f"{ticker} | 현재가: {price:,} {change_str}\n"
                    f"MA120: {curr_ma120:.2f}, MA7: {curr_ma7:.2f}\n"
                    f"{link}"
                )
            record_summary(i, ticker, f"MA120 + MA7 돌파 | MA120: {curr_ma120:.2f}, MA7: {curr_ma7:.2f}", change_str)

        # 📈 BBU 상단 돌파
        key_bbu = key_prefix + "bollinger_upper"
        if prev_close < prev_bbu and curr_close > curr_bbu:
            if i == 0 and should_alert(key_bbu):
                send_message(
                    f"📈 BBU 상단 돌파 (D-{i})\n"
                    f"{ticker} | 현재가: {price:,} {change_str}\n"
                    f"BBU: {curr_bbu:.2f}\n"
                    f"{link}"
                )
            record_summary(i, ticker, f"BBU 상단 돌파 | BBU: {curr_bbu:.2f}", change_str)
async def process_queue():
    while True:
        ticker, price = await price_queue.get()
        try:
            check_conditions(ticker, price, day_indexes=[0])
        except Exception as e:
            print("실시간 분석 오류:", e)
        price_queue.task_done()

async def run_ws():
    uri = "wss://api.upbit.com/websocket/v1"
    tickers = pyupbit.get_tickers(fiat="KRW")
    subscribe = [{"ticket": "ticker"}, {"type": "ticker", "codes": tickers}, {"format": "DEFAULT"}]

    while True:
        try:
            async with websockets.connect(uri) as ws:
                await ws.send(json.dumps(subscribe))
                while True:
                    data = await ws.recv()
                    parsed = json.loads(data)
                    await price_queue.put((parsed['code'], parsed['trade_price']))
        except Exception as e:
            print("웹소켓 오류:", e)
            await asyncio.sleep(5)

async def refresh_summary_conditions():
    tickers = pyupbit.get_tickers(fiat="KRW")
    for ticker in tickers:
        df, weekly = get_ohlcv_cached(ticker)
        if df is None or weekly is None:
            continue
        price = df['close'].iloc[-1]
        try:
            check_conditions(ticker, price, day_indexes=[2, 1, 0])
        except Exception as e:
            print("요약 재분석 오류:", e)

# 날짜 변경 감지 루프
async def reset_daily_cache_loop():
    global current_day, alert_cache, summary_log, ohlcv_cache, last_summary_time, first_summary_sent
    while True:
        await asyncio.sleep(60)
        today = datetime.now().date()
        if today != current_day:
            current_day = today
            alert_cache.clear()
            summary_log = {0: [], 1: [], 2: []}
            ohlcv_cache.clear()
            last_summary_time = 0
            first_summary_sent = False
            send_message("🔄 날짜 변경 감지: 캐시 초기화 완료")

# 요약 메시지 루프 (3시간마다 전송)
async def send_summary_if_due():
    global last_summary_time, first_summary_sent
    while True:
        now = time.time()
        if first_summary_sent is False or now - last_summary_time > 60 * 60 * 3:
            last_summary_time = now
            first_summary_sent = True

            message = f"🗒️ 요약 리포트 ({datetime.now().strftime('%m/%d %H:%M')})\n"
            for i in [2, 1, 0]:
                entries = summary_log[i]
                message += f"\n📆 D-{i} ({len(set([e.split(':')[0] for e in entries]))}종목)\n"

                seen_tickers = set()
                for entry in entries:
                    ticker = entry.split(":")[0]
                    if ticker not in seen_tickers:
                        message += f"• {entry}\n"
                        seen_tickers.add(ticker)

                if not seen_tickers:
                    message += "• 해당 없음\n"

            send_message(message)
        await asyncio.sleep(60)
# 메인 함수
async def main():
    send_message("📡 웹소켓 기반 감시 시스템 시작")
    asyncio.create_task(run_ws())                    # 실시간 가격 감시
    asyncio.create_task(process_queue())             # 조건 검사
    asyncio.create_task(send_summary_if_due())       # 요약 메시지 루프
    asyncio.create_task(reset_daily_cache_loop())    # 날짜 변경 감지 루프
    while True:
        await asyncio.sleep(60)

# 실행 진입점
if __name__ == "__main__":
    asyncio.run(main())

