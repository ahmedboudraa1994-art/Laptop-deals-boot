import os
import re
import html
import time
import hashlib
import requests
from bs4 import BeautifulSoup

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
MAX_PRICE = float(os.environ.get("MAX_PRICE", "1000"))

KEYWORDS = [
    k.strip().lower()
    for k in os.environ.get(
        "KEYWORDS",
        "rtx 4050,rtx 4060,rtx 5050,rtx 5060,lenovo loq,lenovo legion,asus tuf,acer nitro,hp victus,msi katana,thinkpad"
    ).split(",")
    if k.strip()
]

SEARCH_URLS = [
    "https://www.bestbuy.ca/en-ca/search?search=rtx+4060+laptop",
    "https://www.bestbuy.ca/en-ca/search?search=rtx+4050+laptop",
    "https://www.bestbuy.ca/en-ca/search?search=rtx+5050+laptop",
    "https://www.bestbuy.ca/en-ca/search?search=rtx+5060+laptop",
    "https://www.bestbuy.ca/en-ca/search?search=lenovo+loq+laptop",
    "https://www.bestbuy.ca/en-ca/search?search=asus+tuf+laptop",
    "https://www.bestbuy.ca/en-ca/search?search=acer+nitro+laptop",
    "https://www.bestbuy.ca/en-ca/search?search=hp+victus+laptop",
    "https://www.bestbuy.ca/en-ca/search?search=msi+katana+laptop",
    "https://www.bestbuy.ca/en-ca/search?search=thinkpad+t14",
    "https://www.canadacomputers.com/en/search?id_category=0&s=rtx+4060+laptop",
    "https://www.canadacomputers.com/en/search?id_category=0&s=rtx+4050+laptop",
    "https://www.canadacomputers.com/en/search?id_category=0&s=lenovo+loq+laptop",
    "https://www.memoryexpress.com/Search/Products?Search=rtx%204060%20laptop",
    "https://www.memoryexpress.com/Search/Products?Search=rtx%204050%20laptop",
    "https://www.staples.ca/search?query=rtx%204060%20laptop",
    "https://www.staples.ca/search?query=rtx%204050%20laptop",
    "https://www.staples.ca/search?query=thinkpad%20t14",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
    "Accept-Language": "en-CA,en;q=0.9,fr-CA;q=0.8,fr;q=0.7",
}

def send_telegram(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        raise RuntimeError("Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID in GitHub Secrets.")
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text[:3900],
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }
    r = requests.post(url, data=data, timeout=30)
    r.raise_for_status()

def clean_price(raw):
    if not raw:
        return None
    raw = raw.replace("\xa0", " ").replace(",", ".")
    matches = re.findall(r"\$?\s*([0-9]{3,4}(?:[.,][0-9]{2})?)", raw)
    prices = []
    for m in matches:
        try:
            p = float(m.replace(",", "."))
            if 100 <= p <= 3000:
                prices.append(p)
        except ValueError:
            pass
    return min(prices) if prices else None

def normalize_url(base_url, href):
    if href.startswith("http"):
        return href
    if href.startswith("/"):
        if "bestbuy.ca" in base_url:
            return "https://www.bestbuy.ca" + href
        if "canadacomputers.com" in base_url:
            return "https://www.canadacomputers.com" + href
        if "memoryexpress.com" in base_url:
            return "https://www.memoryexpress.com" + href
        if "staples.ca" in base_url:
            return "https://www.staples.ca" + href
    return href

def source_name(url):
    return re.sub(r"^https?://(www\.)?", "", url).split("/")[0]

def product_like(text):
    low = text.lower()
    return any(k in low for k in KEYWORDS) and any(w in low for w in [
        "laptop", "portable", "notebook", "gaming", "thinkpad", "loq", "legion", "tuf", "nitro", "victus", "katana"
    ])

def extract_candidates(url, body):
    soup = BeautifulSoup(body, "html.parser")
    items = []

    for a in soup.find_all("a", href=True):
        title = a.get_text(" ", strip=True)
        if not title or len(title) < 12:
            continue

        block = title
        node = a
        for _ in range(4):
            node = node.parent
            if node:
                block += " " + node.get_text(" ", strip=True)[:1200]

        if not product_like(block):
            continue

        price = clean_price(block)
        if price is not None and price > MAX_PRICE:
            continue

        link = normalize_url(url, a["href"])
        if link == "#" or link.startswith("javascript:"):
            continue

        items.append({
            "title": re.sub(r"\s+", " ", title)[:180],
            "price": price,
            "url": link,
            "source": source_name(url),
        })

    seen = set()
    unique = []
    for item in items:
        key = hashlib.sha1((item["title"].lower() + item["url"]).encode()).hexdigest()
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique

def fetch(url):
    try:
        print("Checking:", url)
        r = requests.get(url, headers=HEADERS, timeout=30)
        if r.status_code >= 400:
            print("HTTP error:", r.status_code)
            return []
        return extract_candidates(url, r.text)
    except Exception as e:
        print("Error:", url, e)
        return []

def score(item):
    t = item["title"].lower()
    s = 0
    for kw, pts in [
        ("rtx 5060", 50), ("rtx 4060", 45), ("rtx 5050", 42), ("rtx 4050", 35),
        ("lenovo loq", 25), ("legion", 25), ("asus tuf", 20),
        ("nitro", 18), ("victus", 16), ("katana", 14), ("thinkpad", 12),
        ("open box", 5), ("refurbished", 3)
    ]:
        if kw in t:
            s += pts
    if item["price"] is not None:
        s += max(0, int((MAX_PRICE - item["price"]) / 25))
    return s

def main():
    all_items = []
    for url in SEARCH_URLS:
        all_items.extend(fetch(url))
        time.sleep(1)

    all_items = sorted(all_items, key=score, reverse=True)
    top = all_items[:12]

    if not top:
        send_telegram(
            f"💻 Aucun deal laptop trouvé maintenant.\n\nBudget: ≤ {MAX_PRICE:.0f} CAD.\nJe revérifierai au prochain passage."
        )
        return

    lines = [f"💻 <b>Deals laptops Canada ≤ {MAX_PRICE:.0f} CAD</b>\n"]
    for i, item in enumerate(top, 1):
        title = html.escape(item["title"])
        price = f"{item['price']:.2f} CAD" if item["price"] is not None else "Prix à vérifier"
        url = html.escape(item["url"])
        source = html.escape(item["source"])
        lines.append(f"{i}. <b>{title}</b>\nPrix: {price}\nSource: {source}\n{url}\n")

    lines.append("Vérifie toujours le prix final, taxes, disponibilité Montréal et état Open Box avant d’acheter.")
    send_telegram("\n".join(lines))

if __name__ == "__main__":
    main()
