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
    requests.post(telegram_url, data={'chat_id': chat_id, 'text': text})

send_message("📡 Upbit 전체 종목 감시 시작\n(일봉 기준 최근 3일 돌파 조건 + 주봉 양봉 필터)")

upbit_tickers = pyupbit.get_tickers(fiat="KRW")

alert_cache = {}
last_cache_reset = None
force_full_scan = True  # 재시작 시 강제 검사

bbd_dict = {2: [], 1: [], 0: []}
ma120_dict = {2: [], 1: [], 0: []}
bbu_dict = {2: [], 1: [], 0: []}

while True:
    try:
        now = dt.datetime.now(dt.timezone.utc)
        kst_now = now.astimezone(dt.timezone(dt.timedelta(hours=9)))

        # 캐시 초기화 및 요약 알림
        if last_cache_reset and (now - last_cache_reset).total_seconds() > 14400:
            alert_cache.clear()

            def format_dict(title, data_dict):
                lines = []
                for d in [2, 1, 0]:
                    if data_dict[d]:
                        tickers = ", ".join(data_dict[d])
                        lines.append(f"- D-{d}: {tickers}")
                return f"\n{title}:\n" + "\n".join(lines) if lines else ""

            summary = "📊 [4시간 요약 알림]\n"
            summary += format_dict("📉 BBD + MA7 돌파", bbd_dict)
            summary += format_dict("➖ MA120 + MA7 돌파", ma120_dict)
            summary += format_dict("📈 BBU 상단 돌파", bbu_dict)

            if summary.strip() != "📊 [4시간 요약 알림]":
                send_message(summary)

            bbd_dict = {2: [], 1: [], 0: []}
            ma120_dict = {2: [], 1: [], 0: []}
            bbu_dict = {2: [], 1: [], 0: []}
            last_cache_reset = now
            force_full_scan = True  # 다음 루프에서 강제 검사

        # 검사 대상 인덱스 결정
        if force_full_scan:
            check_d_indices = [2, 1, 0]
            force_full_scan = False
        elif last_cache_reset and (now - last_cache_reset).total_seconds() < 60:
            check_d_indices = [2, 1, 0]
        else:
            check_d_indices = [0]

        for ticker in upbit_tickers:
            price = pyupbit.get_current_price(ticker)
            if price is None or price < 1:
                continue

            link = f"https://upbit.com/exchange?code=CRIX.UPBIT.{ticker}"

            def should_alert(key):
                last = alert_cache.get(key)
                if not last or (now - last).total_seconds() > 1800:
                    alert_cache[key] = now
                    return True
                return False

            daily_df = pyupbit.get_ohlcv(ticker, interval="day", count=130)
            weekly_df = pyupbit.get_ohlcv(ticker, interval="week", count=3)

            if (
                daily_df is not None and not daily_df.empty and len(daily_df) >= 130 and
                weekly_df is not None and len(weekly_df) >= 2
            ):
                close = daily_df['close']
                ma7 = close.rolling(7).mean()
                ma120 = close.rolling(120).mean()
                std = close.rolling(120).std()
                bbd = ma120 - 2 * std
                bbu = ma120 + 2 * std

                # 주봉 양봉 여부 확인 (지난 주 또는 이번 주 현재가 기준)
                last_week_open = weekly_df['open'].iloc[-2]
                last_week_close = weekly_df['close'].iloc[-2]
                is_weekly_bullish = (
                    last_week_close > last_week_open or
                    price > last_week_close
                )

                for i in check_d_indices:
                    prev = -(i + 2)
                    curr = -(i + 1)

                    prev_close = close.iloc[prev]
                    curr_close = close.iloc[curr]
                    prev_bbd = bbd.iloc[prev]
                    curr_bbd = bbd.iloc[curr]
                    prev_bbu = bbu.iloc[prev]
                    curr_bbu = bbu.iloc[curr]
                    curr_ma7 = ma7.iloc[curr]
                    prev_ma120 = ma120.iloc[prev]
                    curr_ma120 = ma120.iloc[curr]

                    if all(pd.notna(x) for x in [
                        prev_close, curr_close,
                        prev_bbd, curr_bbd,
                        prev_bbu, curr_bbu,
                        curr_ma7, prev_ma120, curr_ma120
                    ]):
                        key_bbd = f"{ticker}_D{i}_bbd_ma7"
                        if is_weekly_bullish and prev_close < prev_bbd and curr_close > curr_bbd and curr_close > curr_ma7:
                            if should_alert(key_bbd):
                                bbd_dict[i].append(ticker)
                                send_message(f"📉 BBD + MA7 돌파 (D-{i})\n{link}")

                        key_ma120 = f"{ticker}_D{i}_ma120_ma7"
                        if prev_close < prev_ma120 and curr_close > curr_ma120 and curr_close > curr_ma7:
                            if should_alert(key_ma120):
                                ma120_dict[i].append(ticker)
                                send_message(f"➖ MA120 + MA7 돌파 (D-{i})\n{link}")

                        key_bbu = f"{ticker}_D{i}_bollinger_upper"
                        if prev_close < prev_bbu and curr_close > curr_bbu:
                            if should_alert(key_bbu):
                                bbu_dict[i].append(ticker)
                                send_message(f"📈 BBU 상단 돌파 (D-{i})\n{{link}")

            time.sleep(10)

        time.sleep(10)

    except Exception:
        time.sleep(10)
