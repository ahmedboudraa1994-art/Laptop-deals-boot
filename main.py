import asyncio
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote_plus, urlparse

import requests
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
MIN_PRICE = int(os.environ.get("MIN_PRICE", "600"))
MAX_PRICE = int(os.environ.get("MAX_PRICE", "1000"))
HEADLESS = os.environ.get("HEADLESS", "1") != "0"

SEEN_FILE = Path("seen_deals.json")
MAX_RESULTS_PER_RUN = int(os.environ.get("MAX_RESULTS_PER_RUN", "10"))
MAX_KEYWORDS_PER_SITE = int(os.environ.get("MAX_KEYWORDS_PER_SITE", "4"))
SITE_TIMEOUT_MS = int(os.environ.get("SITE_TIMEOUT_MS", "12000"))
PRODUCT_TIMEOUT_MS = int(os.environ.get("PRODUCT_TIMEOUT_MS", "10000"))

KEYWORDS = [
    "rtx 4060 laptop", "rtx 4070 laptop", "rtx 4050 laptop",
    "lenovo legion laptop", "lenovo loq laptop", "asus tuf laptop", "asus rog laptop",
    "acer nitro laptop", "msi katana laptop", "dell g15 laptop",
    "gaming laptop rtx", "core i7 rtx laptop", "ryzen 7 rtx laptop",
]

BAD_TITLE_WORDS = [
    "shop laptops", "laptops for business", "laptops for school", "laptops for college",
    "education", "student", "all laptops", "gaming laptops", "laptop computers",
    "business laptops", "compare", "accessories", "monitor", "desktop",
]

GOOD_MODEL_WORDS = [
    "loq", "legion", "thinkpad", "ideapad", "yoga", "nitro", "predator", "tuf", "rog",
    "vivobook", "zenbook", "katana", "pulse", "cyborg", "thin", "stealth", "omen", "victus",
    "g15", "inspiron", "xps", "alienware", "swift", "aspire", "aorus", "gigabyte",
    "rtx 4050", "rtx 4060", "rtx 4070", "ryzen 7", "ryzen 5", "core i7", "core 7", "i7-", "i5-",
]

@dataclass
class Deal:
    title: str
    price: float
    site: str
    url: str
    score: int
    specs: str = ""

SITES = [
    {
        "name": "Lenovo Canada",
        "search": lambda q: f"https://www.lenovo.com/ca/en/search?fq=&text={quote_plus(q)}",
        "allowed_domains": ["lenovo.com"],
    },
    {
        "name": "Dell Canada",
        "search": lambda q: f"https://www.dell.com/en-ca/search/{quote_plus(q)}",
        "allowed_domains": ["dell.com"],
    },
    {
        "name": "Best Buy Canada",
        "search": lambda q: f"https://www.bestbuy.ca/en-ca/search?search={quote_plus(q)}",
        "allowed_domains": ["bestbuy.ca"],
    },
    {
        "name": "Canada Computers",
        "search": lambda q: f"https://www.canadacomputers.com/en/search?s={quote_plus(q)}",
        "allowed_domains": ["canadacomputers.com"],
    },
    {
        "name": "Memory Express",
        "search": lambda q: f"https://www.memoryexpress.com/Search/Products?Search={quote_plus(q)}",
        "allowed_domains": ["memoryexpress.com"],
    },
    {
        "name": "Newegg Canada",
        "search": lambda q: f"https://www.newegg.ca/p/pl?d={quote_plus(q)}",
        "allowed_domains": ["newegg.ca"],
    },
    {
        "name": "Staples Canada",
        "search": lambda q: f"https://www.staples.ca/search?query={quote_plus(q)}",
        "allowed_domains": ["staples.ca"],
    },
    {
        "name": "Walmart Canada",
        "search": lambda q: f"https://www.walmart.ca/search?q={quote_plus(q)}",
        "allowed_domains": ["walmart.ca"],
    },
    {
        "name": "Costco Canada",
        "search": lambda q: f"https://www.costco.ca/CatalogSearch?keyword={quote_plus(q)}",
        "allowed_domains": ["costco.ca"],
    },
    {
        "name": "HP Canada",
        "search": lambda q: f"https://www.hp.com/ca-en/shop/sitesearch?keyword={quote_plus(q)}",
        "allowed_domains": ["hp.com"],
    },
    {
        "name": "ASUS Canada",
        "search": lambda q: f"https://www.asus.com/ca-en/searchresult?searchType=products&searchKey={quote_plus(q)}",
        "allowed_domains": ["asus.com"],
    },
    {
        "name": "Acer Canada",
        "search": lambda q: f"https://store.acer.com/en-ca/catalogsearch/result/?q={quote_plus(q)}",
        "allowed_domains": ["acer.com"],
    },
]

