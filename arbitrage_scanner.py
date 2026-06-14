#!/usr/bin/env python3
"""
💰 ARBITRAGE LIFE — Deal Intelligence Scanner v2
Tom Monfret | Primary: PRG/VIE + SkyTeam | Grey zone: ON

Sources: r/flightdeals, r/awardtravel, r/churning, SecretFlying (multiple feeds)
Sends digest to Telegram @EdgeIntelTury_bot

Grey zone tactics tracked:
  - Fuel dumping (YQ/YR surcharge removal via 1x/3x strikes)
  - Hidden city / skiplag
  - Back-to-back ticketing
  - Positioning flights
  - Triple dip (airline miles + CC bonus + shopping portal)
  - Award arbitrage & partner redemption sweet spots
"""

import json
import os
import re
import sys
import urllib.request
import urllib.parse
import html
from datetime import datetime, date
from pathlib import Path
import xml.etree.ElementTree as ET

# ── Config ──────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent.resolve()
# Reads from env (GitHub Actions secrets) or falls back to hardcoded (local Mac run)
BOT_TOKEN   = os.environ.get("BOT_TOKEN", "8681607136:AAH4s4aV1A5D9Yk9f6sXsBZK38FkFIFQDrw")
CHAT_ID     = int(os.environ.get("CHAT_ID", "313240215"))
SEEN_FILE   = SCRIPT_DIR / "seen_deals.json"

# ── Primary Departure Airports — PRG / VIE / BUD ─────────────────────────────
HOME_AIRPORTS = [
    "prague", "prg",
    "vienna", "vie",
    "budapest", "bud",
]

PRG_VIE_KEYWORDS = [
    "prague", "prg", "czech", "vienna", "vie", "austria",
    "budapest", "bud", "hungary",                    # primary trio
    "bratislava", "bts",                             # positioning
    "warsaw", "waw", "krakow", "cracow",             # positioning hubs
    "central europe", "eastern europe",
]

# ── AF / KLM — globálně relevantní (Flying Blue Platinum) ────────────────────
AF_KLM_KEYWORDS = [
    "air france", "airfrance",
    "klm", "k.l.m",
    "flying blue",
]

# ── Delta — POUZE z PRG/VIE/BUD, jinak ignorovat ─────────────────────────────
# Tom nežije v USA — Delta dealy z ATL/JFK/LAX jsou irelevantní
DELTA_KEYWORDS = [
    "delta", "delta airlines", "delta air lines",
]

# ── SkyTeam carriers — Tom's primary alliance ────────────────────────────────
SKYTEAM_KEYWORDS = [
    "air france", "klm", "delta", "korean air",
    "czech airlines", "csa", "ok airlines",
    "vietnam airlines", "aeromexico", "garuda",
    "middle east airlines", "mea", "saudia",
    "xiamen air", "china eastern", "china southern",
    "kenya airways", "tarom", "skyteam",
    "flying blue", "flying blue promo",             # AF/KLM FF program
]

# ── Grey zone & fuel dump signals ────────────────────────────────────────────
FUEL_DUMP_KEYWORDS = [
    "fuel dump", "fuel dumping", "yq", "yr", "fuel surcharge",
    "1x strike", "2x strike", "3x strike", "strike ticket",
    "surcharge removed", "ita matrix", "fuel hack",
    "no surcharge", "zero surcharge", "dump",
]

GREY_ZONE_KEYWORDS = [
    "hidden city", "skiplag", "skiplagged", "point beyond",
    "back to back", "back-to-back", "b2b ticket",
    "positioning flight", "positioning", "deadhead",
    "mileage run", "status run",
    "triple dip", "triple-dip", "double dip", "quadruple dip",
    "stacking", "portal stacking", "shopping portal",
    "manufactured spend",
]

# ── General high-value deal signals ──────────────────────────────────────────
MISTAKE_FARE_KEYWORDS = [
    "mistake fare", "error fare", "glitch fare", "bug fare",
    "mistake", "glitch", "error price", "pricing error",
    "unicorn", "unicorn alert",
]

