import os, time, threading, json, requests, pyupbit, websocket
import pandas as pd
from flask import Flask
from collections import OrderedDict

# 🔐 환경변수 설정
BOT_TOKEN = os.environ['BOT_TOKEN']
CHAT_ID = os.environ['CHAT_ID']
TELEGRAM_URL = f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage'

# 🛡 슬립 방지용 Flask 서버
app = Flask('')
@app.route('/')
def home(): return "I'm alive!"
threading.Thread(target=lambda: app.run(host='0.0.0.0', port=8080)).start()

# 📦 캐시 설정
ohlcv_cache = OrderedDict()
MAX_CACHE = 300
TTL = 10800  # 3시간

# 🎯 전략 상태
yesterday = set()
today = set()
bought = {}
alerted = {}
ALERT_COOLDOWN = 3600  # 1시간

# 📨 텔레그램 메시지
def send(msg):
    try:
        res = requests.post(TELEGRAM_URL, data={'chat_id': CHAT_ID, 'text': msg})
        print("텔레그램 응답:", res.status_code, res.text)
    except Exception as e:
        print(f"[텔레그램 오류] {e}")

# 📊 OHLCV + 지표 계산
def get_data(ticker):
    now = time.time()
    if ticker in ohlcv_cache and now - ohlcv_cache[ticker]['time'] < TTL:
        return ohlcv_cache[ticker]['df']
    try:
        df = pyupbit.get_ohlcv(ticker, interval="day", count=130)
        close = df['close']
        ma7 = close.rolling(7).mean()
        ma120 = close.rolling(120).mean()
        std = close.rolling(120).std()
        df['MA7'], df['MA120'] = ma7, ma120
        df['BBU'], df['BBD'] = ma120 + 2 * std, ma120 - 2 * std
        if len(ohlcv_cache) >= MAX_CACHE:
            ohlcv_cache.popitem(last=False)
        ohlcv_cache[ticker] = {'df': df, 'time': now}
        return df
    except:
        return None

# 🔍 어제 조건 종목
def find_yesterday():
    result = set()
    for t in pyupbit.get_tickers(fiat="KRW"):
        df = get_data(t)
        if df is None or len(df) < 125: continue
        prev = df.iloc[-2]
        if (
            not pd.isna(prev['BBD']) and not pd.isna(prev['MA7']) and
            prev['close'] < prev['BBD'] < 1_000_000 and
            prev['close'] < prev['MA7']
        ):
            result.add(t)
    return result

# ⚡ 실시간 감시
def on_message(ws, msg):
    global yesterday, today, bought
    data = json.loads(msg)
    t, p = data.get('code'), data.get('trade_price')
    df = get_data(t)
    if df is None or len(df) < 125: return
    cur = df.iloc[-1]

    if p < cur['BBD'] and p < cur['MA7'] and 1 < p < 1_000_000:
        today.add(t)

    if t in yesterday | today and p > cur['BBD'] and p > cur['MA7'] and 1 < p < 1_000_000:
        if t not in bought:
            name = t.replace("KRW-", "")
            change = ((p - cur['open']) / cur['open']) * 100 if cur['open'] > 0 else 0
            send(f"🚀 {name}! {p:,} (+{change:.2f}%)")
            bought[t] = {'price': p, 'time': time.time()}

def on_open(ws):
    tickers = pyupbit.get_tickers(fiat="KRW")
    ws.send(json.dumps([{"ticket": "breakout"}, {"type": "trade", "codes": tickers}]))

# 🔁 감시 루프
def monitor_loop(interval=120):
    global yesterday, today, bought
    last_day = None
    while True:
        now = time.localtime()
        if now.tm_hour >= 9 and now.tm_mday != last_day:
            # ✅ 다음날 MA7 기준 종결
            for t, entry in list(bought.items()):
                df = get_data(t)
                if df is None or len(df) < 2: continue
                cur = df.iloc[-1]
                if cur['close'] < cur['MA7']:
                    pnl = ((cur['close'] - entry['price']) / entry['price']) * 100
                    name = t.replace("KRW-", "")
                    send(f"📉 {name} 종결 {pnl:+.2f}%")
                    del bought[t]
            last_day = now.tm_mday

        yesterday = find_yesterday()
        today = set()
        ws = websocket.WebSocketApp("wss://api.upbit.com/websocket/v1",
                                    on_message=on_message, on_open=on_open)
        threading.Thread(target=ws.run_forever).start()
        time.sleep(interval)
        ws.close()

# ⏱ 상태 알림 루프 (종목별 1시간 쿨타임)
def status_loop(interval=3600):
    while True:
        time.sleep(interval)
        send(f"⏱ 감시 상태: 어제 {len(yesterday)}종목 / 오늘 {len(today)}종목")
        now = time.time()
        for t, entry in bought.items():
            df = get_data(t)
            if df is None or len(df) < 2: continue
            p = pyupbit.get_current_price(t)
            if p is None: continue
            pnl = ((p - entry['price']) / entry['price']) * 100
            dur = (now - entry['time']) / 60
            name = t.replace("KRW-", "")
            if t not in alerted or now - alerted[t] > ALERT_COOLDOWN:
                send(f"📉 {name} {pnl:+.2f}% / {dur:.0f}분")
                alerted[t] = now

# 🚀 실행
if __name__ == "__main__":
    send("📡 실시간 D-day 감시 시스템 시작")
    threading.Thread(target=status_loop, daemon=True).start()
    monitor_loop()
