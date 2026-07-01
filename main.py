import asyncio
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import quote_plus, urlparse

import requests
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
MIN_PRICE = float(os.getenv("MIN_PRICE", "600"))
MAX_PRICE = float(os.getenv("MAX_PRICE", "1000"))
HEADLESS = os.getenv("HEADLESS", "1") != "0"
SEEN_FILE = Path("seen_deals.json")
MAX_RESULTS_PER_SITE = 5
MAX_TOTAL_DEALS = 8

QUERIES = [
    "rtx 4060 laptop",
    "rtx 4070 laptop",
    "rtx 4050 laptop",
    "lenovo legion laptop",
    "lenovo loq laptop",
    "asus tuf laptop",
    "asus rog laptop",
    "acer nitro laptop",
    "msi katana laptop",
    "dell g15 laptop",
]

BAD_WORDS = [
    "desktop", "monitor", "keyboard", "mouse", "charger", "adapter", "case", "bag",
    "stand", "dock", "cooler", "warranty", "skin", "sleeve", "battery", "ram memory",
    "ssd only", "external", "headset", "speaker", "router", "printer", "tablet", "chromebook"
]

GOOD_WORDS = [
    "laptop", "notebook", "gaming", "rtx", "geforce", "legion", "loq", "tuf", "rog",
    "nitro", "katana", "victus", "omen", "g15", "g16", "predator", "alienware"
]

@dataclass
class Site:
    name: str
    domain: str
    search_url: str

SITES = [
    Site("Canada Computers", "canadacomputers.com", "https://www.canadacomputers.com/en/search?s={q}"),
    Site("Best Buy Canada", "bestbuy.ca", "https://www.bestbuy.ca/en-ca/search?search={q}"),
    Site("Memory Express", "memoryexpress.com", "https://www.memoryexpress.com/Search/Products?Search={q}"),
    Site("Newegg Canada", "newegg.ca", "https://www.newegg.ca/p/pl?d={q}"),
    Site("Staples Canada", "staples.ca", "https://www.staples.ca/search?query={q}"),
    Site("Walmart Canada", "walmart.ca", "https://www.walmart.ca/search?q={q}"),
    Site("Costco Canada", "costco.ca", "https://www.costco.ca/CatalogSearch?keyword={q}"),
    Site("Lenovo Canada", "lenovo.com", "https://www.lenovo.com/ca/en/search?text={q}"),
    Site("Dell Canada", "dell.com", "https://www.dell.com/en-ca/shop/scc/sr?~query={q}"),
]


def load_seen() -> set[str]:
    try:
        if SEEN_FILE.exists():
            data = json.loads(SEEN_FILE.read_text(encoding="utf-8"))
            return set(data if isinstance(data, list) else [])
    except Exception:
        pass
    return set()


def save_seen(seen: set[str]) -> None:
    SEEN_FILE.write_text(json.dumps(sorted(seen)[-2000:], indent=2), encoding="utf-8")


def send_telegram(text: str) -> None:
    if not BOT_TOKEN or not CHAT_ID:
        raise RuntimeError("TELEGRAM_BOT_TOKEN ou TELEGRAM_CHAT_ID manquant dans GitHub Secrets")
    for i in range(0, len(text), 3900):
        chunk = text[i:i + 3900]
        r = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": chunk, "disable_web_page_preview": True},
            timeout=20,
        )
        print("Telegram:", r.status_code, r.text[:200])
        r.raise_for_status()


def domain_ok(url: str, domain: str) -> bool:
    try:
        host = urlparse(url).netloc.lower().replace("www.", "")
        return host == domain or host.endswith("." + domain)
    except Exception:
        return False


def normalize_url(url: str) -> str:
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}{p.path}"


def valid_title(title: str) -> bool:
    t = re.sub(r"\s+", " ", title).strip().lower()
    if len(t) < 20 or len(t) > 220:
        return False
    if any(w in t for w in BAD_WORDS):
        return False
    return any(w in t for w in GOOD_WORDS)


