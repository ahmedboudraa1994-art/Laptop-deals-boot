import os, json, re, requests
from bs4 import BeautifulSoup
from urllib.parse import quote_plus

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
MAX_PRICE = float(os.getenv("MAX_PRICE", "1000"))
MIN_PRICE = 500
SEEN_FILE = "seen_deals.json"

HEADERS = {"User-Agent": "Mozilla/5.0"}

QUERIES = [
    "RTX 4060 laptop Canada",
    "RTX 4070 laptop Canada",
    "RTX 5070 laptop Canada",
    "gaming laptop Canada",
    "Lenovo LOQ laptop Canada",
    "Lenovo Legion laptop Canada",
    "ASUS TUF laptop Canada",
    "ASUS ROG laptop Canada",
    "Acer Nitro laptop Canada",
    "MSI Katana laptop Canada",
    "Dell G15 laptop Canada",
]

SITES = [
    "canadacomputers.com",
    "bestbuy.ca",
    "staples.ca",
    "memoryexpress.com",
    "visions.ca",
    "newegg.ca",
    "lenovo.com/ca",
    "asus.com/ca",
    "dell.com/en-ca",
    "hp.com/ca",
    "acer.com/ca",
    "msi.com",
    "amazon.ca",
    "costco.ca",
    "walmart.ca",
    "microbytes.com",
    "pc-canada.com",
    "directdial.com",
    "redflagdeals.com",
    "shopbot.ca",
]

BAD_WORDS = [
    "desktop", "monitor", "keyboard", "mouse", "charger", "adapter",
    "case", "bag", "cooler", "stand", "dock", "warranty", "skin"
]

GOOD_WORDS = [
    "laptop", "notebook", "rtx", "gaming", "legion", "loq",
    "tuf", "rog", "nitro", "predator", "katana", "victus", "omen", "g15"
]


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
        data={
            "chat_id": CHAT_ID,
            "text": text,
            "disable_web_page_preview": True
        },
        timeout=20
    )


def valid_title(title):
    t = title.lower()
    if any(b in t for b in BAD_WORDS):
        return False
    return any(g in t for g in GOOD_WORDS)


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


def search_duckduckgo(query, site):
    url = f"https://duckduckgo.com/html/?q=site:{site}+{quote_plus(query)}"
    r = requests.get(url, headers=HEADERS, timeout=20)
    soup = BeautifulSoup(r.text, "html.parser")

    results = []
    for a in soup.find_all("a", class_="result__a", href=True):
        title = a.get_text(" ", strip=True)
        link = a["href"]

        if site.split("/")[0] not in link:
            continue

        if not valid_title(title):
            continue

        results.append({
            "title": title[:150],
            "url": link,
            "site": site
        })

    return results[:4]


def enrich_price(deal):
    try:
        r = requests.get(deal["url"], headers=HEADERS, timeout=25)
        soup = BeautifulSoup(r.text, "html.parser")
        text = soup.get_text(" ", strip=True)

        prices = extract_prices(text)
        if not prices:
            return None

        price = min(prices)

        if price < MIN_PRICE or price > MAX_PRICE:
            return None

        deal["price"] = price
        return deal
    except:
        return None


def score_deal(d):
    title = d["title"].lower()
    score = 0

    if "rtx 5070" in title:
        score += 50
    if "rtx 4070" in title:
        score += 40
    if "rtx 4060" in title:
        score += 30
    if "i7" in title or "ryzen 7" in title or "ryzen 9" in title:
        score += 15
    if "16gb" in title:
        score += 10
    if "1tb" in title:
        score += 10

    score += max(0, int(MAX_PRICE - d["price"]) // 25)
    return score


def main():
    if not BOT_TOKEN or not CHAT_ID:
        raise Exception("Secrets Telegram manquants")

    seen = load_seen()
    found = []

    for site in SITES:
        for q in QUERIES:
            try:
                results = search_duckduckgo(q, site)
                for deal in results:
                    enriched = enrich_price(deal)
                    if enriched:
                        found.append(enriched)
            except Exception as e:
                print("Erreur:", site, q, e)

    unique = []
    used_urls = set()

    for d in found:
        clean_url = d["url"].split("?")[0]
        if clean_url in used_urls:
            continue
        used_urls.add(clean_url)
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
        msg += (
            f"{i}. {d['title']}\n"
            f"💲 {d['price']:.2f} CAD\n"
            f"🏬 {d['site']}\n"
            f"⭐ Score: {d['score']}\n"
            f"🔗 {d['url']}\n\n"
        )

    send_telegram(msg)
    save_seen(seen)


if __name__ == "__main__":
    main()
