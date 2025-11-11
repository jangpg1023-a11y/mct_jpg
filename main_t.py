import os, time, threading, requests, pyupbit
import pandas as pd
from collections import OrderedDict
from flask import Flask
from threading import Thread

# 🌐 Flask keep-alive
app = Flask('')
@app.route('/')
def home():
    return "I'm alive!"
def run(): app.run(host='0.0.0.0', port=8080)
def keep_alive(): Thread(target=run).start()

# 🔐 환경변수
BOT_TOKEN = os.environ['BOT_TOKEN']
CHAT_ID = os.environ['CHAT_ID']
TELEGRAM_URL = f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage'

# 🧠 상태 변수
ohlcv_cache = OrderedDict()
MAX_CACHE = 300
TTL = 3600
watchlist = set()
support_candidates = set()
reversal_candidates = set()
green_flag = {}

# 📤 텔레그램 메시지
def send(msg):
    try:
        res = requests.post(TELEGRAM_URL, data={"chat_id": CHAT_ID, "text": msg})
        if res.status_code != 200:
            print("텔레그램 전송 실패:", res.text)
    except Exception as e:
        print("텔레그램 예외:", e)

# 📐 호가 단위 및 포맷
def get_tick_size(price):
    if price < 1: return 0.0001
    elif price < 10: return 0.001
    elif price < 100: return 0.01
    elif price < 1000: return 0.1
    elif price < 10000: return 1
    elif price < 100000: return 5
    elif price < 500000: return 10
    else: return 50

def format_price(price):
    tick = get_tick_size(price)
    try:
        tick_str = f"{tick:.10f}".rstrip('0')
        precision = tick_str[::-1].find('.') if '.' in tick_str else 0
        rounded = round(price / tick) * tick
        return f"{rounded:.{precision}f}"
    except Exception as e:
        print(f"format_price 오류: {e}")
        return str(price)

# 📊 데이터 가져오기
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
        std = df['close'].rolling(120).std()
        df['BBU'] = df['MA120'] + 2 * std
        df['BBD'] = df['MA120'] - 2 * std
        ohlcv_cache[ticker] = {'df': df, 'time': now}
        if len(ohlcv_cache) > MAX_CACHE:
            ohlcv_cache.popitem(last=False)
        return df
    except:
        return None

# 🔍 전체 시장 스캔
def scan_market():
    global watchlist, support_candidates, reversal_candidates
    watchlist.clear()
    support_candidates.clear()
    reversal_candidates.clear()

    tickers = pyupbit.get_tickers(fiat="KRW")
    for t in tickers:
        df = get_data(t)
        if df is None or len(df) < 8: continue
        cur = df.iloc[-1]
        prev = df.iloc[-2]
        bd = cur.get('BBD')
        ma = cur.get('MA7')
        p = pyupbit.get_current_price(t)
        if p is None or pd.isna(bd) or pd.isna(ma): continue

        if prev['close'] < bd and prev['close'] < ma:
            watchlist.add(t)

        if prev['close'] > bd and prev['close'] > ma and p < bd and p < ma:
            reversal_candidates.add(t)

        for i in range(-2, -9, -1):
            row = df.iloc[i]
            if pd.isna(row['BBD']) or pd.isna(row['MA7']): continue
            if row['close'] > row['BBD'] and row['close'] > row['MA7']:
                breakout_close = row['close']
                breakout_date = df.index[i]
                today = df.index[-1]
                days_since = (today - breakout_date).days
                if p < breakout_close and p > ma and days_since <= 7:
                    support_candidates.add(t)
                break

