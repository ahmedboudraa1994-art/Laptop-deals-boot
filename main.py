import os
import re
import json
import asyncio
from urllib.parse import quote_plus, urlparse, urljoin

import requests
from playwright.async_api import async_playwright

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
MAX_PRICE = float(os.getenv("MAX_PRICE", "1000"))
MIN_PRICE = float(os.getenv("MIN_PRICE", "600"))
SEEN_FILE = "seen_deals.json"

PAGE_TIMEOUT = 14000
SITE_TIMEOUT = 240
MAX_PRODUCTS_PER_SITE = 10
MAX_RESULTS_TO_SEND = 8
DEBUG_IN_TELEGRAM = True

QUERIES = [
    "gaming laptop", "gaming notebook", "RTX laptop", "GeForce RTX laptop",
    "rtx 4050 laptop", "rtx 4060 laptop", "rtx 5060 laptop",
    "Lenovo Legion", "Lenovo LOQ", "ASUS TUF", "ASUS ROG",
    "Acer Nitro", "Predator Helios", "HP Victus", "HP Omen",
    "Dell G15", "Dell G16", "MSI Katana", "MSI Thin", "MSI Cyborg",
    "Gigabyte A16", "Gigabyte G6",
]

SITE_QUERIES = {
    "Canada Computers": ["rtx 4060 laptop", "rtx 4050 laptop", "rtx 5060 laptop", "gaming laptop", "asus tuf", "lenovo legion", "lenovo loq", "acer nitro", "msi katana", "hp victus", "dell g15", "gigabyte a16"],
    "Best Buy Canada": ["rtx 4060 laptop", "rtx 4050 laptop", "gaming laptop", "lenovo legion", "asus tuf", "acer nitro", "hp victus", "dell g15", "msi katana", "asus rog", "lenovo loq"],
    "Memory Express": ["rtx 4060 laptop", "rtx 4050 laptop", "gaming notebook", "lenovo legion", "asus tuf", "acer nitro", "msi katana", "gigabyte g6", "hp victus"],
    "Newegg Canada": ["rtx 4060 laptop", "rtx 4050 laptop", "gaming laptop", "lenovo legion", "asus tuf", "acer nitro", "msi katana", "hp victus", "dell g15"],
    "Staples Canada": ["gaming laptop", "rtx laptop", "lenovo legion", "asus tuf", "acer nitro", "hp victus", "msi gaming laptop"],
    "Walmart Canada": ["gaming laptop", "rtx laptop", "lenovo legion", "asus tuf", "acer nitro", "msi gaming laptop", "hp victus"],
    "Costco Canada": ["gaming laptop", "rtx laptop", "lenovo legion", "hp victus", "asus tuf", "msi laptop", "acer nitro"],
    "Lenovo Canada": ["Legion", "LOQ", "RTX 4060", "RTX 4050", "gaming laptop", "Legion 5", "LOQ 15", "Legion Slim"],
    "Dell Canada": ["G15", "G16", "Alienware", "RTX 4060", "RTX 4050", "gaming laptop"],
    "HP Canada": ["Victus", "Omen", "RTX 4060", "RTX 4050", "gaming laptop"],
    "ASUS Canada": ["TUF", "ROG", "RTX 4060", "RTX 4050", "gaming laptop"],
    "Acer Canada": ["Nitro", "Predator", "RTX 4060", "RTX 4050", "gaming laptop"],
    "MSI Canada": ["Katana", "Thin", "Cyborg", "RTX 4060", "RTX 4050", "gaming laptop"],
}

MAX_QUERIES_PER_SITE = 999

