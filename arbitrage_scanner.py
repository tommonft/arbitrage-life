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
import time
import urllib.request
import urllib.parse
import urllib.error
import html
from datetime import datetime, date, timedelta
from pathlib import Path
import xml.etree.ElementTree as ET

# ── Config ──────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent.resolve()
# Reads ONLY from env (GitHub Actions secrets). Fallback hardcoded values REMOVED
# 2026-06-28 after GitGuardian leak detection (repo went public).
BOT_TOKEN   = os.environ.get("BOT_TOKEN", "").strip()
CHAT_ID     = int(os.environ.get("CHAT_ID", "0").strip() or "0")
if not BOT_TOKEN or not CHAT_ID:
    print("[!] BOT_TOKEN or CHAT_ID missing in env — Telegram alerts will be skipped")
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
# ── PRG FLIGHTS DEAL — Tom's 16 preferred carriers ──────────────────────────
# When ANY of these airlines + Prague keyword appear in a post → instant alert.
# 2026-07-08 fix (Fable 5 audit): word-boundary matching. The old substring list
# contained "ba ", "sas ", "af ", "lh ", "ek " which matched inside normal words
# ("Cuba " → BA, "Kansas " → SAS, "decaf " → AF) and could fire false 🚨 alerts.
PRG_FLIGHTS_DEAL_AIRLINES = [
    "air france", "airfrance",
    "klm", "k.l.m",
    "delta",                   # already in DELTA_KEYWORDS but kept for explicit detection
    "scandinavian airlines", "sas",   # word-boundary safe now
    "korean air", "korean",
    "turkish airlines", "turkish",
    "lufthansa",
    "qantas",
    "emirates",
    "etihad",
    "finnair",
    "british airways", "british airw",
    "china eastern",
    "china southern",
    "china airlines",
    "xiamen",
]

PRG_KEYWORDS_DETECTOR = [
    "prague", "prg", "praha", "czech republic"
]

def is_prg_flights_deal(title, text=""):
    """Return True if any of the 16 carriers + Prague keyword both present.
    Word-boundary matching to avoid substring false positives (2026-07-08)."""
    combined = (title + " " + text).lower()
    has_airline = word_match(combined, PRG_FLIGHTS_DEAL_AIRLINES)
    has_prg     = word_match(combined, PRG_KEYWORDS_DETECTOR)
    return has_airline and has_prg

# 🇨🇿 PRG ANYTHING — Tom wants INSTANT alert for ANY Prague-related deal
# (flights from/to/via PRG, hotels in Prague, packages, restaurants, transit)
PRG_ANY_KEYWORDS = [
    "prague", "praha", "prg", "czech republic", "czechia",
    "vaclav havel", "ruzyne",            # airport names
]

# EU LowCost airlines — Tom WANTS THESE EXCLUDED from PRG_ANY (rutina, clog)
EU_LCC_NAMES = [
    "wizz", "ryanair", "easyjet", "vueling", "eurowings", "transavia",
    "norwegian", "jet2", "jet 2", "pegasus", "sunexpress", "sun express",
    "volotea", "smartwings", "lauda", "wizzair",
]

# IATA codes of EU low-cost carriers — used for structured (Travelpayouts) deals
# where we get an airline code instead of a name (2026-07-08, Fable 5 audit).
EU_LCC_CODES = {
    "W6", "W4", "W9",   # Wizz Air (+ Malta, + UK)
    "FR", "RK",         # Ryanair (+ UK)
    "U2", "EC", "DS",   # easyJet (+ Europe, + Switzerland)
    "VY",               # Vueling
    "EW",               # Eurowings
    "LS",               # Jet2
    "HV", "TO",         # Transavia (+ France)
    "DY", "D8",         # Norwegian
    "PC",               # Pegasus
    "XQ",               # SunExpress
    "V7",               # Volotea
    "I2",               # Iberia Express
    "QS",               # Smartwings
}

def is_eu_lcc(title, text=""):
    """True if title mentions any EU low-cost carrier."""
    combined = (title + " " + text).lower()
    return any(kw in combined for kw in EU_LCC_NAMES)

def is_lcc_deal(deal):
    """LCC detection for a deal dict: airline IATA code (structured sources like
    Travelpayouts v3) OR carrier name in title/text (RSS sources)."""
    code = (deal.get("airline") or "").strip().upper()
    if code in EU_LCC_CODES:
        return True
    return is_eu_lcc(deal.get("title", ""), deal.get("text", ""))

