import os
import re
import json
import asyncio
from urllib.parse import quote_plus, urlparse, urljoin
from playwright.async_api import async_playwright
import requests

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
MAX_PRICE = float(os.getenv("MAX_PRICE", "1000"))
MIN_PRICE = float(os.getenv("MIN_PRICE", "600"))
SEEN_FILE = "seen_deals.json"

PAGE_TIMEOUT = 9000
SITE_TIMEOUT = 110
MAX_PRODUCTS_PER_SITE = 8
MAX_RESULTS_TO_SEND = 8

QUERIES = [
    "rtx 4060 laptop",
    "rtx 4050 laptop",
    "rtx 5060 laptop",
    "lenovo legion laptop",
    "lenovo loq laptop",
    "asus tuf laptop",
    "acer nitro laptop",
    "msi gaming laptop",
    "hp victus laptop",
    "dell g15 laptop",
]

SITES = {
    "Canada Computers": {
        "domain": "canadacomputers.com",
        "search": "https://www.canadacomputers.com/en/search?s={q}",
        "product_hints": ["/en/gaming-laptops/", "/en/windows-laptops/"],
        "strict": False,
    },
    "Best Buy Canada": {
        "domain": "bestbuy.ca",
        "search": "https://www.bestbuy.ca/en-ca/search?search={q}",
        "product_hints": ["/en-ca/product/"],
        "strict": False,
    },
    "Memory Express": {
        "domain": "memoryexpress.com",
        "search": "https://www.memoryexpress.com/Search/Products?Search={q}",
        "product_hints": ["/Products/"],
        "strict": False,
    },
    "Newegg Canada": {
        "domain": "newegg.ca",
        "search": "https://www.newegg.ca/p/pl?d={q}",
        "product_hints": ["/p/"],
        "strict": True,
    },
    "Staples Canada": {
        "domain": "staples.ca",
        "search": "https://www.staples.ca/search?query={q}",
        "product_hints": ["/products/"],
        "strict": False,
    },
    "Walmart Canada": {
        "domain": "walmart.ca",
        "search": "https://www.walmart.ca/search?q={q}",
        "product_hints": ["/ip/"],
        "strict": False,
    },
    "Costco Canada": {
        "domain": "costco.ca",
        "search": "https://www.costco.ca/CatalogSearch?keyword={q}",
        "product_hints": [".product."],
        "strict": False,
    },
    "Lenovo Canada": {
        "domain": "lenovo.com",
        "search": "https://www.lenovo.com/ca/en/search?text={q}",
        "product_hints": ["/p/", "/ca/en/p/"],
        "strict": False,
    },
    "Dell Canada": {
        "domain": "dell.com",
        "search": "https://www.dell.com/en-ca/shop/scc/sr?~query={q}",
        "product_hints": ["/shop/", "/laptops/"],
        "strict": False,
    },
    "HP Canada": {
        "domain": "hp.com",
        "search": "https://www.hp.com/ca-en/shop/sitesearch?keyword={q}",
        "product_hints": ["/pdp/", "/shop/"],
        "strict": False,
    },
    "ASUS Canada": {
        "domain": "asus.com",
        "search": "https://www.asus.com/ca-en/searchresult?searchType=products&searchKey={q}",
        "product_hints": ["/ca-en/laptops/", "/laptops/"],
        "strict": False,
    },
    "Acer Canada": {
        "domain": "acer.com",
        "search": "https://www.acer.com/ca-en/search?q={q}",
        "product_hints": ["/laptops/", "/notebooks/"],
        "strict": False,
    },
    "MSI Canada": {
        "domain": "msi.com",
        "search": "https://ca.msi.com/search/{q}",
        "product_hints": ["/Laptop/", "/laptop/"],
        "strict": False,
    },
}