SITES = {
    "Canada Computers": {"domain":"canadacomputers.com", "search":"https://www.canadacomputers.com/en/search?s={q}", "hints":["/en/gaming-laptops/", "/en/windows-laptops/", "/en/laptops/"], "hint_regex": r"/en/[a-z0-9-]+/\d{4,7}/[a-z0-9-]+\.html", "strict":False},
    "Best Buy Canada": {"domain":"bestbuy.ca", "search":"https://www.bestbuy.ca/en-ca/search?search={q}", "hints":["/en-ca/product/"], "strict":False},
    "Memory Express": {"domain":"memoryexpress.com", "search":"https://www.memoryexpress.com/Search/Products?Search={q}", "hints":["/Products/"], "strict":False},
    "Newegg Canada": {"domain":"newegg.ca", "search":"https://www.newegg.ca/p/pl?d={q}", "hints":["/p/"], "strict":True},
    "Staples Canada": {"domain":"staples.ca", "search":"https://www.staples.ca/search?query={q}", "hints":["/products/"], "strict":False},
    "Walmart Canada": {"domain":"walmart.ca", "search":"https://www.walmart.ca/search?q={q}", "hints":["/ip/"], "strict":False},
    "Costco Canada": {"domain":"costco.ca", "search":"https://www.costco.ca/CatalogSearch?keyword={q}", "hints":[".product.", "/products/"], "strict":False},
    "Lenovo Canada": {"domain":"lenovo.com", "search":"https://www.lenovo.com/ca/en/search?text={q}", "hints":["/p/", "/ca/en/p/", "/laptops/"], "strict":False},
    "Dell Canada": {"domain":"dell.com", "search":"https://www.dell.com/en-ca/shop/scc/sr?~query={q}", "hints":["/shop/", "/laptops/", "/gaming-laptops/"], "strict":False},
    "HP Canada": {"domain":"hp.com", "search":"https://www.hp.com/ca-en/shop/sitesearch?keyword={q}", "hints":["/pdp/", "/shop/"], "strict":False},
    "ASUS Canada": {"domain":"asus.com", "search":"https://www.asus.com/ca-en/searchresult?searchType=products&searchKey={q}", "hints":["/ca-en/laptops/", "/laptops/"], "strict":False},
    "Acer Canada": {"domain":"acer.com", "search":"https://www.acer.com/ca-en/search?q={q}", "hints":["/laptops/", "/notebooks/", "/gaming/"], "strict":False},
    "MSI Canada": {"domain":"msi.com", "search":"https://ca.msi.com/search/{q}", "hints":["/Laptop/", "/laptop/"], "strict":False},
}

BAD_URL_PARTS = [
    "/p/pl", "/p/pl?", "/search", "search?", "catalogsearch", "/category", "/categories",
    "/collection", "/collections", "/deals", "/sale", "/promotions", "/promo", "/clearance",
    "/laptops-and-netbooks", "/laptops/pc-laptops",
]
BAD_PAGE_TEXT = [
    "sorry this product is not available", "this product is not available", "product is not available",
    "product unavailable", "currently unavailable", "out of stock", "sold out", "discontinued",
    "no longer available", "take me there now", "similar products", "search results", "no more content",
    "you are here", "captcha", "verify you are human", "verify you're human", "access denied",
    "unusual traffic", "are you a robot", "robot check", "blocked", "forbidden", "cloudflare", "akamai", "perimeterx",
    "please enable cookies",
    "enable javascript",
    "request blocked",
    "bot detection",
    "security check",
    "checking your browser",
    "temporarily unavailable",
    "item unavailable",
    "not sold online",
    "not available for delivery",
    "not available in your area",
    "please verify",
    "human verification",
    "automated access",
]
CATEGORY_TITLES = {"gaming laptops", "laptops", "notebooks", "search results", "laptop computers", "windows laptops", "shop laptops", "pc laptops"}
BAD_WORDS = ["desktop", "monitor", "keyboard", "mouse", "charger", "adapter", "case", "bag", "stand", "dock", "cooler", "chair", "tablet", "chromebook", "screen protector"]
GOOD_WORDS = ["laptop", "notebook", "rtx", "gaming", "legion", "loq", "tuf", "rog", "nitro", "predator", "katana", "thin", "cyborg", "victus", "omen", "g15", "g16", "a16", "gigabyte"]
PRICE_RE = re.compile(r"(?:cad|ca\$|\$)\s*([0-9]{1,3}(?:[ ,][0-9]{3})+(?:\.[0-9]{2})?|[0-9]{3,5}(?:\.[0-9]{2})?)", re.I)


def load_seen():
    try:
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception:
        return []


def save_seen(seen):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(seen[-2000:], f, ensure_ascii=False, indent=2)


def send_telegram(text):
    if not BOT_TOKEN or not CHAT_ID:
        print("Telegram secrets missing")
        return
    while text:
        part, text = text[:3900], text[3900:]
        r = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": part, "disable_web_page_preview": True},
            timeout=20,
        )
        print("Telegram:", r.status_code, r.text[:160])


def normalize_title(text):
    return re.sub(r"\s+", " ", text or "").strip()[:180]


def same_domain(url, domain):
    try:
        host = urlparse(url).netloc.lower()
        domain = domain.lower()
        return host == domain or host.endswith("." + domain)
    except Exception:
        return False