def extract_money(text: str) -> list[float]:
    text = text.replace(",", "")
    found = re.findall(r"(?:CAD\s*)?\$\s*([0-9]{3,5}(?:\.[0-9]{2})?)", text, flags=re.I)
    prices = []
    for x in found:
        try:
            p = float(x)
            if MIN_PRICE <= p <= MAX_PRICE:
                prices.append(p)
        except Exception:
            pass
    return prices


def parse_jsonld_price(html: str) -> Optional[float]:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all("script", type="application/ld+json"):
        raw = tag.get_text(" ", strip=True)
        try:
            data = json.loads(raw)
        except Exception:
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            obj = stack.pop(0)
            if isinstance(obj, dict):
                offers = obj.get("offers")
                if isinstance(offers, dict):
                    price = offers.get("price") or offers.get("lowPrice")
                    if price is not None:
                        try:
                            p = float(str(price).replace(",", ""))
                            if MIN_PRICE <= p <= MAX_PRICE:
                                return p
                        except Exception:
                            pass
                elif isinstance(offers, list):
                    stack.extend(offers)
                stack.extend([v for v in obj.values() if isinstance(v, (dict, list))])
            elif isinstance(obj, list):
                stack.extend(obj)
    return None


def parse_meta_price(html: str) -> Optional[float]:
    soup = BeautifulSoup(html, "html.parser")
    selectors = [
        {"property": "product:price:amount"},
        {"property": "og:price:amount"},
        {"itemprop": "price"},
        {"name": "twitter:data1"},
    ]
    for sel in selectors:
        tag = soup.find("meta", attrs=sel)
        if tag and tag.get("content"):
            prices = extract_money("$" + tag.get("content", ""))
            if prices:
                return prices[0]
            try:
                p = float(tag["content"].replace(",", ""))
                if MIN_PRICE <= p <= MAX_PRICE:
                    return p
            except Exception:
                pass
    return None


def impossible_price(title: str, price: float) -> bool:
    t = title.lower().replace(" ", "")
    if "rtx5090" in t or "rtx5080" in t or "rtx5070ti" in t:
        return price < 1400
    if "rtx5070" in t:
        return price < 1100
    if "rtx4080" in t or "rtx4090" in t:
        return price < 1300
    if "rtx4070" in t:
        return price < 750
    if "rtx5060" in t:
        return price < 850
    if "legionpro" in t and ("5070" in t or "5080" in t):
        return True
    return False


def score(title: str, price: float) -> int:
    t = title.lower()
    s = 0
    if "rtx 4070" in t: s += 45
    if "rtx 4060" in t: s += 35
    if "rtx 4050" in t: s += 20
    if "rtx 3050" in t: s += 5
    if "i7" in t or "ryzen 7" in t or "ryzen 9" in t: s += 15
    if "16gb" in t or "16 gb" in t: s += 10
    if "1tb" in t or "1 tb" in t: s += 10
    s += max(0, int(MAX_PRICE - price) // 25)
    return s


async def get_final_same_domain(page, url: str, domain: str) -> Optional[str]:
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=25000)
        await page.wait_for_timeout(1200)
        final_url = page.url
        if not domain_ok(final_url, domain):
            print("Rejected redirected domain:", url, "->", final_url)
            return None
        return final_url
    except PlaywrightTimeoutError:
        print("Timeout product:", url)
        return None
    except Exception as e:
        print("Product open error:", url, e)
        return None


async def confirm_product(context, site: Site, title: str, url: str) -> Optional[dict]:
    if not domain_ok(url, site.domain):
        return None

    page = await context.new_page()
    try:
        final_url = await get_final_same_domain(page, url, site.domain)
        if not final_url:
            return None

        page_title = await page.title()
        html = await page.content()
        visible_text = await page.locator("body").inner_text(timeout=5000)

        combined_title = title
        if page_title and len(page_title) > len(combined_title):
            combined_title = page_title[:180]

        if not valid_title(combined_title):
            return None

        price = parse_jsonld_price(html) or parse_meta_price(html)
        if price is None:
            all_prices = sorted(set(extract_money(visible_text)))
            if not all_prices:
                return None
            if len(all_prices) > 8:
                return None
            price = all_prices[0]

        if impossible_price(combined_title, price):
            print("Rejected impossible price:", price, combined_title[:120], final_url)
            return None

        if price < MIN_PRICE or price > MAX_PRICE:
            return None

        return {
            "title": re.sub(r"\s+", " ", combined_title).strip()[:150],
            "price": float(price),
            "site": site.name,
            "url": normalize_url(final_url),
            "score": score(combined_title, float(price)),
        }
    finally:
        await page.close()