def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())

def extract_prices(text: str) -> List[float]:
    prices = []
    for m in re.finditer(r"(?:CAD\s*)?\$\s*([0-9]{3,4}(?:[, ]?[0-9]{3})*(?:\.\d{2})?)", text, re.I):
        raw = m.group(1).replace(",", "").replace(" ", "")
        try:
            value = float(raw)
            if 250 <= value <= 5000:
                prices.append(value)
        except ValueError:
            pass
    return prices

def is_bad_url(url: str) -> bool:
    u = url.lower()
    bad_bits = [
        "/search", "catalogsearch", "catalogsearch?", "/scr/laptops", "/laptops/results",
        "/laptops/", "appref=", "search?", "?search", "category", "/c/", "/collection",
    ]
    if any(x in u for x in bad_bits):
        # Some real product URLs contain categories, so allow if it clearly has a product id path.
        product_hints = ["/p/", "/product/", "/shop/", "sku", "prod", "item"]
        if not any(h in u for h in product_hints):
            return True
    return False

def title_is_product(title: str) -> bool:
    t = title.lower()
    if len(t) < 18:
        return False
    if any(w in t for w in BAD_TITLE_WORDS):
        return False
    if not any(w in t for w in GOOD_MODEL_WORDS):
        return False
    if "laptop" not in t and "notebook" not in t and not any(g in t for g in ["loq", "legion", "nitro", "katana", "g15"]):
        return False
    return True

def score_deal(title: str, price: float, specs: str, site: str) -> int:
    text = f"{title} {specs}".lower()
    score = 0
    if "rtx 4070" in text: score += 8
    if "rtx 4060" in text: score += 7
    if "rtx 4050" in text: score += 4
    if "16gb" in text or "16 gb" in text: score += 2
    if "32gb" in text or "32 gb" in text: score += 4
    if "1tb" in text or "1 tb" in text: score += 3
    if "512" in text: score += 1
    if "ryzen 7" in text or "i7" in text or "core 7" in text: score += 3
    if any(x in text for x in ["legion", "loq", "tuf", "rog", "nitro", "katana", "g15", "victus", "omen"]): score += 3
    if price <= 800: score += 3
    elif price <= 900: score += 2
    elif price <= 1000: score += 1
    if site in ["Lenovo Canada", "Dell Canada", "Best Buy Canada", "Canada Computers", "Memory Express"]: score += 1
    return score

def load_seen() -> set:
    if SEEN_FILE.exists():
        try:
            return set(json.loads(SEEN_FILE.read_text()))
        except Exception:
            return set()
    return set()

def save_seen(seen: set) -> None:
    SEEN_FILE.write_text(json.dumps(sorted(seen), indent=2))

def deal_key(url: str, title: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.netloc}{parsed.path}".lower().rstrip("/") or title.lower()

async def safe_goto(page, url: str, timeout_ms: int) -> bool:
    for wait_until in ["domcontentloaded", "load"]:
        try:
            await page.goto(url, wait_until=wait_until, timeout=timeout_ms)
            await page.wait_for_timeout(1500)
            return True
        except Exception as e:
            last = str(e).split("\n")[0]
    print(f"Navigation failed: {url} :: {last}", flush=True)
    return False

async def collect_links_from_search(page, site: Dict, keyword: str) -> List[str]:
    url = site["search"](keyword)
    ok = await safe_goto(page, url, SITE_TIMEOUT_MS)
    if not ok:
        return []
    links = await page.locator("a[href]").evaluate_all("""
        els => els.map(a => ({href:a.href, text:(a.innerText || a.textContent || '').trim()}))
    """)
    results = []
    for a in links:
        href = a.get("href", "")
        text = clean_text(a.get("text", ""))
        host_ok = any(d in href for d in site["allowed_domains"])
        if not host_ok or not href.startswith("http"):
            continue
        if is_bad_url(href):
            continue
        if title_is_product(text) or any(g in href.lower() for g in GOOD_MODEL_WORDS):
            results.append(href.split("#")[0])
    # Dedupe while preserving order.
    out = []
    for x in results:
        if x not in out:
            out.append(x)
    return out[:6]

