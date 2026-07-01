import os
import re
import json
import html
import time
import hashlib
from pathlib import Path
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
MAX_PRICE = float(os.environ.get("MAX_PRICE", "1000"))

SEEN_FILE = Path("seen_deals.json")

SEARCHES = [
    "site:bestbuy.ca/en-ca/product laptop RTX 4060 Canada",
    "site:bestbuy.ca/en-ca/product laptop RTX 4050 Canada",
    "site:bestbuy.ca/en-ca/product Lenovo LOQ RTX laptop Canada",
    "site:bestbuy.ca/en-ca/product ASUS TUF RTX laptop Canada",
    "site:bestbuy.ca/en-ca/product Acer Nitro RTX laptop Canada",
    "site:bestbuy.ca/en-ca/product HP Victus RTX laptop Canada",
    "site:canadacomputers.com laptop RTX 4060",
    "site:canadacomputers.com laptop RTX 4050",
    "site:memoryexpress.com laptop RTX 4060",
    "site:memoryexpress.com laptop RTX 4050",
    "site:staples.ca laptop RTX 4060",
    "site:staples.ca laptop RTX 4050",
    "site:lenovo.com/ca Lenovo LOQ RTX laptop",
    "site:lenovo.com/ca ThinkPad T14 Core Ultra 7",
]

DIRECT_URLS = [
    "https://www.bestbuy.ca/en-ca/search?search=rtx+4060+laptop",
    "https://www.bestbuy.ca/en-ca/search?search=rtx+4050+laptop",
    "https://www.bestbuy.ca/en-ca/search?search=lenovo+loq+laptop",
    "https://www.bestbuy.ca/en-ca/search?search=asus+tuf+laptop",
    "https://www.bestbuy.ca/en-ca/search?search=acer+nitro+laptop",
    "https://www.bestbuy.ca/en-ca/search?search=hp+victus+laptop",
    "https://www.canadacomputers.com/en/search?id_category=0&s=rtx+4060+laptop",
    "https://www.canadacomputers.com/en/search?id_category=0&s=rtx+4050+laptop",
    "https://www.memoryexpress.com/Search/Products?Search=rtx%204060%20laptop",
    "https://www.memoryexpress.com/Search/Products?Search=rtx%204050%20laptop",
    "https://www.staples.ca/search?query=rtx%204060%20laptop",
    "https://www.staples.ca/search?query=rtx%204050%20laptop",
]

GOOD_WORDS = [
    "rtx 4060", "rtx 4050", "rtx 5060", "rtx 5050",
    "lenovo loq", "legion", "asus tuf", "rog",
    "acer nitro", "predator", "hp victus", "omen",
    "msi katana", "cyborg", "thinkpad",
    "core ultra 7", "core 7", "i7-13", "i7 13", "i7-14", "i7 14",
    "ryzen 7", "ryzen ai"
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 AppleWebKit/537.36 Chrome/121 Safari/537.36",
    "Accept-Language": "en-CA,en;q=0.9,fr-CA;q=0.8,fr;q=0.7",
}

def telegram(text):
    if not BOT_TOKEN or not CHAT_ID:
        raise RuntimeError("Ajoute TELEGRAM_BOT_TOKEN et TELEGRAM_CHAT_ID dans GitHub Secrets.")
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    res = requests.post(url, data={
        "chat_id": CHAT_ID,
        "text": text[:3900],
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }, timeout=30)
    res.raise_for_status()

def load_seen():
    if SEEN_FILE.exists():
        try:
            return set(json.loads(SEEN_FILE.read_text()))
        except Exception:
            return set()
    return set()

def save_seen(seen):
    SEEN_FILE.write_text(json.dumps(sorted(list(seen))[-500:], indent=2))

def price_from_text(text):
    text = text.replace("\xa0", " ").replace(",", ".")
    prices = []
    for m in re.finditer(r"\$?\s*([0-9]{3,4}(?:\.[0-9]{2})?)", text):
        try:
            p = float(m.group(1))
            if 250 <= p <= 2500:
                prices.append(p)
        except Exception:
            pass
    return min(prices) if prices else None

