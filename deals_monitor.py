import os
import re
import html
import json
import time
import requests
from datetime import datetime
from bs4 import BeautifulSoup

# ====== CONFIG ======
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

MAX_BUDGET = float(os.getenv("MAX_BUDGET", "1000"))
ALERT_TOLERANCE = float(os.getenv("ALERT_TOLERANCE", "50"))
SEND_ALWAYS = os.getenv("SEND_ALWAYS", "true").lower() == "true"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148 Safari/604.1",
    "Accept-Language": "fr-CA,fr;q=0.9,en-CA;q=0.8,en;q=0.7",
}

# Pages de recherche. Ce script lit les pages publiques.
# Certains sites peuvent bloquer les robots; le rapport indiquera les pages non lues.
SEARCH_PAGES = [
    # Best Buy
    ("Best Buy RTX 4050", "https://www.bestbuy.ca/en-ca/search?search=rtx%204050%20laptop", 10),
    ("Best Buy RTX 4060", "https://www.bestbuy.ca/en-ca/search?search=rtx%204060%20laptop", 10),
    ("Best Buy Open Box RTX", "https://www.bestbuy.ca/en-ca/search?search=open%20box%20rtx%204060%20laptop", 10),
    ("Best Buy ThinkPad", "https://www.bestbuy.ca/en-ca/search?search=thinkpad%20laptop", 7),
    ("Best Buy Refurbished laptop", "https://www.bestbuy.ca/en-ca/search?search=refurbished%20laptop%20i7%2016gb", 7),

    # Staples
    ("Staples RTX 4050", "https://www.staples.ca/search?query=rtx%204050%20laptop", 8),
    ("Staples RTX 4060", "https://www.staples.ca/search?query=rtx%204060%20laptop", 8),
    ("Staples ThinkPad", "https://www.staples.ca/search?query=thinkpad%20laptop", 6),

    # Walmart
    ("Walmart RTX 4050", "https://www.walmart.ca/search?q=rtx%204050%20laptop", 6),
    ("Walmart RTX 4060", "https://www.walmart.ca/search?q=rtx%204060%20laptop", 6),
    ("Walmart ThinkPad", "https://www.walmart.ca/search?q=thinkpad%20laptop", 5),
    ("Walmart Refurbished", "https://www.walmart.ca/search?q=refurbished%20laptop%20i7%2016gb", 5),

    # Amazon
    ("Amazon RTX 4050", "https://www.amazon.ca/s?k=rtx+4050+laptop", 6),
    ("Amazon RTX 4060", "https://www.amazon.ca/s?k=rtx+4060+laptop", 6),
    ("Amazon ThinkPad", "https://www.amazon.ca/s?k=thinkpad+laptop", 5),

    # Canada Computers
    ("Canada Computers RTX 4050", "https://www.canadacomputers.com/search/results_details.php?language=en&keywords=rtx+4050+laptop", 8),
    ("Canada Computers RTX 4060", "https://www.canadacomputers.com/search/results_details.php?language=en&keywords=rtx+4060+laptop", 8),
    ("Canada Computers ThinkPad", "https://www.canadacomputers.com/search/results_details.php?language=en&keywords=thinkpad+laptop", 6),

    # Memory Express
    ("Memory Express RTX 4050", "https://www.memoryexpress.com/Search/Products?Search=rtx%204050%20laptop", 7),
    ("Memory Express RTX 4060", "https://www.memoryexpress.com/Search/Products?Search=rtx%204060%20laptop", 7),

    # Newegg
    ("Newegg RTX 4050", "https://www.newegg.ca/p/pl?d=rtx+4050+laptop", 6),
    ("Newegg RTX 4060", "https://www.newegg.ca/p/pl?d=rtx+4060+laptop", 6),
    ("Newegg ThinkPad", "https://www.newegg.ca/p/pl?d=thinkpad+laptop", 5),

    # Official stores / outlets
    ("Lenovo Canada LOQ", "https://www.lenovo.com/ca/en/search?fq=&text=loq%20rtx%204050", 8),
    ("Lenovo Canada Legion", "https://www.lenovo.com/ca/en/search?fq=&text=legion%20rtx%204050", 8),
    ("Lenovo Canada ThinkPad", "https://www.lenovo.com/ca/en/search?fq=&text=thinkpad%20i7%2016gb", 7),
    ("Dell Canada G15", "https://www.dell.com/en-ca/search/g15%20rtx%204050", 7),
    ("Dell Canada Precision", "https://www.dell.com/en-ca/search/precision%20laptop", 7),
    ("HP Canada Victus", "https://www.hp.com/ca-en/shop/sitesearch?keyword=victus%20rtx%204050", 7),
    ("HP Canada ZBook", "https://www.hp.com/ca-en/shop/sitesearch?keyword=zbook", 6),
    ("ASUS Canada TUF", "https://shop.asus.com/ca-en/catalogsearch/result/?q=tuf%20rtx%204050", 7),
    ("Acer Canada Nitro", "https://store.acer.com/en-ca/catalogsearch/result/?q=nitro%20rtx%204050", 7),
    ("MSI Canada Katana", "https://ca.msi.com/search/katana%20rtx%204050", 6),

    # Other Canadian sources
    ("Visions RTX laptop", "https://www.visions.ca/search?q=rtx%204050%20laptop", 5),
    ("PC-Canada laptop", "https://www.pc-canada.com/search.asp?keywords=rtx+4050+laptop", 5),
    ("DirectDial laptop", "https://www.directdial.com/search?q=rtx%204050%20laptop", 5),
    ("eBay Canada ThinkPad", "https://www.ebay.ca/sch/i.html?_nkw=thinkpad+i7+16gb+laptop&_sacat=0&LH_BIN=1&_udhi=1000", 4),
    ("eBay Canada RTX 4050", "https://www.ebay.ca/sch/i.html?_nkw=rtx+4050+laptop&_sacat=0&LH_BIN=1&_udhi=1000", 4),
]