# 📬 상태 메시지 전송
def send_status():
    msg = "📊 감시 종목\n"
    for t in watchlist:
        df = get_data(t)
        if df is None or len(df) < 2: continue
        cur = df.iloc[-1]
        prev = df.iloc[-2]
        bd = cur.get('BBD')
        ma = cur.get('MA7')
        p = pyupbit.get_current_price(t)
        name = t.replace("KRW-", "")
        if p is None or pd.isna(bd) or pd.isna(ma): continue
        change = ((p - prev['close']) / prev['close']) * 100
        flag = " 🟢" if green_flag.get(t, False) else ""
        msg += f"{name}: {format_price(p)}원 {change:+.2f}%{flag}\n"

    msg += "\n📌 지지 종목\n"
    for t in support_candidates:
        df = get_data(t)
        if df is None or len(df) < 8: continue
        p = pyupbit.get_current_price(t)
        name = t.replace("KRW-", "")
        if p is None: continue

        breakout_close = None
        days_since = None

        for i in range(-2, -9, -1):
            row = df.iloc[i]
            if pd.isna(row['BBD']) or pd.isna(row['MA7']): continue
            if row['close'] > row['BBD'] and row['close'] > row['MA7']:
                breakout_close = row['close']
                breakout_date = df.index[i]
                today = df.index[-1]
                days_since = (today - breakout_date).days
                break

        if breakout_close is None or days_since is None: continue
        ma7_today = df.iloc[-1]['MA7']
        if pd.isna(ma7_today): continue

        change = ((p - df.iloc[-2]['close']) / df.iloc[-2]['close']) * 100
        flag = " 🟢" if green_flag.get(t, False) else ""

        if (p < breakout_close and p > ma7_today and days_since <= 7) or green_flag.get(t, False):
            msg += f"{name}: {format_price(p)}원 {change:+.2f}% (D+{days_since}){flag}\n"

    msg += "\n📉 전환 종목\n"
    for t in reversal_candidates:
        df = get_data(t)
        if df is None or len(df) < 2: continue
        cur = df.iloc[-1]
        prev = df.iloc[-2]
        bd_prev = prev.get('BBD')
        ma_prev = prev.get('MA7')
        bd_cur = cur.get('BBD')
        ma_cur = cur.get('MA7')
        p = pyupbit.get_current_price(t)
        name = t.replace("KRW-", "")
        if p is None or pd.isna(bd_prev) or pd.isna(ma_prev) or pd.isna(bd_cur) or pd.isna(ma_cur): continue

        if (prev['close'] > bd_prev or prev['close'] > ma_prev) and (p < bd_cur and p < ma_cur):
            change = ((p - prev['close']) / prev['close']) * 100
            flag = " 🟢" if green_flag.get(t, False) else ""
            msg += f"{name}: {format_price(p)}원 {change:+.2f}%{flag}\n"

    send(msg.strip())

# 🔁 실시간 감시 루프
def polling_loop():
    breakout_cache = {}
    while True:
        for code in watchlist.union(support_candidates):
            if green_flag.get(code, False): continue
            df = get_data(code)
            if df is None or len(df) < 8: continue
            cur = df.iloc[-1]
            bd = cur.get('BBD')
            ma = cur.get('MA7')
            if pd.isna(bd) or pd.isna(ma): continue
            price = pyupbit.get_current_price(code)
            if price is None: continue

            if code in watchlist:
                if code not in green_flag:
                    green_flag[code] = False
                if price > bd and price > ma:
                    send(f"🚀 돌파: {code.replace('KRW-', '')} {format_price(price)}원")
                    green_flag[code] = True

            if code in support_candidates:
                for i in range(-2, -9, -1):
                    row = df.iloc[i]
                    if pd.isna(row['BBD']) or pd.isna(row['MA7']): continue
                    if row['close'] > row['BBD'] and row['close'] > row['MA7']:
                        breakout_close = row['close']
                        breakout_date = df.index[i]
                        today = df.index[-1]
                        days_since = (today - breakout_date).days
                        ma7_today = df.iloc[-1]['MA7']
                        if pd.isna(ma7_today): continue
                        if price < breakout_close and price > ma7_today and days_since <= 7:
                            breakout_cache[code] = {'price': breakout_close, 'date': breakout_date}
                        break

                if code in breakout_cache:
                    breakout_price = breakout_cache[code]['price']
                    breakout_date = breakout_cache[code]['date']
                    today = df.index[-1]
                    days_since = (today - breakout_date).days
                    if price > breakout_price:
                        rate_now = ((price - df.iloc[-2]['close']) / df.iloc[-2]['close']) * 100
                        rate_vs_breakout = ((price - breakout_price) / breakout_price) * 100
                        send(
                            f"🔺 종가돌파: {code.replace('KRW-', '')} {format_price(price)}원 {rate_now:+.2f}% "
                            f"(D+{days_since} {format_price(breakout_price)} {rate_vs_breakout:+.2f}%)"
                        )
                        green_flag[code] = True
                        del breakout_cache[code]

        for code in list(green_flag):
            if not green_flag[code]: continue
            price = pyupbit.get_current_price(code)
            df = get_data(code)
            if df is None or len(df) < 2: continue
            cur = df.iloc[-1]
            bd = cur.get('BBD')
            ma = cur.get('MA7')
            if pd.isna(bd) or pd.isna(ma): continue
            if price < bd or price < ma:
                green_flag[code] = False

        time.sleep(3)

# ⏱️ 30분마다 시장 스캔 및 알림
def status_loop():
    while True:
        scan_market()
        send_status()
        time.sleep(1800)

# 🧩 실행부
if __name__ == '__main__':
    keep_alive()
    scan_market()
    time.sleep(5)
    threading.Thread(target=polling_loop).start()
    threading.Thread(target=status_loop).start()