def abs_url(base, href):
    if href.startswith("http"):
        return href
    if href.startswith("/"):
        if "bestbuy.ca" in base:
            return "https://www.bestbuy.ca" + href
        if "canadacomputers.com" in base:
            return "https://www.canadacomputers.com" + href
        if "memoryexpress.com" in base:
            return "https://www.memoryexpress.com" + href
        if "staples.ca" in base:
            return "https://www.staples.ca" + href
        if "lenovo.com" in base:
            return "https://www.lenovo.com" + href
    return href

def source(url):
    return re.sub(r"^https?://(www\.)?", "", url).split("/")[0]

def is_good(text):
    low = text.lower()
    if not any(w in low for w in GOOD_WORDS):
        return False
    if not any(w in low for w in ["laptop", "portable", "notebook", "gaming", "thinkpad", "loq", "victus", "nitro", "tuf", "legion"]):
        return False
    return True

def fetch_products(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=25)
        if r.status_code >= 400:
            return []
        soup = BeautifulSoup(r.text, "html.parser")
        results = []
        for a in soup.find_all("a", href=True):
            title = a.get_text(" ", strip=True)
            if len(title) < 12:
                continue
            node = a
            block = title
            for _ in range(4):
                node = node.parent
                if node:
                    block += " " + node.get_text(" ", strip=True)[:1200]
            if not is_good(block):
                continue
            price = price_from_text(block)
            if price and price > MAX_PRICE:
                continue
            link = abs_url(url, a["href"])
            if link.startswith("javascript") or link == "#":
                continue
            results.append({
                "title": re.sub(r"\s+", " ", title)[:170],
                "price": price,
                "url": link,
                "source": source(url),
            })
        return results
    except Exception as e:
        print("Erreur:", url, e)
        return []

def score(item):
    t = item["title"].lower()
    s = 0
    weights = {
        "rtx 5060": 80, "rtx 4060": 75, "rtx 5050": 70, "rtx 4050": 60,
        "legion": 35, "lenovo loq": 32, "rog": 30, "asus tuf": 27,
        "predator": 25, "acer nitro": 22, "hp victus": 20, "omen": 20,
        "thinkpad": 18, "core ultra 7": 18, "ryzen 7": 15,
    }
    for k, v in weights.items():
        if k in t:
            s += v
    if item["price"]:
        s += max(0, int((MAX_PRICE - item["price"]) / 20))
    return s

def deal_id(item):
    return hashlib.sha1((item["title"].lower() + item["url"]).encode()).hexdigest()

def main():
    seen = load_seen()
    items = []

    for url in DIRECT_URLS:
        print("Checking", url)
        items.extend(fetch_products(url))
        time.sleep(1)

    unique = {}
    for it in items:
        unique[deal_id(it)] = it

    ranked = sorted(unique.values(), key=score, reverse=True)
    ranked = [x for x in ranked if deal_id(x) not in seen][:8]

    if not ranked:
        telegram(f"💻 Aucun nouveau deal laptop trouvé maintenant.\nBudget: ≤ {MAX_PRICE:.0f} CAD.")
        return

    lines = [f"🔥 <b>Nouveaux deals laptops Canada ≤ {MAX_PRICE:.0f} CAD</b>\n"]
    for i, it in enumerate(ranked, 1):
        p = f"{it['price']:.2f} CAD" if it["price"] else "Prix à vérifier"
        lines.append(
            f"{i}. <b>{html.escape(it['title'])}</b>\n"
            f"💲 {p}\n"
            f"🏬 {html.escape(it['source'])}\n"
            f"🔗 {html.escape(it['url'])}\n"
        )
        seen.add(deal_id(it))

    lines.append("Vérifie toujours prix final, taxes, disponibilité Montréal et condition Open Box.")
    telegram("\n".join(lines))
    save_seen(seen)

if __name__ == "__main__":
    main()