def is_prg_anything(title, text=""):
    """True if ANY Prague reference appears in title/text — EXCLUDING EU LCC dealy.
    Tom's frustration 2026-06-28: 590 alerts/day mostly Ryanair/Wizz PRG→EU rutina.
    Now: Wizz/Ryanair/EasyJet/Vueling/Eurowings/etc. → skipped from PRG ANY."""
    combined = (title + " " + text).lower()
    has_prg = any(kw in combined for kw in PRG_ANY_KEYWORDS)
    if not has_prg:
        return False
    # Skip if it's a EU LCC deal (Tom doesn't want Ryanair/Wizz spam)
    if is_eu_lcc(title, text):
        return False
    return True

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
    # Reddit: .json endpoint is 403-blocked for CI IPs; .rss (Atom) works.
    # Switched 2026-07-08 (Fable 5 audit) — same pattern as arbitrage_weekly_digest.py.
    {
        "name": "r/flightdeals",
        "url": "https://www.reddit.com/r/flightdeals/new/.rss?limit=30",
        "type": "reddit_rss",
    },
    {
        "name": "r/awardtravel",
        "url": "https://www.reddit.com/r/awardtravel/new/.rss?limit=20",
        "type": "reddit_rss",
    },
    {
        "name": "r/churning",
        "url": "https://www.reddit.com/r/churning/new/.rss?limit=15",
        "type": "reddit_rss",
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
        "name": "r/Flights",
        "url": "https://www.reddit.com/r/Flights/new/.rss?limit=15",
        "type": "reddit_rss",
    },
    # ── HIGH-VOLUME RELIABLE RSS BLOGS (added 2026-06-14) ───────────────────
    # These were tested and produce 80%+ of the deal volume in the old DB.
    {
        "name": "Fly4Free",
        "url": "https://www.fly4free.com/feed/",
        "type": "rss",
    },
    {
        "name": "Fly4Free Europe",
        "url": "https://www.fly4free.com/category/flight-deals/europe/feed/",
        "type": "rss",
    },
    {
        "name": "Fly4Free Error Fares",
        "url": "https://www.fly4free.com/category/flight-deals/error-fares/feed/",
        "type": "rss",
    },
    {
        "name": "DoctorOfCredit",
        "url": "https://www.doctorofcredit.com/feed/",
        "type": "rss",
    },
    {
        "name": "FrequentMiler",
        "url": "https://frequentmiler.com/feed/",
        "type": "rss",
    },
    {
        "name": "DansDeals",
        "url": "https://www.dansdeals.com/feed/",
        "type": "rss",
    },
    {
        "name": "UpgradedPoints",
        "url": "https://upgradedpoints.com/feed/",
        "type": "rss",
    },
    {
        "name": "OneMileAtATime",
        "url": "https://onemileatatime.com/feed/",
        "type": "rss",
    },
    {
        "name": "ThePointsGuy",
        "url": "https://thepointsguy.com/feed/",
        "type": "rss",
    },
    # ── EXTRA aggregators worth trying ──────────────────────────────────────
    {
        "name": "HolidayPirates",
        "url": "https://www.holidaypirates.com/rss/all",
        "type": "rss",
    },
    {
        "name": "ViewFromTheWing",
        "url": "https://viewfromthewing.com/feed/",
        "type": "rss",
    },
    {
        "name": "MilesToMemories",
        "url": "https://www.milestomemories.com/feed/",
        "type": "rss",
    },
    {
        "name": "LiveAndLetsFly",
        "url": "https://liveandletsfly.com/feed/",
        "type": "rss",
    },
    {
        "name": "MonkeyMiles",
        "url": "https://monkeymiles.boardingarea.com/feed/",
        "type": "rss",
    },
    {
        "name": "MightyTravels",
        "url": "https://www.mightytravels.com/feed/",
        "type": "rss",
    },
    {
        "name": "FlyerTalk Mileage Run",
        "url": "https://www.flyertalk.com/forum/mileage-run-deals-326/external.php?type=RSS2",
        "type": "rss",
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

    # 🚨 PRG FLIGHTS DEAL — Tom's top priority: 16 carriers + Prague combo
    if is_prg_flights_deal(title=title, text=text):
        score += 6        # massive boost so it lands at top of digest
        tags.append("PRG_FLIGHTS_DEAL")
        # Also add identified carrier as a tag for filtering (word-boundary safe)
        for a in PRG_FLIGHTS_DEAL_AIRLINES:
            if a.strip() and word_match(combined, [a]):
                # canonical airline label
                label = a.strip().upper().replace(".", "")
                tags.append(f"AIRLINE_{label}")
                break

    # 🇺🇸 USA-ORIGIN detection (Tom is in EU; USA→world deals clog the digest)
    if is_usa_origin(title, text):
        tags.append("USA_ORIGIN")

    # 🇨🇿 PRG_ANY — any Prague reference (from/to/in/via). Tom wants instant alert.
    if is_prg_anything(title, text):
        tags.append("PRG_ANY")

    return score, tags

# ── USA origin detection ─────────────────────────────────────────────────────
# Tom lives in Prague. The deal-blog ecosystem is US-centric, so most posts
# describe USA→world fares (LAX-TYO, JFK-LON…). We still keep them in the JSON
# (Tom can see in the USA tab), but skip them from the Telegram digest unless
# they also touch a home airport (PRG/VIE/BUD).
USA_AIRPORT_CODES = {
    "ATL","LAX","JFK","ORD","DFW","DEN","SFO","SEA","LAS","MCO","MIA","PHX",
    "IAH","EWR","BOS","MSP","DTW","FLL","PHL","LGA","BWI","SLC","IAD","DCA",
    "MDW","SAN","TPA","BNA","AUS","MCI","RDU","SJC","OAK","MSY","SMF","STL",
    "RSW","PDX","CLT","CVG","IND","PIT","MEM","JAX","OKC","BUF","PWM","OMA",
    "RIC","ABQ","BUR","ONT","LGB","SNA","HNL","OGG","KOA","LIH","ITO","ANC",
    "FAI","JNU","BOI","COS","DAL","ELP","GEG","GRR","HPN","ICT","LIT","MHT",
    "MKE","ORF","PBI","PSP","RNO","SAT","SAV","SDF","SYR","TUL","XNA",
}
USA_CITY_KEYWORDS = [
    "los angeles","san francisco","new york","newark","boston","miami","atlanta",
    "chicago","seattle","denver","dallas","houston","phoenix","portland","oregon",
    "philadelphia","washington dc","washington d.c.","orlando","tampa","honolulu",
    "san diego","las vegas","minneapolis","detroit","st. louis","st louis","nashville",
    "austin","kansas city","raleigh","oakland","sacramento","fort lauderdale",
    "salt lake city","baltimore","charlotte","cincinnati","pittsburgh","memphis",
    "indianapolis","jacksonville","milwaukee","cleveland","columbus","san jose",
    "u.s. cities","us cities","united states","usa to ","u.s. to ","u.s.→",
]
USA_CARRIER_KEYWORDS = [
    "american airlines","delta:","united:","jetblue","alaska airlines",
    "southwest","spirit airlines","frontier airlines","hawaiian airlines",
    "sun country",
]

def is_usa_origin(title, text=""):
    """Detect deals that originate in the USA.
    Heuristics:
    - title contains a USA city name in the 'origin' part (before separator)
    - airport code matching USA list appears in title
    - US-only carriers in title (without EU home airport mention)

    IMPORTANT: also returns True for deals that mention both USA origin AND
    European destination (USA→EU/Asia/etc) — they're not useful for a EU-based user.
    Returns False if the deal mentions PRG/VIE/BUD/Prague/Wien anywhere AND the
    USA reference is only a destination (e.g. PRG→LAX).
    """
    t = (title or "").lower()
    combined = (t + " " + (text or "").lower())

    # If title mentions home airport as ORIGIN (PRG to LAX), it's not USA-origin
    # We detect by checking if "prague" / "prg" appears BEFORE any USA reference.
    home_words = ["prg ", "prague", "praha", "vie ", "vienna", "wien", "bud ", "budapest"]
    home_pos = min((t.find(h) for h in home_words if h in t), default=-1)

    # Split on common origin/dest separators; take origin half.
    # Includes hyphen, en-dash (–), em-dash (—), arrows, " to ", " - "
    parts = re.split(r" to |\s*[-–—→>]\s*", t, maxsplit=1)
    origin_part = parts[0] if parts else t

    # If home airport is in origin half, NOT USA-origin
    if any(h.strip() in origin_part for h in home_words):
        return False

    # 1) USA city keyword in origin half
    for kw in USA_CITY_KEYWORDS:
        if kw in origin_part:
            return True

    # 2) Airport-code based detection — first 3-letter code in title
    codes = re.findall(r"\b([A-Z]{3})\b", title or "")
    if codes and codes[0] in USA_AIRPORT_CODES:
        return True

    # 3) US-only carriers in title — only if home airport not mentioned at all
    for kw in USA_CARRIER_KEYWORDS:
        if kw in t:
            if home_pos < 0:
                return True
    return False

# ── Fetch helpers ─────────────────────────────────────────────────────────────
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    )
}

