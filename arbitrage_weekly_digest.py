#!/usr/bin/env python3
"""
💰 ARBITRAGE LIFE — WEEKLY INTELLIGENCE DIGEST
Tom Monfret | Runs every Sunday morning

Pulls top-of-week posts from r/awardtravel, r/churning, r/flightdeals (Reddit Atom RSS,
since reddit .json is 403-blocked), filters for high-relevance arbitrage (business class,
miles/points, Europe, mistake fares, churning bonuses), then appends evergreen award
sweet spots, a rotating subscription hack, and a weekly action-items checklist.
Delivers everything as a single Telegram message.

Note: SecretFlying RSS feeds are dead (return HTML), so they are intentionally omitted.
"""

import json, os, re, html, time, urllib.request
from datetime import datetime, date
import xml.etree.ElementTree as ET

BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
CHAT_ID   = int(os.environ.get("CHAT_ID", "0").strip() or "0")

HEADERS = {"User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")}
ATOM = "{http://www.w3.org/2005/Atom}"

REDDIT_FEEDS = [
    ("r/awardtravel", "https://www.reddit.com/r/awardtravel/top/.rss?t=week"),
    ("r/churning",    "https://www.reddit.com/r/churning/top/.rss?t=week"),
    ("r/flightdeals", "https://www.reddit.com/r/flightdeals/top/.rss?t=week"),
]

# ── Relevance scoring (lightweight, weekly-roundup oriented) ──────────────────
HOME = ["prague","prg","vienna","vie","budapest","bud","bratislava","central europe","eastern europe","europe","european"]
AFKLM = ["air france","klm","flying blue","skyteam"]
BIZ = ["business class","first class","biz class","lie-flat","lie flat","la premiere","suites"]
AWARD = ["miles","points","award","avios","sweet spot","redeem","redemption","transfer bonus","ana","turkish","aeroplan","virgin"]
MISTAKE = ["mistake fare","error fare","glitch","price error","fat finger"]
CHURN = ["bonus","sign-up","signup","offer","100k","90k","80k","75k","points bonus","welcome offer","referral"]
SKIP = ["[trip report]","trip report","question thread","daily question","weekly discussion","what credit card","data points thread"]

def score(title, text=""):
    c = (title + " " + text).lower()
    if any(k in c for k in SKIP):
        return -1, []
    s, tags = 0, []
    if any(re.search(r'\b'+re.escape(k)+r'\b', c) for k in HOME): s += 3; tags.append("🇪🇺EU")
    if any(k in c for k in AFKLM):   s += 3; tags.append("AF/KLM")
    if any(k in c for k in MISTAKE): s += 5; tags.append("🔥MISTAKE")
    if any(k in c for k in BIZ):     s += 3; tags.append("💺BIZ")
    if any(k in c for k in AWARD):   s += 2; tags.append("🎯AWARD")
    if any(k in c for k in CHURN):   s += 2; tags.append("💳BONUS")
    return s, tags

def fetch_reddit():
    deals = []
    for idx, (name, url) in enumerate(REDDIT_FEEDS):
        ok = False
        for attempt in range(2):
            try:
                req = urllib.request.Request(url, headers=HEADERS)
                with urllib.request.urlopen(req, timeout=15) as resp:
                    raw = resp.read()
                root = ET.fromstring(raw)
                for e in root.findall(f"{ATOM}entry"):
                    title = (e.findtext(f"{ATOM}title") or "").strip()
                    link_el = e.find(f"{ATOM}link")
                    link = link_el.get("href") if link_el is not None else ""
                    content = re.sub(r'<[^>]+>', ' ', e.findtext(f"{ATOM}content") or "")
                    content = html.unescape(content)[:500]
                    deals.append({"title": html.unescape(title), "url": link,
                                  "text": content, "source": name})
                ok = True
                break
            except Exception as ex:
                print(f"[!] {name} attempt {attempt+1} failed: {ex}")
                if attempt == 0:
                    time.sleep(7)
        if not ok:
            print(f"[✗] {name} gave up after retries")
        if idx < len(REDDIT_FEEDS) - 1:
            time.sleep(7)  # polite gap between feeds to dodge Reddit 429
    print(f"[✓] Fetched {len(deals)} posts")
    return deals

