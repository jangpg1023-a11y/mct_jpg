import asyncio, pyupbit, requests, os, time
from datetime import datetime, timedelta, timezone
from collections import OrderedDict
from bs4 import BeautifulSoup
from keep_alive import keep_alive

keep_alive()
BOT_TOKEN = os.environ['BOT_TOKEN']
CHAT_ID = os.environ['CHAT_ID']
TELEGRAM_URL = f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage'

ohlcv_cache = OrderedDict()
summary_log = {0: [], 1: [], 2: []}
MAX_CACHE_SIZE = 300
TTL_SECONDS = 10800  # 3시간

def send_message(text):
    try:
        res = requests.post(TELEGRAM_URL, data={'chat_id': CHAT_ID, 'text': text})
        print("텔레그램 응답:", res.status_code, res.text)
    except Exception as e:
        print(f"[텔레그램 오류] {e}")

def get_tick_size(price):
    if price >= 2_000_000: return 1000
    elif price >= 1_000_000: return 1000
    elif price >= 500_000: return 500
    elif price >= 100_000: return 100
    elif price >= 50_000: return 50
    elif price >= 10_000: return 10
    elif price >= 5_000: return 5
    elif price >= 1_000: return 1
    elif price >= 100: return 1
    elif price >= 10: return 0.1
    elif price >= 1: return 0.01
    elif price >= 0.1: return 0.001
    elif price >= 0.01: return 0.0001
    elif price >= 0.001: return 0.00001
    elif price >= 0.0001: return 0.000001
    elif price >= 0.00001: return 0.0000001
    else: return 0.00000001

def get_usdkrw():
    try:
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
    except Exception as e:
        print("❌ 환율 오류:", e)
        return 1350.0, 1350.0

def get_bybit_day_rates():
    try:
        today_date = datetime.now(timezone.utc).date().strftime("%Y-%m-%d")
        yesterday_date = (datetime.now(timezone.utc).date() - timedelta(days=1)).strftime("%Y-%m-%d")
        url = "https://api.bybit.com/v5/market/kline?category=linear&symbol=BTCUSDT&interval=D&limit=10"
        res = requests.get(url)
        data = res.json()
        ohlcv = data.get('result', {}).get('list', [])
        today_rate = yesterday_rate = today_close = 0.0

        for candle in ohlcv:
            ts = int(candle[0]) // 1000
            candle_date = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
            if candle_date == today_date:
                open_t = float(candle[1])
                close_t = float(candle[4])
                today_rate = round((close_t - open_t) / open_t * 100, 2)
                today_close = close_t
            elif candle_date == yesterday_date:
                open_y = float(candle[1])
                close_y = float(candle[4])
                yesterday_rate = round((close_y - open_y) / open_y * 100, 2)

        return today_rate, yesterday_rate, today_close
    except Exception as e:
        print("❌ BYBIT 일별 변동률 오류:", e)
        return 0.0, 0.0, 0.0

def get_btc_summary_block():
    try:
        usdkrw_today, usdkrw_yesterday = get_usdkrw()
        df = pyupbit.get_ohlcv("KRW-BTC", interval="day", count=2)
        if df is None or len(df) < 2:
            raise ValueError("UPBIT 일봉 데이터 부족")

        today_open = df.iloc[-1]['open']
        today_close = df.iloc[-1]['close']
        yesterday_open = df.iloc[-2]['open']
        yesterday_close = df.iloc[-2]['close']
        upbit_price = int(today_close)
        upbit_usd = int(upbit_price / usdkrw_today)
        upbit_today_rate = round((today_close - today_open) / today_open * 100, 2)
        upbit_yesterday_rate = round((yesterday_close - yesterday_open) / yesterday_open * 100, 2)

        bybit_today_rate, bybit_yesterday_rate, bybit_close = get_bybit_day_rates()
        bybit_price_krw = int(bybit_close * usdkrw_today)
        bybit_price_usd = int(bybit_close)

        df_hour = pyupbit.get_ohlcv("KRW-BTC", interval="minute60", count=17)
        if df_hour is None or len(df_hour) < 17:
            raise ValueError("UPBIT 시간봉 데이터 부족")

        changes = []
        for i in range(1, 17):
            open_price = df_hour.iloc[i - 1]['close']
            close_price = df_hour.iloc[i]['close']
            rate = round((close_price - open_price) / open_price * 100, 2)
            changes.append(rate)

        lines = [
            f"📊₿TC info  💱 {usdkrw_today:.1f} ({usdkrw_yesterday:.1f})",
            f"UPBIT  {upbit_price / 1e8:.2f}억  {upbit_today_rate:+.2f}% ({upbit_yesterday_rate:+.2f}%)  ${upbit_usd:,}",
            f"BYBIT  {bybit_price_krw / 1e8:.2f}억  {bybit_today_rate:+.2f}% ({bybit_yesterday_rate:+.2f}%)  ${bybit_price_usd:,}",
            "4H rate (1H rate)"
        ]
        for i in range(0, len(changes), 4):
            block = changes[i:i+4]
            block_total = round(sum(block), 2)
            block_line = f"{block_total:+.2f}% ・{'  '.join([f'{r:+.2f}.' for r in block])}"
            lines.append(block_line)

        return "\n".join(lines)
    except Exception as e:
        return f"❌ BTC 요약 오류: {e}"

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
    if day_index not in summary_log:
        summary_log[day_index] = []
    entries = summary_log[day_index]
    tickers_in_log = [entry.split(" | ")[0] for entry in entries]
    if ticker not in tickers_in_log:
        entry = f"{ticker} | {condition_text} | {change_str} | {yesterday_str}"
        entries.append(entry)

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