BUSINESS_CLASS_KEYWORDS = [
    "business class", "first class", "lie flat", "j class",
    "business", "biz", "f class", "premium cabin",
    "la premiere", "suites", "polaris", "a380",
]

AWARD_KEYWORDS = [
    "award", "miles", "points", "sweet spot", "saver award",
    "partner award", "transfer bonus", "transfer partner",
    "flying blue promo", "promo award", "promo rewards", "off-peak",
    "united miles", "ana miles", "turkish miles", "avianca",
    "lifemiles", "aeroplan", "velocity",
    # Triple dip specific
    "triple dip", "double dip", "quadruple dip",
    "shopping portal", "portal stacking", "stacking rewards",
    "rakuten", "amex offer", "membership rewards", "amex mr",
    "transfer bonus", "25% bonus", "30% bonus", "20% bonus",
    "flying blue shopping", "fb promo", "promo rewards april",
    # Mistake fare specifics
    "mistake fare", "error fare", "glitch fare", "unicorn alert",
    "unicorn fare", "thrifty traveler", "secret flying error",
    # Award arbitrage
    "vietnam airlines business", "korean air business",
    "north africa miles", "canary islands miles",
    "transatlantic business", "lie flat",
]

MEDIUM_DEAL_KEYWORDS = [
    "sale", "deal", "cheap", "low fare", "flash sale",
    "round trip", "roundtrip", "nonstop", "direct",
    "transatlantic", "europe", "amsterdam", "london",
    "paris", "rome", "madrid", "barcelona",
    "new york", "jfk", "los angeles", "lax",
    "chase", "amex", "citi", "transfer bonus",
    "hyatt", "globalist", "marriott", "ihg",
]

SKIP_KEYWORDS = [
    "domestic only", "us domestic only", "hawaii only",
    "australia only",
]

# ── Sources ──────────────────────────────────────────────────────────────────
SOURCES = [
    {
        "name": "r/flightdeals",
        "url": "https://www.reddit.com/r/flightdeals/new.json?limit=30&sort=new",
        "type": "reddit_json",
    },
    {
        "name": "r/awardtravel",
        "url": "https://www.reddit.com/r/awardtravel/new.json?limit=20&sort=new",
        "type": "reddit_json",
    },
    {
        "name": "r/churning",
        "url": "https://www.reddit.com/r/churning/new.json?limit=15&sort=new",
        "type": "reddit_json",
    },
    {
        "name": "SecretFlying Europe",
        "url": "https://www.secretflying.com/posts/category/europe/feed/",
        "type": "rss",
    },
    {
        "name": "SecretFlying Error Fares",
        "url": "https://www.secretflying.com/posts/category/error-fare/feed/",
        "type": "rss",
    },
    {
        "name": "SecretFlying Business",
        "url": "https://www.secretflying.com/posts/category/business-class-deals/feed/",
        "type": "rss",
    },
    {
        "name": "SecretFlying USA→EU",
        "url": "https://www.secretflying.com/posts/category/usa-to-europe/feed/",
        "type": "rss",
    },
    # ── Direct airline deal aggregators ──────────────────────────────────────
    {
        "name": "TheFlightDeal",
        "url": "https://www.theflightdeal.com/feed/",
        "type": "rss",
    },
    {
        "name": "Airfarewatchdog",
        "url": "https://www.airfarewatchdog.com/blog/feed/",
        "type": "rss",
    },
    {
        "name": "Thrifty Traveler",
        "url": "https://thriftytraveler.com/feed/",
        "type": "rss",
    },
    {
        "name": "r/solotravel deals",
        "url": "https://www.reddit.com/r/Flights/new.json?limit=15&sort=new",
        "type": "reddit_json",
    },
]

# ── Word-boundary safe matching ───────────────────────────────────────────────
def word_match(text, keywords):
    """Match keywords as whole words to avoid false positives (bud→budget, vie→believe)."""
    for kw in keywords:
        if re.search(r'\b' + re.escape(kw) + r'\b', text):
            return True
    return False

