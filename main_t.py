import os, time, threading, json, requests, pyupbit, websocket
import pandas as pd
from flask import Flask
from collections import OrderedDict

# 환경변수
BOT_TOKEN = os.environ['BOT_TOKEN']
CHAT_ID = os.environ['CHAT_ID']
TELEGRAM_URL = f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage'

#미사용
#ACCESS_KEY = os.environ['UPBIT_ACCESS']
#SECRET_KEY = os.environ['UPBIT_SECRET']
#upbit = pyupbit.Upbit(ACCESS_KEY, SECRET_KEY)

# 슬립 방지용 서버
app = Flask('')
@app.route('/')
def home(): return "I'm alive!"
threading.Thread(target=lambda: app.run(host='0.0.0.0', port=8080)).start()

# 캐시
ohlcv_cache = OrderedDict()
MAX_CACHE = 300
TTL = 10800  # 3시간

# 상태
watchlist = set()
alert_cache = {}
ALERT_TTL = 3600
last_update_day = None

# 텔레그램
def send(msg):
    try:
        requests.post(TELEGRAM_URL, data={'chat_id': CHAT_ID, 'text': msg})
    except Exception as e:
        print(f"[텔레그램 오류] {e}")

# OHLCV + 지표
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

# 감시 대상 선정
def update_watchlist():
    global watchlist, last_update_day
    today = time.strftime("%Y-%m-%d")
    new_watchlist = set()
    for t in pyupbit.get_tickers(fiat="KRW"):
        df = get_data(t)
        if df is None or len(df) < 125: continue
        prev = df.iloc[-2]
        if (
            not pd.isna(prev['BBD']) and not pd.isna(prev['MA7']) and
            prev['close'] < prev['BBD'] and
            prev['close'] < prev['MA7']
        ):
            new_watchlist.add(t)
    watchlist = new_watchlist
    last_update_day = today

# 실시간 감시
def on_message(ws, msg):
    try:
        data = json.loads(msg)
        code = data['code']
        price = data['trade_price']
        name = code.replace("KRW-", "")
        if code not in watchlist:
            return
        now = time.time()
        if name in alert_cache and now - alert_cache[name] < ALERT_TTL:
            return
        df = get_data(code)
        if df is None or len(df) < 2: return
        cur = df.iloc[-1]
        bd = cur.get('BBD', None)
        ma = cur.get('MA7', None)
        if pd.isna(bd) or pd.isna(ma): return
        if price > bd and price > ma:
            change = ((price - df.iloc[-2]['close']) / df.iloc[-2]['close']) * 100
            send(f"📈 반등 감지\n{name}: {price:,}원 ({change:+.2f}%)")
            alert_cache[name] = now
            update_watchlist()  # 반등 발생 시 감시 대상 재선정
    except Exception as e:
        print(f"[반등 감지 오류] {e}")

def on_open(ws):
    ws.send(json.dumps([{"ticket": "watch"}, {"type": "trade", "codes": list(watchlist)}]))

# 실시간 감시 루프
def monitor_loop(interval=120):
    global last_update_day
    while True:
        now = time.localtime()
        today = time.strftime("%Y-%m-%d")

        # 감시 대상이 없으면 즉시 갱신
        if len(watchlist) == 0:
            update_watchlist()
        # 하루 1회 갱신 (9시 이후)
        elif last_update_day != today and now.tm_hour >= 9:
            update_watchlist()

        ws = websocket.WebSocketApp("wss://api.upbit.com/websocket/v1",
                                    on_message=on_message, on_open=on_open)
        threading.Thread(target=ws.run_forever).start()
        time.sleep(interval)
        ws.close()

# 상태 요약 루프
def status_loop(interval=3600):
    while True:
        time.sleep(interval)
        rows = []
        for t in watchlist:
            df = get_data(t)
            if df is None or len(df) < 2: continue
            cur = df.iloc[-1]
            prev = df.iloc[-2]
            name = t.replace("KRW-", "")
            bd = cur.get('BBD', None)
            ma = cur.get('MA7', None)
            p = pyupbit.get_current_price(t)
            if p is None or pd.isna(bd) or pd.isna(ma): continue
            change = ((p - prev['close']) / prev['close']) * 100
            rows.append((bd, ma, p, name, change))
        rows.sort(key=lambda x: -x[4])

        if rows:
            msg += "📊 감시 종목({len(watchlist)})\n"
            for _, _, _, name, change in rows:
                msg += f"{name}: {change:+.2f}%\n"
        fallen = [(name, change) for bd, ma, p, name, change in rows if p < bd and p < ma]
        if fallen:
            msg += "\n📉 오늘 하락\n"
            for name, change in fallen:
                msg += f"{name}: {change:+.2f}%\n"
        send(msg.strip())

# 시작
if __name__ == "__main__":
    send("📡 실시간 반등 감시 시스템 시작")
    threading.Thread(target=status_loop, daemon=True).start()
    monitor_loop()
