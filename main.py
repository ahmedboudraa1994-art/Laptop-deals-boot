import os, re, json, asyncio
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
MAX_QUERIES_PER_SITE = 4
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
        "hints": ["/en/gaming-laptops/", "/en/windows-laptops/"],
        "strict": False,
    },
    "Best Buy Canada": {
        "domain": "bestbuy.ca",
        "search": "https://www.bestbuy.ca/en-ca/search?search={q}",
        "hints": ["/en-ca/product/"],
        "strict": False,
    },
    "Memory Express": {
        "domain": "memoryexpress.com",
        "search": "https://www.memoryexpress.com/Search/Products?Search={q}",
        "hints": ["/Products/"],
        "strict": False,
    },
    "Newegg Canada": {
        "domain": "newegg.ca",
        "search": "https://www.newegg.ca/p/pl?d={q}",
        "hints": ["/p/"],
        "strict": True,
    },
    "Staples Canada": {
        "domain": "staples.ca",
        "search": "https://www.staples.ca/search?query={q}",
        "hints": ["/products/"],
        "strict": False,
    },
    "Walmart Canada": {
        "domain": "walmart.ca",
        "search": "https://www.walmart.ca/search?q={q}",
        "hints": ["/ip/"],
        "strict": False,
    },
    "Costco Canada": {
        "domain": "costco.ca",
        "search": "https://www.costco.ca/CatalogSearch?keyword={q}",
        "hints": [".product.", "/products/"],
        "strict": False,
    },
    "Lenovo Canada": {
        "domain": "lenovo.com",
        "search": "https://www.lenovo.com/ca/en/search?text={q}",
        "hints": ["/p/", "/ca/en/p/"],
        "strict": False,
    },
    "Dell Canada": {
        "domain": "dell.com",
        "search": "https://www.dell.com/en-ca/shop/scc/sr?~query={q}",
        "hints": ["/shop/", "/laptops/"],
        "strict": False,
    },
    "HP Canada": {
        "domain": "hp.com",
        "search": "https://www.hp.com/ca-en/shop/sitesearch?keyword={q}",
        "hints": ["/pdp/", "/shop/"],
        "strict": False,
    },
    "ASUS Canada": {
        "domain": "asus.com",
        "search": "https://www.asus.com/ca-en/searchresult?searchType=products&searchKey={q}",
        "hints": ["/ca-en/laptops/", "/laptops/"],
        "strict": False,
    },
    "Acer Canada": {
        "domain": "acer.com",
        "search": "https://www.acer.com/ca-en/search?q={q}",
        "hints": ["/laptops/", "/notebooks/"],
        "strict": False,
    },
    "MSI Canada": {
        "domain": "msi.com",
        "search": "https://ca.msi.com/search/{q}",
        "hints": ["/Laptop/", "/laptop/"],
        "strict": False,
    },
}

BAD_URL_PARTS = [
    "/p/pl", "/p/pl?", "/search", "search?", "catalogsearch", "/category",
    "/gaming-laptops", "/windows-laptops", "/laptops-and-netbooks",
    "/collection", "/collections", "/deals", "/sale", "/promotions"
]

BAD_PAGE_TEXT = [
    "sorry this product is not available",
    "this product is not available",
    "product is not available",
    "product unavailable",
    "currently unavailable",
    "out of stock",
    "sold out",
    "discontinued",
    "no longer available",
    "take me there now",
    "similar products",
    "search results",
    "no more content",
    "you are here",
    "captcha",
    "verify you are human",
    "verify you're human",
    "access denied",
    "unusual traffic",
    "are you a robot",
    "robot check",
    "blocked",
    "forbidden",
    "cloudflare",
    "akamai",
    "perimeterx",
]

CATEGORY_TITLES = {
    "gaming laptops", "laptops", "notebooks", "search results",
    "laptop computers", "windows laptops", "shop laptops"
}

BAD_WORDS = [
    "desktop", "monitor", "keyboard", "mouse", "charger", "adapter", "case",
    "bag", "stand", "dock", "cooler", "chair", "tablet", "chromebook"
]

GOOD_WORDS = [
    "laptop", "notebook", "rtx", "gaming", "legion", "loq", "tuf", "rog",
    "nitro", "katana", "victus", "omen", "g15", "a16", "thin"
]

PRICE_RE = re.compile(r"(?:cad|ca\$|\$)\s*([0-9]{3,5}(?:[ ,][0-9]{3})*(?:\.[0-9]{2})?)", re.I)

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
    while text:
        part, text = text[:3900], text[3900:]
        r = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": part, "disable_web_page_preview": True},
            timeout=20,
        )
        print("Telegram:", r.status_code, r.text[:160])

