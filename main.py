import requests
import pandas as pd
import time
import datetime as dt
from keep_alive import keep_alive
keep_alive()

# 텔레그램 설정 (당신 방식 유지)
bot_token = '8310701870:AAF_MnWZmzLUcMt83TBNJmQBeIQmubWOaro'
bot_token1 = '6090575536:AAFvYG92OwqX71i3IkcfxMOEN0emgXuq3wE'
chat_id = '7510297803'
chat_id1 = '5092212639'
telegram_url = f'https://api.telegram.org/bot{bot_token}/sendMessage'
telegram_url1 = f'https://api.telegram.org/bot{bot_token1}/sendMessage'

def send_message(text):
    requests.post(telegram_url, data={'chat_id': chat_id, 'text': text})
    requests.post(telegram_url1, data={'chat_id': chat_id1, 'text': text})

# 볼린저 밴드 상단 계산
def calc_bbu(df):
    if len(df) < 100:
        return None
    ma = df['close'].rolling(100).mean().iloc[-1]
    std = df['close'].rolling(100).std().iloc[-1]
    return ma + 2 * std

# Upbit 전체 종목 가져오기
def get_upbit_all_markets():
    url = "https://api.upbit.com/v1/market/all"
    res = requests.get(url)
    markets = res.json()
    return [m['market'] for m in markets if m['market'].startswith('KRW-')]

# Upbit 현재가
def get_upbit_price(symbol):
    try:
        url = f"https://api.upbit.com/v1/ticker?markets={symbol}"
        res = requests.get(url)
        return float(res.json()[0]['trade_price'])
    except Exception as e:
        print(f"❌ 오류 발생: {e}")
        return None


# Upbit OHLCV
def get_upbit_ohlcv(symbol, interval="minute60", count=120):
    try:
        to = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        url = f"https://api.upbit.com/v1/candles/{interval}?market={symbol}&count={count}&to={to}"
        res = requests.get(url)
        data = res.json()
        df = pd.DataFrame(data)
        df = df[['candle_date_time_kst','opening_price','high_price','low_price','trade_price','candle_acc_trade_volume']]
        df.columns = ['timestamp','open','high','low','close','volume']
        df[['open','high','low','close','volume']] = df[['open','high','low','close','volume']].astype(float)
        df = df.sort_values('timestamp')
        return df
    except:
        return pd.DataFrame()

# Bybit 전체 종목 가져오기
def get_bybit_all_symbols(category="linear"):
    url = f"https://api.bybit.com/v5/market/tickers?category={category}"
    res = requests.get(url)
    data = res.json()
    return [item['symbol'] for item in data['result']['list']]

# Bybit 현재가
def get_bybit_price(symbol, category):
    try:
        url = f"https://api.bybit.com/v5/market/tickers?category={category}&symbol={symbol}"
        res = requests.get(url)
        return float(res.json()['result']['list'][0]['lastPrice'])
    except:
        return None

# Bybit OHLCV
def get_bybit_ohlcv(symbol, category, interval="60", limit=120):
    try:
        url = f"https://api.bybit.com/v5/market/kline?category={category}&symbol={symbol}&interval={interval}&limit={limit}"
        res = requests.get(url)
        data = res.json()
        ohlcv_list = data.get('result', {}).get('list', [])
        df = pd.DataFrame(ohlcv_list)
        df.columns = ['timestamp','open','high','low','close','volume','turnover']
        df[['open','high','low','close','volume']] = df[['open','high','low','close','volume']].astype(float)
        df = df.sort_values('timestamp')
        return df
    except:
        return pd.DataFrame()

# 시작 메시지
send_message("📡 Upbit + Bybit 전체 종목 감시 시작 (1시간, 4시간, 일봉 기준)")

# 종목 리스트 초기화
upbit_symbols = get_upbit_all_markets()
bybit_futures = get_bybit_all_symbols("linear")
bybit_spot = get_bybit_all_symbols("spot")

# 감시 루프
while True:
    try:
        now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        send_message("⏰", now)
        print("⏰", now)

        # Upbit 감시
        for symbol in upbit_symbols:
            price = get_upbit_price(symbol)
            df60 = get_upbit_ohlcv(symbol, interval="minute60")
            df240 = get_upbit_ohlcv(symbol, interval="minute240")
            df_day = get_upbit_ohlcv(symbol, interval="day")
            if df60.empty or df240.empty or df_day.empty or price is None:
                continue
            bbu60 = calc_bbu(df60)
            bbu240 = calc_bbu(df240)
            bbu_day = calc_bbu(df_day)
            if None not in [bbu60, bbu240, bbu_day] and price > bbu60 and price > bbu240 and price > bbu_day:
                send_message(f"[Upbit] {symbol} 현재가: {price:.0f} → 볼린저 상단 돌파!")
            time.sleep(0.5)

        # Bybit 선물 감시
        for symbol in bybit_futures:
            price = get_bybit_price(symbol, category="linear")
            df60 = get_bybit_ohlcv(symbol, category="linear", interval="60")
            df240 = get_bybit_ohlcv(symbol, category="linear", interval="240")
            df_day = get_bybit_ohlcv(symbol, category="linear", interval="D")
            if df60.empty or df240.empty or df_day.empty or price is None:
                continue
            bbu60 = calc_bbu(df60)
            bbu240 = calc_bbu(df240)
            bbu_day = calc_bbu(df_day)
            if None not in [bbu60, bbu240, bbu_day] and price > bbu60 and price > bbu240 and price > bbu_day:
                send_message(f"[Bybit 선물] {symbol} 현재가: {price:.2f} → 볼린저 상단 돌파!")
            time.sleep(0.5)

        # Bybit 현물 감시
        for symbol in bybit_spot:
            price = get_bybit_price(symbol, category="spot")
            df60 = get_bybit_ohlcv(symbol, category="spot", interval="60")
            df240 = get_bybit_ohlcv(symbol, category="spot", interval="240")
            df_day = get_bybit_ohlcv(symbol, category="spot", interval="D")
            if df60.empty or df240.empty or df_day.empty or price is None:
                continue
            bbu60 = calc_bbu(df60)
            bbu240 = calc_bbu(df240)
            bbu_day = calc_bbu(df_day)
            if None not in [bbu60, bbu240, bbu_day] and price > bbu60 and price > bbu240 and price > bbu_day:
                send_message(f"[Bybit 현물] {symbol} 현재가: {price:.2f} → 볼린저 상단 돌파!")
            time.sleep(0.5)

        time.sleep(1)

    except Exception as e:
        send_message(f"❌ 오류 발생: {e}")
        time.sleep(1)


