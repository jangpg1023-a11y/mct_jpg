import requests
import pandas as pd
import time
from datetime import datetime, timezone

# 텔레그램 설정 (원래 값 유지)
bot_token = '8310701870:AAF_MnWZmzLUcMt83TBNJmQBeIQmubWOaro'
bot_token1 = '6090575536:AAFvYG92OwqX71i3IkcfxMOEN0emgXuq3wE'
chat_id = '7510297803'
chat_id1 = '5092212639'
telegram_url = f'https://api.telegram.org/bot{bot_token}/sendMessage'
telegram_url1 = f'https://api.telegram.org/bot{bot_token1}/sendMessage'

def send_message(text):
    for url, cid in [(telegram_url, chat_id), (telegram_url1, chat_id1)]:
        try:
            requests.post(url, data={'chat_id': cid, 'text': text})
        except Exception as e:
            print(f"❌ 텔레그램 전송 오류: {e}")

def calc_bbu(df):
    if len(df) < 100:
        return None
    ma = df['close'].rolling(100).mean().iloc[-1]
    std = df['close'].rolling(100).std().iloc[-1]
    return ma + 2 * std

def safe_get_json(url):
    try:
        res = requests.get(url)
        if res.status_code == 200 and res.text:
            return res.json()
        else:
            print(f"❌ API 응답 오류: {res.status_code}, 내용: {res.text}")
            return None
    except Exception as e:
        print(f"❌ JSON 파싱 오류: {e}")
        return None

# Upbit 관련 함수
def get_upbit_all_markets():
    url = "https://api.upbit.com/v1/market/all"
    data = safe_get_json(url)
    return [m['market'] for m in data if m['market'].startswith('KRW-')] if data else []

def get_upbit_price(symbol):
    url = f"https://api.upbit.com/v1/ticker?markets={symbol}"
    data = safe_get_json(url)
    return float(data[0]['trade_price']) if data else None

def get_upbit_ohlcv(symbol, interval="minute60", count=120):
    to = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    url = f"https://api.upbit.com/v1/candles/{interval}?market={symbol}&count={count}&to={to}"
    data = safe_get_json(url)
    if not data:
        return pd.DataFrame()
    df = pd.DataFrame(data)[['candle_date_time_kst','opening_price','high_price','low_price','trade_price','candle_acc_trade_volume']]
    df.columns = ['timestamp','open','high','low','close','volume']
    df[['open','high','low','close','volume']] = df[['open','high','low','close','volume']].astype(float)
    return df.sort_values('timestamp')

# Bybit 관련 함수
def get_bybit_all_symbols(category="linear"):
    url = f"https://api.bybit.com/v5/market/tickers?category={category}"
    data = safe_get_json(url)
    return [item['symbol'] for item in data['result']['list']] if data else []

def get_bybit_price(symbol, category):
    url = f"https://api.bybit.com/v5/market/tickers?category={category}&symbol={symbol}"
    data = safe_get_json(url)
    return float(data['result']['list'][0]['lastPrice']) if data else None

def get_bybit_ohlcv(symbol, category, interval="60", limit=120):
    url = f"https://api.bybit.com/v5/market/kline?category={category}&symbol={symbol}&interval={interval}&limit={limit}"
    data = safe_get_json(url)
    ohlcv_list = data.get('result', {}).get('list', []) if data else []
    if not ohlcv_list:
        return pd.DataFrame()
    df = pd.DataFrame(ohlcv_list, columns=['timestamp','open','high','low','close','volume','turnover'])
    df[['open','high','low','close','volume']] = df[['open','high','low','close','volume']].astype(float)
    return df.sort_values('timestamp')

# 감시 로직
def monitor(symbols, get_price_fn, get_ohlcv_fn, label):
    for symbol in symbols:
        price = get_price_fn(symbol)
        df60 = get_ohlcv_fn(symbol, interval="60")
        df240 = get_ohlcv_fn(symbol, interval="240")
        df_day = get_ohlcv_fn(symbol, interval="D") if label.startswith("Bybit") else get_ohlcv_fn(symbol, interval="day")
        if df60.empty or df240.empty or df_day.empty or price is None:
            continue
        bbu60 = calc_bbu(df60)
        bbu240 = calc_bbu(df240)
        bbu_day = calc_bbu(df_day)
        if None not in [bbu60, bbu240, bbu_day] and price > bbu60 and price > bbu240 and price > bbu_day:
            send_message(f"[{label}] {symbol} 현재가: {price:.2f} → 볼린저 상단 돌파!")
        time.sleep(0.3)

# 시작 메시지
send_message("📡 Upbit + Bybit 전체 종목 감시 시작 (1시간, 4시간, 일봉 기준)")

# 종목 리스트 초기화
upbit_symbols = get_upbit_all_markets()
bybit_futures = get_bybit_all_symbols("linear")
bybit_spot = get_bybit_all_symbols("spot")

# 감시 루프
while True:
    try:
        print("⏰", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"))
        monitor(upbit_symbols, get_upbit_price, lambda s, interval: get_upbit_ohlcv(s, interval), "Upbit")
        monitor(bybit_futures, lambda s: get_bybit_price(s, "linear"), lambda s, interval: get_bybit_ohlcv(s, "linear", interval), "Bybit 선물")
        monitor(bybit_spot, lambda s: get_bybit_price(s, "spot"), lambda s, interval: get_bybit_ohlcv(s, "spot", interval), "Bybit 현물")
        time.sleep(5)
    except Exception as e:
        send_message(f"❌ 전체 루프 오류 발생: {e}")
        time.sleep(5)
