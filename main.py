import time
import requests
from growwapi import GrowwAPI
from openai import OpenAI
from bs4 import BeautifulSoup
import re
import schedule, time
import os

GROWW_API_TOKEN = os.environ.get('GROWW_API_TOKEN')
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')
NEWSAPI_KEY  = os.environ.get('NEWSAPI_KEY')
AGENT_ERWIN_BOT = os.environ.get('AGENT_ERWIN_BOT')
CHAT_ID = os.environ.get('CHAT_ID')

groww = GrowwAPI(GROWW_API_TOKEN)

def get_news(symbol, n=10):
    url = (f"https://newsapi.org/v2/everything?q={symbol}&apiKey={NEWSAPI_KEY}"
           f"&language=en&pageSize={n}&sortBy=publishedAt")
    try:
        data = requests.get(url).json()
        # Only keep the last 7 days’ news for relevance
        news_items = []
        for a in data.get("articles", []):
            published = a.get("publishedAt", "")
            title = a.get("title", "")
            description = a.get("description", "")
            url_link = a.get("url", "")
            news_items.append(f"{title} — {description[:70]}... {url_link}")
        return news_items[:n]
    except Exception as e:
        print("News error:", e)
        return []


def get_price_history(symbol, days=30):
    end_time = int(time.time() * 1000)
    start_time = end_time - (days * 24 * 60 * 60 * 1000)
    candles = groww.get_historical_candle_data(
        trading_symbol=symbol,
        exchange="NSE",
        segment="CASH",
        start_time=start_time,
        end_time=end_time,
        interval_in_minutes=15
    )
    closes = [c[4] for c in candles['candles']]
    return closes[-7:] if len(closes) >= 7 else closes

def get_sector_yahoo(symbol):
    url = f"https://finance.yahoo.com/quote/{symbol}.NS/profile?p={symbol}.NS"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        resp = requests.get(url, headers=headers, timeout=8)
        soup = BeautifulSoup(resp.text, "html.parser")
        labels = soup.find_all("span")
        for idx, span in enumerate(labels):
            if "Sector" in span.text:
                return labels[idx+1].text.strip()
    except Exception as e:
        print("Sector fallback failed for", symbol, ":", e)
    return "Unknown"

def get_fundamentals_screener(symbol):
    url = f"https://www.screener.in/company/{symbol}/consolidated/"
    headers = {"User-Agent": "Mozilla/5.0"}
    fundamentals = {}
    try:
        resp = requests.get(url, headers=headers, timeout=8)
        soup = BeautifulSoup(resp.text, "html.parser")
        ratio_map = {"ROE": "ROE", "P/E": "PE", "EPS": "EPS", "Profit growth": "Profit Growth"}
        for li in soup.select('li.flex.flex-space-between'):
            key = li.find('span', {'class': 'name'}).text.strip()
            val = li.find('span', {'class': 'number'}).text.strip()
            if key in ratio_map:
                fundamentals[ratio_map[key]] = val
    except Exception as e:
        print(f"Screener fallback failed for {symbol}:", e)
    return fundamentals

def get_fundamentals_yahoo(symbol):
    url = f"https://finance.yahoo.com/quote/{symbol}.NS/key-statistics?p={symbol}.NS"
    headers = {"User-Agent": "Mozilla/5.0"}
    fundamentals = {}
    try:
        resp = requests.get(url, headers=headers, timeout=8)
        soup = BeautifulSoup(resp.text, "html.parser")
        text = soup.get_text()
        roe_match = re.search(r"Return on Equity.*?([0-9.]+%)", text)
        pe_match = re.search(r"Trailing P/E.*?([0-9.,]+)", text)
        eps_match = re.search(r"EPS \(TTM\).*?([0-9.,]+)", text)
        if roe_match:
            fundamentals["ROE"] = roe_match.group(1)
        if pe_match:
            fundamentals["PE"] = pe_match.group(1)
        if eps_match:
            fundamentals["EPS"] = eps_match.group(1)
    except Exception as e:
        print(f"Yahoo fallback failed for {symbol}: {e}")
    return fundamentals