ATOM_NS = "{http://www.w3.org/2005/Atom}"

def fetch_reddit(source):
    """Fetch a subreddit via the Atom .rss endpoint (the .json endpoint returns
    HTTP 403 for GitHub Actions runner IPs — observed continuously since 06/2026).
    One retry with a polite pause; same approach as arbitrage_weekly_digest.py."""
    deals = []
    for attempt in range(2):
        try:
            req = urllib.request.Request(source["url"], headers=HEADERS)
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read()
            root = ET.fromstring(raw)
            for e in root.findall(f"{ATOM_NS}entry"):
                title   = html.unescape((e.findtext(f"{ATOM_NS}title") or "").strip())
                link_el = e.find(f"{ATOM_NS}link")
                url     = link_el.get("href") if link_el is not None else ""
                entry_id = (e.findtext(f"{ATOM_NS}id") or "").strip()  # e.g. t3_1abcde
                content = re.sub(r'<[^>]+>', ' ', e.findtext(f"{ATOM_NS}content") or "")
                text    = html.unescape(content)[:600]
                rid     = entry_id.replace("t3_", "") or (url.rstrip("/").split("/")[-2] if url else title[:40])
                deals.append({
                    "id":     f"reddit_{rid}",
                    "title":  title,
                    "url":    url,
                    "text":   text,
                    "source": source["name"],
                })
            break
        except Exception as e:
            print(f"[!] Failed to fetch {source['name']} (attempt {attempt+1}): {e}")
            if attempt == 0:
                time.sleep(5)
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

def _tp_make_deal(origin_c, dest_c, value, depart, ret, airline, link=""):
    """Build one deal dict from Travelpayouts fields (shared by v3/v2 parsers).
    NO FAKE DATA: airline stays '' when the API doesn't provide it."""
    trip_type = "RT" if ret else "OW"
    price_str = f"€{value}"
    airline   = (airline or "").strip().upper()
    airline_part = f"{airline}, " if airline else ""
    title     = f"{origin_c} → {dest_c} — {price_str} {trip_type} ({airline_part}{depart}{' to ' + ret if ret else ''})"
    deal_id   = f"tp_{origin_c}_{dest_c}_{depart}_{ret}_{value}"
    if link:
        url = "https://www.aviasales.com" + link if link.startswith("/") else link
    else:
        dep_short = depart.replace("-", "")[2:] if depart else ""
        ret_short = ret.replace("-", "")[2:] if ret else ""
        url = (f"https://www.skyscanner.com/transport/flights/{origin_c.lower()}/{dest_c.lower()}/{dep_short}/{ret_short}/"
               if dep_short else
               f"https://www.skyscanner.com/transport/flights/{origin_c.lower()}/{dest_c.lower()}/")
    text_airline = airline if airline else "?"
    return {
        "id":      deal_id,
        "title":   title,
        "url":     url,
        "text":    f"Price: {price_str} · Airline: {text_airline} · Depart: {depart} · Return: {ret}",
        "source":  "Travelpayouts",
        "airline": airline,          # IATA code (v3) or "" (v2) — used by LCC filter + UI
        "price":   value,
        "currency": "€",
        "dates":   f"{depart}{' → ' + ret if ret else ''}",
    }

