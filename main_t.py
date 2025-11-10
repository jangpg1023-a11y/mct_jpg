import os, time, threading, json, requests, pyupbit
import pandas as pd
from flask import Flask
from collections import OrderedDict

# 환경변수
BOT_TOKEN = os.environ['BOT_TOKEN']
CHAT_ID = os.environ['CHAT_ID']
TELEGRAM_URL = f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage'

# 슬립 방지용 서버
app = Flask('')
@app.route('/')
def home(): return "I'm alive!"
threading.Thread(target=lambda: app.run(host='0.0.0.0', port=8080)).start()

# 캐시
ohlcv_cache = OrderedDict()
MAX_CACHE = 300
TTL = 10800  # 3시간

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

# 감시 루프 (5초마다)
def monitor_loop(interval=5):
    while True:
        rows = []
        for t in pyupbit.get_tickers(fiat="KRW"):
            df = get_data(t)
            if df is None or len(df) < 2: continue
            cur = df.iloc[-1]
            prev = df.iloc[-2]
            name = t.replace("KRW-", "")
            bd = cur.get('BBD', None)
            ma = cur.get('MA7', None)
            p = pyupbit.get_current_price(t)
            if p is None or pd.isna(bd) or pd.isna(ma): continue

            # 감시 조건: 어제 종가 < BBD and < MA7
            if prev['close'] < bd and prev['close'] < ma:
                change = ((p - prev['close']) / prev['close']) * 100
                rows.append((bd, ma, p, name, change))

        rows.sort(key=lambda x: -x[4])
        msg = f"📊 감시 종목\n"
        for _, _, _, name, change in rows:
            msg += f"{name}: {change:+.2f}%\n"

        fallen = [(name, change) for bd, ma, p, name, change in rows if p < bd and p < ma]
        if fallen:
            msg += "\n📉 하락 종목\n"
            for name, change in fallen:
                msg += f"{name}: {change:+.2f}%\n"

        send(msg.strip())
        time.sleep(interval)

# 시작
if __name__ == "__main__":
    send("📡 실시간 BBD 감지")
    monitor_loop()
