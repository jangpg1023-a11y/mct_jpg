import asyncio, pyupbit, requests, os, time
from datetime import datetime, timezone
from collections import OrderedDict
from bs4 import BeautifulSoup
from keep_alive import keep_alive

keep_alive()
BOT_TOKEN = os.environ['BOT_TOKEN']
CHAT_ID = os.environ['CHAT_ID']
TELEGRAM_URL = f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage'

ohlcv_cache = OrderedDict()
summary_log = {0: [], 1: [], 2: []}
watchlist = []
MAX_CACHE_SIZE = 300
TTL_SECONDS = 10800  # 3시간

def format_price(price):
    if price >= 10: return f"{price:,.0f}"
    elif price >= 1: return f"{price:,.2f}"
    elif price >= 0.1: return f"{price:,.3f}"
    elif price >= 0.01: return f"{price:,.4f}"
    else: return f"{price:,.5f}"

def send_message(text):
    try:
        requests.post(TELEGRAM_URL, data={'chat_id': CHAT_ID, 'text': text})
    except Exception as e:
        print(f"[텔레그램 오류] {e}")

def get_usdkrw():
    url = "https://finance.naver.com/marketindex/"
    res = requests.get(url)
    soup = BeautifulSoup(res.text, "html.parser")

    today_price = soup.select_one("div.head_info > span.value").text
    today = float(today_price.replace(",", ""))

    diff_text = soup.select_one("div.head_info > span.change").text
    diff = float(diff_text.replace(",", "").replace("+", "").replace("-", ""))
    direction = soup.select_one("div.head_info > span.blind").text

    yesterday = today + diff if "하락" in direction else today - diff
    return today, yesterday
    
def get_bybit_yesterday_rate():
    url = "https://api.bybit.com/v5/market/kline?category=linear&symbol=BTCUSDT&interval=D&limit=2"
    res = requests.get(url)
    data = res.json()
    ohlcv = data.get('result', {}).get('list', [])
    if len(ohlcv) < 2:
        return None
    open_y = float(ohlcv[-2][1])
    close_y = float(ohlcv[-2][4])
    rate = (close_y - open_y) / open_y * 100
    return rate

def get_btc_summary_block():
    usdkrw_today, usdkrw_yesterday = get_usdkrw()

    # 📈 UPBIT
    df = pyupbit.get_ohlcv("KRW-BTC", interval="day", count=2)
    today_open = df.iloc[-1]['open']
    today_close = df.iloc[-1]['close']
    yesterday_open = df.iloc[-2]['open']
    yesterday_close = df.iloc[-2]['close']

    upbit_price = int(today_close)
    upbit_usd = int(upbit_price / usdkrw_today)
    upbit_today_rate = round((today_close - today_open) / today_open * 100, 2)
    upbit_yesterday_rate = round((yesterday_close - yesterday_open) / yesterday_open * 100, 2)

    # 📉 BYBIT
    url = "https://api.bybit.com/v5/market/tickers?category=linear&symbol=BTCUSDT"
    res = requests.get(url).json()
    bybit_data = res['result']['list'][0]

    bybit_usd_float = float(bybit_data['lastPrice'])
    bybit_usd = int(bybit_usd_float)
    bybit_price = int(bybit_usd_float * usdkrw_today)
    bybit_today_rate = round(float(bybit_data['price24hPcnt']) * 100, 2)
    bybit_yesterday_rate = get_bybit_yesterday_rate()

    # ⏱️ 1시간 단위 변화율
    df_hour = pyupbit.get_ohlcv("KRW-BTC", interval="minute60", count=17)
    changes = []
    for i in range(1, 17):
        open_price = df_hour.iloc[i - 1]['close']
        close_price = df_hour.iloc[i]['close']
        rate = round((close_price - open_price) / open_price * 100, 2)
        changes.append(rate)

    # 🧾 메시지 구성
    lines = []
    lines.append(f"📊₿TC info  💱 {usdkrw_today:.1f} ({usdkrw_yesterday:.1f})")
    lines.append(f"UPBIT  {upbit_price / 1e8:.2f}억  {upbit_today_rate:.2f}% ({upbit_yesterday_rate:.2f}%)  ${upbit_usd:,}")
    lines.append(f"BYBIT  {bybit_price / 1e8:.2f}억  {bybit_today_rate:.2f}% ({bybit_yesterday_rate:.2f}%)  ${bybit_usd:,}")
    lines.append("4H rate (1H rate)")

    for i in range(0, len(changes), 4):
        block = changes[i:i+4]
        block_total = round(sum(block), 2)
        block_line = f"{block_total:+.2f}% ({'  '.join([f'{r:+.2f}%' for r in block])})"
        lines.append(block_line)

    return "\n".join(lines)