def parse_tp_v3(payload, origin):
    """Parse /aviasales/v3/prices_for_dates response.
    v3 items include the airline IATA code — that's the whole point of using v3."""
    deals = []
    for item in payload.get("data", []):
        deals.append(_tp_make_deal(
            origin_c=item.get("origin", origin),
            dest_c=item.get("destination", "?"),
            value=item.get("value", item.get("price", 0)),
            depart=(item.get("depart_date") or item.get("departure_at") or "")[:10],
            ret=(item.get("return_date") or item.get("return_at") or "")[:10],
            airline=item.get("airline", ""),
            link=item.get("link", ""),
        ))
    return deals

def parse_tp_v2(payload, origin):
    """Parse legacy /v2/prices/latest response (no airline field)."""
    deals = []
    for item in payload.get("data", []):
        deals.append(_tp_make_deal(
            origin_c=item.get("origin", origin),
            dest_c=item.get("destination", "?"),
            value=item.get("value", 0),
            depart=item.get("depart_date", ""),
            ret=item.get("return_date", ""),
            airline=item.get("airline", ""),   # v2 does not return this → ""
        ))
    return deals

def _tp_get(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())

def fetch_travelpayouts():
    """Query Travelpayouts for top routes from PRG/VIE/BUD.

    2026-07-08 (Fable 5 audit): switched primary endpoint to
    /aviasales/v3/prices_for_dates — unlike v2/prices/latest it returns the
    airline IATA code, which makes the LCC filter work for 60 % of the feed
    (v2 left `airline` empty → €32 Wizz fares slipped into instant PRG alerts).
    Queries the next 3 months per origin (v3 needs a departure period).
    Falls back to the old v2 endpoint if v3 errors or returns nothing.
    Rate limits: v3 = 600 req/min, we send 9 → fine.
    Requires TRAVELPAYOUTS_TOKEN env var (free signup at travelpayouts.com)."""
    token = os.environ.get("TRAVELPAYOUTS_TOKEN", "").strip()
    if not token:
        print("[!] TRAVELPAYOUTS_TOKEN not set — skipping Travelpayouts API")
        return []
    # Next 3 months as YYYY-MM (v3 accepts a whole month as departure_at)
    today = date.today()
    months = []
    y, m = today.year, today.month
    for _ in range(3):
        months.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            m, y = 1, y + 1
    deals = []
    for origin in ("PRG", "VIE", "BUD"):
        got = []
        # Primary: v3 prices_for_dates (includes airline code + aviasales link)
        for month in months:
            try:
                params = {
                    "origin":       origin,
                    "departure_at": month,
                    "currency":     "eur",
                    "limit":        35,
                    "page":         1,
                    "sorting":      "price",
                    "one_way":      "false",
                    "token":        token,
                }
                url = ("https://api.travelpayouts.com/aviasales/v3/prices_for_dates?"
                       + urllib.parse.urlencode(params))
                payload = _tp_get(url)
                if payload.get("success"):
                    got.extend(parse_tp_v3(payload, origin))
            except Exception as e:
                print(f"[!] Travelpayouts v3 {origin} {month}: {e}")
        if got:
            print(f"[✓] Travelpayouts v3 {origin}: {len(got)} routes ({len(months)} months)")
        # Fallback: v2 (no airline, but better than nothing)
        if not got:
            try:
                params = {
                    "origin":   origin,
                    "currency": "eur",
                    "limit":    100,
                    "page":     1,
                    "sorting":  "price",
                    "token":    token,
                }
                url = ("https://api.travelpayouts.com/v2/prices/latest?"
                       + urllib.parse.urlencode(params))
                payload = _tp_get(url)
                if payload.get("success"):
                    got = parse_tp_v2(payload, origin)
                    print(f"[✓] Travelpayouts v2 fallback {origin}: {len(got)} routes")
            except urllib.error.HTTPError as e:
                print(f"[!] Travelpayouts v2 {origin}: HTTP {e.code}")
            except Exception as e:
                print(f"[!] Travelpayouts v2 {origin}: {e}")
        deals.extend(got)
    return deals

def fetch_all():
    all_deals = []
    for source in SOURCES:
        if source["type"] in ("reddit_rss", "reddit_json"):
            all_deals.extend(fetch_reddit(source))
            time.sleep(3)   # polite gap between Reddit feeds (dodge 429)
        elif source["type"] == "rss":
            all_deals.extend(fetch_rss(source))
    # Travelpayouts API (separate from RSS/Reddit, runs only if token set)
    all_deals.extend(fetch_travelpayouts())
    print(f"[✓] Načteno {len(all_deals)} příspěvků ze všech zdrojů (vč. Travelpayouts)")
    return all_deals

# ── Load/save seen deals ──────────────────────────────────────────────────────
# 2026-07-08 (Fable 5 audit): seen is now a dict {deal_id: last_seen_iso}.
# The old format was a JSON list capped via list(set)[-600:], which evicted
# RANDOM ids (set order is undefined) — and one scan produces ~500 ids, so
# still-live deals kept falling out and re-triggered Telegram alerts.
# Now: eviction by age (not seen for >21 days) + hard cap on newest 5000.
SEEN_MAX_AGE_DAYS = 21
SEEN_HARD_CAP     = 5000