def is_bad_url(url):
    u = (url or "").lower()
    return any(x in u for x in BAD_URL_PARTS)


GENERIC_LISTING_PATTERNS = re.compile(
    r"^(all|shop all|view all|browse all|explore all|see all|discover)\b", re.I
)


def is_category_title(title):
    low = normalize_title(title).lower()
    if low in CATEGORY_TITLES:
        return True
    if GENERIC_LISTING_PATTERNS.match(low):
        return True
    return any(low.startswith(c + " |") or low.startswith(c + " -") or low.startswith(c + " at ") for c in CATEGORY_TITLES)


def valid_title(title):
    t = normalize_title(title).lower()
    if len(t) < 18 or is_category_title(t):
        return False
    if any(b in t for b in BAD_WORDS):
        return False
    return any(g in t for g in GOOD_WORDS)


def extract_prices(text):
    return extract_prices_loose(text)

def page_is_bad(text, url):
    low = (text or "").lower()
    return is_bad_url(url) or any(term in low for term in BAD_PAGE_TEXT)


def realistic_price(title, price, strict=False):
    t = normalize_title(title).lower()
    if is_category_title(t):
        return False
    if ("rtx 5080" in t or "rtx 5090" in t or "rtx 5070 ti" in t) and price < 1400:
        return False
    if "rtx 5070" in t and price < 1100:
        return False
    if "rtx 5060" in t and price < 750:
        return False
    if not any(x in t for x in ["rtx", "gaming", "legion", "loq", "tuf", "rog", "nitro", "predator", "katana", "thin", "cyborg", "victus", "omen", "g15", "g16"]):
        return False
    if strict:
        if "gateway" in t or "iris xe" in t or "uhd graphics" in t:
            return False
        if not any(x in t for x in ["rtx 4050", "rtx 4060", "rtx 4070", "rtx 5060", "gaming", "legion", "tuf", "nitro", "katana", "victus", "omen"]):
            return False
    return True


def score_deal(title, price):
    t, score = title.lower(), 0
    if "rtx 4070" in t: score += 45
    if "rtx 4060" in t: score += 38
    if "rtx 5060" in t: score += 36
    if "rtx 4050" in t: score += 22
    if any(x in t for x in ["i9", "ryzen 9", "ultra 9"]): score += 18
    if any(x in t for x in ["i7", "ryzen 7", "ultra 7"]): score += 15
    if "32gb" in t: score += 15
    if "16gb" in t: score += 10
    if "1tb" in t: score += 10
    score += max(0, int(MAX_PRICE - price) // 30)
    return score


async def safe_goto(page, url):
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT)
        await page.wait_for_timeout(1200)
        return True
    except Exception as e:
        print("goto failed:", url, str(e)[:120])
        return False


async def body_text(page):
    try:
        return await page.locator("body").inner_text(timeout=3500)
    except Exception:
        return ""


async def page_title(page, fallback):
    try:
        title = normalize_title(await page.title())
        if valid_title(title):
            return title
    except Exception:
        pass
    return normalize_title(fallback)


async def jsonld_price(page, fallback):
    try:
        scripts = await page.locator('script[type="application/ld+json"]').all_text_contents()
    except Exception:
        scripts = []
    for raw in scripts:
        try:
            data = json.loads(raw)
        except Exception:
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            item = stack.pop()
            if isinstance(item, list):
                stack.extend(item); continue
            if not isinstance(item, dict):
                continue
            name = normalize_title(item.get("name") or fallback)
            offers = item.get("offers")
            if isinstance(offers, list):
                stack.extend(offers)
            elif isinstance(offers, dict):
                price = offers.get("price") or offers.get("lowPrice")
                try:
                    p = float(str(price).replace(",", ""))
                    if MIN_PRICE <= p <= MAX_PRICE and valid_title(name):
                        return name, p
                except Exception:
                    pass
            for v in item.values():
                if isinstance(v, (list, dict)):
                    stack.append(v)
    return None, None