def get_all_krw_tickers():
    return pyupbit.get_tickers(fiat="KRW")

def set_ohlcv_cache(ticker, df):
    now = time.time()
    expired_keys = [k for k, v in ohlcv_cache.items() if now - v['time'] > TTL_SECONDS]
    for k in expired_keys:
        del ohlcv_cache[k]
    while len(ohlcv_cache) >= MAX_CACHE_SIZE:
        ohlcv_cache.popitem(last=False)
    ohlcv_cache[ticker] = {'df': df, 'time': now}

def get_ohlcv_cached(ticker):
    now = time.time()
    if ticker in ohlcv_cache and now - ohlcv_cache[ticker]['time'] < TTL_SECONDS:
        return ohlcv_cache[ticker]['df']
    try:
        df = pyupbit.get_ohlcv(ticker, interval="day", count=130)
        set_ohlcv_cache(ticker, df)
        return df
    except:
        return None

def calculate_indicators(df):
    close = df['close']
    df['MA7'] = close.rolling(7).mean()
    df['MA120'] = close.rolling(120).mean()
    df['STD120'] = close.rolling(120).std()
    df['BBU'] = df['MA120'] + 2 * df['STD120']
    df['BBD'] = df['MA120'] - 2 * df['STD120']
    return df

def record_summary(day_index, ticker, condition_text, change_str, yesterday_str):
    if day_index in summary_log:
        summary_log[day_index].append(f"{ticker} | {condition_text} | {change_str} | {yesterday_str}")

def check_conditions(ticker, price, day_indexes=[0]):
    df = get_ohlcv_cached(ticker)
    if df is None or len(df) < 125:
        return
    df = calculate_indicators(df)

    open_price = df['open'].iloc[-1]
    change_str = f"{((price - open_price) / open_price) * 100:+.2f}%" if open_price else "N/A"
    yesterday_open = df['open'].iloc[-2]
    yesterday_close = df['close'].iloc[-2]
    yesterday_rate = f"{((yesterday_close - yesterday_open) / yesterday_open) * 100:+.2f}%" if yesterday_open else "N/A"

    for i in day_indexes:
        try:
            idx = -1 - i
            prev = -2 - i
            pc = df['close'].iloc[prev]
            cc = df['close'].iloc[idx]
            ma7p = df['MA7'].iloc[prev]
            ma7c = df['MA7'].iloc[idx]
            ma120p = df['MA120'].iloc[prev]
            ma120c = df['MA120'].iloc[idx]
            bbdp = df['BBD'].iloc[prev]
            bbdc = df['BBD'].iloc[idx]
            bbup = df['BBU'].iloc[prev]
            bbuc = df['BBU'].iloc[idx]
        except:
            continue

        if pc < bbdp and pc < ma7p and cc > bbdc and cc > ma7c:
            record_summary(i, ticker, "BBD", change_str, yesterday_rate)
        if pc < ma120p and pc < ma7p and cc > ma120c and cc > ma7c:
            record_summary(i, ticker, "MA", change_str, yesterday_rate)
        if pc < bbup and cc > bbuc:
            record_summary(i, ticker, "BBU", change_str, yesterday_rate)