BAD_WORDS = ["desktop", "monitor", "keyboard", "mouse", "charger", "adapter", "case", "bag", "stand", "dock", "cooler", "chair", "tablet", "chromebook"]
GOOD_WORDS = ["laptop", "notebook", "rtx", "gaming", "legion", "loq", "tuf", "rog", "nitro", "katana", "victus", "omen", "g15", "a16", "thin"]
PRICE_RE = re.compile(r"(?:CAD|CA\$|\$)\s*([0-9]{3,5}(?:[, ][0-9]{3})*(?:\.[0-9]{2})?)", re.I)

def load_seen():
    try:
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception:
        return []

def save_seen(seen):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(seen[-1500:], f, ensure_ascii=False, indent=2)

def send_telegram(text):
    if not BOT_TOKEN or not CHAT_ID:
        print("Telegram secrets missing")
        return
    parts = []
    while text:
        parts.append(text[:3900])
        text = text[3900:]
    for part in parts:
        r = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": part, "disable_web_page_preview": True},
            timeout=20,
        )
        print("Telegram:", r.status_code, r.text[:200])

def same_domain(url, domain):
    try:
        host = urlparse(url).netloc.lower()
        domain = domain.lower()
        return host == domain or host.endswith("." + domain)
    except Exception:
        return False

def clean_url(base, href, domain):
    if not href:
        return None
    u = urljoin(base, href).split("#")[0]
    if not u.startswith("http"):
        return None
    if not same_domain(u, domain):
        return None
    return u

def looks_product_url(url, hints):
    low = url.lower()
    return any(h.lower() in low for h in hints)

def normalize_title(t):
    t = re.sub(r"\s+", " ", t or "").strip()
    return t[:180]

def valid_title(title):
    t = title.lower()
    if len(t) < 18:
        return False
    if any(b in t for b in BAD_WORDS):
        return False
    return any(g in t for g in GOOD_WORDS)

def extract_prices(text):
    text = (text or "").replace(",", "")
    prices = []
    for m in PRICE_RE.findall(text):
        try:
            p = float(m.replace(" ", ""))
            if MIN_PRICE <= p <= MAX_PRICE:
                prices.append(p)
        except Exception:
            pass
    return sorted(set(prices))

def realistic_price(title, price, strict=False):
    t = title.lower()
    if ("rtx 5080" in t or "rtx 5090" in t or "rtx 5070 ti" in t) and price < 1400:
        return False
    if "rtx 5070" in t and price < 1100:
        return False
    if "rtx 5060" in t and price < 750:
        return False
    if not any(x in t for x in ["rtx", "gaming", "legion", "loq", "tuf", "rog", "nitro", "katana", "victus", "omen", "g15"]):
        return False
    if strict:
        if not any(x in t for x in ["rtx 4050", "rtx 4060", "rtx 4070", "rtx 5060", "gaming", "legion", "tuf", "nitro", "katana", "victus", "omen"]):
            return False
        if "gateway" in t or "iris xe" in t or "uhd graphics" in t:
            return False
    return True

def score_deal(title, price):
    t = title.lower()
    s = 0
    if "rtx 4070" in t: s += 45
    if "rtx 4060" in t: s += 38
    if "rtx 5060" in t: s += 36
    if "rtx 4050" in t: s += 22
    if "i7" in t or "ryzen 7" in t or "ryzen 9" in t or "ultra 7" in t or "ultra 9" in t: s += 15
    if "16gb" in t: s += 10
    if "32gb" in t: s += 15
    if "1tb" in t: s += 10
    s += max(0, int(MAX_PRICE - price) // 30)
    return s

async def safe_goto(page, url):
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT)
        await page.wait_for_timeout(1200)
        return True
    except Exception as e:
        print("goto failed:", url, str(e)[:120])
        return False

async def get_page_text(page):
    try:
        return await page.locator("body").inner_text(timeout=3000)
    except Exception:
        return ""