GOOD_TERMS = [
    "rtx 4050", "rtx 4060", "rtx 4070",
    "loq", "legion", "tuf", "rog", "nitro", "predator",
    "victus", "omen", "katana", "sword", "cyborg", "g15", "alienware",
    "thinkpad", "x1 carbon", "x1 extreme", "thinkbook",
    "precision", "xps", "zbook", "elitebook", "proart", "surface laptop",
    "macbook air m", "macbook pro m"
]

BAD_TERMS = [
    "chromebook", "celeron", "pentium", "athlon silver", "mediatek",
    "rtx 2050", "gtx 1650"
]

def money_to_float(s):
    if not s:
        return None
    s = s.replace(",", "").replace("CAD", "").replace("$", "").strip()
    try:
        return float(s)
    except:
        return None

def extract_prices(text):
    # $999.99 / CAD $999.99 / $1,099.99
    raw = re.findall(r"(?:CAD\s*)?\$\s?([0-9]{2,4}(?:,[0-9]{3})?(?:\.[0-9]{2})?)", text, re.I)
    vals = []
    for r in raw:
        v = money_to_float(r)
        if v and 150 <= v <= 5000:
            vals.append(v)
    return vals

def find_best_price(prices):
    if not prices:
        return None
    # ignore tiny accessory prices if any, choose lowest plausible laptop price
    laptop_prices = [p for p in prices if p >= 300]
    return min(laptop_prices) if laptop_prices else None

def clean(s, max_len=260):
    s = html.unescape(re.sub(r"\s+", " ", s)).strip()
    return s[:max_len] + ("..." if len(s) > max_len else "")

