import pyupbit
import pandas as pd
import time
import datetime as dt
import requests
from keep_alive import keep_alive
import os


keep_alive()

# 텔레그램 설정
bot_token = os.environ['bot_token']
chat_id = os.environ['chat_id']
telegram_url = f'https://api.telegram.org/bot{bot_token}/sendMessage'

def send_message(text):
    print(text)
    requests.post(telegram_url, data={'chat_id': chat_id, 'text': text})

# 볼린저 밴드 계산
def calc_bbu(df):
    if len(df) < 100:
        return None
    ma = df['close'].rolling(100).mean().iloc[-1]
    std = df['close'].rolling(100).std().iloc[-1]
    return ma + 2 * std

def calc_bbl(df):
    if len(df) < 100:
        return None
    ma = df['close'].rolling(100).mean().iloc[-1]
    std = df['close'].rolling(100).std().iloc[-1]
    return ma - 2 * std

# 시작 메시지
send_message("📡 Upbit 전체 종목 감시 시작 (볼린저밴드)")

# 종목 리스트 초기화
upbit_tickers = pyupbit.get_tickers(fiat="KRW")

# 중복 알림 캐시
alert_cache = {}

# 감시 루프
while True:
    try:
        now = dt.datetime.now(dt.timezone.utc)
        print("⏰", now.strftime("%Y-%m-%d %H:%M:%S"))

        for ticker in upbit_tickers:
            price = pyupbit.get_current_price(ticker)
            if price is None:
                continue

            # 시간대별 캔들 데이터
            intervals = ["minute5", "minute15", "minute30", "minute60", "minute240"]
            ohlcv = {i: pyupbit.get_ohlcv(ticker, interval=i, count=120) for i in intervals}

            if any(df is None or df.empty for df in ohlcv.values()):
                continue

            # 볼린저 밴드 계산
            bbu = {i: calc_bbu(df) for i, df in ohlcv.items()}
            bbl = {i: calc_bbl(df) for i, df in ohlcv.items()}

            # Upbit 링크
            link = f"https://upbit.com/exchange?code=CRIX.UPBIT.{ticker}"

            # 중복 알림 체크
            def should_alert(key):
                last = alert_cache.get(key)
                if not last or (now - last).total_seconds() > 1800:
                    alert_cache[key] = now
                    return True
                return False

            # 1시간/4시간 상단 돌파
            if None not in [bbu["minute60"], bbu["minute240"]] and price > bbu["minute60"] and price > bbu["minute240"]:
                key = f"{ticker}_bbu_60_240"
                if should_alert(key):
                    send_message(f"[Upbit] {ticker} 현재가: {price:.0f} 🚀 [1H/4H 상단 돌파]\n📈 {link}")

            # 1시간/4시간 하단 이탈
            if None not in [bbl["minute60"], bbl["minute240"]] and price < bbl["minute60"] and price < bbl["minute240"]:
                key = f"{ticker}_bbl_60_240"
                if should_alert(key):
                    send_message(f"[Upbit] {ticker} 현재가: {price:.0f} ⚠️ [1H/4H 하단 이탈]\n📉 {link}")

            # 5/15/30분 상단 돌파
            if None not in [bbu["minute5"], bbu["minute15"], bbu["minute30"]] and price > bbu["minute5"] and price > bbu["minute15"] and price > bbu["minute30"]:
                key = f"{ticker}_bbu_5_15_30"
                if should_alert(key):
                    send_message(f"[Upbit] {ticker} 현재가: {price:.0f} 🚀 [M5/M15/M30 상단 돌파]\n📈 {link}")

            # 5/15/30분 하단 이탈
            if None not in [bbl["minute5"], bbl["minute15"], bbl["minute30"]] and price < bbl["minute5"] and price < bbl["minute15"] and price < bbl["minute30"]:
                key = f"{ticker}_bbl_5_15_30"
                if should_alert(key):
                    send_message(f"[Upbit] {ticker} 현재가: {price:.0f} ⚠️ [M5/M15/M30 하단 이탈]\n📉 {link}")

            time.sleep(1)

        time.sleep(5)

    except Exception as e:
        send_message(f"❌ 오류 발생: {e}")
        time.sleep(5)