async def product_price_and_title(page, fallback_title):
    # 1) Prefer the visible product title (h1). It is usually safer than link text.
    title = normalize_title(fallback_title)
    try:
        h1 = await page.locator("h1").first.inner_text(timeout=2000)
        if h1 and len(h1.strip()) >= 10:
            title = normalize_title(h1)
    except Exception:
        pass

    # 2) JSON-LD is the safest source when available because it belongs to the product.
    try:
        scripts = await page.locator('script[type="application/ld+json"]').all_text_contents()
        for raw in scripts:
            try:
                data = json.loads(raw)
                stack = data if isinstance(data, list) else [data]
                stack = list(stack)
                while stack:
                    item = stack.pop()
                    if isinstance(item, list):
                        stack.extend(item)
                        continue
                    if not isinstance(item, dict):
                        continue

                    item_title = item.get("name") or title
                    offer = item.get("offers")
                    if isinstance(offer, list):
                        stack.extend(offer)
                    elif isinstance(offer, dict):
                        price = offer.get("price") or offer.get("lowPrice")
                        if price:
                            try:
                                p = float(str(price).replace(",", ""))
                                if MIN_PRICE <= p <= MAX_PRICE:
                                    return normalize_title(item_title), p
                            except Exception:
                                pass

                    for v in item.values():
                        if isinstance(v, (dict, list)):
                            stack.append(v)
            except Exception:
                continue
    except Exception:
        pass

    # 3) Meta product price is also relatively safe.
    meta_selectors = [
        'meta[property="product:price:amount"]',
        'meta[property="og:price:amount"]',
        'meta[itemprop="price"]',
    ]
    for sel in meta_selectors:
        try:
            content = await page.locator(sel).first.get_attribute("content", timeout=1200)
            if content:
                p = float(str(content).replace(",", ""))
                if MIN_PRICE <= p <= MAX_PRICE:
                    return title, p
        except Exception:
            pass

    # 4) Fallback: scan only likely product containers, not the whole page first.
    # This avoids taking a price from recommended products lower on the page.
    container_selectors = [
        '[itemtype*="Product"]',
        '[data-testid*="product"]',
        '[class*="product-detail"]',
        '[class*="productDetail"]',
        '[class*="product-page"]',
        '[class*="productPage"]',
        '[class*="product-info"]',
        '[class*="productInfo"]',
        '#productDetails',
        '#product-summary',
        'main',
    ]
    for sel in container_selectors:
        try:
            loc = page.locator(sel).first
            txt = await loc.inner_text(timeout=2000)
            prices = extract_prices(txt)
            prices = sorted(set(prices))
            if 1 <= len(prices) <= 4:
                return title, prices[0]
        except Exception:
            pass

    # 5) Last resort: use visible price selectors, but reject noisy pages.
    price_selectors = [
        '[data-testid*="price"]',
        '[class*="sale-price"]',
        '[class*="salePrice"]',
        '[class*="current-price"]',
        '[class*="currentPrice"]',
        '[class*="product-price"]',
        '[class*="productPrice"]',
        '[id*="price"]',
        '.price',
    ]
    all_prices = []
    for sel in price_selectors:
        try:
            vals = await page.locator(sel).all_text_contents()
            for v in vals[:8]:
                all_prices.extend(extract_prices(v))
        except Exception:
            pass

    all_prices = sorted(set(all_prices))
    if 1 <= len(all_prices) <= 4:
        return title, all_prices[0]

    # Do not scan the full body if there are too many prices; it causes false deals.
    return title, None

async def collect_candidate_links(page, search_url, domain, hints):
    try:
        anchors = await page.locator("a[href]").evaluate_all("""
            els => els.map(a => ({href: a.href, text: (a.innerText || a.textContent || '').trim()}))
        """)
    except Exception:
        anchors = []
    links = []
    seen = set()
    for a in anchors:
        url = clean_url(search_url, a.get("href"), domain)
        title = normalize_title(a.get("text"))
        if not url or url in seen:
            continue
        if not looks_product_url(url, hints):
            continue
        if not valid_title(title):
            continue
        seen.add(url)
        links.append((title, url))
        if len(links) >= MAX_PRODUCTS_PER_SITE:
            break
    return links