def send_past_summary():
    emoji_map = {"BBD": "📉", "MA": "➖", "BBU": "📈"}
    day_labels = {0: "🔥 D-day ━━", 1: "⏳ D+1 ━━", 2: "⌛ D+2 ━━"}
    msg = get_btc_summary_block() + "\n\n"
    msg += f"📊 Summary (UTC {datetime.now(timezone.utc).strftime('%m/%d %H:%M')})\n\n"

    # 종목 등장 횟수 계산
    symbol_counts = {}
    for i in [0, 1, 2]:
        for entry in summary_log.get(i, []):
            parts = entry.split(" | ")
            if len(parts) == 4:
                symbol = parts[0].replace("KRW-", "")
                symbol_counts[symbol] = symbol_counts.get(symbol, 0) + 1

    # 날짜별 출력
    for i in [0, 1, 2]:
        entries = summary_log.get(i, [])

        # 상승/하락 종목 수 및 비율 계산
        up_count = 0
        down_count = 0
        for entry in entries:
            parts = entry.split(" | ")
            if len(parts) == 4:
                _, _, change, _ = parts
                try:
                    rate = float(change.replace('%', '').replace('+', ''))
                    if rate > 0:
                        up_count += 1
                    elif rate < 0:
                        down_count += 1
                except:
                    continue

        total = up_count + down_count
        if total > 0:
            up_ratio = round(up_count / total * 100, 1)
            msg += f"{day_labels[i]} {up_ratio}% ({up_count} / {down_count})\n"
        else:
            msg += f"{day_labels[i]} 상승/하락 종목 없음\n"

        # 조건별 그룹화
        grouped = {"BBD": {}, "MA": {}, "BBU": {}}
        for entry in entries:
            parts = entry.split(" | ")
            if len(parts) == 4:
                symbol, condition, change, yest = parts
                symbol = symbol.replace("KRW-", "")
                if condition in grouped:
                    grouped[condition][symbol] = (change, yest)

        # 조건별 출력
        for condition in ["BBD", "MA", "BBU"]:
            symbols = grouped[condition]
            if symbols:
                max_len = max(len(s) for s in symbols)
                sorted_items = sorted(
                    symbols.items(),
                    key=lambda x: float(x[1][0].replace('%', '').replace('+', '')) if x[1][0] != "N/A" else -999,
                    reverse=True
                )
                msg += f"      {emoji_map[condition]} {condition}:\n"
                for s, (change, yest) in sorted_items:
                    count = symbol_counts.get(s, 0)
                    yest_part = f"({yest})"
                    if count == 2:
                        yest_part += " 🟢"
                    elif count >= 3:
                        yest_part += " 🔴"
                    msg += f"            {s:<{max_len}}  {change:>8} {yest_part}\n"
        msg += "\n"

    send_message(msg.strip())

async def d0_loop():
    while True:
        summary_log[0] = []
        for ticker in watchlist:
            price = pyupbit.get_current_price(ticker) or 0
            check_conditions(ticker, price, day_indexes=[0])
            await asyncio.sleep(0.5)
        send_past_summary()
        await asyncio.sleep(60 * 5)  # 5분 주기

async def analyze_past_conditions():
    summary_log[1] = []
    summary_log[2] = []
    for ticker in watchlist:
        price = pyupbit.get_current_price(ticker) or 0
        check_conditions(ticker, price, day_indexes=[1, 2])
        await asyncio.sleep(0.5)

async def daily_summary_loop():
    while True:
        await analyze_past_conditions()
        send_past_summary()
        await asyncio.sleep(60 * 60 * 3)  # 3시간 주기

async def main():
    global watchlist
    watchlist = get_all_krw_tickers()
    send_message("📡 종목 감시 시작")

    asyncio.create_task(daily_summary_loop())
    asyncio.create_task(d0_loop())

    while True:
        await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(main())