# ── Score a deal ─────────────────────────────────────────────────────────────
def score_deal(title, text=""):
    combined = (title + " " + text).lower()
    score = 0
    tags = []

    # Hard skip
    for kw in SKIP_KEYWORDS:
        if kw in combined:
            return -1, []

    # 🏠 Home airport hit — word boundary matching (prevents bud→budget, vie→believe)
    home_hit = word_match(combined, HOME_AIRPORTS)
    if home_hit:
        score += 5
        tags.append("PRG/VIE/BUD")
    elif word_match(combined, PRG_VIE_KEYWORDS):
        score += 2
        tags.append("CentralEU")

    # ✈️ AF / KLM — vždy relevantní (Flying Blue Platinum)
    afklm_hit = word_match(combined, AF_KLM_KEYWORDS)
    if afklm_hit:
        score += 4
        tags.append("AF/KLM")

    # ✈️ Delta — POUZE pokud je zmíněno PRG/VIE/BUD (jinak ignorovat)
    delta_hit = word_match(combined, DELTA_KEYWORDS)
    delta_relevant = delta_hit and home_hit  # Delta bez domácího letiště = skip

    # Zpětná kompatibilita pro JACKPOT logiku
    big3_hit = afklm_hit or delta_relevant
    if delta_relevant and not afklm_hit:
        score += 4
        tags.append("Delta+PRG")

    # 🚨 JACKPOT: AF/KLM/Delta + home airport = nejvyšší priorita
    if home_hit and big3_hit:
        score += 5
        tags.append("🎯JACKPOT")

    # ✈️ SkyTeam carriers (broader)
    skyteam_hit = any(kw in combined for kw in SKYTEAM_KEYWORDS)
    if skyteam_hit and not big3_hit:
        score += 2
        tags.append("SkyTeam")

    # 🔥 Mistake/error fares — top priority
    if any(kw in combined for kw in MISTAKE_FARE_KEYWORDS):
        score += 4
        tags.append("MistakeFare")

    # 💺 Business/First class
    if any(kw in combined for kw in BUSINESS_CLASS_KEYWORDS):
        score += 3
        tags.append("BizClass")

    # 🏆 Award/miles sweet spots
    if any(kw in combined for kw in AWARD_KEYWORDS):
        score += 2
        tags.append("Award")

    # ⛽ Fuel dumping
    if any(kw in combined for kw in FUEL_DUMP_KEYWORDS):
        score += 4
        tags.append("FuelDump")

    # 🎯 Grey zone tactics
    if any(kw in combined for kw in GREY_ZONE_KEYWORDS):
        score += 3
        tags.append("GreyZone")

    # General deal signals
    if any(kw in combined for kw in MEDIUM_DEAL_KEYWORDS):
        score += 1

    return score, tags

# ── Fetch helpers ─────────────────────────────────────────────────────────────
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    )
}

