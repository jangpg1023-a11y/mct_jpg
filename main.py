import asyncio, websockets, json, pyupbit, requests, os
from datetime import datetime

# ──────────────── 텔레그램 설정 ────────────────
BOT_TOKEN = os.environ['BOT_TOKEN']
CHAT_ID = os.environ['CHAT_ID']
TELEGRAM_URL = f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage'

def send_message(text):
    try:
        requests.post(TELEGRAM_URL, data={'chat_id': CHAT_ID, 'text': text})
    except Exception as e:
        print(f"[텔레그램 오류] {e}")

# ──────────────── 지표 계산 및 전송 ────────────────
def send_jst_indicators(price):
    ticker = "KRW-JST"
    df = pyupbit.get_ohlcv(ticker, interval="day", count=130)
    if df is None or len(df) < 125:
        send_message("⚠️ KRW-JST 데이터 부족")
        return

    # 지표 계산
    df['MA7'] = df['close'].rolling(7).mean()
    df['MA120'] = df['close'].rolling(120).mean()
    df['STD120'] = df['close'].rolling(120).std()
    df['BBU'] = df['MA120'] + 2 * df['STD120']
    df['BBD'] = df['MA120'] - 2 * df['STD120']

    msg = f"📊 KRW-JST 지표 요약 ({datetime.now().strftime('%m/%d %H:%M')})\n"
    msg += f"💰 실시간 가격: {price:,.0f}\n"
    for i in [2, 1, 0]:
        idx = -1 - i
        try:
            date = df.index[idx].strftime('%Y-%m-%d')
            close = df['close'].iloc[idx]
            ma7 = df['MA7'].iloc[idx]
            ma120 = df['MA120'].iloc[idx]
            bbu = df['BBU'].iloc[idx]
            bbd = df['BBD'].iloc[idx]
            msg += f"\n📆 D-{i} ({date})\n"
            msg += f"• 종가: {close:,.0f}\n"
            msg += f"• MA7: {ma7:,.0f}\n"
            msg += f"• MA120: {ma120:,.0f}\n"
            msg += f"• BBU: {bbu:,.0f}\n"
            msg += f"• BBD: {bbd:,.0f}\n"
        except:
            msg += f"\n📆 D-{i} 지표 계산 실패\n"

    send_message(msg)

# ──────────────── 웹소켓 수신 ────────────────
async def run_ws():
    uri = "wss://api.upbit.com/websocket/v1"
    try:
        async with websockets.connect(uri) as ws:
            subscribe = [{"ticket": "test"}, {"type": "ticker", "codes": ["KRW-JST"]}]
            await ws.send(json.dumps(subscribe))
            while True:
                data = await ws.recv()
                msg = json.loads(data)
                price = msg['trade_price']
                send_jst_indicators(price)
                await asyncio.sleep(1800)  # 30분마다 전송
    except Exception as e:
        print(f"[웹소켓 오류] {e}")
        await asyncio.sleep(5)
        await run_ws()

# ──────────────── 실행 ────────────────
if __name__ == "__main__":
    asyncio.run(run_ws())
