import pyupbit
import pandas as pd
import datetime as dt
import requests
import os
import time
from keep_alive import keep_alive

keep_alive()

# 텔레그램 설정
bot_token = os.getenv('BOT_TOKEN')
chat_id = os.getenv('CHAT_ID')
telegram_url = f'https://api.telegram.org/bot{bot_token}/sendMessage'

def send_message(text):
    if bot_token and chat_id:
        requests.post(telegram_url, data={'chat_id': chat_id, 'text': text})
    else:
        print("❌ 텔레그램 환경변수가 누락되었습니다.")

send_message("📡 pyupbit 기반 감시 시작")

# 종목 리스트
tickers = pyupbit.get_tickers(fiat="KRW")

# 알림 캐시
alert_cache = {}

# OHLCV 캐시
ohlcv_cache = {}

def should_alert(key):
    now = dt.datetime.now()
    last = alert_cache.get(key)
    if not last or (now - last).total_seconds() > 1800:
        alert_cache[key] = now
        return True
    return False

def get_ohlcv_cached(ticker, interval, count):
    key = f"{ticker}_{interval}_{count}"
    now = dt.datetime.now()
    cached = ohlcv_cache.get(key)
    if cached and (now - cached['time']).total_seconds() < 300:
        return cached['data']
    df = pyupbit.get_ohlcv(ticker, interval=interval, count=count)
    if df is not None:
        ohlcv_cache[key] = {'data': df, 'time': now}
    return df

def check_conditions(ticker, price):
    df = get_ohlcv_cached(ticker, interval="day", count=130)
    weekly_df = get_ohlcv_cached(ticker, interval="week", count=3)

    if df is None or weekly_df is None or len(df) < 130 or len(weekly_df) < 2:
        return

    close = df['close']
    open_price = df['open'].iloc[-1]
    if pd.isna(open_price) or open_price == 0:
        change_str = "N/A"
    else:
        change_pct = ((price - open_price) / open_price) * 100
        change_str = f"{change_pct:+.2f}%"

    ma7 = close.rolling(7).mean()
    ma120 = close.rolling(120).mean()
    std = close.rolling(120).std()
    bbd = ma120 - 2 * std
    bbu = ma120 + 2 * std

    last_week_open = weekly_df['open'].iloc[-2]
    last_week_close = weekly_df['close'].iloc[-2]
    is_weekly_bullish = last_week_close > last_week_open or price > last_week_close

    for i in [0]:
        prev = -(i + 2)
        curr = -(i + 1)

        try:
            prev_close = close.iloc[prev]
            curr_close = close.iloc[curr]
            prev_bbd = bbd.iloc[prev]
            curr_bbd = bbd.iloc[curr]
            prev_bbu = bbu.iloc[prev]
            curr_bbu = bbu.iloc[curr]
            curr_ma7 = ma7.iloc[curr]
            prev_ma120 = ma120.iloc[prev]
            curr_ma120 = ma120.iloc[curr]
        except:
            continue

        link = f"https://upbit.com/exchange?code=CRIX.UPBIT.{ticker}"

        if all(pd.notna(x) for x in [
            prev_close, curr_close,
            prev_bbd, curr_bbd,
            prev_bbu, curr_bbu,
            curr_ma7, prev_ma120, curr_ma120
        ]):
            key_bbd = f"{ticker}_D{i}_bbd_ma7"
            if is_weekly_bullish and prev_close < prev_bbd and curr_close > curr_bbd and curr_close > curr_ma7:
                if should_alert(key_bbd):
                    send_message(f"📉 BBD + MA7 돌파 (D-{i})\n{ticker}\n현재가: {price:,} {change_str}\n{link}")

            key_ma120 = f"{ticker}_D{i}_ma120_ma7"
            if prev_close < prev_ma120 and curr_close > curr_ma120 and curr_close > curr_ma7:
                if should_alert(key_ma120):
                    send_message(f"➖ MA120 + MA7 돌파 (D-{i})\n{ticker}\n현재가: {price:,} {change_str}\n{link}")

            key_bbu = f"{ticker}_D{i}_bollinger_upper"
            if prev_close < prev_bbu and curr_close > curr_bbu:
                if should_alert(key_bbu):
                    send_message(f"📈 BBU 상단 돌파 (D-{i})\n{ticker}\n현재가: {price:,} {change_str}\n{link}")

# 🔁 주기적 감시 루프
while True:
    try:
        prices = pyupbit.get_current_price(tickers)
        for ticker, price in prices.items():
            if price:
                check_conditions(ticker, price)
        time.sleep(60)  # 1분마다 반복
    except Exception as e:
        print(f"❌ 감시 오류: {e}")
        time.sleep(60)