def fetch_reddit(source):
    deals = []
    req = urllib.request.Request(source["url"], headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
        posts = data.get("data", {}).get("children", [])
        for post in posts:
            p = post.get("data", {})
            deal_id = p.get("id", "")
            title   = p.get("title", "")
            url     = "https://reddit.com" + p.get("permalink", "")
            text    = p.get("selftext", "")[:600]
            deals.append({
                "id":     f"reddit_{deal_id}",
                "title":  title,
                "url":    url,
                "text":   text,
                "source": source["name"],
            })
    except Exception as e:
        print(f"[!] Failed to fetch {source['name']}: {e}")
    return deals

def clean_xml(content_bytes):
    """Fix malformed RSS/XML: invalid chars, unescaped &, bad HTML entities."""
    text = content_bytes.decode("utf-8", errors="replace")
    # Remove invalid XML control characters (keep \t \n \r)
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', text)
    # Fix unescaped & — the #1 cause of SecretFlying XML errors
    # Replace & not already part of a valid XML entity
    text = re.sub(r'&(?!(?:amp|lt|gt|apos|quot|#\d+|#x[0-9a-fA-F]+);)', '&amp;', text)
    # Replace remaining common HTML entities
    text = text.replace('&nbsp;', ' ').replace('&mdash;', '—').replace('&ndash;', '–')
    text = text.replace('&hellip;', '…').replace('&laquo;', '«').replace('&raquo;', '»')
    text = text.replace('&ldquo;', '"').replace('&rdquo;', '"')
    return text.encode("utf-8")

def fetch_rss(source):
    deals = []
    try:
        req = urllib.request.Request(source["url"], headers=HEADERS)
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read()
        # Try clean parse first, fallback to lenient
        try:
            root = ET.fromstring(raw)
        except ET.ParseError:
            root = ET.fromstring(clean_xml(raw))
        items = root.findall(".//item")
        for item in items[:20]:
            title   = item.findtext("title", "").strip()
            url     = item.findtext("link", "").strip()
            summary = re.sub(r'<[^>]+>', '', item.findtext("description", ""))[:400]
            deal_id = url.split("/")[-2] if url else title[:40]
            deals.append({
                "id":     f"rss_{deal_id}",
                "title":  title,
                "url":    url,
                "text":   summary,
                "source": source["name"],
            })
    except Exception as e:
        print(f"[!] Failed to fetch RSS {source['name']}: {e}")
    return deals

def fetch_all():
    all_deals = []
    for source in SOURCES:
        if source["type"] == "reddit_json":
            all_deals.extend(fetch_reddit(source))
        elif source["type"] == "rss":
            all_deals.extend(fetch_rss(source))
    print(f"[✓] Načteno {len(all_deals)} příspěvků ze všech zdrojů")
    return all_deals

# ── Load/save seen deals ──────────────────────────────────────────────────────
def load_seen():
    if SEEN_FILE.exists():
        try:
            with open(SEEN_FILE) as f:
                data = json.load(f)
                if len(data) > 600:
                    data = data[-600:]
                return set(data)
        except Exception:
            return set()
    return set()

def save_seen(seen_set):
    with open(SEEN_FILE, "w") as f:
        json.dump(list(seen_set)[-600:], f)

# ── Save latest deals to JSON for the static HTML to read ────────────────────
# (Phase 1 architecture: scanner → JSON → GitHub Pages → HTML on mobile.
#  No Flask needed for viewing. Accumulates across runs, keeps newest 500.)
LATEST_FILE = SCRIPT_DIR / "latest_deals.json"

def save_latest_json(hot_deals, warm_deals, grey_deals, total_scanned, json_deals=None):
    """Save scored deals so HTML (locally or on GitHub Pages) can read them.

    If json_deals is provided, it's used as the source of items (all current posts).
    Otherwise falls back to hot+warm+grey from this scan only.
    """
    existing = []
    if LATEST_FILE.exists():
        try:
            with open(LATEST_FILE) as f:
                existing = json.load(f)
        except Exception:
            existing = []

    now_iso = datetime.now().isoformat()

    def to_dict(score, d, tags):
        title = d.get("title", "") or ""
        text  = d.get("text", "") or ""
        is_hotel = any(t.upper() in ("HOTEL",) for t in tags) or \
                   any(k in title.lower() for k in ("hotel", "resort", "stay", "/night"))
        # Try to pull a price from the title — best-effort, no fakes.
        price = 0
        currency = ""
        m = re.search(r"(€|\$|EUR|USD|CZK)\s*([0-9][0-9,]{0,7})", title)
        if m:
            currency = m.group(1).replace("EUR", "€").replace("USD", "$")
            try: price = int(m.group(2).replace(",", ""))
            except Exception: price = 0
        return {
            "id":       d.get("id", ""),
            "route":    title[:160],
            "type":     "hotel" if is_hotel else "flight",
            "url":      d.get("url", ""),
            "source":   d.get("source", ""),
            "score":    int(score),
            "tags":     tags,
            "price":    price,
            "currency": currency,
            "savings":  0,        # not parsed from scanner; HTML shows 0%
            "airline":  "",       # unknown from scanner text
            "dates":    "",       # unknown from scanner text
            "grey_zone": ("GreyZone" in tags or "FuelDump" in tags),
            "approved": False,
            "created_at": now_iso,
            "text":     text[:200],
        }

    # Prefer json_deals (all current posts) when provided; falls back to scored buckets.
    source_items = json_deals if json_deals else (hot_deals + warm_deals + grey_deals)
    new_items = [to_dict(s, d, t) for (s, d, t) in source_items]

    # Merge with existing — newest wins on duplicates, keep top 500 newest.
    by_id = {x.get("id"): x for x in existing}
    for x in new_items:
        by_id[x["id"]] = x
    combined = sorted(
        by_id.values(),
        key=lambda x: x.get("created_at", ""),
        reverse=True,
    )[:500]

    with open(LATEST_FILE, "w", encoding="utf-8") as f:
        json.dump(combined, f, indent=2, ensure_ascii=False)

    print(f"[✓] latest_deals.json saved — {len(combined)} deals, {len(new_items)} from this scan, {total_scanned} sources scanned")

# ── Send Telegram ─────────────────────────────────────────────────────────────
def send_telegram(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    if len(text) > 4000:
        text = text[:4000] + "\n\n_...zkráceno_"
    payload = json.dumps({
        "chat_id":    CHAT_ID,
        "text":       text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }).encode("utf-8")
    req = urllib.request.Request(
        url, data=payload,
        headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode())
            if result.get("ok"):
                print("[✓] Telegram message sent")
                return True
            else:
                print(f"[✗] Telegram error: {result}")
                return False
    except Exception as e:
        print(f"[✗] Telegram failed: {e}")
        return False

# ── Format digest ─────────────────────────────────────────────────────────────
def tag_emoji(tags):
    mapping = {
        "🎯JACKPOT":    "🚨🎯",
        "PRG/VIE/BUD":  "🇨🇿",
        "CentralEU":    "🌍",
        "AF/KLM":       "✈️",
        "Delta+PRG":    "🔺✈️",
        "SkyTeam":      "🔵",
        "MistakeFare":  "💥",
        "BizClass":     "💺",
        "Award":        "🏆",
        "FuelDump":     "⛽",
        "GreyZone":     "🎰",
    }
    return " ".join(mapping.get(t, "") for t in tags if t in mapping)

def format_daily_digest(hot_deals, warm_deals, grey_deals, today_str, total_scanned):
    lines = [f"💰 *ARBITRAGE LIFE — {today_str}*\n"]

    if not hot_deals and not warm_deals and not grey_deals:
        lines.append("😴 Dnes žádné relevantní dealy. Systém hlídá dál.")
        lines.append(f"_Zkontrolováno {total_scanned} příspěvků_")
        return "\n".join(lines)

    # 🚨 JACKPOT alert — AF/KLM/Delta + PRG/VIE/BUD
    jackpot = [(s, d, t) for s, d, t in hot_deals if "🎯JACKPOT" in t]
    if jackpot:
        lines.append("🚨🚨 *JACKPOT — AF/KLM/DELTA z PRG/VIE/BUD* 🚨🚨")
        for score, d, tags in jackpot[:3]:
            title = d["title"][:90].replace("*","").replace("[","").replace("]","")
            lines.append(f"➤ [{title}]({d['url']})")
            lines.append(f"  _{d['source']} | score: {score}_\n")
        lines.append("---")

    if hot_deals:
        lines.append(f"🔥 *FIRE DEALS ({len(hot_deals)})*")
        for score, d, tags in hot_deals[:6]:
            title  = d["title"][:85].replace("*","").replace("[","").replace("]","")
            emojis = tag_emoji(tags)
            lines.append(f"• {emojis} [{title}]({d['url']})")
            lines.append(f"  _{d['source']}_\n")

    if grey_deals:
        lines.append(f"\n⛽ *GREY ZONE — Fuel dump / Hidden city ({len(grey_deals)})*")
        for score, d, tags in grey_deals[:4]:
            title  = d["title"][:80].replace("*","").replace("[","").replace("]","")
            emojis = tag_emoji(tags)
            lines.append(f"• {emojis} [{title}]({d['url']})")
            lines.append(f"  _{d['source']}_\n")

    if warm_deals:
        lines.append(f"\n🟡 *ZAJÍMAVÉ ({len(warm_deals)})*")
        for score, d, tags in warm_deals[:5]:
            title  = d["title"][:70].replace("*","").replace("[","").replace("]","")
            emojis = tag_emoji(tags)
            lines.append(f"• {emojis} [{title}]({d['url']}) — _{d['source']}_")

    lines.append(
        f"\n_Skenováno: {datetime.now().strftime('%H:%M')} | "
        f"{total_scanned} příspěvků | PRG/VIE focus_"
    )
    return "\n".join(lines)

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    today_str = date.today().strftime("%d. %m. %Y")
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] Arbitrage scanner v2 spuštěn...")

    seen     = load_seen()
    all_deals = fetch_all()

    new_deals = [d for d in all_deals if d["id"] not in seen]
    print(f"[✓] Nových: {len(new_deals)}")

    # Score all deals
    hot_deals  = []  # score >= 8  (business class from PRG = 8, mistake fare PRG = 9)
    grey_deals = []  # FuelDump or GreyZone tag, score >= 4
    warm_deals = []  # score 2-7
    json_deals = []  # everything from this scan — for HTML feed (not deduped by 'seen')

    # Telegram digest uses only NEW deals (so it doesn't repeat past alerts).
    for d in new_deals:
        score, tags = score_deal(d["title"], d.get("text", ""))
        if score < 1:
            continue

        is_grey = "FuelDump" in tags or "GreyZone" in tags

        if score >= 8:
            hot_deals.append((score, d, tags))
        elif is_grey and score >= 4:
            grey_deals.append((score, d, tags))
        elif score >= 2:
            warm_deals.append((score, d, tags))

    # JSON for HTML uses ALL current posts (seen or not) so the public feed
    # stays populated even when no new posts arrive in this scan. Score is
    # included so HTML can sort/filter; 0-score items are kept too.
    for d in all_deals:
        score, tags = score_deal(d["title"], d.get("text", ""))
        json_deals.append((max(0, score), d, tags))

    # Sort by score descending
    hot_deals.sort(key=lambda x: x[0], reverse=True)
    grey_deals.sort(key=lambda x: x[0], reverse=True)
    warm_deals.sort(key=lambda x: x[0], reverse=True)

    print(f"[✓] Hot: {len(hot_deals)}, Grey zone: {len(grey_deals)}, Warm: {len(warm_deals)}")

    has_deals = hot_deals or grey_deals or warm_deals

    if has_deals or "--force" in sys.argv:
        msg = format_daily_digest(hot_deals, warm_deals, grey_deals, today_str, len(all_deals))
        send_telegram(msg)
    else:
        # Send brief "nothing today" every 3rd day
        day_of_year = date.today().timetuple().tm_yday
        if day_of_year % 3 == 0 or "--test" in sys.argv:
            send_telegram(
                f"💰 *ARBITRAGE LIFE — {today_str}*\n\n"
                "😴 Dnes žádné relevantní dealy. Systém hlídá dál.\n"
                f"_Zkontrolováno {len(all_deals)} příspěvků_"
            )

    # Update seen IDs
    seen.update(d["id"] for d in new_deals)
    save_seen(seen)

    # Phase 1: write the public JSON snapshot the static HTML reads on mobile.
    save_latest_json(hot_deals, warm_deals, grey_deals, len(all_deals), json_deals=json_deals)

    print(f"[{datetime.now().strftime('%H:%M:%S')}] Hotovo.")

if __name__ == "__main__":
    main()