def summarize_and_score_news(news_list):
    if not news_list:
        return "No relevant news.", "neutral"
    prompt = (
        "You are a financial news analyst. Summarize the following news headlines for an Indian stock. "
        "Highlight major events (earnings, big wins/losses, management changes, legal/regulatory issues). "
        "Rate the overall news sentiment as positive, negative, or neutral. "
        "NEWS HEADLINES:\n" + "\n".join(news_list)
    )
    client = OpenAI(api_key=OPENAI_API_KEY)
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=180,
        temperature=0.2,
    )
    content = response.choices[0].message.content.strip()
    # Optionally parse sentiment if you want to show as emoji
    sentiment = "neutral"
    if "positive" in content.lower():
        sentiment = "positive"
    elif "negative" in content.lower():
        sentiment = "negative"
    return content, sentiment


def get_profit_growth_screener(symbol):
    url = f"https://www.screener.in/company/{symbol}/consolidated/"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        resp = requests.get(url, headers=headers, timeout=8)
        soup = BeautifulSoup(resp.text, "html.parser")
        growth_table = soup.find('table', class_='data-table')
        if not growth_table:
            return "N/A"
        for row in growth_table.find_all('tr'):
            th = row.find('th')
            if th and "Profit growth" in th.text:
                td = row.find('td')
                if td:
                    return td.text.strip()
    except Exception as e:
        print(f"Screener profit growth fallback failed for {symbol}: {e}")
    return "N/A"

def get_live_data(symbol):
    try:
        quote = groww.get_quote(
            exchange="NSE",
            segment="CASH",
            trading_symbol=symbol
        )
        ltp = quote.get("last_price")
        high_52 = quote.get("week_52_high")
        low_52 = quote.get("week_52_low")
        return ltp, high_52, low_52
    except Exception as e:
        print(f"Live data fetch failed for {symbol}:", e)
        return None, None, None

def get_fundamentals(symbol):
    f1 = get_fundamentals_screener(symbol)
    f2 = get_fundamentals_yahoo(symbol)
    fundamentals = {}
    fundamentals['ROE'] = f1.get('ROE') or f2.get('ROE') or "N/A"
    fundamentals['PE'] = f1.get('PE') or f2.get('PE') or "N/A"
    fundamentals['EPS'] = f1.get('EPS') or f2.get('EPS') or "N/A"
    fundamentals['Profit Growth'] = f1.get('Profit Growth') or get_profit_growth_screener(symbol) or "N/A"
    return fundamentals

def summarize_momentum(closes):
    if not closes or len(closes) < 2:
        return "Insufficient data"
    pct = 100 * (closes[-1] - closes[0]) / closes[0]
    if pct > 5: return f"Uptrend (+{pct:.1f}%)"
    if pct < -5: return f"Downtrend ({pct:.1f}%)"
    return f"Sideways ({pct:.1f}%)"

def build_llm_prompt(symbol, sector, news_summary, closes, fundamentals):
    # Extract values from the fundamentals dict
    roe = fundamentals.get('ROE', 'N/A')
    pe = fundamentals.get('PE', 'N/A')
    eps = fundamentals.get('EPS', 'N/A')
    pg = fundamentals.get('Profit Growth', 'N/A')
    high = fundamentals.get('52W High', 'N/A')
    low = fundamentals.get('52W Low', 'N/A')
    # Price momentum and closes
    price_str = ", ".join([str(round(c,2)) for c in closes])
    momentum = summarize_momentum(closes)

    prompt = (
        f"You are a senior Indian equity analyst. Given these FACTS for {symbol} (Sector: {sector}):\n"
        f"• Key Ratios: ROE={roe}, PE={pe}, EPS={eps}, Profit Growth={pg}, 52W High={high}, 52W Low={low}\n"
        f"• Price Momentum: {momentum}, last 7 closes: {price_str}\n"
        f"• News Summary: {news_summary}\n"
        "Give a clear and professional VERDICT (Buy/Sell/Hold, Entry price, Target, Stop if needed, Risk stars 1-5). "
        "Explain rationale in 2-3 lines, referencing both fundamentals, price trend, and news sentiment. "
        "NO company description. NO indecisive language. If any factor is missing, estimate from sector/peers. "
        "If risk/valuation is high, call it out. If conflicting factors, show a yellow flag. Format as an analyst summary report."
    )
    return prompt


