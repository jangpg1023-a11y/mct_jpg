import os, time, threading, json, requests, pyupbit
import pandas as pd
from collections import OrderedDict
from websocket import WebSocketApp
from flask import Flask

# 슬립 방지용 서버
app = Flask('')
@app.route('/')
def home(): return "I'm alive!"
threading.Thread(target=lambda: app.run(host='0.0.0.0', port=8080)).start()


# 환경변수
BOT_TOKEN = os.environ['BOT_TOKEN']
CHAT_ID = os.environ['CHAT_ID']
TELEGRAM_URL = f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage'

# 캐시
ohlcv_cache = OrderedDict()
MAX_CACHE = 300
TTL = 10800  # 3시간

# 상태
watchlist = set()
green_flag = {}

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

# 감시 종목 선정
def update_watchlist():
    global watchlist
    new_watchlist = set()
    for t in pyupbit.get_tickers(fiat="KRW"):
        df = get_data(t)
        if df is None or len(df) < 2: continue
        cur = df.iloc[-1]
        prev = df.iloc[-2]
        bd = cur.get('BBD', None)
        ma = cur.get('MA7', None)
        if pd.isna(bd) or pd.isna(ma): continue
        if prev['close'] < bd and prev['close'] < ma:
            new_watchlist.add(t)
    watchlist = new_watchlist

# 감시 종목 재선정 루프 (1분마다)
def update_watchlist_loop():
    while True:
        update_watchlist()
        time.sleep(60)

# 상태 요약 알림
def send_status():
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
        prev_close = prev['close']
        rows.append((t, bd, ma, p, name, change, prev_close))

    msg = f"📊 감시 종목\n"
    for t, _, _, _, name, change, prev_close in rows:
        flag = " 🟢" if green_flag.get(t, False) else ""
        msg += f"{name}: {change:+.2f}%{flag}\n"

    fallen = [(name, change) for t, bd, ma, p, name, change, prev_close in rows if prev_close > bd and prev_close > ma and p < bd and p < ma]
    if fallen:
        msg += "\n📉 하락 전환\n"
        for name, change in fallen:
            msg += f"{name}: {change:+.2f}%\n"

    send(msg.strip())

# 상태 요약 루프 (1시간마다)
def status_loop():
    while True:
        time.sleep(3600)
        send_status()

# 실시간 반등 감시
def handle_message(ws, message):
    try:
        data = json.loads(message)
        code = data['code']
        price = data['trade_price']
        if code not in watchlist: return
        df = get_data(code)
        if df is None or len(df) < 2: return
        cur = df.iloc[-1]
        bd = cur.get('BBD', None)
        ma = cur.get('MA7', None)
        if pd.isna(bd) or pd.isna(ma): return

        if code not in green_flag:
            green_flag[code] = False

        if price > bd and price > ma:
            if not green_flag[code]:
                send(f"🚀 돌파: {code.replace('KRW-', '')} 가격 {price:.2f}원 (BBD/MA7 돌파)")
                green_flag[code] = True
        else:
            if green_flag[code]:
                green_flag[code] = False
    except Exception as e:
        print(f"[웹소켓 오류] {e}")

def monitor_loop():
    def run_socket():
        tickers = pyupbit.get_tickers(fiat="KRW")
        codes = [f'"{t}"' for t in tickers]
        payload = {
            "type": "ticker",
            "codes": codes
        }
        ws = WebSocketApp("wss://api.upbit.com/websocket/v1",
                          on_message=handle_message,
                          on_error=lambda ws, err: print(f"[WS 오류] {err}"),
                          on_close=lambda ws: print("[WS 종료]"),
                          on_open=lambda ws: ws.send(json.dumps(payload)))
        ws.run_forever()
    threading.Thread(target=run_socket, daemon=True).start()

# 실행
if __name__ == "__main__":
    send("📡 실시간 BBD 돌파감시")
    update_watchlist()  # 시작 시 감시 종목 선정
    send_status()       # 시작 시 상태 요약 알림
    threading.Thread(target=update_watchlist_loop, daemon=True).start()
    threading.Thread(target=status_loop, daemon=True).start()
    monitor_loop()




