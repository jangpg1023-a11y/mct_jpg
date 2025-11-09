import websocket, json, pyupbit, requests, os, time, threading
from collections import OrderedDict
from keepalive import keepalive

🔐 환경변수 설정
keep_alive()
BOT_TOKEN = os.environ['BOTTOKEN']
CHAT_ID = os.environ['CHATID']
TELEGRAMURL = f'https://api.telegram.org/bot{BOTTOKEN}/sendMessage'

📦 캐시 설정
ohlcv_cache = OrderedDict()
MAXCACHESIZE = 300
TTL_SECONDS = 10800  # 3시간

🎯 감시 대상
yesterday_candidates = set()
todayfallencandidates = set()
bought = {}

📨 텔레그램 메시지 전송
def send_message(text):
    try:
        res = requests.post(TELEGRAMURL, data={'chatid': CHAT_ID, 'text': text})
        print("텔레그램 응답:", res.status_code, res.text)
    except Exception as e:
        print(f"[텔레그램 오류] {e}")

📊 OHLCV 캐싱
def setohlcvcache(ticker, df):
    now = time.time()
    expired = [k for k, v in ohlcvcache.items() if now - v['time'] > TTLSECONDS]
    for k in expired:
        del ohlcv_cache[k]
    while len(ohlcvcache) >= MAXCACHE_SIZE:
        ohlcv_cache.popitem(last=False)
    ohlcv_cache[ticker] = {'df': df, 'time': now}

def getohlcvcached(ticker):
    now = time.time()
    if ticker in ohlcvcache and now - ohlcvcache[ticker]['time'] < TTL_SECONDS:
        return ohlcv_cache[ticker]['df']
    try:
        df = pyupbit.get_ohlcv(ticker, interval="day", count=130)
        setohlcvcache(ticker, df)
        return df
    except:
        return None

📈 기술적 지표 계산
def calculate_indicators(df):
    close = df['close']
    df['MA7'] = close.rolling(7).mean()
    df['MA120'] = close.rolling(120).mean()
    df['STD120'] = close.rolling(120).std()
    df['BBU'] = df['MA120'] + 2 * df['STD120']
    df['BBD'] = df['MA120'] - 2 * df['STD120']
    return df

📏 호가 단위 계산
def getpriceunit(price):
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

🔍 어제 조건 만족 종목 찾기
def getyesterdaybreakout_candidates():
    candidates = set()
    for ticker in pyupbit.get_tickers(fiat="KRW"):
        df = getohlcvcached(ticker)
        if df is None or len(df) < 125:
            continue
        df = calculate_indicators(df)
        prev = df.iloc[-2]
        if prev['close'] < prev['BBD'] and prev['close'] < prev['MA7']:
            if 1 < prev['close'] < 1000000:
                candidates.add(ticker)
    return candidates

⚡ 실시간 가격 수신 및 조건 체크
def on_message(ws, message):
    global todayfallencandidates, bought
    data = json.loads(message)
    ticker = data.get('code')
    price = data.get('trade_price')

    df = getohlcvcached(ticker)
    if df is None or len(df) < 125:
        return
    df = calculate_indicators(df)
    current = df.iloc[-1]

    if price < current['BBD'] and price < current['MA7']:
        if 1 < price < 1000000:
            todayfallencandidates.add(ticker)

    if ticker in yesterdaycandidates or ticker in todayfallen_candidates:
        if price > current['BBD'] and price > current['MA7']:
            if price <= 1 or price >= 1000000:
                return

            open_price = current['open']
            if open_price > 0:
                change = ((price - openprice) / openprice) * 100
                name = ticker.replace("KRW-", "")
                send_message(f"🚀 {name}! {price:,} (+{change:.2f}%)")

            balance = 0.0
            if balance >= 10000:
                unit = getpriceunit(price)
                rounded_price = round(price / unit) * unit
                volume = balance / rounded_price
                order = upbit.buymarketorder(ticker, volume)
                sendmessage(f"🛒 매수 주문: {name} - {volume:.6f}개 @ {roundedprice:,.0f}원\n{order}")

            bought[ticker] = {'price': price, 'time': time.time()}

            if price < current['MA7']:
                name = ticker.replace("KRW-", "")
                send_message(f"📉 {name} 진입 실패 0.00% / 0분 종결")
                del bought[ticker]

    if ticker in bought and price < current['MA7']:
        entry = bought[ticker]
        duration = (time.time() - entry['time']) / 60
        pnl = ((price - entry['price']) / entry['price']) * 100
        name = ticker.replace("KRW-", "")
        send_message(f"📉 {name} 종결 {pnl:+.2f}% / {duration:.0f}분 종결")
        del bought[ticker]

🌐 웹소켓 연결
def on_open(ws):
    tickers = pyupbit.get_tickers(fiat="KRW")
    subscribe_data = [
        {"ticket": "breakout-monitor"},
        {"type": "trade", "codes": tickers}
    ]
    ws.send(json.dumps(subscribe_data))

🔁 감시 사이클 루프
def websocketcycleloop(interval=120):
    global yesterdaycandidates, todayfallen_candidates, bought
    lastresetday = None

    while True:
        now = time.localtime()
        if now.tmhour >= 9 and now.tmmday != lastresetday:
            bought.clear()
            lastresetday = now.tm_mday

        yesterdaycandidates = getyesterdaybreakoutcandidates()
        todayfallencandidates = set()

        ws = websocket.WebSocketApp("wss://api.upbit.com/websocket/v1",
                                     onmessage=onmessage,
                                     onopen=onopen)
        wst = threading.Thread(target=ws.run_forever)
        wst.start()

        time.sleep(interval)
        ws.close()

⏱ 1시간마다 감시 상태 및 매수 종목 알림
def monitoringstatusalert_loop(interval=3600):
    global yesterdaycandidates, todayfallen_candidates, bought
    while True:
        time.sleep(interval)

        sendmessage(f"⏱ 감시 상태: D+1 {len(yesterdaycandidates)} D-day {len(todayfallencandidates)}")

        for ticker, entry in bought.items():
            df = getohlcvcached(ticker)
            if df is None or len(df) < 2:
                continue
            price = pyupbit.getcurrentprice(ticker)
            if price is None:
                continue
            pnl = ((price - entry['price']) / entry['price']) * 100
            duration = (time.time() - entry['time']) / 60
            name = ticker.replace("KRW-", "")
            send_message(f"📉 {name} {pnl:+.2f}% / {duration:.0f}분")

🚀 메인 실행
if name == "main":
    send_message("📡 실시간 D-day 감시 시스템 시작")
    threading.Thread(target=monitoringstatusalert_loop, daemon=True).start()
    websocketcycleloop()

