import os, json, re, random, time, traceback
import requests
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote_plus, urljoin, urlparse

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
MAX_PRICE = float(os.getenv("MAX_PRICE", "1000"))
MIN_PRICE = float(os.getenv("MIN_PRICE", "600"))
SEEN_FILE = "seen_deals.json"
TIMEOUT = 12
MAX_SITE_WORKERS = 6       # requêtes de recherche en parallèle (par site x query)
MAX_PRICE_WORKERS = 4      # réduit les blocages et accélère GitHub Actions
MAX_CANDIDATES_PER_SEARCH = 6  # évite de vérifier 100 liens inutiles par recherche

# ---------------------------------------------------------------------------
# PERSISTANCE seen_deals.json (GitHub Actions) :
# Le workflow fourni (.github/workflows/deals.yml) commit automatiquement
# seen_deals.json dans le repo après chaque run. Ne supprime pas cette étape.
# ---------------------------------------------------------------------------

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
]

def make_session():
    s = requests.Session()
    s.headers.update({
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-CA,en;q=0.9,fr-CA;q=0.8",
        "Connection": "keep-alive",
    })
    return s

SEARCHES = {
    "Canada Computers": "https://www.canadacomputers.com/en/search?s={q}",
    "Best Buy Canada": "https://www.bestbuy.ca/en-ca/search?search={q}",
    "Memory Express": "https://www.memoryexpress.com/Search/Products?Search={q}",
    "Newegg Canada": "https://www.newegg.ca/p/pl?d={q}",
    "Staples Canada": "https://www.staples.ca/search?query={q}",
    "Walmart Canada": "https://www.walmart.ca/search?q={q}",
    "Costco Canada": "https://www.costco.ca/CatalogSearch?keyword={q}",
    "Lenovo Canada": "https://www.lenovo.com/ca/en/search?text={q}",
    "Dell Canada": "https://www.dell.com/en-ca/shop/scc/sr?~query={q}",
}

# Sites au rendu fortement JS / WAF agressif : avec de simples requêtes HTTP
# (pas de navigateur headless), le taux de succès sera souvent bas ou nul
# pour ceux-ci. Le log te le dira clairement plutôt que de laisser un doute.
JS_HEAVY_SITES = {"Best Buy Canada", "Walmart Canada", "Costco Canada", "Dell Canada", "Newegg Canada"}

