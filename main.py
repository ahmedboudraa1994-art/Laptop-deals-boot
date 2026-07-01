import os, json, re, requests
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote_plus, urljoin

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
MAX_PRICE = float(os.getenv("MAX_PRICE", "1000"))
MIN_PRICE = 600
SEEN_FILE = "seen_deals.json"
TIMEOUT = 10

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}

SOURCES = [
    ("Canada Computers", "https://www.canadacomputers.com/en/search?s={q}"),
    ("Best Buy Canada", "https://www.bestbuy.ca/en-ca/search?search={q}"),
    ("Memory Express", "https://www.memoryexpress.com/Search/Products?Search={q}"),
    ("Newegg Canada", "https://www.newegg.ca/p/pl?d={q}"),
    ("Staples Canada", "https://www.staples.ca/search?query={q}"),
    ("Walmart Canada", "https://www.walmart.ca/search?q={q}"),
    ("Lenovo Canada", "https://www.lenovo.com/ca/en/search?fq=&text={q}"),
    ("Dell Canada", "https://www.dell.com/en-ca/search/{q}"),
    ("Amazon Canada", "https://www.amazon.ca/s?k={q}"),
    ("Costco Canada", "https://www.costco.ca/CatalogSearch?keyword={q}"),
]

QUERIES = [
    "rtx 4060 laptop",
    "rtx 4070 laptop",
    "rtx 4050 laptop",
    "lenovo legion laptop",
    "lenovo loq laptop",
    "asus tuf laptop",
    "acer nitro laptop",
    "msi gaming laptop",
    "dell g15 laptop",
]

BAD_WORDS = ["desktop", "monitor", "keyboard", "mouse", "charger", "adapter", "bag", "case", "dock", "stand"]
GOOD_WORDS = ["laptop", "notebook", "rtx", "gaming", "legion", "loq", "tuf", "rog", "nitro", "katana", "victus", "omen", "g15"]


def load_seen():
    try:
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return []


def save_seen(seen):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(seen[-800:], f)


def send_telegram(text):
    requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        data={"chat_id": CHAT_ID, "text": text, "disable_web_page_preview": True},
        timeout=TIMEOUT
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


def clean_url(base, href):
    if not href:
        return None
    if href.startswith("http"):
        return href.split("?")[0]
    return urljoin(base, href).split("?")[0]


def scrape_source(source):
    site_name, search_url = source
    deals = []

    for q in QUERIES:
        try:
            url = search_url.format(q=quote_plus(q))
            r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            soup = BeautifulSoup(r.text, "html.parser")

            for a in soup.find_all("a", href=True):
                title = a.get_text(" ", strip=True)

                if not title or len(title) < 15:
                    continue
                if not valid_title(title):
                    continue

                href = clean_url(url, a.get("href"))
                if not href:
                    continue

                parent = a.find_parent()
                block_text = parent.get_text(" ", strip=True) if parent else title
                prices = extract_prices(block_text)

                if not prices:
                    continue

                price = min(prices)

                deals.append({
                    "title": title[:150],
                    "price": price,
                    "site": site_name,
                    "url": href
                })

        except Exception as e:
            print("Erreur:", site_name, q, e)

    return deals


def score_deal(d):
    t = d["title"].lower()
    score = 0

    if "rtx 4070" in t:
        score += 45
    if "rtx 4060" in t:
        score += 35
    if "rtx 4050" in t:
        score += 20
    if "i7" in t or "ryzen 7" in t or "ryzen 9" in t:
        score += 15
    if "16gb" in t:
        score += 10
    if "1tb" in t:
        score += 10

    score += max(0, int(MAX_PRICE - d["price"]) // 25)
    return score


def main():
    if not BOT_TOKEN or not CHAT_ID:
        raise Exception("Secrets Telegram manquants")

    seen = load_seen()
    all_deals = []

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(scrape_source, source) for source in SOURCES]
        for f in as_completed(futures):
            all_deals.extend(f.result())

    unique = []
    used = set()

    for d in all_deals:
        key = d["url"]
        if key in used:
            continue
        used.add(key)
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

    msg = f"🔥 Deals laptops Canada {MIN_PRICE:.0f}$–{MAX_PRICE:.0f}$ CAD\n\n"

    for i, d in enumerate(new_deals[:8], 1):
        msg += (
            f"{i}. {d['title']}\n"
            f"💲 {d['price']:.2f} CAD\n"
            f"🏬 {d['site']}\n"
            f"⭐ Score: {d['score']}\n"
            f"🔗 {d['url']}\n\n"
        )

    msg += "Vérifie toujours le prix final, taxes, stock Montréal et condition Open Box."

    send_telegram(msg)
    save_seen(seen)


if __name__ == "__main__":
    main()