async def script_price(page, fallback):
    try:
        scripts = await page.locator("script").all_text_contents()
    except Exception:
        scripts = []

    best_title = normalize_title(fallback)
    prices = []

    for raw in scripts[:80]:
        if not raw:
            continue

        try:
            data = json.loads(raw)
            stack = [data]
            while stack:
                item = stack.pop()
                if isinstance(item, list):
                    stack.extend(item)
                elif isinstance(item, dict):
                    name = item.get("name") or item.get("title") or item.get("productName")
                    if name and valid_title(str(name)):
                        best_title = normalize_title(str(name))

                    for key in ["price", "salePrice", "finalPrice", "currentPrice", "lowPrice", "value"]:
                        p = parse_price_value(item.get(key))
                        if p is not None:
                            prices.append(p)

                    for v in item.values():
                        if isinstance(v, (dict, list)):
                            stack.append(v)
        except Exception:
            pass

        prices.extend(extract_prices_loose(raw[:300000]))

    prices = sorted(set(prices))
    if 1 <= len(prices) <= 10:
        return best_title, prices[0]

    return None, None


async def meta_price(page):
    for sel in ['meta[property="product:price:amount"]', 'meta[property="og:price:amount"]', 'meta[itemprop="price"]']:
        try:
            content = await page.locator(sel).get_attribute("content", timeout=1000)
            if content:
                price = float(content.replace(",", ""))
                if MIN_PRICE <= price <= MAX_PRICE:
                    return price
        except Exception:
            pass
    return None



def parse_price_value(value):
    try:
        if value is None:
            return None
        s = str(value)
        s = s.replace("CAD", "").replace("CA$", "").replace("$", "")
        s = s.replace(",", "").replace(" ", "").strip()
        p = float(s)
        if MIN_PRICE <= p <= MAX_PRICE:
            return p
    except Exception:
        pass
    return None


def extract_prices_loose(text):
    vals = []
    text = text or ""

    try:
        for raw in PRICE_RE.findall(text):
            p = parse_price_value(raw)
            if p is not None:
                vals.append(p)
    except Exception:
        pass

    patterns = [
        r'"price"\s*:\s*"?([0-9]{3,5}(?:\.[0-9]{2})?)"?',
        r'"salePrice"\s*:\s*"?([0-9]{3,5}(?:\.[0-9]{2})?)"?',
        r'"finalPrice"\s*:\s*"?([0-9]{3,5}(?:\.[0-9]{2})?)"?',
        r'"currentPrice"\s*:\s*"?([0-9]{3,5}(?:\.[0-9]{2})?)"?',
        r'"lowPrice"\s*:\s*"?([0-9]{3,5}(?:\.[0-9]{2})?)"?',
        r'"value"\s*:\s*"?([0-9]{3,5}(?:\.[0-9]{2})?)"?',
        r'price\s*:\s*"?([0-9]{3,5}(?:\.[0-9]{2})?)"?',
        r'salePrice\s*:\s*"?([0-9]{3,5}(?:\.[0-9]{2})?)"?',
        r'finalPrice\s*:\s*"?([0-9]{3,5}(?:\.[0-9]{2})?)"?',
    ]

    for pat in patterns:
        for raw in re.findall(pat, text, flags=re.I):
            p = parse_price_value(raw)
            if p is not None:
                vals.append(p)

    return sorted(set(vals))


def all_prices_any_range(text):
    """Same regex as extract_prices_loose but without the MIN/MAX filter, used to sanity-check
    that we're not confirming a decoy price while the real (higher) price sits elsewhere on the page."""
    vals = []
    text = text or ""
    try:
        for raw in PRICE_RE.findall(text):
            p = parse_price_value_any_range(raw)
            if p is not None:
                vals.append(p)
    except Exception:
        pass
    return vals


def parse_price_value_any_range(value):
    try:
        if value is None:
            return None
        s = str(value).replace("CAD", "").replace("CA$", "").replace("$", "")
        s = s.replace(",", "").replace(" ", "").strip()
        return float(s)
    except Exception:
        return None


async def scoped_price(page):
    selectors = [
        "[itemtype*='Product']",
        "[data-testid*='product']",
        "[data-test*='product']",
        "[class*='Product']",
        "[class*='product']",
        "main",
        "#product-page",
        "#productPage",
        "#pdp",
        ".pdp",
        ".product-page",
        ".product-detail",
        ".productDetails",
        ".product-info",
        ".product-main",
        ".priceView-hero-price",
        ".priceView-customer-price",
        ".pricing",
        ".productPricing",
        ".price",
        "[class*='price']",
    ]

    for sel in selectors:
        try:
            texts = await page.locator(sel).all_inner_texts(timeout=1800)
        except Exception:
            continue

        prices = []
        raw_prices = []
        for txt in texts[:8]:
            prices.extend(extract_prices_loose(txt))
            raw_prices.extend(all_prices_any_range(txt))

        prices = sorted(set(prices))
        much_larger_nearby = any(rp > MAX_PRICE * 1.5 for rp in raw_prices)

        if 1 <= len(prices) <= 8:
            if much_larger_nearby:
                print(f"[scoped-price-skip] in-range price {prices[0]} ignored: a larger price also found nearby (likely the real price)")
                continue
            return prices[0]

    return None