async def scrape_site(browser, site_name, cfg):
    stats = {"tested": 0, "confirmed": 0, "rejected": 0, "errors": 0}
    deals = []

    async def inner():
        context = await browser.new_context(locale="en-CA", user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36", viewport={"width": 1365, "height": 900})
        page = await context.new_page()
        try:
            candidates = []
            seen_urls = set()
            for q in QUERIES:
                search_url = cfg["search"].format(q=quote_plus(q))
                if not await safe_goto(page, search_url):
                    stats["errors"] += 1
                    continue
                found = await collect_candidate_links(page, search_url, cfg["domain"], cfg["product_hints"])
                for title, url in found:
                    if url not in seen_urls:
                        seen_urls.add(url)
                        candidates.append((title, url))
                if len(candidates) >= MAX_PRODUCTS_PER_SITE:
                    break
            print(f"[{site_name}] candidates={len(candidates)}")
            for fallback_title, url in candidates[:MAX_PRODUCTS_PER_SITE]:
                stats["tested"] += 1
                if not await safe_goto(page, url):
                    stats["errors"] += 1
                    continue
                final_url = page.url
                if not same_domain(final_url, cfg["domain"]):
                    stats["rejected"] += 1
                    print(f"[{site_name}] rejected external redirect {final_url}")
                    continue
                title, price = await product_price_and_title(page, fallback_title)
                if price is None:
                    stats["rejected"] += 1
                    print(f"[{site_name}] rejected no price: {title[:80]}")
                    continue
                if not realistic_price(title, price, cfg.get("strict", False)):
                    stats["rejected"] += 1
                    print(f"[{site_name}] rejected unrealistic/basic: {price} {title[:100]}")
                    continue
                stats["confirmed"] += 1
                deals.append({"title": title, "price": price, "site": site_name, "url": final_url.split("?")[0], "score": score_deal(title, price)})
        finally:
            await context.close()

    try:
        await asyncio.wait_for(inner(), timeout=SITE_TIMEOUT)
    except asyncio.TimeoutError:
        stats["errors"] += 1
        print(f"[{site_name}] timeout site")
    except Exception as e:
        stats["errors"] += 1
        print(f"[{site_name}] error: {e}")
    return deals, stats

async def run():
    seen = load_seen()
    all_deals = []
    all_stats = {}
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        try:
            for site_name, cfg in SITES.items():
                deals, stats = await scrape_site(browser, site_name, cfg)
                all_deals.extend(deals)
                all_stats[site_name] = stats
        finally:
            await browser.close()

    unique = []
    used = set()
    for d in all_deals:
        if d["url"] in used:
            continue
        used.add(d["url"])
        unique.append(d)
    unique.sort(key=lambda x: (-x["score"], x["price"]))

    new = []
    for d in unique:
        if d["url"] not in seen:
            new.append(d)
            seen.append(d["url"])

    if not new:
        msg = "Aucun nouveau vrai deal confirmé cette fois.\n\nSites vérifiés ce run:\n"
        for site, st in all_stats.items():
            msg += f"- {site}: {st['confirmed']} confirmés, {st['tested']} testés, {st['rejected']} rejetés, {st['errors']} erreurs\n"
        send_telegram(msg)
        save_seen(seen)
        return

    msg = f"🔥 Deals laptops confirmés Canada {MIN_PRICE:.0f}$–{MAX_PRICE:.0f}$ CAD\n\n"
    for i, d in enumerate(new[:MAX_RESULTS_TO_SEND], 1):
        msg += f"{i}. {d['title']}\n💲 {d['price']:.2f} CAD confirmé\n🏬 {d['site']}\n⭐ Score: {d['score']}\n🔗 {d['url']}\n\n"
    msg += "Sites vérifiés ce run:\n"
    for site, st in all_stats.items():
        msg += f"- {site}: {st['confirmed']} confirmés, {st['tested']} testés, {st['rejected']} rejetés, {st['errors']} erreurs\n"
    msg += "\nPrix vérifié sur la page produit. Vérifie quand même taxes, stock Montréal et condition Open Box."
    send_telegram(msg)
    save_seen(seen)

if __name__ == "__main__":
    asyncio.run(run())
