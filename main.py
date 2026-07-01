import os, json, re, requests
from bs4 import BeautifulSoup
from urllib.parse import quote_plus
from concurrent.futures import ThreadPoolExecutor, as_completed

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
MAX_PRICE = float(os.getenv("MAX_PRICE", "1000"))
MIN_PRICE = 600
SEEN_FILE = "seen_deals.json"

HEADERS = {"User-Agent": "Mozilla/5.0"}
TIMEOUT = 8

QUERIES = [
    "RTX 4060 laptop Canada",
    "RTX 4070 laptop Canada",
    "gaming laptop Canada",
    "Lenovo Legion laptop Canada",
    "Lenovo LOQ laptop Canada",
    "ASUS TUF laptop Canada",
    "Acer Nitro laptop Canada",
    "Dell G15 laptop Canada",
]

SITES = [
    "canadacomputers.com", "bestbuy.ca", "staples.ca",
    "memoryexpress.com", "visions.ca", "newegg.ca",
    "lenovo.com/ca", "dell.com/en-ca", "amazon.ca",
    "costco.ca", "walmart.ca", "microbytes.com",
    "pc-canada.com", "directdial.com", "redflagdeals.com"
]

BAD = ["desktop", "monitor", "keyboard", "mouse", "charger", "adapter", "case", "bag", "cooler", "stand", "dock"]
GOOD = ["laptop", "notebook", "rtx", "gaming", "legion", "loq", "tuf", "rog", "nitro", "katana", "victus", "omen", "g15"]

def load_seen():
    try:
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return []

def save_seen(seen):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(seen[-500:], f)

def send_telegram(text):
    requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        data={"chat_id": CHAT_ID, "text": text, "disable_web_page_preview": True},
        timeout=TIMEOUT
    )

def valid_title(title):
    t = title.lower()
    return any(g in t for g in GOOD) and not any(b in t for b in BAD)

def extract_prices(text):
    text = text.replace(",", "")
    nums = re.findall(r"\$?\s*([0-9]{3,5}(?:\.[0-9]{2})?)", text)
    prices = []
    for n in nums:
        try:
            p = float(n)
            if MIN_PRICE <= p <= MAX_PRICE:
                prices.append(p)
        except:
            pass
    return prices

def search_site(site, query):
    try:
        url = f"https://duckduckgo.com/html/?q=site:{site}+{quote_plus(query)}"
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        soup = BeautifulSoup(r.text, "html.parser")
        results = []

        for a in soup.find_all("a", class_="result__a", href=True):
            title = a.get_text(" ", strip=True)
            link = a["href"]

            if site.split("/")[0] not in link:
                continue
            if not valid_title(title):
                continue

            results.append({"title": title[:150], "url": link, "site": site})

        return results[:3]
    except:
        return []

def enrich_price(deal):
    try:
        r = requests.get(deal["url"], headers=HEADERS, timeout=TIMEOUT)
        text = BeautifulSoup(r.text, "html.parser").get_text(" ", strip=True)
        prices = extract_prices(text)
        if not prices:
            return None

        deal["price"] = min(prices)
        return deal
    except:
        return None

def score_deal(d):
    t = d["title"].lower()
    score = 0
    if "rtx 4070" in t: score += 45
    if "rtx 4060" in t: score += 35
    if "i7" in t or "ryzen 7" in t or "ryzen 9" in t: score += 15
    if "16gb" in t: score += 10
    if "1tb" in t: score += 10
    score += max(0, int(MAX_PRICE - d["price"]) // 25)
    return score

def main():
    if not BOT_TOKEN or not CHAT_ID:
        raise Exception("Secrets Telegram manquants")

    seen = load_seen()
    raw = []

    tasks = []
    with ThreadPoolExecutor(max_workers=12) as executor:
        for site in SITES:
            for query in QUERIES:
                tasks.append(executor.submit(search_site, site, query))

        for task in as_completed(tasks):
            raw.extend(task.result())

    enriched = []
    with ThreadPoolExecutor(max_workers=12) as executor:
        futures = [executor.submit(enrich_price, d) for d in raw]
        for f in as_completed(futures):
            d = f.result()
            if d:
                enriched.append(d)

    unique = []
    used = set()

    for d in enriched:
        clean_url = d["url"].split("?")[0]
        if clean_url in used:
            continue
        used.add(clean_url)
        d["url"] = clean_url
        d["score"] = score_deal(d)
        unique.append(d)

    unique.sort(key=lambda x: (-x["score"], x["price"]))

    new_deals = []
    for d in unique:
        if d["url"] not in seen:
            new_deals.append(d)
            seen.append(d["url"])

    if not new_deals:
        send_telegram(f"Aucun nouveau vrai deal laptop trouvé entre {MIN_PRICE:.0f}$ et {MAX_PRICE:.0f}$ CAD.")
        save_seen(seen)
        return

    msg = f"🔥 Meilleurs deals laptops Canada {MIN_PRICE:.0f}$–{MAX_PRICE:.0f}$ CAD\n\n"
    for i, d in enumerate(new_deals[:8], 1):
        msg += f"{i}. {d['title']}\n💲 {d['price']:.2f} CAD\n🏬 {d['site']}\n⭐ Score: {d['score']}\n🔗 {d['url']}\n\n"

    send_telegram(msg)
    save_seen(seen)

if __name__ == "__main__":
    main()