# ── Evergreen award sweet spots ───────────────────────────────────────────────
SWEET_SPOTS = [
    "United→ANA biz JFK–TYO: *88K* miles one-way (transfer Chase/Bilt)",
    "Turkish Miles&Smiles→United domestic US: *10K* | Star Alliance biz Europe→US: *45K*",
    "Chase UR→Hyatt: book Park Hyatt cat 1–8, *3.5K–45K* pts (best cpp in points)",
    "Flying Blue Promo Rewards (monthly): biz Europe↔US often *50–60K* — check 1st of month",
    "LifeMiles biz Europe→US *63K*, no fuel surcharges (watch for 'buy miles' promos ~1.5¢)",
    "Aeroplan→biz to Europe *60K* + stopover for 5K; great sweet-spot distance chart",
    "Virgin→ANA RTW biz *125K* round-trip (one of the best premium redemptions alive)",
]

# ── Rotating subscription hacks (1 per week, by ISO week) ──────────────────────
SUB_HACKS = [
    "Spotify Premium via SK/Slovakia pricing — *~€5.99* vs €10.99 (VPN + local payment)",
    "YouTube Premium via Turkey/India — *~€2–3/mo* vs €12.99 (family plan even cheaper)",
    "Adobe CC via India pricing — *~50–60% off* vs EU (regional billing arbitrage)",
    "Netflix via Turkey/Pakistan tier — *~€3–4/mo* for Standard (price varies, re-check)",
    "NordVPN/Surfshark — buy 2yr via Black Friday + stack cashback portal (~70% off)",
    "ChatGPT/Claude — annual vs monthly: ~2 months free; check edu/regional offers",
]

def weekly_pick(lst):
    wk = date.today().isocalendar()[1]
    return lst[wk % len(lst)]

ACTION_ITEMS = [
    "Check Flying Blue Promo Rewards (resets 1st of month) for biz EU↔US",
    "Scan for credit card welcome bonuses ≥75K before next big trip",
    "Verify any INTL-EVENT / G28 travel dates → set award alerts on those routes",
    "Re-run mistake-fare watch: ITA Matrix + Google Flights price-error patterns",
    "Review subscription stack — cancel/rotate anything not used this month",
]

def send_telegram(text):
    if len(text) > 4096:
        text = text[:4050] + "\n\n_…zkráceno_"
    payload = json.dumps({"chat_id": CHAT_ID, "text": text,
                          "parse_mode": "Markdown", "disable_web_page_preview": True}).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                                 data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            r = json.loads(resp.read().decode())
            print("[✓] Telegram sent" if r.get("ok") else f"[✗] Telegram error: {r}")
            return r.get("ok", False)
    except Exception as e:
        print(f"[✗] Telegram failed: {e}")
        return False

def main():
    today = date.today().strftime("%d.%m.%Y")
    deals = fetch_reddit()
    scored = []
    for d in deals:
        s, tags = score(d["title"], d["text"])
        if s >= 3:
            scored.append((s, tags, d))
    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:10]

    L = [f"💰 *ARBITRAGE WEEKLY DIGEST* — {today}",
         f"_Top-of-week scan: awardtravel · churning · flightdeals_", ""]

    if top:
        L.append(f"🔥 *BEST DEALS THIS WEEK* ({len(top)} of {len(scored)} relevant)")
        for i, (s, tags, d) in enumerate(top, 1):
            t = d["title"][:120]
            tagstr = " ".join(tags[:3])
            L.append(f"{i}. {t}\n   {tagstr} · _{d['source']}_ · [link]({d['url']})")
        L.append("")
    else:
        L.append("🔥 *BEST DEALS THIS WEEK*")
        L.append("_No high-relevance hits scored this week (feeds quiet or rate-limited)._")
        L.append("")

    L.append("🏆 *EVERGREEN AWARD SWEET SPOTS*")
    for sp in SWEET_SPOTS:
        L.append(f"• {sp}")
    L.append("")

    L.append("📺 *SUBSCRIPTION HACK OF THE WEEK*")
    L.append(f"• {weekly_pick(SUB_HACKS)}")
    L.append("")

    L.append("✅ *WEEKLY ACTION ITEMS*")
    for a in ACTION_ITEMS:
        L.append(f"☐ {a}")
    L.append("")
    L.append("_Stay predatory. — Arbitrage Life_")

    msg = "\n".join(L)
    print(msg)
    print("-" * 50)
    send_telegram(msg)

if __name__ == "__main__":
    main()