async def get_product_data(page, fallback_title, strict):
    text = await body_text(page)
    if page_is_bad(text, page.url):
        snippet = re.sub(r"\s+", " ", (text or ""))[:200]
        print(f"[antibot-debug] {page.url} -> {snippet!r}")
        return None, None, "bad/unavailable/category/antibot page"
    title, price = await jsonld_price(page, fallback_title)
    if price is None:
        s_title, s_price = await script_price(page, fallback_title)
        if s_price is not None:
            title, price = s_title, s_price
    if price is None:
        meta = await meta_price(page)
        if meta is not None:
            title, price = await page_title(page, fallback_title), meta
    if price is None:
        scoped = await scoped_price(page)
        if scoped is not None:
            title, price = await page_title(page, fallback_title), scoped
    if price is None:
        return None, None, "no reliable price"
    if not valid_title(title):
        return None, None, "bad/category title"
    if not realistic_price(title, price, strict):
        return None, None, f"unrealistic/basic price {price}"
    return title, price, "ok"


async def collect_links(page, search_url, cfg):
    debug = {"anchors": 0, "bad_domain": 0, "bad_url": 0, "bad_hint": 0, "bad_title": 0, "kept": 0}
    try:
        anchors = await page.locator("a[href]").evaluate_all("""
            els => els.map(a => ({href: a.href, text: (a.innerText || a.textContent || '').trim()}))
        """)
    except Exception:
        anchors = []
    debug["anchors"] = len(anchors)
    results, seen = [], set()
    for a in anchors:
        raw_url = a.get("href")
        raw_title = normalize_title(a.get("text"))
        if not raw_url:
            continue
        full = urljoin(search_url, raw_url).split("#")[0]
        if not same_domain(full, cfg["domain"]):
            debug["bad_domain"] += 1; continue
        if is_bad_url(full):
            debug["bad_url"] += 1; continue
        matches_hint = any(h.lower() in full.lower() for h in cfg["hints"])
        if not matches_hint and cfg.get("hint_regex"):
            matches_hint = bool(re.search(cfg["hint_regex"], full, re.I))
        if not matches_hint:
            debug["bad_hint"] += 1; continue
        if not valid_title(raw_title):
            debug["bad_title"] += 1; continue
        if full in seen:
            continue
        seen.add(full)
        results.append((raw_title, full))
        debug["kept"] += 1
        if len(results) >= MAX_PRODUCTS_PER_SITE:
            break
    return results, debug


