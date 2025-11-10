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
watchlist = set()

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

# 🔍 감시 대상 종목 선정 (어제 종가 기준)
def build_watchlist():
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
def on_message(ws, msg): pass  # 보유 종목 제거됨

def on_open(ws):
    ws.send(json.dumps([{"ticket": "watch"}, {"type": "trade", "codes": list(watchlist)}]))

# 🔁 감시 루프
def monitor_loop(interval=120):
    global watchlist
    while True:
        watchlist = build_watchlist()
        ws = websocket.WebSocketApp("wss://api.upbit.com/websocket/v1",
                                    on_message=on_message, on_open=on_open)
        threading.Thread(target=ws.run_forever).start()
        time.sleep(interval)
        ws.close()

# ⏱ 상태 알림 루프
def status_loop(interval=180):
    while True:
        time.sleep(interval)
        send(f"⏱ 감시 상태: 감시 {len(watchlist)}종목")
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

        # 📊 상승률 기준으로 종목 정렬
        rows.sort(key=lambda x: -x[4])

        # 📊 메시지 구성: 종목명 + 상승률만 표시 (R 제거)
        if rows:
            msg = "📊 감시 종목\n"
            for _, _, _, name, change in rows:
                msg += f"{name}: {change:+.2f}%\n"
            send(msg.strip())

        # 📉 오늘 하락: 현재가가 BBD와 MA7 모두 아래인 종목
        fallen = []
        for bd, ma, p, name, _ in rows:
            if p < bd and p < ma:
                fallen.append(name)
        if fallen:
            msg = "\n📉 오늘 하락\n" + ", ".join(fallen)
            send(msg)

# 🚀 실행
if __name__ == "__main__":
    send("📡 실시간 D-day 감시 시스템 시작")
    threading.Thread(target=status_loop, daemon=True).start()
    monitor_loop()
