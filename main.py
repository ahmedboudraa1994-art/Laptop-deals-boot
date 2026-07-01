import os
import json
import re
import requests
from bs4 import BeautifulSoup

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
MAX_PRICE = float(os.getenv("MAX_PRICE", "1000"))

SEEN_FILE = "seen_deals.json"
MIN_PRICE = 500

SEARCH_URLS = [
    "https://www.canadacomputers.com/en/search?s=rtx%204060%20laptop",
    "https://www.canadacomputers.com/en/search?s=gaming%20laptop",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}


def load_seen():
    if not os.path.exists(SEEN_FILE):
        return []
    try:
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def save_seen(seen):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(seen[-200:], f, indent=2)


def clean_price(text):
    if not text:
        return None

    text = text.replace(",", "")
    prices = re.findall(r"\$?\s*([0-9]{3,5}(?:\.[0-9]{2})?)", text)

    valid_prices = []
    for p in prices:
        try:
            price = float(p)
            if MIN_PRICE <= price <= MAX_PRICE:
                valid_prices.append(price)
        except Exception:
            pass

    if not valid_prices:
        return None

    return min(valid_prices)


def send_telegram(message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = {
        "chat_id": CHAT_ID,
        "text": message,
        "disable_web_page_preview": True
    }
    requests.post(url, data=data, timeout=20)


def scrape_canada_computers(url):
    deals = []

    r = requests.get(url, headers=HEADERS, timeout=20)
    soup = BeautifulSoup(r.text, "html.parser")

    products = soup.find_all("a", href=True)

    for a in products:
        title = a.get_text(" ", strip=True)
        href = a.get("href", "")

        if not title:
            continue

        title_low = title.lower()

        if "laptop" not in title_low and "notebook" not in title_low:
            continue

        if not any(x in title_low for x in ["rtx", "gaming", "ryzen", "intel", "legion", "tuf", "loq", "nitro"]):
            continue

        parent_text = ""
        parent = a.find_parent()
        if parent:
            parent_text = parent.get_text(" ", strip=True)

        price = clean_price(parent_text)

        if price is None:
            continue

        if href.startswith("/"):
            href = "https://www.canadacomputers.com" + href

        deals.append({
            "title": title[:140],
            "price": price,
            "site": "canadacomputers.com",
            "url": href
        })

    return deals


def dedupe_deals(deals):
    clean = []
    seen_urls = set()

    for d in deals:
        if d["url"] in seen_urls:
            continue
        seen_urls.add(d["url"])
        clean.append(d)

    clean.sort(key=lambda x: x["price"])
    return clean[:10]


def main():
    if not BOT_TOKEN or not CHAT_ID:
        raise Exception("TELEGRAM_BOT_TOKEN ou TELEGRAM_CHAT_ID manquant")

    seen = load_seen()
    all_deals = []

    for url in SEARCH_URLS:
        try:
            all_deals.extend(scrape_canada_computers(url))
        except Exception as e:
            print("Erreur scrape:", url, e)

    deals = dedupe_deals(all_deals)

    new_deals = []
    for d in deals:
        deal_id = d["url"]
        if deal_id not in seen:
            new_deals.append(d)
            seen.append(deal_id)

    if not new_deals:
        send_telegram("Aucun nouveau deal laptop fiable trouvé pour le moment.")
        save_seen(seen)
        return

    message = f"🔥 Nouveaux deals laptops Canada entre {MIN_PRICE:.0f} et {MAX_PRICE:.0f} CAD\n\n"

    for i, d in enumerate(new_deals[:5], 1):
        message += (
            f"{i}. {d['title']}\n"
            f"💲 {d['price']:.2f} CAD\n"
            f"🏬 {d['site']}\n"
            f"🔗 {d['url']}\n\n"
        )

    send_telegram(message)
    save_seen(seen)


if __name__ == "__main__":
    main()
