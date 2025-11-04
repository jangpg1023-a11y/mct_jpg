import asyncio
import websockets
import json
import pyupbit
import requests
import os
from datetime import datetime
from keep_alive import keep_alive

keep_alive()

BOT_TOKEN = os.environ['BOT_TOKEN']
CHAT_ID = os.environ['CHAT_ID']
TELEGRAM_URL = f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage'

def send_message(text):
    try:
        requests.post(TELEGRAM_URL, data={'chat_id': CHAT_ID, 'text': text})
    except:
        pass

alert_cache = {}

def should_alert(key, limit=1800):
    now = datetime.now().timestamp()
    last = alert_cache.get(key, 0)
    if now - last > limit:
        alert_cache[key] = now
        return True
    return False

def check_condition(ticker, price):
    df = pyupbit.get_ohlcv(ticker, interval="day", count=130)
    if df is None or len(df) < 120:
        return

    close = df['close']
    ma120 = close.rolling(120).mean().iloc[-1]
    if price > ma120:
        key = f"{ticker}_ma120"
        if should_alert(key):
            send_message(f"📈 {ticker} MA120 돌파!\n현재가: {price:,}\nhttps://upbit.com/exchange?code=CRIX.UPBIT.{ticker}")

async def run_ws():
    uri = "wss://api.upbit.com/websocket/v1"
    tickers = pyupbit.get_tickers(fiat="KRW")
    subscribe = [
        {"ticket": "ticker"},
        {"type": "ticker", "codes": tickers},
        {"format": "DEFAULT"}
    ]

    async with websockets.connect(uri) as ws:
        await ws.send(json.dumps(subscribe))
        while True:
            try:
                data = await ws.recv()
                parsed = json.loads(data)
                ticker = parsed['code']
                price = parsed['trade_price']
                check_condition(ticker, price)
            except:
                await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(run_ws())
