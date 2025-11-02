import pyupbit
import pandas as pd
import time
import datetime as dt
import requests
import os
from keep_alive import keep_alive

keep_alive()

# 텔레그램 설정
bot_token = os.environ['BOT_TOKEN']
chat_id = os.environ['CHAT_ID']
telegram_url = f'https://api.telegram.org/bot{bot_token}/sendMessage'

def send_message(text):
    print(text)
    requests.post(telegram_url, data={'chat_id': chat_id, 'text': text})

# 시작 메시지
send_message("📡 Upbit 전체 종목 감시 시작\n(일봉 기준 최근 3일 돌파 조건)")

# 종목 리스트
upbit_tickers = pyupbit.get_tickers(fiat="KRW")

# 중복 알림 캐시
alert_cache = {}
last_cache_reset = dt.datetime.now(dt.timezone.utc)

# 감시 루프
while True:
    try:
        now = dt.datetime.now(dt.timezone.utc)
        kst_now = now.astimezone(dt.timezone(dt.timedelta(hours=9)))

        # 4시간마다 캐시 초기화
        if (now - last_cache_reset).total_seconds() > 14400:
            alert_cache.clear()
            last_cache_reset = now

        # 검사 대상 인덱스 결정
        if kst_now.minute == 0 and kst_now.hour in [9, 13, 17, 21]:
            check_d_indices = [2, 1, 0]  # 정각 검사 (새벽 제외)
        else:
            check_d_indices = [0]  # D-0만 실시간 감시

        for ticker in upbit_tickers:
            price = pyupbit.get_current_price(ticker)
            if price is None:
                continue

            link = f"https://upbit.com/exchange?code=CRIX.UPBIT.{ticker}"

            def should_alert(key):
                last = alert_cache.get(key)
                if not last or (now - last).total_seconds() > 1800:
                    alert_cache[key] = now
                    return True
                return False

            # 일봉 기준 조건 계산
            daily_df = pyupbit.get_ohlcv(ticker, interval="day", count=130)
            if daily_df is not None and not daily_df.empty and len(daily_df) >= 130:
                close = daily_df['close']
                ma7 = close.rolling(7).mean()
                ma120 = close.rolling(120).mean()
                std = close.rolling(120).std()
                bbl = ma120 - 2 * std
                bbu = ma120 + 2 * std  # 볼린저 상단

                for i in check_d_indices:
                    prev = -(i + 2)
                    curr = -(i + 1)

                    prev_close = close.iloc[prev]
                    curr_close = close.iloc[curr]
                    prev_bbl = bbl.iloc[prev]
                    curr_bbl = bbl.iloc[curr]
                    prev_bbu = bbu.iloc[prev]
                    curr_bbu = bbu.iloc[curr]
                    curr_ma7 = ma7.iloc[curr]
                    prev_ma120 = ma120.iloc[prev]
                    curr_ma120 = ma120.iloc[curr]

                    # NaN 방어 처리
                    if all(pd.notna(x) for x in [
                        prev_close, curr_close,
                        prev_bbl, curr_bbl,
                        prev_bbu, curr_bbu,
                        curr_ma7, prev_ma120, curr_ma120
                    ]):

                        # 볼린저 하단 + MA7 돌파
                        key_bbl = f"{ticker}_D{i}_bollinger_ma7"
                        if prev_close < prev_bbl and curr_close > curr_bbl and curr_close > curr_ma7:
                            if should_alert(key_bbl):
                                send_message(f"📉 bbl + MA7 돌파 (D-{i}) \n {link}")

                        # MA120 + MA7 돌파
                        key_ma120 = f"{ticker}_D{i}_ma120_ma7"
                        if prev_close < prev_ma120 and curr_close > curr_ma120 and curr_close > curr_ma7:
                            if should_alert(key_ma120):
                                send_message(f"➖ ma120 + MA7 돌파 (D-{i}) \n {link}")

                        # 볼린저 상단 돌파
                        key_bbu = f"{ticker}_D{i}_bollinger_upper"
                        if prev_close < prev_bbu and curr_close > curr_bbu:
                            if should_alert(key_bbu):
                                send_message(f"📈 bbu 돌파 (D-{i}) \n {link}")

            time.sleep(5)

        time.sleep(5)

    except Exception as e:
        send_message(f"❌ 오류 발생: {e}")
        time.sleep(5)