def get_updown_ratio_by_day(day_offset):
    tickers = get_all_krw_tickers()
    up_count = down_count = 0

    for ticker in tickers:
        try:
            df = get_ohlcv_cached(ticker)
            if df is None or len(df) < day_offset + 2:
                continue

            row = df.iloc[-(day_offset + 1)]
            open_price = row['open']
            close_price = row['close']
            if open_price == 0:
                continue

            rate = (close_price - open_price) / open_price * 100
            if rate > 0:
                up_count += 1
            elif rate < 0:
                down_count += 1
        except Exception as e:
            print(f"❌ {ticker} 오류: {e}")
            continue

    total = up_count + down_count
    if total > 0:
        up_ratio = round(up_count / total * 100, 1)
        return f"{up_ratio}% ({up_count} / {down_count})"
    else:
        return ""

def send_past_summary():
    emoji_map = {"BBD": "📉", "MA": "➖", "BBU": "📈"}
    day_labels = {0: "🔥 D-day ━━", 1: "⏳ D+1 ━━", 2: "⌛ D+2 ━━"}
    msg = get_btc_summary_block() + "\n\n"
    msg += f"📊 Summary (UTC {datetime.now(timezone.utc).strftime('%m/%d %H:%M')})\n\n"

    symbol_counts = {}
    for i in [0, 1, 2]:
        for entry in summary_log.get(i, []):
            parts = entry.split(" | ")
            if len(parts) == 4:
                symbol = parts[0].replace("KRW-", "")
                symbol_counts[symbol] = symbol_counts.get(symbol, 0) + 1

    for i in [0, 1, 2]:
        entries = summary_log.get(i, [])
        ratio_text = get_updown_ratio_by_day(i)
        msg += f"{day_labels[i]} {ratio_text}\n"

        grouped = {"BBD": {}, "MA": {}, "BBU": {}}
        for entry in entries:
            parts = entry.split(" | ")
            if len(parts) == 4:
                symbol, condition, change, yest = parts
                symbol = symbol.replace("KRW-", "")
                if condition in grouped:
                    grouped[condition][symbol] = (change, yest)

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
        for ticker in watchlist:
            try:
                price = pyupbit.get_current_price(ticker) or 0
                check_conditions(ticker, price, day_indexes=[0])
            except Exception as e:
                print(f"가격 조회 실패: {ticker} - {e}")
            await asyncio.sleep(0.5)

        summary_log[0] = []  # 전송 후 초기화
        await asyncio.sleep(3600)  # 1시간

async def analyze_past_conditions():
    summary_log[1] = []
    summary_log[2] = []
    for ticker in watchlist:
        df = get_ohlcv_cached(ticker)
        price = df['close'].iloc[-1] if df is not None else 0
        check_conditions(ticker, price, day_indexes=[1, 2])
        await asyncio.sleep(0.5)

async def daily_summary_loop():
    while True:
        await analyze_past_conditions()
        send_past_summary()
        await asyncio.sleep(3600)  # 1시간

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


