import websocket, json, pyupbit, requests, os, time, threading
from collections import OrderedDict
from keep_alive import keep_alive

# 🔐 환경변수 설정
keep_alive()
BOT_TOKEN = os.environ['BOT_TOKEN']
CHAT_ID = os.environ['CHAT_ID']
ACCESS_KEY = os.environ['UPBIT_ACCESS_KEY']
SECRET_KEY = os.environ['UPBIT_SECRET_KEY']
TELEGRAM_URL = f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage'

# 📦 캐시 설정
ohlcv_cache = OrderedDict()
MAX_CACHE_SIZE = 300
TTL_SECONDS = 10800  # 3시간

# 🎯 감시 대상
yesterday_candidates = set()
today_fallen_candidates = set()
bought = {}

# 📨 텔레그램 메시지 전송
def send_message(text):
    try:
        res = requests.post(TELEGRAM_URL, data={'chat_id': CHAT_ID, 'text': text})
        print("텔레그램 응답:", res.status_code, res.text)
    except Exception as e:
        print(f"[텔레그램 오류] {e}")

# 📊 OHLCV 캐싱
def set_ohlcv_cache(ticker, df):
    now = time.time()
    expired = [k for k, v in ohlcv_cache.items() if now - v['time'] > TTL_SECONDS]
    for k in expired:
        del ohlcv_cache[k]
    while len(ohlcv_cache) >= MAX_CACHE_SIZE:
        ohlcv_cache.popitem(last=False)
    ohlcv_cache[ticker] = {'df': df, 'time': now}

def get_ohlcv_cached(ticker):
    now = time.time()
    if ticker in ohlcv_cache and now - ohlcv_cache[ticker]['time'] < TTL_SECONDS:
        return ohlcv_cache[ticker]['df']
    try:
        df = pyupbit.get_ohlcv(ticker, interval="day", count=130)
        set_ohlcv_cache(ticker, df)
        return df
    except:
        return None

# 📈 기술적 지표 계산
def calculate_indicators(df):
    close = df['close']
    df['MA7'] = close.rolling(7).mean()
    df['MA120'] = close.rolling(120).mean()
    df['STD120'] = close.rolling(120).std()
    df['BBU'] = df['MA120'] + 2 * df['STD120']
    df['BBD'] = df['MA120'] - 2 * df['STD120']
    return df

# 📏 호가 단위 계산
def get_price_unit(price):
    if price < 10:
        return 0.01
    elif price < 100:
        return 0.1
    elif price < 1000:
        return 1
    elif price < 10000:
        return 5
    elif price < 100000:
        return 10
    elif price < 500000:
        return 50
    elif price < 1000000:
        return 100
    else:
        return 500

# 🔍 어제 조건 만족 종목 찾기
def get_yesterday_breakout_candidates():
    candidates = set()
    for ticker in pyupbit.get_tickers(fiat="KRW"):
        df = get_ohlcv_cached(ticker)
        if df is None or len(df) < 125:
            continue
        df = calculate_indicators(df)
        prev = df.iloc[-2]
        if prev['close'] < prev['BBD'] and prev['close'] < prev['MA7']:
            if 1 < prev['close'] < 1_000_000:
                candidates.add(ticker)
    return candidates

# ⚡ 실시간 가격 수신 및 조건 체크
def on_message(ws, message):
    global today_fallen_candidates, bought
    data = json.loads(message)
    ticker = data.get('code')
    price = data.get('trade_price')

    df = get_ohlcv_cached(ticker)
    if df is None or len(df) < 125:
        return
    df = calculate_indicators(df)
    current = df.iloc[-1]

    # 오늘 조건 진입 감지
    if price < current['BBD'] and price < current['MA7']:
        if 1 < price < 1_000_000:
            today_fallen_candidates.add(ticker)

    # 조건 돌파 감지
    if ticker in yesterday_candidates or ticker in today_fallen_candidates:
        if price > current['BBD'] and price > current['MA7']:
            if price <= 1 or price >= 1_000_000:
                return

            open_price = current['open']
            if open_price > 0:
                change = ((price - open_price) / open_price) * 100
                name = ticker.replace("KRW-", "")
                send_message(f"🚀 {name}! {price:,} (+{change:.2f}%)")

            # 실전매매 (테스트용 balance = 0.0)
            balance = 0.0
            if balance >= 10000:
                unit = get_price_unit(price)
                rounded_price = round(price / unit) * unit
                volume = balance / rounded_price
                order = upbit.buy_market_order(ticker, volume)
                send_message(f"🛒 매수 주문: {name} - {volume:.6f}개 @ {rounded_price:,.0f}원\n{order}")

            # 매수 기록
            bought[ticker] = {'price': price, 'time': time.time()}

            # 매수 직후 MA7 아래면 진입 실패
            if price < current['MA7']:
                name = ticker.replace("KRW-", "")
                send_message(f"📉 {name} 진입 실패 0.00% / 0분 종결")
                del bought[ticker]

    # MA7 하락 → 전략 종결
    if ticker in bought and price < current['MA7']:
        entry = bought[ticker]
        duration = (time.time() - entry['time']) / 60
        pnl = ((price - entry['price']) / entry['price']) * 100
        name = ticker.replace("KRW-", "")
        send_message(f"📉 {name} 종결 {pnl:+.2f}% / {duration:.0f}분 종결")
        del bought[ticker]

# 🌐 웹소켓 연결
def on_open(ws):
    tickers = pyupbit.get_tickers(fiat="KRW")
    subscribe_data = [
        {"ticket": "breakout-monitor"},
        {"type": "trade", "codes": tickers}
    ]
    ws.send(json.dumps(subscribe_data))

# 🔁 감시 사이클 루프
def websocket_cycle_loop(interval=120):
    global yesterday_candidates, today_fallen_candidates, bought
    last_reset_day = None

    while True:
        now = time.localtime()
        if now.tm_hour >= 9 and now.tm_mday != last_reset_day:
            bought.clear()
            last_reset_day = now.tm_mday

        yesterday_candidates = get_yesterday_breakout_candidates()
        today_fallen_candidates = set()
        send_message(f"👀 감시 시작: 어제 조건 {len(yesterday_candidates)}종목 + 오늘 진입 0종목")

        ws = websocket.WebSocketApp("wss://api.upbit.com/websocket/v1",
                                     on_message=on_message,
                                     on_open=on_open)
        wst = threading.Thread(target=ws.run_forever)
        wst.start()

        time.sleep(interval)
        ws.close()

# ⏱ 1시간마다 진행 중 종목 알림
def monitoring_status_alert_loop(interval=3600):
    while True:
        time.sleep(interval)
        for ticker, entry in bought.items():
            df = get_ohlcv_cached(ticker)
            if df is None or len(df) < 2:
                continue
            price = pyupbit.get_current_price(ticker)
            if price is None:
                continue
            pnl = ((price - entry['price']) / entry['price']) * 100
            duration = (time.time() - entry['time']) / 60
            name = ticker.replace("KRW-", "")
            send_message(f"📉 {name} {pnl:+.2f}% / {duration:.0f}분")

# 🚀 메인 실행
if __name__ == "__main__":
    send_message("📡 실시간 D-day 감시 시스템 시작")
    threading.Thread(target=monitoring_status_alert_loop, daemon=True).start()
    websocket_cycle_loop()