def load_seen():
    """Return dict {deal_id: last_seen_iso}. Accepts legacy list format."""
    if SEEN_FILE.exists():
        try:
            with open(SEEN_FILE) as f:
                data = json.load(f)
            if isinstance(data, list):          # legacy format → migrate
                now_iso = datetime.now().isoformat()
                return {deal_id: now_iso for deal_id in data}
            if isinstance(data, dict):
                return data
        except Exception:
            return {}
    return {}

def save_seen(seen):
    """Evict entries not seen for SEEN_MAX_AGE_DAYS, keep newest SEEN_HARD_CAP."""
    cutoff = (datetime.now() - timedelta(days=SEEN_MAX_AGE_DAYS)).isoformat()
    fresh = {k: v for k, v in seen.items() if v >= cutoff}
    if len(fresh) > SEEN_HARD_CAP:
        newest = sorted(fresh.items(), key=lambda kv: kv[1], reverse=True)[:SEEN_HARD_CAP]
        fresh = dict(newest)
    with open(SEEN_FILE, "w") as f:
        json.dump(fresh, f)

# ── Save latest deals to JSON for the static HTML to read ────────────────────
# (Phase 1 architecture: scanner → JSON → GitHub Pages → HTML on mobile.
#  No Flask needed for viewing. Accumulates across runs, keeps newest 500.)
LATEST_FILE = SCRIPT_DIR / "latest_deals.json"

# ── URL liveness check (mark dead URLs so HTML can hide them) ────────────────
def check_url_alive(url, timeout=4):
    """HEAD request; returns True if URL responds with <400, False on 4xx/5xx/timeout."""
    if not url or not url.startswith(('http://', 'https://')):
        return True   # missing URL → don't mark dead, can't verify
    try:
        req = urllib.request.Request(url, method='HEAD', headers=HEADERS)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status < 400
    except urllib.error.HTTPError as e:
        # 404, 410, 451 — page intentionally gone
        return e.code < 400
    except Exception:
        # Network timeout / DNS fail / SSL error → don't mark dead immediately,
        # might be transient. Only HEAD-returned-4xx counts as dead.
        return True

def mark_dead_urls(deals, max_check=300):
    """Parallel HEAD-checks; mutates each deal with d['dead'] = True/False.
       Only checks the first max_check items (saves CI minutes)."""
    import concurrent.futures
    targets = deals[:max_check]
    print(f"[~] Checking {len(targets)} URLs for liveness...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(lambda d: check_url_alive(d.get('url', '')), targets))
    dead_count = 0
    for d, alive in zip(targets, results):
        d['dead'] = not alive
        if not alive:
            dead_count += 1
    print(f"[✓] Liveness check complete — {dead_count} dead URLs flagged")
    return deals

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
            if not isinstance(existing, list):
                existing = []
        except Exception as e:
            # DATA-LOSS GUARD (2026-07-08, Fable 5 audit): a corrupt file used to
            # silently become existing=[] → the whole 500-deal pool got wiped by
            # a single bad scan. Now we refuse to overwrite and keep the old file.
            print(f"[✗] latest_deals.json is unreadable ({e}) — REFUSING to overwrite. "
                  f"Fix or delete the file manually.")
            return

    now_iso = datetime.now().isoformat()

    def to_dict(score, d, tags):
        title = d.get("title", "") or ""
        text  = d.get("text", "") or ""
        is_hotel = any(t.upper() in ("HOTEL",) for t in tags) or \
                   any(k in title.lower() for k in ("hotel", "resort", "stay", "/night"))
        # Price/currency: prefer structured fields (Travelpayouts v3),
        # else best-effort parse from the title — no fakes, 0 means "unknown".
        price = 0
        currency = ""
        if d.get("price"):
            try: price = int(d["price"])
            except Exception: price = 0
            currency = d.get("currency", "")
        if not price:
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
            "savings":  0,        # not computed — the UI hides 0 (no fake "0% below avg")
            "airline":  d.get("airline", ""),   # IATA code from TP v3, "" elsewhere
            "dates":    d.get("dates", ""),
            "grey_zone": ("GreyZone" in tags or "FuelDump" in tags),
            "approved": False,
            "created_at": now_iso,
            "last_seen":  now_iso,
            "text":     text[:200],
        }

    # Prefer json_deals (all current posts) when provided; falls back to scored buckets.
    source_items = json_deals if json_deals else (hot_deals + warm_deals + grey_deals)
    new_items = [to_dict(s, d, t) for (s, d, t) in source_items]

    # Merge with existing. FIRST-SEEN FIX (2026-07-08): keep the original
    # created_at of an already-known deal, so age badges in the app reflect how
    # long a deal has been around (previously every rescan reset it to "now"
    # and everything showed 🆕 NEW forever). last_seen tracks feed liveness.
    by_id = {x.get("id"): x for x in existing}
    for x in new_items:
        prev = by_id.get(x["id"])
        if prev and prev.get("created_at"):
            x["created_at"] = prev["created_at"]
        by_id[x["id"]] = x
    combined = sorted(
        by_id.values(),
        key=lambda x: x.get("last_seen") or x.get("created_at", ""),
        reverse=True,
    )[:500]

    # Mark dead URLs (auto-cleanup of removed/expired deals)
    combined = mark_dead_urls(combined)

    with open(LATEST_FILE, "w", encoding="utf-8") as f:
        json.dump(combined, f, indent=2, ensure_ascii=False)

    print(f"[✓] latest_deals.json saved — {len(combined)} deals, {len(new_items)} from this scan, {total_scanned} sources scanned")