# Domaines de pub / tracking / comparateurs à rejeter systématiquement,
# même s'ils apparaissent dans le HTML d'un site marchand.
BLOCKED_DOMAIN_FRAGMENTS = [
    "doubleclick", "googleadservices", "googlesyndication", "criteo",
    "taboola", "outbrain", "adsystem", "adnxs", "sharethis", "pinterest",
    "facebook.com", "twitter.com", "instagram.com", "youtube.com",
    "bing.com/aclk", "awin1.com", "clickserve", "pricegrabber",
    "shopbot", "shopping.google", "pricespy", "skimlinks", "rakuten",
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

BAD = ["desktop", "monitor", "keyboard", "mouse", "charger", "adapter", "case", "bag", "stand", "dock"]
GOOD = ["laptop", "notebook", "rtx", "gaming", "legion", "loq", "tuf", "rog", "nitro", "katana", "victus", "omen", "g15"]


def load_seen():
    try:
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def save_seen(seen):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(seen[-1000:], f)


def send_telegram(text, retries=2):
    chunks = []
    limit = 3900
    while text:
        chunks.append(text[:limit])
        text = text[limit:]

    for chunk in chunks:
        ok = False
        for attempt in range(retries + 1):
            try:
                r = requests.post(
                    f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                    data={"chat_id": CHAT_ID, "text": chunk, "disable_web_page_preview": True},
                    timeout=TIMEOUT,
                )
                if r.status_code == 200:
                    ok = True
                    break
                else:
                    print(f"[Telegram] status={r.status_code} body={r.text[:300]}")
            except Exception as e:
                print(f"[Telegram] tentative {attempt+1} échouée: {e}")
            time.sleep(1.5)
        if not ok:
            print("[Telegram] échec définitif d'envoi d'un chunk de message.")


def valid_title(title):
    t = title.lower()
    return any(x in t for x in GOOD) and not any(x in t for x in BAD)


def money_prices(text):
    text = text.replace(",", "")
    vals = re.findall(r"\$\s*([0-9]{3,5}(?:\.[0-9]{2})?)", text)
    out = []
    for v in vals:
        try:
            p = float(v)
            if MIN_PRICE <= p <= MAX_PRICE:
                out.append(p)
        except Exception:
            pass
    return out




def plausible_price_for_title(title, price, site):
    """Filtre anti-faux prix.
    Beaucoup de pages affichent des montants qui ne sont PAS le prix final:
    mensualités, économies, accessoires, ancien prix partiel, prix vendeur externe.
    Ici on rejette les combinaisons impossibles sous 1000 CAD.
    """
    t = title.lower()

    # Ces GPU / machines sont presque impossibles sous 1000 CAD au Canada.
    impossible_under_1000 = [
        "rtx 5090", "rtx 5080", "rtx 5070 ti", "rtx 5070",
        "legion pro 7", "legion pro 7i", "legion pro 5", "legion pro 5i",
        "core ultra 9", "i9-", " i9 ", "ryzen 9 275hx", "ryzen 9 7945hx",
    ]
    if price < 1000 and any(x in t for x in impossible_under_1000):
        print(f"[{site}] REJETÉ prix impossible: {price} CAD | {title[:90]}")
        return False

    # RTX 5060 à très bas prix est souvent un faux montant extrait.
    if "rtx 5060" in t and price < 900:
        print(f"[{site}] REJETÉ RTX 5060 trop bas: {price} CAD | {title[:90]}")
        return False

    # RTX 4070 sous 750 CAD est très suspect sauf si clairement open box/refurbished.
    if "rtx 4070" in t and price < 750 and "open box" not in t and "refurb" not in t:
        print(f"[{site}] REJETÉ RTX 4070 trop bas: {price} CAD | {title[:90]}")
        return False

    return True

def get_jsonld_price(soup):
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            raw = tag.get_text(strip=True)
            data = json.loads(raw)
            items = data if isinstance(data, list) else [data]
            for item in items:
                if not isinstance(item, dict):
                    continue
                offer = item.get("offers")
                if isinstance(offer, list):
                    offer = offer[0]
                if isinstance(offer, dict):
                    price = offer.get("price") or offer.get("lowPrice")
                    if price:
                        p = float(str(price).replace(",", ""))
                        if MIN_PRICE <= p <= MAX_PRICE:
                            return p
        except Exception:
            continue
    return None


def get_meta_price(soup):
    keys = [
        {"property": "product:price:amount"},
        {"property": "og:price:amount"},
        {"itemprop": "price"},
    ]
    for k in keys:
        tag = soup.find("meta", attrs=k)
        if tag and tag.get("content"):
            try:
                p = float(tag["content"].replace(",", ""))
                if MIN_PRICE <= p <= MAX_PRICE:
                    return p
            except Exception:
                pass
    return None


# ---------------------------------------------------------------------------
# VERROUILLAGE DE DOMAINE
# C'est le coeur du correctif "je clique et je tombe sur un autre site".
# ---------------------------------------------------------------------------

def base_domain(netloc):
    """Réduit www.bestbuy.ca -> bestbuy.ca pour comparer les domaines
    sans se faire piéger par des sous-domaines différents."""
    netloc = netloc.lower().split(":")[0]
    parts = netloc.split(".")
    if len(parts) >= 2:
        return ".".join(parts[-2:])
    return netloc


def is_blocked_domain(url):
    u = url.lower()
    return any(frag in u for frag in BLOCKED_DOMAIN_FRAGMENTS)


def same_site(url, allowed_domain):
    try:
        netloc = urlparse(url).netloc
        return base_domain(netloc) == allowed_domain
    except Exception:
        return False


def clean_url(base, href, allowed_domain):
    """Ne retourne une URL que si elle appartient bien au domaine du site
    scrapé. Rejette les liens publicitaires, trackers, et tout domaine
    externe — c'est ce qui causait les liens menant vers 'un autre site'."""
    if not href:
        return None
    if href.startswith("javascript:") or href.startswith("#") or href.startswith("mailto:"):
        return None

    u = urljoin(base, href).split("?")[0].split("#")[0]
    if not u.startswith("http"):
        return None

    if is_blocked_domain(u):
        return None

    if not same_site(u, allowed_domain):
        return None

    return u


def confirmed_price(session, product_url, site, allowed_domain):
    """Récupère le prix sur la page produit, en vérifiant explicitement
    que l'URL finale (après redirections) reste sur le même domaine.
    Si le site redirige ailleurs (ex: page produit expirée -> comparateur,
    ou lien affilié), le deal est rejeté au lieu d'être affiché avec un
    lien trompeur."""
    try:
        r = session.get(product_url, timeout=TIMEOUT, allow_redirects=True)

        if r.status_code != 200:
            print(f"[{site}] status={r.status_code} sur {product_url}")
            return None, None

        final_url = r.url
        if not same_site(final_url, allowed_domain):
            print(f"[{site}] REJETÉ - redirection hors domaine: {product_url} -> {final_url}")
            return None, None

        soup = BeautifulSoup(r.text, "html.parser")

        p = get_jsonld_price(soup)
        if p:
            return p, final_url

        p = get_meta_price(soup)
        if p:
            return p, final_url

        text = soup.get_text(" ", strip=True)
        prices = money_prices(text)

        if not prices:
            return None, None

        unique = sorted(set(prices))
        if len(unique) > 6:
            return None, None

        return min(unique), final_url
    except Exception as e:
        print(f"[{site}] erreur confirmed_price sur {product_url}: {e}")
        return None, None


def scrape_search(site, template, query):
    deals = []
    session = make_session()
    try:
        search_url = template.format(q=quote_plus(query))
        allowed_domain = base_domain(urlparse(search_url).netloc)

        r = session.get(search_url, timeout=TIMEOUT, allow_redirects=True)

        if r.status_code != 200:
            print(f"[{site}] recherche '{query}' -> status={r.status_code}")
            return deals

        soup = BeautifulSoup(r.text, "html.parser")

        candidates = []
        seen_urls = set()
        for a in soup.find_all("a", href=True):
            title = a.get_text(" ", strip=True)
            if not title or len(title) < 20:
                continue
            if not valid_title(title):
                continue

            url = clean_url(search_url, a["href"], allowed_domain)
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            candidates.append((title, url))

        if not candidates and site in JS_HEAVY_SITES:
            print(f"[{site}] 0 candidat pour '{query}' (rendu JS probable, requests seul insuffisant)")

        # Limite importante : on vérifie seulement les premiers candidats propres.
        # Ça évite les runs longs et les faux liens de footer/menu.
        candidates = candidates[:MAX_CANDIDATES_PER_SEARCH]

        with ThreadPoolExecutor(max_workers=MAX_PRICE_WORKERS) as pool:
            futures = {
                pool.submit(confirmed_price, session, url, site, allowed_domain): (title, url)
                for title, url in candidates
            }
            for fut in as_completed(futures):
                title, url = futures[fut]
                try:
                    price, final_url = fut.result()
                except Exception as e:
                    print(f"[{site}] erreur future prix pour {url}: {e}")
                    price, final_url = None, None
                if price is None:
                    continue

                if not plausible_price_for_title(title, price, site):
                    continue

                deals.append({
                    "title": title[:150],
                    "price": price,
                    "site": site,
                    "url": final_url or url,
                })

    except Exception as e:
        print(f"[{site}] erreur recherche '{query}': {e}")
        print(traceback.format_exc(limit=2))

    return deals


def score(d):
    t = d["title"].lower()
    s = 0
    if "rtx 4070" in t: s += 45
    if "rtx 4060" in t: s += 35
    if "rtx 4050" in t: s += 20
    if "i7" in t or "ryzen 7" in t or "ryzen 9" in t: s += 15
    if "16gb" in t: s += 10
    if "1tb" in t: s += 10
    s += max(0, int(MAX_PRICE - d["price"]) // 25)
    return s


def main():
    if not BOT_TOKEN or not CHAT_ID:
        raise Exception("Secrets Telegram manquants")

    seen = load_seen()
    all_deals = []
    stats = {}
    errors = {}

    with ThreadPoolExecutor(max_workers=MAX_SITE_WORKERS) as ex:
        futures = {}
        for site, template in SEARCHES.items():
            stats[site] = 0
            errors[site] = 0
            for q in QUERIES:
                fut = ex.submit(scrape_search, site, template, q)
                futures[fut] = site

        for fut in as_completed(futures):
            site = futures[fut]
            try:
                deals = fut.result()
                stats[site] += len(deals)
                all_deals.extend(deals)
            except Exception as e:
                errors[site] += 1
                print(f"[{site}] tâche échouée: {e}")

    unique = []
    used = set()

    for d in all_deals:
        if d["url"] in used:
            continue
        used.add(d["url"])
        d["score"] = score(d)
        unique.append(d)

    unique.sort(key=lambda x: (-x["score"], x["price"]))

    new = []
    for d in unique:
        if d["url"] not in seen:
            new.append(d)
            seen.append(d["url"])

    if not new:
        msg = f"Aucun nouveau deal confirmé entre {MIN_PRICE:.0f}$ et {MAX_PRICE:.0f}$ CAD.\n\n"
        msg += "Sites vérifiés (prix confirmés / erreurs):\n"
        for site in SEARCHES:
            msg += f"- {site}: {stats[site]} confirmés, {errors[site]} erreurs\n"
        send_telegram(msg)
        save_seen(seen)
        return

    msg = f"🔥 Deals laptops confirmés Canada {MIN_PRICE:.0f}$–{MAX_PRICE:.0f}$ CAD\n\n"

    for i, d in enumerate(new[:8], 1):
        msg += (
            f"{i}. {d['title']}\n"
            f"💲 {d['price']:.2f} CAD confirmé\n"
            f"🏬 {d['site']}\n"
            f"⭐ Score: {d['score']}\n"
            f"🔗 {d['url']}\n\n"
        )

    msg += "Sites vérifiés ce run:\n"
    for site in SEARCHES:
        msg += f"- {site}: {stats[site]} confirmés, {errors[site]} erreurs\n"

    msg += "\nPrix vérifié sur la page produit (lien validé, même domaine que le site). Vérifie quand même taxes, stock Montréal et Open Box."

    send_telegram(msg)
    save_seen(seen)


if __name__ == "__main__":
    main()