async def collect_candidates(context, site: Site, query: str) -> list[tuple[str, str]]:
    page = await context.new_page()
    candidates = []
    try:
        search_url = site.search_url.format(q=quote_plus(query))
        await page.goto(search_url, wait_until="domcontentloaded", timeout=25000)
        await page.wait_for_timeout(2200)

        links = await page.locator("a[href]").evaluate_all("""
            els => els.map(a => ({href: a.href, text: (a.innerText || a.textContent || '').trim()}))
        """)

        seen = set()
        for item in links:
            href = normalize_url(item.get("href", ""))
            text = re.sub(r"\s+", " ", item.get("text", "")).strip()
            if not href or href in seen:
                continue
            seen.add(href)
            if not domain_ok(href, site.domain):
                continue
            if not valid_title(text):
                continue
            candidates.append((text, href))
            if len(candidates) >= MAX_RESULTS_PER_SITE:
                break
    except Exception as e:
        print(f"[{site.name}] search error for {query}: {e}")
    finally:
        await page.close()
    return candidates


async def scrape_site(context, site: Site) -> tuple[list[dict], int]:
    confirmed = []
    tested = 0
    seen_urls = set()

    for query in QUERIES:
        candidates = await collect_candidates(context, site, query)
        for title, url in candidates:
            if url in seen_urls:
                continue
            seen_urls.add(url)
            tested += 1
            deal = await confirm_product(context, site, title, url)
            if deal:
                confirmed.append(deal)
                if len(confirmed) >= MAX_RESULTS_PER_SITE:
                    return confirmed, tested
    return confirmed, tested


async def run_bot() -> None:
    seen = load_seen()
    all_deals = []
    stats = {}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=HEADLESS, args=["--no-sandbox"])
        context = await browser.new_context(
            locale="en-CA",
            timezone_id="America/Toronto",
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        )

        for site in SITES:
            print("Checking", site.name)
            deals, tested = await scrape_site(context, site)
            stats[site.name] = {"confirmed": len(deals), "tested": tested}
            all_deals.extend(deals)

        await browser.close()

    unique = {}
    for d in all_deals:
        unique[d["url"]] = d

    deals = sorted(unique.values(), key=lambda x: (-x["score"], x["price"]))
    new_deals = []
    for d in deals:
        if d["url"] not in seen:
            new_deals.append(d)
            seen.add(d["url"])

    save_seen(seen)

    if not new_deals:
        msg = f"Aucun nouveau deal fiable trouvé entre {MIN_PRICE:.0f}$ et {MAX_PRICE:.0f}$ CAD.\n\n"
        msg += "Sites vérifiés ce run:\n"
        for name, s in stats.items():
            msg += f"- {name}: {s['confirmed']} confirmés, {s['tested']} liens testés\n"
        send_telegram(msg)
        return

    msg = f"🔥 Deals laptops fiables Canada {MIN_PRICE:.0f}$–{MAX_PRICE:.0f}$ CAD\n\n"
    for i, d in enumerate(new_deals[:MAX_TOTAL_DEALS], 1):
        msg += (
            f"{i}. {d['title']}\n"
            f"💲 {d['price']:.2f} CAD\n"
            f"🏬 {d['site']}\n"
            f"⭐ Score: {d['score']}\n"
            f"🔗 {d['url']}\n\n"
        )

    msg += "Sites vérifiés ce run:\n"
    for name, s in stats.items():
        msg += f"- {name}: {s['confirmed']} confirmés, {s['tested']} liens testés\n"
    msg += "\nPrix filtrés contre les valeurs impossibles. Vérifie toujours taxes, stock Montréal et Open Box."

    send_telegram(msg)


if __name__ == "__main__":
    asyncio.run(run_bot())