# ── Send Telegram ─────────────────────────────────────────────────────────────
# 2026-07-08 (Fable 5 audit): switched parse_mode Markdown → HTML.
# Legacy Markdown has no escaping mechanism: a single "_" or ")" in a scraped
# title made the API return 400 "can't parse entities" and the WHOLE digest was
# silently lost. HTML mode + html.escape() on every dynamic string is the
# 2026 best practice (core.telegram.org/bots/api#formatting-options).
# Also added: ≥1.1 s spacing between messages (Telegram limit ~1 msg/s per chat)
# and one retry honoring retry_after on HTTP 429.

def esc(s):
    """Escape dynamic text for Telegram HTML parse mode."""
    return html.escape(str(s or ""), quote=False)

def esc_url(u):
    """Escape a URL for use inside href=\"...\"."""
    return html.escape(str(u or ""), quote=True)

_LAST_TG_SEND = [0.0]   # module-level, list so it's mutable in function scope

def _tg_post(payload_dict, timeout=15):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = json.dumps(payload_dict).encode("utf-8")
    req = urllib.request.Request(url, data=payload,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())

def send_telegram(text):
    if not BOT_TOKEN or not CHAT_ID:
        print("[!] BOT_TOKEN/CHAT_ID missing — Telegram send skipped")
        return False
    # Truncate safely at a line boundary (never mid-tag)
    if len(text) > 4000:
        cut = text[:3900]
        nl = cut.rfind("\n")
        if nl > 2000:
            cut = cut[:nl]
        text = cut + "\n\n<i>… zkráceno</i>"
    payload = {
        "chat_id":    CHAT_ID,
        "text":       text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    # Enforce ~1 msg/s per chat
    wait = 1.1 - (time.time() - _LAST_TG_SEND[0])
    if wait > 0:
        time.sleep(wait)
    for attempt in range(2):
        try:
            result = _tg_post(payload)
            _LAST_TG_SEND[0] = time.time()
            if result.get("ok"):
                print("[✓] Telegram message sent")
                return True
            if result.get("error_code") == 429 and attempt == 0:
                retry_after = (result.get("parameters") or {}).get("retry_after", 3)
                print(f"[!] Telegram 429 — waiting {retry_after}s and retrying")
                time.sleep(min(int(retry_after) + 1, 60))
                continue
            print(f"[✗] Telegram error: {result}")
            return False
        except urllib.error.HTTPError as e:
            _LAST_TG_SEND[0] = time.time()
            if e.code == 429 and attempt == 0:
                try:
                    body = json.loads(e.read().decode())
                    retry_after = (body.get("parameters") or {}).get("retry_after", 3)
                except Exception:
                    retry_after = 3
                print(f"[!] Telegram 429 — waiting {retry_after}s and retrying")
                time.sleep(min(int(retry_after) + 1, 60))
                continue
            print(f"[✗] Telegram failed: HTTP {e.code}")
            return False
        except Exception as e:
            print(f"[✗] Telegram failed: {e}")
            return False
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

def build_category_message(header, deals, today_str, limit=8):
    """Build a per-category digest in Telegram HTML format (separated from
    sending so smoke tests can verify escaping without network)."""
    lines = [f"{header} — <i>{esc(today_str)}</i>\n"]
    for score, d, tags in deals[:limit]:
        title  = esc(d.get("title", "")[:90])
        url    = esc_url(d.get("url", ""))
        source = esc(d.get("source", "?"))
        emojis = tag_emoji(tags)
        lines.append(f'• {emojis} <a href="{url}">{title}</a>')
        lines.append(f"  <i>{source} · score {score}</i>\n")
    if len(deals) > limit:
        lines.append(f"<i>+ {len(deals) - limit} more in the app</i>")
    return "\n".join(lines)

def send_category_message(header, deals, today_str, limit=8):
    """Send a per-category Telegram digest. Skip silently if no deals.
    `deals` is list of (score, deal_dict, tags) tuples sorted by score desc.
    NOTE: `header` may contain HTML tags (<b>…</b>) — don't escape it."""
    if not deals:
        return
    send_telegram(build_category_message(header, deals, today_str, limit))
    print(f"[📨] Sent category: {header[:40]} ({len(deals)} deals)")

# NOTE (2026-07-08, Fable 5 audit): format_daily_digest() was removed here.
# It was dead code (never called since the 5-category digest replaced it) and
# used legacy Markdown formatting that the new HTML-mode send_telegram() would
# render literally. Recover from git history if ever needed.

# ── Weekly LCC roundup ────────────────────────────────────────────────────────
# Tom's rule (2026-07-08): EU low-cost deals NEVER appear in daily Telegram —
# instead ONE Sunday-morning message with the top 5-7 LCC fares from home
# airports. Fires only in the Sunday run that starts between 05:00-08:59 UTC
# (the 06:17 UTC scheduled run; window is wide because GitHub cron drifts).
LCC_WEEKLY_LIMIT = 7

def build_lcc_weekly_message(all_deals, today_str, limit=LCC_WEEKLY_LIMIT):
    """Pick top LCC fares from home airports out of ALL current deals.
    Returns None when there is nothing to send (no fake 'empty' messages)."""
    pool = []
    seen_routes = set()
    for d in all_deals:
        if not is_lcc_deal(d):
            continue
        score, tags = score_deal(d.get("title", ""), d.get("text", ""))
        if "PRG/VIE/BUD" not in tags and "PRG_ANY" not in tags:
            continue   # only fares relevant to Tom's home airports
        # de-duplicate by route (origin→dest), keep the cheapest/first
        route_key = re.sub(r"—.*$", "", d.get("title", "")).strip()[:30]
        if route_key in seen_routes:
            continue
        seen_routes.add(route_key)
        price = d.get("price") or 0
        pool.append((price if price > 0 else 10**9, score, d))
    if not pool:
        return None
    pool.sort(key=lambda x: (x[0], -x[1]))   # cheapest first, then score
    lines = [f"🟠 <b>LOWCOST TÝDNE — top {min(limit, len(pool))}</b> — <i>{esc(today_str)}</i>",
             "<i>Wizz/Ryanair/easyJet a spol. z PRG/VIE/BUD. Jednou týdně, ať tě to nezahlcuje.</i>\n"]
    for price_key, score, d in pool[:limit]:
        title = esc(d.get("title", "")[:90])
        url = esc_url(d.get("url", ""))
        lines.append(f'• <a href="{url}">{title}</a>')
    lines.append("\n<i>Zbytek lowcostů najdeš v appce (vypni pill 🚫 LowCost).</i>")
    return "\n".join(lines)

def send_weekly_lcc_roundup(all_deals, today_str):
    now = datetime.utcnow()
    if now.weekday() != 6:          # Sunday only
        return False
    if not (5 <= now.hour < 9):     # the ~06:17 UTC run (cron drift tolerant)
        return False
    msg = build_lcc_weekly_message(all_deals, today_str)
    if not msg:
        print("[🟠] Weekly LCC roundup: nothing to send")
        return False
    send_telegram(msg)
    print("[🟠] Weekly LCC roundup sent")
    return True

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
    # We now route deals into 5 category buckets so Telegram gets SEPARATE messages
    # per category (Tom can mute each category independently).
    prg_flights_alerts = []         # immediate instant alerts (Tom's top priority)
    prg_any_alerts     = []         # 🇨🇿 INSTANT — anything Prague-related
    cat_prg     = []   # 🇨🇿 PRG ANYTHING (incl. hotels, packages, transit)
    cat_mispgrey = []  # 💥 Mistake / Grey zone
    cat_hotels  = []   # 🏨 Hotels (non-PRG)
    cat_eu      = []   # 🌍 Other EU
    cat_usa     = []   # 🇺🇸 USA → World

    # GLOBAL LCC EXCLUSION (Tom 2026-06-28): EU low-cost carriers do NOT enter
    # ANY Telegram category. They still go to JSON (for the app), but Telegram
    # noise is the user-facing problem — Ryanair/Wizz/EasyJet PRG→EU is rutina.
    # 2026-07-08 (Tom's request): instead they accumulate into ONE weekly
    # roundup message (top 5-7, Sunday morning) — see send_weekly_lcc_roundup().
    lcc_skipped_count = 0
    for d in new_deals:
        score, tags = score_deal(d["title"], d.get("text", ""))
        if score < 1 and "PRG_ANY" not in tags:
            continue   # PRG_ANY items bypass the score floor (Tom wants ALL Prague)

        # ─── GLOBAL EU LCC SKIP — applies to ALL Telegram routing ───────
        # 2026-07-08: is_lcc_deal() also checks the airline IATA code, so
        # structured Travelpayouts deals (W6/FR/U2…) are finally caught too —
        # previously €32 Wizz fares had no airline name and slipped through.
        if is_lcc_deal(d):
            lcc_skipped_count += 1
            continue   # LCC stays in JSON via json_deals loop below; just not Telegram

        is_grey   = "FuelDump" in tags or "GreyZone" in tags or "MistakeFare" in tags
        is_hotel  = any(k in (d.get("title","") + " " + d.get("text","")).lower()
                        for k in ("hotel", "resort", "/night", " night ", "all-inclusive"))
        is_usa    = "USA_ORIGIN" in tags
        is_prg    = "PRG_ANY" in tags   # widest net — Tom wants everything Prague

        # PRG FLIGHTS DEAL → immediate Telegram alert (16 specific carriers)
        if "PRG_FLIGHTS_DEAL" in tags:
            prg_flights_alerts.append((score, d, tags))

        # PRG_ANY → immediate Telegram alert (anything Prague, lower urgency emoji)
        # but only if NOT already covered by PRG_FLIGHTS_DEAL above
        if "PRG_ANY" in tags and "PRG_FLIGHTS_DEAL" not in tags:
            prg_any_alerts.append((score, d, tags))

        # Add to LEGACY buckets (kept for backwards compatibility / fallback)
        if score >= 8 and not is_usa:
            hot_deals.append((score, d, tags))
        elif is_grey and score >= 4 and not is_usa:
            grey_deals.append((score, d, tags))
        elif score >= 2 and not is_usa:
            warm_deals.append((score, d, tags))

        # CATEGORY ROUTING (each deal goes into exactly ONE category)
        if is_prg:
            cat_prg.append((score, d, tags))
        elif is_grey:
            cat_mispgrey.append((score, d, tags))
        elif is_hotel:
            cat_hotels.append((score, d, tags))
        elif is_usa:
            cat_usa.append((score, d, tags))
        else:
            cat_eu.append((score, d, tags))

    # Send instant 🚨🚨🚨 alerts for any PRG flights deals found this scan
    for score, d, tags in prg_flights_alerts:
        airline = next((t.replace("AIRLINE_", "") for t in tags if t.startswith("AIRLINE_")), "?")
        title = esc(d.get("title", "")[:200])
        url = esc_url(d.get("url", ""))
        msg = (
            f"🚨🚨🚨 <b>PRG FLIGHTS DEAL</b> 🚨🚨🚨\n\n"
            f"<b>Airline:</b> {esc(airline)}\n"
            f"<b>Deal:</b> {title}\n\n"
            f'<a href="{url}">Open source link</a>\n\n'
            f"<i>Score: {score} · Source: {esc(d.get('source','?'))}</i>"
        )
        send_telegram(msg)
        print(f"[🚨] PRG FLIGHTS DEAL alert sent: {airline} — {d.get('title','')[:60]}")

    # 🇨🇿 PRG ANYTHING — INSTANT alerts (limited to top 8 per scan by score)
    # Wider net than PRG_FLIGHTS_DEAL — Tom wants quality PRG signals only.
    # Filters applied:
    #   1) EU LCC airlines excluded (Ryanair/Wizz/EasyJet — too much routine clog)
    #   2) Min score threshold = 3 (skip score 1-2 PRG mentions)
    #   3) Top-8 cap — rest goes to digest only (prevents 590-msg flood)
    prg_any_alerts.sort(key=lambda x: x[0], reverse=True)   # sort by score desc
    PRG_ANY_INSTANT_CAP = 3       # tightened 2026-06-28 per Tom's request
    PRG_ANY_MIN_SCORE   = 5       # tightened — only quality PRG signals reach instant
    sent_instant = 0
    for score, d, tags in prg_any_alerts:
        if score < PRG_ANY_MIN_SCORE:
            break   # rest is sorted by score so we can stop
        if sent_instant >= PRG_ANY_INSTANT_CAP:
            break
        title = esc(d.get("title", "")[:200])
        url = esc_url(d.get("url", ""))
        msg = (
            f"🇨🇿 <b>PRG ANYTHING</b> 🇨🇿\n\n"
            f"<b>Deal:</b> {title}\n\n"
            f'<a href="{url}">Open source link</a>\n\n'
            f"<i>Score: {score} · Source: {esc(d.get('source','?'))}</i>"
        )
        send_telegram(msg)
        print(f"[🇨🇿] PRG ANY alert sent: {d.get('title','')[:60]}")
        sent_instant += 1
    skipped = max(0, len(prg_any_alerts) - sent_instant)
    if skipped:
        print(f"[🇨🇿] {skipped} more PRG ANY items skipped from instant alerts "
              f"(score < {PRG_ANY_MIN_SCORE} or cap {PRG_ANY_INSTANT_CAP} reached) — they're in JSON + digest")

    # JSON for HTML uses ALL current posts (seen or not) so the public feed
    # stays populated even when no new posts arrive in this scan. Score is
    # included so HTML can sort/filter; 0-score items are kept too.
    for d in all_deals:
        score, tags = score_deal(d["title"], d.get("text", ""))
        json_deals.append((max(0, score), d, tags))

    # Sort each category by score descending
    for cat in (cat_prg, cat_mispgrey, cat_hotels, cat_eu, cat_usa,
                hot_deals, grey_deals, warm_deals):
        cat.sort(key=lambda x: x[0], reverse=True)

    print(f"[✓] Categories — PRG:{len(cat_prg)} MISP/GREY:{len(cat_mispgrey)} "
          f"HOTELS:{len(cat_hotels)} EU:{len(cat_eu)} USA:{len(cat_usa)}")
    print(f"[🚫] LCC skipped from Telegram: {lcc_skipped_count} (still in JSON for app)")

    has_deals = any((cat_prg, cat_mispgrey, cat_hotels, cat_eu, cat_usa))

    if has_deals or "--force" in sys.argv:
        # SEND CATEGORIZED MESSAGES (Tom can mute each independently)
        send_category_message("🇨🇿 <b>PRG / VIE / BUD DEALS</b>",   cat_prg,      today_str, 8)
        send_category_message("💥 <b>MISPRICE + GREY ZONE</b>",      cat_mispgrey, today_str, 6)
        send_category_message("🏨 <b>HOTEL DEALS</b>",               cat_hotels,   today_str, 5)
        send_category_message("🌍 <b>EU DEALS</b>",                  cat_eu,       today_str, 6)
        send_category_message("🇺🇸 <b>USA → WORLD</b>",             cat_usa,      today_str, 5)
    else:
        # Send brief "nothing today" every 3rd day
        day_of_year = date.today().timetuple().tm_yday
        if day_of_year % 3 == 0 or "--test" in sys.argv:
            send_telegram(
                f"💰 <b>ARBITRAGE LIFE — {esc(today_str)}</b>\n\n"
                "😴 Dnes žádné relevantní dealy. Systém hlídá dál.\n"
                f"<i>Zkontrolováno {len(all_deals)} příspěvků</i>"
            )

    # 🟠 Weekly LCC roundup — Sundays only, one message, top 5-7 (Tom 2026-07-08).
    # Independent of the daily categories: LCC deals never appear in those.
    send_weekly_lcc_roundup(all_deals, today_str)

    # Update seen IDs — refresh last_seen for EVERY currently fetched deal
    # (not just new ones), so still-live deals never age out and re-alert.
    now_iso = datetime.now().isoformat()
    for d in all_deals:
        seen[d["id"]] = now_iso
    save_seen(seen)

    # Phase 1: write the public JSON snapshot the static HTML reads on mobile.
    save_latest_json(hot_deals, warm_deals, grey_deals, len(all_deals), json_deals=json_deals)

    print(f"[{datetime.now().strftime('%H:%M:%S')}] Hotovo.")

if __name__ == "__main__":
    main()