def classify(text, price, priority):
    t = text.lower()
    if any(bad in t for bad in BAD_TERMS) and not any(x in t for x in ["rtx 4050", "rtx 4060", "rtx 4070"]):
        return None

    if not any(term in t for term in GOOD_TERMS):
        return None

    if not price:
        return None

    gpu = None
    if "rtx 4070" in t:
        gpu = "RTX 4070"
    elif "rtx 4060" in t:
        gpu = "RTX 4060"
    elif "rtx 4050" in t:
        gpu = "RTX 4050"

    # Professional/value laptops allowed if price is crazy and recent-ish
    pro = any(x in t for x in ["thinkpad", "precision", "xps", "zbook", "elitebook", "x1", "thinkbook", "macbook"])
    gaming = gpu is not None

    score = priority
    if gpu == "RTX 4070":
        score += 45
    elif gpu == "RTX 4060":
        score += 35
    elif gpu == "RTX 4050":
        score += 24

    for term in ["loq", "legion", "tuf", "nitro", "victus", "omen", "katana", "thinkpad", "precision", "xps", "zbook"]:
        if term in t:
            score += 8

    if any(x in t for x in ["open box", "geek squad", "refurb", "renewed", "recertified", "outlet"]):
        score += 5

    if "16gb" in t or "16 gb" in t:
        score += 5
    if "32gb" in t or "32 gb" in t:
        score += 9
    if "1tb" in t or "1 tb" in t:
        score += 4

    # Price scoring
    if price <= 800:
        score += 20
    elif price <= 900:
        score += 14
    elif price <= 1000:
        score += 8
    elif price <= MAX_BUDGET + ALERT_TOLERANCE:
        score += 2
    else:
        score -= 25

    if price <= MAX_BUDGET:
        decision = "🟢 Sous 1000$ — à vérifier"
    elif price <= MAX_BUDGET + ALERT_TOLERANCE and (gpu in ["RTX 4060", "RTX 4070"]):
        decision = "🟡 Un peu au-dessus, mais peut valoir le coup"
    else:
        decision = "⚪ Trop cher pour ton budget"

    if gaming and price <= MAX_BUDGET and gpu in ["RTX 4060", "RTX 4070"]:
        decision = "🔥 DEAL TRÈS FORT — regarde vite"
    elif gaming and price <= 900 and gpu == "RTX 4050":
        decision = "🔥 Très bon deal RTX 4050"
    elif pro and price <= 700:
        decision = "🔥 Deal pro/refurb intéressant"

    return {"score": round(score, 1), "gpu": gpu or "Pro/Business", "decision": decision}

def fetch(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=25)
        return r.status_code, r.text
    except Exception as e:
        return None, str(e)

def scan():
    found = []
    errors = []
    for store, url, priority in SEARCH_PAGES:
        time.sleep(0.8)
        status, body = fetch(url)
        if status != 200:
            errors.append(f"{store}: {status}")
            continue

        text = BeautifulSoup(body, "html.parser").get_text(" ", strip=True)
        prices = extract_prices(text)
        price = find_best_price(prices)
        c = classify(text, price, priority)
        if not c:
            continue

        found.append({
            "store": store,
            "url": url,
            "price": price,
            "snippet": clean(text),
            **c
        })

    found.sort(key=lambda x: (-x["score"], x["price"] or 99999))
    return found[:10], errors[:10]

def send_telegram(msg):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print(msg)
        print("Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID")
        return

    endpoint = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": msg,
        "parse_mode": "HTML",
        "disable_web_page_preview": False
    }
    r = requests.post(endpoint, json=payload, timeout=25)
    print(r.status_code, r.text[:500])
    r.raise_for_status()

def build_message(results, errors):
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        f"🔎 <b>Recherche laptop deals Canada</b>",
        f"⏱ {now}",
        f"💰 Budget max: <b>{int(MAX_BUDGET)}$ CAD</b>",
        ""
    ]

    strong = [r for r in results if "🔥" in r["decision"] or "🟢" in r["decision"]]
    if strong:
        lines.append("✅ <b>Meilleures pistes détectées:</b>")
        for i, r in enumerate(strong[:6], 1):
            lines += [
                "",
                f"{i}. <b>{r['store']}</b>",
                f"Type: <b>{r['gpu']}</b>",
                f"Prix détecté: <b>{r['price']:.2f}$ CAD</b>",
                f"Verdict: <b>{r['decision']}</b>",
                f"Lien: {r['url']}"
            ]
    else:
        lines += [
            "Aujourd’hui: <b>aucun deal exceptionnel sous 1000$ détecté automatiquement.</b>",
            "Verdict: 🟡 attendre encore.",
        ]

    if results:
        lines += ["", "📌 <b>Autres résultats à surveiller:</b>"]
        for r in results[:3]:
            lines.append(f"• {r['store']} — {r['price']:.0f}$ — {r['gpu']}")

    if errors:
        lines += ["", "⚠️ Certaines pages peuvent bloquer la lecture automatique:", "; ".join(errors[:6])]

    lines += ["", "Note: vérifie toujours le vendeur, la garantie, Open Box/Refurbished et le stock avant achat."]
    return "\n".join(lines)

if __name__ == "__main__":
    results, errors = scan()
    msg = build_message(results, errors)
    if SEND_ALWAYS or results:
        send_telegram(msg)
    else:
        print(msg)