def format_verdict(symbol, verdict, sector, fundamentals, closes, ltp, high_52, low_52):
    icon = "🟢" if "buy" in verdict.lower() else "🔴" if "sell" in verdict.lower() else "⏸️"
    roe = fundamentals.get('ROE', 'N/A')
    pe = fundamentals.get('PE', 'N/A')
    eps = fundamentals.get('EPS', 'N/A')
    pg = fundamentals.get('Profit Growth', 'N/A')
    price_str = ", ".join([str(round(c,2)) for c in closes])
    momentum = summarize_momentum(closes)
    vline = verdict.splitlines()[0] if verdict else ""
    fblock = (
        f"{icon} <b>{symbol}</b> | <i>Sector:</i> <b>{sector}</b>\n"
        f"<b>Verdict:</b> {vline}\n"
        f"<b>Key:</b> ROE={roe}, PE={pe}, EPS={eps}, ProfitG={pg}, 52W:{low_52}-{high_52}\n"
        f"<b>Current Price:</b> {ltp}\n"
        f"<b>Momentum:</b> {momentum}\n"
        f"<b>Last 7 closes:</b> <code>{price_str}</code>\n"
        f"{verdict}\n"
        + "-" * 40)
    return fblock

def send_report_block(text):
    url = f'https://api.telegram.org/bot{AGENT_ERWIN_BOT}/sendMessage'
    try:
        resp = requests.get(url, params={
            'chat_id': CHAT_ID,
            'text': text,
            'parse_mode': 'HTML'
        })
        print("Telegram response:", resp.json())
    except Exception as e:
        print("Telegram send error:", e)

def main():
    print("hELLO LAVDE")
    holdings_response = groww.get_holdings_for_user(timeout=8)
    print("Holdings response received:", holdings_response)  # <-- ADD THIS
    stocks = holdings_response['holdings']
    print("Stocks to process:", stocks) 
    header = "<b>📊 AI Deep Dive Stock Report (Pro Version)</b>"
    send_report_block(header)
    client = OpenAI(api_key=OPENAI_API_KEY)
    for h in stocks:
        sym = h['trading_symbol']
        news_list = get_news(sym, n=10)
        news_summary, news_sentiment = summarize_and_score_news(news_list)
        closes = get_price_history(sym)
        fundamentals = get_fundamentals(sym)
        sector = get_sector_yahoo(sym)
        ltp, high_52, low_52 = get_live_data(sym)
        
        # Always inject Groww 52W values if present
        fundamentals['52W High'] = high_52 if high_52 not in [None, '', 'N/A'] else fundamentals.get('52W High', 'N/A')
        fundamentals['52W Low']  = low_52  if low_52 not in [None, '', 'N/A'] else fundamentals.get('52W Low', 'N/A')
        
        prompt = build_llm_prompt(sym, sector, news_summary, closes, fundamentals)
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=350,
            temperature=0.22,
        )
        verdict = response.choices[0].message.content.strip()
        report_block = format_verdict(sym, verdict, sector, fundamentals, closes, ltp, high_52, low_52)
        if len(report_block) > 4000:
            report_block = report_block[:3990] + "…"
        send_report_block(report_block)
        print(f"\n--- {sym} ---\nPrompt:\n{prompt}\n----\nVerdict:\n{verdict}\n")


if __name__ == "__main__":
    main()