async def verify_product(page, url: str, site_name: str) -> Optional[Deal]:
    ok = await safe_goto(page, url, PRODUCT_TIMEOUT_MS)
    if not ok:
        return None
    title = clean_text(await page.title())
    try:
        h1 = clean_text(await page.locator("h1").first.inner_text(timeout=3000))
        if len(h1) > 10:
            title = h1
    except Exception:
        pass
    body = clean_text(await page.locator("body").inner_text(timeout=8000))[:20000]
    if not title_is_product(title):
        return None
    prices = extract_prices(body)
    if not prices:
        return None
    price = min([p for p in prices if MIN_PRICE <= p <= MAX_PRICE], default=None)
    if price is None:
        return None
    lower = body.lower()
    buy_words = ["add to cart", "add to basket", "buy now", "ajouter au panier", "in stock", "available"]
    out_words = ["out of stock", "sold out", "unavailable", "not available", "épuisé"]
    has_buy_signal = any(w in lower for w in buy_words)
    is_out = any(w in lower for w in out_words)
    if not has_buy_signal or is_out:
        return None
    specs_bits = []
    for pat in [r"RTX\s?40[567]0", r"Ryzen\s?[579][^,|\n]{0,18}", r"Core\s?i[579][^,|\n]{0,18}", r"\b[0-9]{2}\s?GB\b", r"\b(?:512\s?GB|1\s?TB|2\s?TB)\b"]:
        m = re.search(pat, body, re.I)
        if m:
            specs_bits.append(clean_text(m.group(0)))
    specs = " • ".join(dict.fromkeys(specs_bits))
    score = score_deal(title, price, specs, site_name)
    if score < 6:
        return None
    return Deal(title=title, price=price, site=site_name, url=url, score=score, specs=specs)

async def run_scraper() -> Tuple[List[Deal], List[str]]:
    deals: List[Deal] = []
    reports: List[str] = []
    seen_urls = set()
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=HEADLESS, args=[
            "--disable-http2", "--disable-blink-features=AutomationControlled", "--no-sandbox",
        ])
        context = await browser.new_context(
            viewport={"width": 1365, "height": 900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36",
            locale="en-CA",
        )
        page = await context.new_page()
        print("Bot started - strict product mode", flush=True)
        for site in SITES:
            tested = 0
            confirmed = 0
            print(f"Checking {site['name']}", flush=True)
            site_links = []
            for kw in KEYWORDS[:MAX_KEYWORDS_PER_SITE]:
                try:
                    site_links.extend(await collect_links_from_search(page, site, kw))
                except Exception as e:
                    print(f"[{site['name']}] search error for {kw}: {str(e).splitlines()[0]}", flush=True)
            unique_links = []
            for link in site_links:
                if link not in unique_links:
                    unique_links.append(link)
            for link in unique_links[:12]:
                if link in seen_urls:
                    continue
                seen_urls.add(link)
                tested += 1
                try:
                    deal = await verify_product(page, link, site["name"])
                    if deal:
                        confirmed += 1
                        deals.append(deal)
                        print(f"CONFIRMED {deal.site}: {deal.title} - ${deal.price}", flush=True)
                except Exception as e:
                    print(f"[{site['name']}] verify error: {str(e).splitlines()[0]}", flush=True)
            reports.append(f"- {site['name']}: {confirmed} confirmés, {tested} liens produits testés")
            print(f"Done {site['name']}: {confirmed} confirmed, {tested} tested", flush=True)
        await browser.close()
    deals.sort(key=lambda d: (-d.score, d.price))
    return deals[:MAX_RESULTS_PER_RUN], reports

def send_telegram(text: str) -> None:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print(text)
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    chunks = [text[i:i+3900] for i in range(0, len(text), 3900)]
    for chunk in chunks:
        r = requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": chunk, "disable_web_page_preview": True}, timeout=30)
        r.raise_for_status()

def format_message(deals: List[Deal], reports: List[str]) -> str:
    if not deals:
        return "Aucun vrai produit confirmé cette fois. Le bot a ignoré les pages catégories/recherche.\n\nSites vérifiés ce run:\n" + "\n".join(reports)
    lines = [f"🔥 Deals laptops fiables Canada {MIN_PRICE}$–{MAX_PRICE}$ CAD\n"]
    for i, d in enumerate(deals, 1):
        specs = f"\n💻 {d.specs}" if d.specs else ""
        lines.append(
            f"{i}. {d.title}\n"
            f"💵 {d.price:,.2f} CAD{specs}\n"
            f"🏬 {d.site}\n"
            f"⭐ Score: {d.score}\n"
            f"🔗 {d.url}\n"
        )
    lines.append("Sites vérifiés ce run:")
    lines.extend(reports)
    lines.append("\nPages catégories/recherche bloquées automatiquement. Vérifie toujours taxes, stock Montréal et Open Box.")
    return "\n".join(lines)

async def main():
    seen = load_seen()
    deals, reports = await run_scraper()
    new_deals = []
    for d in deals:
        k = deal_key(d.url, d.title)
        if k not in seen:
            new_deals.append(d)
            seen.add(k)
    save_seen(seen)
    send_telegram(format_message(new_deals, reports))

if __name__ == "__main__":
    asyncio.run(main())
