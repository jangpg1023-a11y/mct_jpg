import websocket
import json
import pyupbit
import pandas as pd
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

send_message("📡 WebSocket 기반 감시 시작")

# 종목 리스트
tickers = pyupbit.get_tickers(fiat="KRW")
ticker_codes = [f"KRW-{t.split('-')[1]}" if '-' in t else t for t in tickers]

# 알림 캐시
alert_cache = {}

def should_alert(key):
    now = dt.datetime.now()
    last = alert_cache.get(key)
    if not last or (now - last).total_seconds() > 1800:
        alert_cache[key] = now
        return True
    return False

def check_conditions(ticker, price):
    df = pyupbit.get_ohlcv(ticker, interval="day", count=130)
    weekly_df = pyupbit.get_ohlcv(ticker, interval="week", count=3)

    if df is None or weekly_df is None or len(df) < 130 or len(weekly_df) < 2:
        return

    close = df['close']
    ma7 = close.rolling(7).mean()
    ma120 = close.rolling(120).mean()
    std = close.rolling(120).std()
    bbd = ma120 - 2 * std
    bbu = ma120 + 2 * std

    last_week_open = weekly_df['open'].iloc[-2]
    last_week_close = weekly_df['close'].iloc[-2]
    is_weekly_bullish = last_week_close > last_week_open or price > last_week_close

    for i in [0]:  # 실시간이므로 D-0만 검사
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
                    send_message(f"📉 BBD + MA7 돌파 (D-{i})\n{ticker}\n{link}")

            key_ma120 = f"{ticker}_D{i}_ma120_ma7"
            if prev_close < prev_ma120 and curr_close > curr_ma120 and curr_close > curr_ma7:
                if should_alert(key_ma120):
                    send_message(f"➖ MA120 + MA7 돌파 (D-{i})\n{ticker}\n{link}")

            key_bbu = f"{ticker}_D{i}_bollinger_upper"
            if prev_close < prev_bbu and curr_close > curr_bbu:
                if should_alert(key_bbu):
                    send_message(f"📈 BBU 상단 돌파 (D-{i})\n{ticker}\n{link}")

def on_message(ws, message):
    data = json.loads(message)[0]
    code = data['code'].replace('KRW-', 'KRW-')
    price = data['trade_price']
    check_conditions(code, price)

def on_open(ws):
    payload = [{
        "ticket": "test",
    }, {
        "type": "trade",
        "codes": [f"KRW-{t.split('-')[1]}" for t in tickers],
    }]
    ws.send(json.dumps(payload))

ws = websocket.WebSocketApp(
    "wss://api.upbit.com/websocket/v1",
    on_message=on_message,
    on_open=on_open
)

ws.run_forever()
