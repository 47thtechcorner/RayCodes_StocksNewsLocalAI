"""Indian Stock Alert Bot — yfinance + Ollama LLM + Telegram"""
import os, json, time, signal, logging, requests, yfinance as yf
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()
TOKEN, CHAT_ID = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
CFG = json.load(open("config.json"))
OLLAMA, running = "http://localhost:11434/api/generate", True
logging.basicConfig(format="%(asctime)s | %(message)s", datefmt="%H:%M:%S", level=logging.INFO)
log = logging.getLogger(__name__)

def stop(s, f): global running; log.info("🛑 Shutting down..."); running = False
signal.signal(signal.SIGINT, stop); signal.signal(signal.SIGBREAK, stop)

def fetch_stock(ticker):
    t = yf.Ticker(ticker); info = t.info
    price = info.get("currentPrice") or info.get("regularMarketPrice", 0)
    prev = info.get("previousClose") or info.get("regularMarketPreviousClose", 0)
    chg = round(((price - prev) / prev) * 100, 2) if prev else 0
    hist = t.history(period="5d")
    avg_v = int(hist["Volume"].mean()) if not hist.empty else 0
    w52h, w52l = info.get("fiftyTwoWeekHigh", 0), info.get("fiftyTwoWeekLow", 0)
    cur = "$" if "USD" in ticker.upper() else "₹"
    news = []
    for n in t.news[:3]:
        title = n.get("title") or n.get("content", {}).get("title")
        if title: news.append(title)
        
    # Fallback for NIFTYBEES
    if not news and ticker == "NIFTYBEES.NS":
        try:
            nt = yf.Ticker("^NSEI")
            for n in nt.news[:3]:
                title = n.get("title") or n.get("content", {}).get("title")
                if title: news.append(title)
        except: pass

    return {"name": info.get("shortName", ticker), "price": price, "chg": chg,
            "high": info.get("dayHigh", 0), "low": info.get("dayLow", 0),
            "w52h": w52h, "w52l": w52l, "vol": info.get("volume", 0), "avg_v": avg_v, "cur": cur, "news": news}

def llm_insight(d):
    c, news_str = d['cur'], " | ".join(d['news']) if d['news'] else "No recent news."
    prompt = (f"Stock: {d['name']} @ {c}{d['price']}, 1D chg {d['chg']:+.2f}%, "
              f"Day H/L {c}{d['high']}/{c}{d['low']}, 52W H/L {c}{d['w52h']}/{c}{d['w52l']}, "
              f"Vol {d['vol']:,} vs 5D avg {d['avg_v']:,}. News: {news_str}. "
              f"Output format: 'Sentiment: [Bullish/Bearish/Neutral] | Insight: [2-line trading insight]'. No preamble.")
    try:
        resp = requests.post(OLLAMA, json={"model": CFG["llm_model"], "prompt": prompt, "stream": False}, timeout=120).json().get("response", "N/A").strip()
        if " | " in resp:
            parts = resp.split(" | ", 1)
            sent = parts[0].replace("Sentiment:", "").strip()
            insight = parts[1].replace("Insight:", "").strip()
            return sent, insight
        return "Neutral", resp
    except Exception as e: return "Unknown", f"⚠️ LLM unavailable: {e}"

def format_and_send(d, analysis):
    sentiment, insight = analysis
    icon, c, vr = "🟢" if d["chg"] >= 0 else "🔴", d["cur"], round(d["vol"] / d["avg_v"], 2) if d["avg_v"] else 0
    s_icon = "🔥" if "Bullish" in sentiment else "❄️" if "Bearish" in sentiment else "⚖️"
    
    # Format Headlines
    news_list = list(dict.fromkeys(d['news']))[:3]
    news_section = f"🗞️ *Latest News:*\n" + "\n".join([f"• {h}" for h in news_list]) + "\n━━━━━━━━━━━━━━━━━━\n" if news_list else ""
    
    msg = (f"📊 *{d['name']}* — {datetime.now().strftime('%I:%M %p IST')}\n"
           f"━━━━━━━━━━━━━━━━━━\n"
           f"{news_section}"
           f"{s_icon} *AI Sentiment:* {sentiment}\n"
           f"🧠 *Insight:* {insight}\n"
           f"━━━━━━━━━━━━━━━━━━\n"
           f"💰 Price: {c}{d['price']:,.2f} ({icon} {d['chg']:+.2f}%)\n"
           f"{'🔥' if vr > 1.3 else '📊'} Volume: {d['vol']:,} ({vr}x 5D avg)\n"
           f"━━━━━━━━━━━━━━━━━━")
    
    try: requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=15); log.info("✅ Sent")
    except Exception as e: log.error(f"❌ TG failed: {e}")

if __name__ == "__main__":
    log.info("🚀 Stock Bot started — Ctrl+C to stop")
    while running:
        for tk in CFG["stocks"]:
            if not running: break
            try: log.info(f"📡 {tk}..."); d = fetch_stock(tk); log.info(f"   {d['name']}={d['cur']}{d['price']:,.2f} ({d['chg']:+.2f}%)"); format_and_send(d, llm_insight(d))
            except Exception as e: log.error(f"Error [{tk}]: {e}")
        if running:
            log.info(f"💤 Next in {CFG['interval_seconds']}s...")
            for _ in range(CFG["interval_seconds"]):
                if not running: break
                time.sleep(1)
    log.info("👋 Bot stopped.")