def same_domain(url, domain):
    try:
        host = urlparse(url).netloc.lower()
        return host == domain.lower() or host.endswith("." + domain.lower())
    except Exception:
        return False

def is_bad_url(url):
    u = (url or "").lower()
    return any(x in u for x in BAD_URL_PARTS)

def clean_url(base, href, domain):
    if not href:
        return None
    u = urljoin(base, href).split("#")[0]
    if not u.startswith("http"):
        return None
    if not same_domain(u, domain):
        return None
    if is_bad_url(u):
        return None
    return u

def normalize_title(t):
    return re.sub(r"\s+", " ", t or "").strip()[:180]

def is_category_title(t):
    low = normalize_title(t).lower()
    if low in CATEGORY_TITLES:
        return True
    return any(low.startswith(x + " |") or low.startswith(x + " -") for x in CATEGORY_TITLES)

def valid_title(title):
    t = normalize_title(title).lower()
    if len(t) < 18 or is_category_title(t):
        return False
    if any(b in t for b in BAD_WORDS):
        return False
    return any(g in t for g in GOOD_WORDS)

def extract_prices(text):
    vals = []
    for m in PRICE_RE.findall(text or ""):
        try:
            p = float(m.replace(",", "").replace(" ", ""))
            if MIN_PRICE <= p <= MAX_PRICE:
                vals.append(p)
        except Exception:
            pass
    return sorted(set(vals))

def page_is_bad(text, url):
    low = (text or "").lower()
    if is_bad_url(url):
        return True
    return any(x in low for x in BAD_PAGE_TEXT)

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
    if not any(x in t for x in ["rtx", "gaming", "legion", "loq", "tuf", "rog", "nitro", "katana", "victus", "omen", "g15"]):
        return False
    if strict:
        if "gateway" in t or "iris xe" in t or "uhd graphics" in t:
            return False
        if not any(x in t for x in ["rtx 4050", "rtx 4060", "rtx 4070", "rtx 5060", "gaming", "legion", "tuf", "nitro", "katana", "victus", "omen"]):
            return False
    return True

def score_deal(title, price):
    t = title.lower()
    s = 0
    if "rtx 4070" in t: s += 45
    if "rtx 4060" in t: s += 38
    if "rtx 5060" in t: s += 36
    if "rtx 4050" in t: s += 22
    if any(x in t for x in ["i7", "ryzen 7", "ryzen 9", "ultra 7", "ultra 9"]): s += 15
    if "16gb" in t: s += 10
    if "32gb" in t: s += 15
    if "1tb" in t: s += 10
    s += max(0, int(MAX_PRICE - price) // 30)
    return s

async def safe_goto(page, url):
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT)
        await page.wait_for_timeout(900)
        return True
    except Exception as e:
        print("goto failed:", url, str(e)[:100])
        return False

async def body_text(page):
    try:
        return await page.locator("body").inner_text(timeout=3000)
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
                stack.extend(item)
            elif isinstance(item, dict):
                name = normalize_title(item.get("name") or fallback)
                offer = item.get("offers")
                if isinstance(offer, list):
                    stack.extend(offer)
                elif isinstance(offer, dict):
                    price = offer.get("price") or offer.get("lowPrice")
                    try:
                        p = float(str(price).replace(",", ""))
                        if MIN_PRICE <= p <= MAX_PRICE and valid_title(name):
                            return name, p
                    except Exception:
                        pass
                for v in item.values():
                    if isinstance(v, (dict, list)):
                        stack.append(v)
    return None, None

async def meta_price(page):
    selectors = [
        'meta[property="product:price:amount"]',
        'meta[property="og:price:amount"]',
        'meta[itemprop="price"]',
    ]
    for sel in selectors:
        try:
            c = await page.locator(sel).get_attribute("content", timeout=1000)
            if c:
                p = float(c.replace(",", ""))
                if MIN_PRICE <= p <= MAX_PRICE:
                    return p
        except Exception:
            pass
    return None

async def scoped_prices(page):
    selectors = [
        "main", "#product-page", ".product-page", ".product-detail", ".productDetails",
        ".product-info", ".product-main", "[data-testid*='product']"
    ]
    for sel in selectors:
        try:
            txts = await page.locator(sel).all_inner_texts(timeout=1500)
            prices = []
            for t in txts[:4]:
                prices.extend(extract_prices(t))
            prices = sorted(set(prices))
            if 1 <= len(prices) <= 5:
                return prices[0]
        except Exception:
            pass
    return None

