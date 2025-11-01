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
    try:
        requests.post(telegram_url, data={'chat_id': chat_id, 'text': text})
    except Exception as e:
        print(f"텔레그램 전송 오류: {e}")

# 볼린저 밴드 계산
def calc_bb(df, upper=True):
    if df is None or len(df) < 100:
        return None
    ma = df['close'].rolling(100).mean()
    std = df['close'].rolling(100).std()
    if pd.isna(ma.iloc[-1]) or pd.isna(std.iloc[-1]):
        return None
    return ma.iloc[-1] + 2 * std.iloc[-1] if upper else ma.iloc[-1] - 2 * std.iloc[-1]

# 알림 캐시
alert_cache = {}

def should_alert(key, now, interval=1800):
    last = alert_cache.get(key)
    if not last or (now - last).total_seconds() > interval:
        alert_cache[key] = now
        return True
    return False

def check_and_alert(ticker, price, now, condition_key, condition_text, link):
    if should_alert(condition_key, now):
        send_message(f"[Upbit] {ticker} 현재가: {price:.0f} {condition_text}\n📈 {link}")

# 시작 메시지
send_message("📡 Upbit 전체 종목 감시 시작 (볼린저밴드 + MA100 일봉 돌파)")

# 종목 리스트
upbit_tickers = pyupbit.get_tickers(fiat="KRW")

# 캐시 초기화 타이머
last_cache_reset_time = time.time()
CACHE_RESET_INTERVAL = 3600  # 1시간

# 감시 루프
while True:
    try:
        now = dt.datetime.now(dt.timezone.utc)

        # 캐시 초기화 체크
        if time.time() - last_cache_reset_time > CACHE_RESET_INTERVAL:
            alert_cache.clear()
            last_cache_reset_time = time.time()
            send_message("🔄 1시간 경과: 알림 캐시 초기화 완료")

        for ticker in upbit_tickers:
            try:
                price = pyupbit.get_current_price(ticker)
                if price is None:
                    continue

                link = f"https://upbit.com/exchange?code=CRIX.UPBIT.{ticker}"

                # 캔들 데이터 수집
                intervals = ["minute5", "minute15", "minute30", "minute60", "minute240"]
                ohlcv_data = {}
                for i in intervals:
                    df = pyupbit.get_ohlcv(ticker, interval=i, count=120)
                    ohlcv_data[i] = df if df is not None and not df.empty else None

                # 볼린저 밴드 계산
                bbu = {i: calc_bb(ohlcv_data[i], upper=True) for i in intervals}
                bbl = {i: calc_bb(ohlcv_data[i], upper=False) for i in intervals}

                # 조건 체크
                if all(bbu[i] is not None for i in ["minute60", "minute240"]) and price > bbu["minute60"] and price > bbu["minute240"]:
                    check_and_alert(ticker, price, now, f"{ticker}_bbu_60_240", "🚀 [1H/4H 상단 돌파]", link)

                if all(bbl[i] is not None for i in ["minute60", "minute240"]) and price < bbl["minute60"] and price < bbl["minute240"]:
                    check_and_alert(ticker, price, now, f"{ticker}_bbl_60_240", "⚠️ [1H/4H 하단 이탈]", link)

                if all(bbu[i] is not None for i in ["minute5", "minute15", "minute30"]) and price > bbu["minute5"] and price > bbu["minute15"] and price > bbu["minute30"]:
                    check_and_alert(ticker, price, now, f"{ticker}_bbu_5_15_30", "🚀 [M5/M15/M30 상단 돌파]", link)

                if all(bbl[i] is not None for i in ["minute5", "minute15", "minute30"]) and price < bbl["minute5"] and price < bbl["minute15"] and price < bbl["minute30"]:
                    check_and_alert(ticker, price, now, f"{ticker}_bbl_5_15_30", "⚠️ [M5/M15/M30 하단 이탈]", link)

                # MA100 일봉 돌파
                daily_df = pyupbit.get_ohlcv(ticker, interval="day", count=120)
                if daily_df is not None and len(daily_df) >= 101:
                    ma100 = daily_df['close'].rolling(100).mean()
                    prev_ma = ma100.iloc[-2]
                    curr_ma = ma100.iloc[-1]
                    prev_close = daily_df['close'].iloc[-2]
                    curr_close = daily_df['close'].iloc[-1]

                    if prev_close < prev_ma and curr_close > curr_ma:
                        check_and_alert(ticker, curr_close, now, f"{ticker}_ma100_daily_cross", "📈 일봉 MA100 상향 돌파!", link)

                time.sleep(0.3)

            except Exception as e:
                print(f"{ticker} 처리 중 오류: {e}")
                continue

        time.sleep(5)

    except Exception as e:
        send_message(f"❌ 전체 루프 오류 발생: {e}")
        time.sleep(10)
