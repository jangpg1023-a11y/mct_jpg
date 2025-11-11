import os, time, threading, requests, pyupbit
import pandas as pd
from flask import Flask
from collections import OrderedDict

app = Flask(__name__)

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

# 텔레그램 메시지 전송
def send(msg):
    requests.post(TELEGRAM_URL, data={"chat_id": CHAT_ID, "text": msg})

# 호가 단위 계산
def get_tick_size(price):
    if price < 1:
        return 0.0001
    elif price < 10:
        return 0.001
    elif price < 100:
        return 0.01
    elif price < 1000:
        return 0.1
    elif price < 10000:
        return 1
    elif price < 100000:
        return 5
    elif price < 500000:
        return 10
    else:
        return 50

# 가격 포맷
def format_price(price):
    tick = get_tick_size(price)
    return f"{round(price / tick) * tick:.{str(tick)[::-1].find('.')}f}"

# 데이터 가져오기
def get_data(ticker):
    now = time.time()
    if ticker in ohlcv_cache and now - ohlcv_cache[ticker]['time'] < TTL:
        return ohlcv_cache[ticker]['df']
    try:
        df = pyupbit.get_ohlcv(ticker, interval="day")
        if df is None or len(df) < 120:
            return None
        df['MA7'] = df['close'].rolling(7).mean()
        df['MA120'] = df['close'].rolling(120).mean()
        std = df['close'].rolling(20).std()
        df['MA20'] = df['close'].rolling(20).mean()
        df['BBU'] = df['MA20'] + 2 * std
        df['BBD'] = df['MA20'] - 2 * std
        ohlcv_cache[ticker] = {'df': df, 'time': now}
        if len(ohlcv_cache) > MAX_CACHE:
            ohlcv_cache.popitem(last=False)
        return df
    except:
        return None

# 감시 종목 업데이트
def update_watchlist():
    tickers = pyupbit.get_tickers(fiat="KRW")
    new_watchlist = set()
    for t in tickers:
        price = pyupbit.get_current_price(t)
        if price is None or price < 1 or price > 1000000:
            continue

        df = get_data(t)
        if df is None or len(df) < 2:
            continue
        cur = df.iloc[-1]
        prev = df.iloc[-2]
        bd = cur.get('BBD', None)
        ma = cur.get('MA7', None)
        if pd.isna(bd) or pd.isna(ma):
            continue
        if prev['close'] < bd and prev['close'] < ma:
            new_watchlist.add(t)
    global watchlist
    watchlist = new_watchlist

# 요약 메시지 전송
def send_status():
    rows = []
    for t in watchlist:
        df = get_data(t)
        if df is None or len(df) < 8: continue
        cur = df.iloc[-1]
        prev = df.iloc[-2]
        name = t.replace("KRW-", "")
        bd = cur.get('BBD', None)
        ma = cur.get('MA7', None)
        p = pyupbit.get_current_price(t)
        if p is None or pd.isna(bd) or pd.isna(ma): continue
        change = ((p - prev['close']) / prev['close']) * 100
        prev_close = prev['close']
        rows.append((t, bd, ma, p, name, change, prev_close, df))

    msg = f"📊 감시 종목\n"
    for t, _, _, p, name, change, _, _ in rows:
        flag = " 🟢" if green_flag.get(t, False) else ""
        msg += f"{name}: {format_price(p)}원 {change:+.2f}%{flag}\n"

    msg += "\n📌 지지 종목\n"
    for t, _, _, p, name, change, _, df in rows:
        for i in range(-8, -1):
            row = df.iloc[i]
            if pd.isna(row['BBD']) or pd.isna(row['MA7']):
                continue
            if row['close'] > row['BBD'] and row['close'] > row['MA7']:
                breakout_close = row['close']
                ma7_today = df.iloc[-1]['MA7']
                if pd.isna(ma7_today):
                    continue
                if p < breakout_close and p > ma7_today:
                    days_since = len(df) - (i + 1)
                    msg += f"{name}: {format_price(p)}원 {change:+.2f}% (D+{days_since})\n"
                    break

    msg += "\n📉 하락 전환\n"
    for t, bd, ma, p, name, change, prev_close, _ in rows:
        if prev_close > bd and prev_close > ma and p < bd and p < ma:
            msg += f"{name}: {change:+.2f}%\n"

    send(msg.strip())

# 실시간 반등 감시
def polling_loop():
    breakout_cache = {}

    while True:
        for code in watchlist:
            df = get_data(code)
            if df is None or len(df) < 8:
                continue
            cur = df.iloc[-1]
            bd = cur.get('BBD', None)
            ma = cur.get('MA7', None)
            if pd.isna(bd) or pd.isna(ma):
                continue

            price = pyupbit.get_current_price(code)
            if price is None:
                continue

            if code not in green_flag:
                green_flag[code] = False

            if price > bd and price > ma:
                if not green_flag[code]:
                    send(f"🚀 돌파: {code.replace('KRW-', '')} 가격 {format_price(price)}원 (BBD/MA7 돌파)")
                    green_flag[code] = True
            else:
                if green_flag[code]:
                    green_flag[code] = False

            for i in range(-8, -1):
                row = df.iloc[i]
                if pd.isna(row['BBD']) or pd.isna(row['MA7']):
                    continue
                if row['close'] > row['BBD'] and row['close'] > row['MA7']:
                    breakout_close = row['close']
                    ma7_today = df.iloc[-1]['MA7']
                    if pd.isna(ma7_today):
                        continue
                    if price < breakout_close and price > ma7_today:
                        breakout_cache[code] = {'price': breakout_close, 'index': i}
                    break

            if code in breakout_cache:
                breakout_price = breakout_cache[code]['price']
                breakout_day_index = breakout_cache[code]['index']
                days_since = len(df) - (breakout_day_index + 1)
                if price > breakout_price:
                    rate_now = ((price - df.iloc[-2]['close']) / df.iloc[-2]['close']) * 100
                    rate_vs_breakout = ((price - breakout_price) / breakout_price) * 100
                    send(
                        f"📈 재돌파: {code.replace('KRW-', '')} {format_price(price)}원 {rate_now:+.2f}% "
                        f"(D+{days_since} 종가 {format_price(breakout_price)} {rate_vs_breakout:+.2f}%)"
                    )
                    del breakout_cache[code]

        time.sleep(3)

# 1시간마다 요약 알림 루프
def status_loop():
    while True:
        send_status()
        time.sleep(3600)

# Flask routes
@app.route('/')
def home():
    return "자동매매 감시 시스템 작동 중"

@app.route('/status')
def status():
    return f"감시 종목 수: {len(watchlist)}"

@app.route('/update', methods=['POST'])
def update():
    update_watchlist()
    return "감시 종목 업데이트 완료"

# 앱 실행
if __name__ == '__main__':
    update_watchlist()
    time.sleep(5)  # 캐시 준비 시간 확보
    threading.Thread(target
