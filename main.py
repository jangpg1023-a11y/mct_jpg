import asyncio, websockets, json, pyupbit, requests, os
from datetime import datetime
from statistics import mean, stdev
from keep_alive import keep_alive

keep_alive()

BOT_TOKEN = os.environ['BOT_TOKEN']
CHAT_ID = os.environ['CHAT_ID']
TELEGRAM_URL = f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage'

alert_cache = {}
summary_log = {0: [], 1: [], 2: []}
last_summary_time = datetime.now().timestamp()

def send_message(text):
    try:
        requests.post(TELEGRAM_URL, data={'chat_id': CHAT_ID, 'text': text})
    except:
        pass

def should_alert(key, limit=1800):
    now = datetime.now().timestamp()
    last = alert_cache.get(key, 0)
    if now - last > limit:
        alert_cache[key] = now
        return True
    return False

def record_summary(day_index, ticker, condition, change_str):
    summary_log[day_index].append(f"{ticker}: {condition} ({change_str})")

async def send_summary_if_due():
    global last_summary_time
    while True:
        await asyncio.sleep(60)
        now = datetime.now().timestamp()
        if now - last_summary_time >= 1800:
            lines = ["📊 요약 메시지 (30분 주기)"]
            for i in [2, 1, 0]:
                lines.append(f"\n[D-{i}]")
                if summary_log[i]:
                    lines.extend(summary_log[i])
                else:
                    lines.append("조건을 만족한 종목 없음")
            send_message("\n".join(lines))
            for i in [2, 1, 0]:
                summary_log[i].clear()
            last_summary_time = now
            for key in list(alert_cache.keys()):
                if "_D1_" in key or "_D2_" in key:
                    del alert_cache[key]

async def clear_d0_cache_loop():
    while True:
        await asyncio.sleep(60)
        now = datetime.now().timestamp()
        for key in list(alert_cache.keys()):
            if "_D0_" in key and now - alert_cache[key] > 1800:
                del alert_cache[key]

def check_conditions(ticker, price):
    df = pyupbit.get_ohlcv(ticker, interval="day", count=130)
    weekly = pyupbit.get_ohlcv(ticker, interval="week", count=3)
    if df is None or weekly is None or len(df) < 125 or len(weekly) < 2:
        return

    close = df['close'].tolist()
    open_price = df['open'].iloc[-1]
    change_str = "N/A" if open_price == 0 else f"{((price - open_price) / open_price) * 100:+.2f}%"

    # 지표 계산
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

    for i in [2, 1, 0]:
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
                send_message(f"📉 BBD + MA7 돌파 (D-{i})\n{ticker} | 현재가: {price:,} {change_str}\n{link}")
            record_summary(i, ticker, "BBD + MA7 돌파", change_str)

        # ➖ MA120 + MA7 돌파
        key_ma120 = key_prefix + "ma120_ma7"
        if (
            prev_close < prev_ma120 and
            prev_close < prev_ma7 and
            curr_close > curr_ma120 and
            curr_close > curr_ma7
        ):
            if i == 0 and should_alert(key_ma120):
                send_message(f"➖ MA120 + MA7 돌파 (D-{i})\n{ticker} | 현재가: {price:,} {change_str}\n{link}")
            record_summary(i, ticker, "MA120 + MA7 돌파", change_str)

        # 📈 BBU 상단 돌파
        key_bbu = key_prefix + "bollinger_upper"
        if prev_close < prev_bbu and curr_close > curr_bbu:
            if i == 0 and should_alert(key_bbu):
                send_message(f"📈 BBU 상단 돌파 (D-{i})\n{ticker} | 현재가: {price:,} {change_str}\n{link}")
            record_summary(i, ticker, "BBU 상단 돌파", change_str)

async def run_ws():
    uri = "wss://api.upbit.com/websocket/v1"
    tickers = pyupbit.get_tickers(fiat="KRW")
    subscribe = [
        {"ticket": "ticker"},
        {"type": "ticker", "codes": tickers},
        {"format": "DEFAULT"}
    ]

    async with websockets.connect(uri) as ws:
        await ws.send(json.dumps(subscribe))
        while True:
            try:
                data = await ws.recv()
                parsed = json.loads(data)
                ticker = parsed['code']
                price = parsed['trade_price']
                check_conditions(ticker, price)
            except:
                await asyncio.sleep(5)

async def main():
    send_message("📡 웹소켓 기반 감시 시스템 시작")
    asyncio.create_task(run_ws())
    asyncio.create_task(send_summary_if_due())
    asyncio.create_task(clear_d0_cache_loop())
    while True:
        await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(main())