async def get_product_data(page, fallback_title, strict):
    text = await body_text(page)
    if page_is_bad(text, page.url):
        return None, None, "bad/unavailable/category/antibot page"

    title, price = await jsonld_price(page, fallback_title)
    if price is None:
        meta = await meta_price(page)
        if meta is not None:
            title = await page_title(page, fallback_title)
            price = meta

    if price is None:
        scoped = await scoped_prices(page)
        if scoped is not None:
            title = await page_title(page, fallback_title)
            price = scoped

    if price is None:
        return None, None, "no reliable price"

    if not valid_title(title):
        return None, None, "bad/category title"

    if not realistic_price(title, price, strict):
        return None, None, f"unrealistic/basic price {price}"

    return title, price, "ok"

async def collect_links(page, search_url, cfg):
    try:
        anchors = await page.locator("a[href]").evaluate_all("""
            els => els.map(a => ({href: a.href, text: (a.innerText || a.textContent || '').trim()}))
        """)
    except Exception:
        anchors = []
    out, seen = [], set()
    for a in anchors:
        url = clean_url(search_url, a.get("href"), cfg["domain"])
        title = normalize_title(a.get("text"))
        if not url or url in seen:
            continue
        if not any(h.lower() in url.lower() for h in cfg["hints"]):
            continue
        if not valid_title(title):
            continue
        seen.add(url)
        out.append((title, url))
        if len(out) >= MAX_PRODUCTS_PER_SITE:
            break
    return out

async def scrape_site(browser, site_name, cfg):
    stats = {"tested": 0, "confirmed": 0, "rejected": 0, "errors": 0}
    deals = []

    async def inner():
        context = await browser.new_context(
            locale="en-CA",
            viewport={"width": 1365, "height": 900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        )
        page = await context.new_page()
        try:
            candidates, used = [], set()
            for q in QUERIES[:MAX_QUERIES_PER_SITE]:
                search_url = cfg["search"].format(q=quote_plus(q))
                if not await safe_goto(page, search_url):
                    stats["errors"] += 1
                    continue
                for title, url in await collect_links(page, search_url, cfg):
                    if url not in used:
                        used.add(url)
                        candidates.append((title, url))
                if len(candidates) >= MAX_PRODUCTS_PER_SITE:
                    break

            print(f"[{site_name}] candidates={len(candidates)}")
            for fallback, url in candidates[:MAX_PRODUCTS_PER_SITE]:
                stats["tested"] += 1
                if not await safe_goto(page, url):
                    stats["errors"] += 1
                    continue
                if not same_domain(page.url, cfg["domain"]) or is_bad_url(page.url):
                    stats["rejected"] += 1
                    print(f"[{site_name}] reject url {page.url}")
                    continue
                title, price, reason = await get_product_data(page, fallback, cfg.get("strict", False))
                if reason != "ok":
                    stats["rejected"] += 1
                    print(f"[{site_name}] reject {reason}: {fallback[:80]}")
                    continue
                stats["confirmed"] += 1
                deals.append({
                    "title": title,
                    "price": price,
                    "site": site_name,
                    "url": page.url.split("?")[0],
                    "score": score_deal(title, price),
                })
        finally:
            await context.close()

    try:
        await asyncio.wait_for(inner(), timeout=SITE_TIMEOUT)
    except asyncio.TimeoutError:
        stats["errors"] += 1
        print(f"[{site_name}] site timeout")
    except Exception as e:
        stats["errors"] += 1
        print(f"[{site_name}] error {e}")
    return deals, stats

async def run():
    seen = load_seen()
    all_deals, all_stats = [], {}
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        try:
            for name, cfg in SITES.items():
                deals, stats = await scrape_site(browser, name, cfg)
                all_deals.extend(deals)
                all_stats[name] = stats
        finally:
            await browser.close()

    unique, used = [], set()
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
        msg = "Aucun nouveau vrai deal confirmé cette fois.\\n\\nSites vérifiés ce run:\\n"
    else:
        msg = f"🔥 Deals laptops confirmés Canada {MIN_PRICE:.0f}$–{MAX_PRICE:.0f}$ CAD\\n\\n"
        for i, d in enumerate(new[:MAX_RESULTS_TO_SEND], 1):
            msg += f"{i}. {d['title']}\\n💲 {d['price']:.2f} CAD confirmé\\n🏬 {d['site']}\\n⭐ Score: {d['score']}\\n🔗 {d['url']}\\n\\n"
        msg += "Sites vérifiés ce run:\\n"

    for site, st in all_stats.items():
        msg += f"- {site}: {st['confirmed']} confirmés, {st['tested']} testés, {st['rejected']} rejetés, {st['errors']} erreurs\\n"
    msg += "\\nPrix vérifié sur fiche produit disponible. Vérifie quand même taxes, stock Montréal et Open Box."
    send_telegram(msg)
    save_seen(seen)

if __name__ == "__main__":
    asyncio.run(run())