async def scrape_site(browser, site_name, cfg):
    stats = {"tested": 0, "confirmed": 0, "rejected": 0, "errors": 0, "links_found": 0, "bad_domain": 0, "bad_url": 0, "bad_hint": 0, "bad_title": 0, "kept_links": 0}
    reject_reasons, deals = {}, []
    async def inner():
        context = await browser.new_context(locale="en-CA", viewport={"width": 1365, "height": 900}, user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36", extra_http_headers={"Accept-Language":"en-CA,en;q=0.9,fr-CA;q=0.8"})
        page = await context.new_page()
        try:
            candidates, used = [], set()
            for q in SITE_QUERIES.get(site_name, QUERIES)[:MAX_QUERIES_PER_SITE]:
                search_url = cfg["search"].format(q=quote_plus(q))
                if not await safe_goto(page, search_url):
                    stats["errors"] += 1; continue
                links, dbg = await collect_links(page, search_url, cfg)
                for k in ["anchors", "bad_domain", "bad_url", "bad_hint", "bad_title", "kept"]:
                    pass
                stats["links_found"] += dbg["anchors"]
                stats["bad_domain"] += dbg["bad_domain"]
                stats["bad_url"] += dbg["bad_url"]
                stats["bad_hint"] += dbg["bad_hint"]
                stats["bad_title"] += dbg["bad_title"]
                stats["kept_links"] += dbg["kept"]
                if not links:
                    await page.wait_for_timeout(2500)
                    links, dbg = await collect_links(page, search_url, cfg)
                    stats["links_found"] += dbg["anchors"]
                    stats["bad_domain"] += dbg["bad_domain"]
                    stats["bad_url"] += dbg["bad_url"]
                    stats["bad_hint"] += dbg["bad_hint"]
                    stats["bad_title"] += dbg["bad_title"]
                    stats["kept_links"] += dbg["kept"]
                    if dbg["anchors"] == 0:
                        raw = await body_text(page)
                        snippet = re.sub(r"\s+", " ", (raw or ""))[:200]
                        print(f"[search-empty-debug] [{site_name}] {page.url} -> {snippet!r}")
                for title, url in links:
                    if url not in used:
                        used.add(url); candidates.append((title, url))
                if len(candidates) >= MAX_PRODUCTS_PER_SITE:
                    break
            print(f"[{site_name}] candidates={len(candidates)}")
            for fallback, url in candidates[:MAX_PRODUCTS_PER_SITE]:
                stats["tested"] += 1
                if not await safe_goto(page, url):
                    stats["errors"] += 1; continue
                if not same_domain(page.url, cfg["domain"]) or is_bad_url(page.url):
                    stats["rejected"] += 1; reject_reasons["bad url/redirect"] = reject_reasons.get("bad url/redirect", 0) + 1; continue
                title, price, reason = await get_product_data(page, fallback, cfg.get("strict", False))
                if reason != "ok":
                    stats["rejected"] += 1; reject_reasons[reason] = reject_reasons.get(reason, 0) + 1
                    print(f"[{site_name}] reject {reason}: {fallback[:80]}"); continue
                stats["confirmed"] += 1
                deals.append({"title": title, "price": price, "site": site_name, "url": page.url.split("?")[0], "score": score_deal(title, price)})
        finally:
            await context.close()
    try:
        await asyncio.wait_for(inner(), timeout=SITE_TIMEOUT)
    except asyncio.TimeoutError:
        stats["errors"] += 1; reject_reasons["site timeout"] = reject_reasons.get("site timeout", 0) + 1
        print(f"[{site_name}] site timeout")
    except Exception as e:
        stats["errors"] += 1; reject_reasons[f"error {str(e)[:40]}"] = reject_reasons.get(f"error {str(e)[:40]}", 0) + 1
        print(f"[{site_name}] error {e}")
    return deals, stats, reject_reasons


async def run():
    seen, all_deals, all_stats, all_reasons = load_seen(), [], {}, {}
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        try:
            for site_name, cfg in SITES.items():
                deals, stats, reasons = await scrape_site(browser, site_name, cfg)
                all_deals.extend(deals); all_stats[site_name] = stats; all_reasons[site_name] = reasons
        finally:
            await browser.close()
    unique, used = [], set()
    for d in all_deals:
        if d["url"] in used: continue
        used.add(d["url"]); unique.append(d)
    unique.sort(key=lambda x: (-x["score"], x["price"]))
    new = []
    for d in unique:
        if d["url"] not in seen:
            new.append(d); seen.append(d["url"])
    if new:
        msg = f"🔥 Deals laptops confirmés Canada {MIN_PRICE:.0f}$–{MAX_PRICE:.0f}$ CAD\n\n"
        for i, d in enumerate(new[:MAX_RESULTS_TO_SEND], 1):
            msg += f"{i}. {d['title']}\n💲 {d['price']:.2f} CAD confirmé\n🏬 {d['site']}\n⭐ Score: {d['score']}\n🔗 {d['url']}\n\n"
    else:
        msg = "Aucun nouveau vrai deal confirmé cette fois.\n\n"
    msg += "Sites vérifiés ce run:\n"
    for site, st in all_stats.items():
        msg += f"- {site}: {st['confirmed']} confirmés, {st['tested']} testés, {st['rejected']} rejetés, {st['errors']} erreurs | liens: {st['links_found']} trouvés, {st['kept_links']} gardés, {st['bad_hint']} bad_hint, {st['bad_title']} bad_title, {st['bad_url']} bad_url\n"
        if all_reasons.get(site):
            top = sorted(all_reasons[site].items(), key=lambda x: -x[1])[:2]
            msg += "  rejets: " + ", ".join(f"{k}={v}" for k, v in top) + "\n"
    msg += "\nPrix vérifié sur fiche produit disponible. Vérifie quand même taxes, stock Montréal et Open Box."
    send_telegram(msg)
    save_seen(seen)


if __name__ == "__main__":
    asyncio.run(run())
