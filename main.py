import requests
import pandas as pd
import time
import datetime as dt
from keep_alive import keep_alive
keep_alive()

# 텔레그램 설정
bot_token = '8310701870:AAF_MnWZmzLUcMt83TBNJmQBeIQmubWOaro'
chat_id = '7510297803'
telegram_url = f'https://api.telegram.org/bot{bot_token}/sendMessage'

def send_message(text):
    print(text)  # 콘솔 출력
    requests.post(telegram_url, data={'chat_id': chat_id, 'text': text})

# 볼린저 밴드 상단 계산
def calc_bbu(df):
    if len(df) < 100:
        return None
    ma = df['close'].rolling(100).mean().iloc[-1]
    std = df['close'].rolling(100).std().iloc[-1]
    return ma + 2 * std

# 볼린저 밴드 하단 계산
def calc_bbl(df):
    if len(df) < 100:
        return None
    ma = df['close'].rolling(100).mean().iloc[-1]
    std = df['close'].rolling(100).std().iloc[-1]
    return ma - 2 * std

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

# 시작 메시지
send_message("📡 Upbit 전체 종목 감시 시작 (볼린저밴드)")

# 종목 리스트 초기화
upbit_symbols = get_upbit_all_markets()

# 중복 알림 캐시
alert_cache = {}

# 감시 루프
while True:
    try:
        now = dt.datetime.now(dt.timezone.utc)
        print("⏰", now.strftime("%Y-%m-%d %H:%M:%S"))

        for symbol in upbit_symbols:
            price = get_upbit_price(symbol)
            df5 = get_upbit_ohlcv(symbol, interval="minute5")
            df15 = get_upbit_ohlcv(symbol, interval="minute15")
            df30 = get_upbit_ohlcv(symbol, interval="minute30")
            df60 = get_upbit_ohlcv(symbol, interval="minute60")
            df240 = get_upbit_ohlcv(symbol, interval="minute240")

            if any(df.empty for df in [df5, df15, df30, df60, df240]) or price is None:
                continue

            # 볼린저 밴드 계산
            bbu5, bbl5 = calc_bbu(df5), calc_bbl(df5)
            bbu15, bbl15 = calc_bbu(df15), calc_bbl(df15)
            bbu30, bbl30 = calc_bbu(df30), calc_bbl(df30)
            bbu60, bbl60 = calc_bbu(df60), calc_bbl(df60)
            bbu240, bbl240 = calc_bbu(df240), calc_bbl(df240)

            # 거래량 필터링 (최근 5분 평균 거래량 기준)
            avg_vol = df5['volume'].tail(5).mean()
            if avg_vol < 1000:
                continue

            # Upbit 링크 생성
            link = f"https://upbit.com/exchange?code=CRIX.UPBIT.{symbol}"

            # 중복 알림 체크 함수
            def should_alert(key):
                last = alert_cache.get(key)
                if not last or (now - last).total_seconds() > 1800:  # 30분
                    alert_cache[key] = now
                    return True
                return False

            # 1시간/4시간 상단 돌파
            if None not in [bbu60, bbu240] and price > bbu60 and price > bbu240:
                key = f"{symbol}_bbu_60_240"
                if should_alert(key):
                    alert = f"[Upbit] {symbol} 현재가: {price:.0f} 🚀 [1H/4H 상단 돌파]\n📈 {link}"
                    print(alert)
                    send_message(alert)

            # 1시간/4시간 하단 이탈
            if None not in [bbl60, bbl240] and price < bbl60 and price < bbl240:
                key = f"{symbol}_bbl_60_240"
                if should_alert(key):
                    alert = f"[Upbit] {symbol} 현재가: {price:.0f} ⚠️ [1H/4H 하단 이탈]\n📉 {link}"
                    print(alert)
                    send_message(alert)

            # 5/15/30분 상단 돌파
            if None not in [bbu5, bbu15, bbu30] and price > bbu5 and price > bbu15 and price > bbu30:
                key = f"{symbol}_bbu_5_15_30"
                if should_alert(key):
                    alert = f"[Upbit] {symbol} 현재가: {price:.0f} 🚀 [M5/M15/M30 상단 돌파]\n📈 {link}"
                    print(alert)
                    send_message(alert)

            # 5/15/30분 하단 이탈
            if None not in [bbl5, bbl15, bbl30] and price < bbl5 and price < bbl15 and price < bbl30:
                key = f"{symbol}_bbl_5_15_30"
                if should_alert(key):
                    alert = f"[Upbit] {symbol} 현재가: {price:.0f} ⚠️ [M5/M15/M30 하단 이탈]\n📉 {link}"
                    print(alert)
                    send_message(alert)

            time.sleep(1)

        time.sleep(5)

    except Exception as e:
        alert = f"❌ 오류 발생: {e}"
        print(alert)
        send_message(alert)
        time.sleep(5)

