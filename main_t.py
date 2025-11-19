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

# 📦 캐시 및 설정
ohlcv_cache = OrderedDict()
MAX_CACHE = 300
TTL = 3600

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
    if price >= 2_000_000: return 1000
    elif price >= 1_000_000: return 1000
    elif price >= 500_000: return 500
    elif price >= 100_000: return 100
    elif price >= 50_000: return 50
    elif price >= 10_000: return 10
    elif price >= 5_000: return 5
    elif price >= 1_000: return 1
    elif price >= 100: return 1
    elif price >= 10: return 0.1
    elif price >= 1: return 0.01
    elif price >= 0.1: return 0.001
    elif price >= 0.01: return 0.0001
    elif price >= 0.001: return 0.00001
    elif price >= 0.0001: return 0.000001
    elif price >= 0.00001: return 0.0000001
    else: return 0.00000001

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

# 🧠 전략 스캔 및 출력
def scan_status():
    msg = "📊 감시 종목\n"
    watch_lines = []
    support_lines = []
    reversal_lines = []

    tickers = pyupbit.get_tickers(fiat="KRW")
    for t in tickers:
        df = get_data(t)
        if df is None or len(df) < 10:
            continue

        cur = df.iloc[-1]
        prev = df.iloc[-2]
        p = pyupbit.get_current_price(t)
        bd = cur.get('BBD')
        ma = cur.get('MA7')
        name = t.replace("KRW-", "")
        if p is None or pd.isna(bd) or pd.isna(ma):
            continue

        # 오늘 상승률
        change = ((p - prev['close']) / prev['close']) * 100

        # 전일 상승률
        if len(df) >= 3:
            prev_change = ((prev['close'] - df.iloc[-3]['close']) / df.iloc[-3]['close']) * 100
        else:
            prev_change = 0.0

        breakout_close = None
        breakout_date = None
        days_since = None

        # 돌파 탐색: 과거 MA7 & BBD 동시 돌파
        for i in range(-2, -10, -1):
            if abs(i) >= len(df):
                continue
            row = df.iloc[i]
            prev_row = df.iloc[i - 1]
            if pd.isna([row['BBD'], row['MA7'], prev_row['BBD'], prev_row['MA7']]).any():
                continue
            if prev_row['close'] < prev_row['BBD'] and prev_row['close'] < prev_row['MA7']:
                if row['close'] > row['BBD'] and row['close'] > row['MA7']:
                    breakout_close = row['close']
                    breakout_date = df.index[i]
                    days_since = (df.index[-1] - breakout_date).days
                    break

        # 전환 조건: 전일 종가가 지지선 위 + 오늘 저가가 지지선 아래
        is_reversal = False
        if prev['close'] > prev['BBD'] and prev['close'] > prev['MA7']:
            if cur['low'] < cur['BBD'] and cur['low'] < cur['MA7']:
                is_reversal = True

        # 지지 조건: 돌파 이후 + 전환 제외 + 현재가가 MA7 or BBD 위
        is_support = False
        if breakout_close and not is_reversal:
            if p > cur['MA7'] or p > cur['BBD']:
                is_support = True

        # 녹색불 조건: 전략별 분기
        is_green = False
        if breakout_close:
            if is_support:
                if p > breakout_close:
                    is_green = True
            elif p > breakout_close and p > cur['MA7'] and p > cur['BBD']:
                is_green = True

        # 감시 조건: 전일 종가가 지지선 아래 + 오늘 상승
        if prev['close'] < prev['BBD'] and prev['close'] < prev['MA7'] and change > 0:
            flag = " 🟢" if is_green else ""
            watch_lines.append((
                change,
                f"{name}: {format_price(p)}원 {change:+.2f}% ({prev_change:+.2f}%)" + flag
            ))

        # 지지 종목
        if is_support and days_since is not None:
            flag = " 🟢" if is_green else ""
            support_lines.append((
                change,
                f"{name}: {format_price(p)}원 {change:+.2f}% ({prev_change:+.2f}%) (D+{days_since})" + flag
def scan_status():
    msg = "📊 감시 종목\n"
    watch_lines = []
    support_lines = []
    reversal_lines = []

    tickers = pyupbit.get_tickers(fiat="KRW")
    for t in tickers:
        df = get_data(t)
        if df is None or len(df) < 10:
            continue

        cur = df.iloc[-1]
        prev = df.iloc[-2]
        p = pyupbit.get_current_price(t)
        bd = cur.get('BBD')
        ma = cur.get('MA7')
        name = t.replace("KRW-", "")
        if p is None or pd.isna(bd) or pd.isna(ma):
            continue

        # 오늘 상승률
        change = ((p - prev['close']) / prev['close']) * 100

        # 전일 상승률
        if len(df) >= 3:
            prev_change = ((prev['close'] - df.iloc[-3]['close']) / df.iloc[-3]['close']) * 100
        else:
            prev_change = 0.0

        breakout_close = None
        breakout_date = None
        days_since = None

        # 돌파 탐색: 과거 MA7 & BBD 동시 돌파
        for i in range(-2, -10, -1):
            if abs(i) >= len(df):
                continue
            row = df.iloc[i]
            prev_row = df.iloc[i - 1]
            if pd.isna([row['BBD'], row['MA7'], prev_row['BBD'], prev_row['MA7']]).any():
                continue
            if prev_row['close'] < prev_row['BBD'] and prev_row['close'] < prev_row['MA7']:
                if row['close'] > row['BBD'] and row['close'] > row['MA7']:
                    breakout_close = row['close']
                    breakout_date = df.index[i]
                    days_since = (df.index[-1] - breakout_date).days
                    break

        # 전환 조건: 전일 종가가 지지선 위 + 오늘 저가가 지지선 아래
        is_reversal = False
        if prev['close'] > prev['BBD'] and prev['close'] > prev['MA7']:
            if cur['low'] < cur['BBD'] and cur['low'] < cur['MA7']:
                is_reversal = True

        # 지지 조건: 돌파 이후 + 전환 제외 + 현재가가 MA7 or BBD 위
        is_support = False
        if breakout_close and not is_reversal:
            if p > cur['MA7'] or p > cur['BBD']:
                is_support = True

        # 녹색불 조건: 전략별 분기
        is_green = False
        if is_support and breakout_close and p > breakout_close:
            is_green = True
        elif is_reversal and p > cur['MA7'] and p > cur['BBD']:
            is_green = True
        elif not is_support and not is_reversal and p > cur['MA7'] and p > cur['BBD']:
            is_green = True  # 감시 종목

        # 감시 조건: 전일 종가가 지지선 아래 + 오늘 상승
        if prev['close'] < prev['BBD'] and prev['close'] < prev['MA7'] and change > 0:
            flag = " 🟢" if is_green else ""
            watch_lines.append((
                change,
                f"{name}: {format_price(p)}원 {change:+.2f}% ({prev_change:+.2f}%)" + flag
            ))

        # 지지 종목
        if is_support and days_since is not None:
            flag = " 🟢" if is_green else ""
            support_lines.append((
                change,
                f"{name}: {format_price(p)}원 {change:+.2f}% ({prev_change:+.2f}%) (D+{days_since})" + flag
            ))

        # 전환 종목
        if is_reversal:
            flag = " 🟢" if is_green else ""
            reversal_lines.append((
                change,
                f"{name}: {format_price(p)}원 {change:+.2f}% ({prev_change:+.2f}%)" + flag
            ))

    for _, line in sorted(watch_lines, key=lambda x: x[0], reverse=True):
        msg += line + "\n"

    msg += "\n📌 지지 종목\n"
    for _, line in sorted(support_lines, key=lambda x: x[0], reverse=True):
        msg += line + "\n"

    msg += "\n📉 전환 종목\n"
    for _, line in sorted(reversal_lines, key=lambda x: x[0], reverse=True):
        msg += line + "\n"

    send(msg.strip())
    
# ⏱️ 루프 실행
def status_loop():
    while True:
        scan_status()
        time.sleep(3600)

# 🧩 실행부
if __name__ == '__main__':
    keep_alive()
    time.sleep(5)
    threading.Thread(target=status_loop).start()




