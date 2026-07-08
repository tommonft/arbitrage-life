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
# UPDATED 2026-07-08 (Fable 5 audit, web-verified): several "evergreen" spots
# died in 2024-2026 devaluations — Turkish 45K TATL (now 65K, 02/2024),
# LifeMiles 63K (now 92.4K after 3 devals), United Excursionist (killed 08/2025).
# Sources: onemileatatime.com, awardwallet.com, frequentmiler.com (2026-07-08).
SWEET_SPOTS = [
    "Flying Blue Promo Rewards (monthly, 25% off): biz Europe↔US often <b>45K</b> — check 1st of month",
    "Flying Blue saver TATL biz floor: <b>60K</b> OW (post-01/2025; ~€300 YQ each way)",
    "AA partner chart (last fixed chart alive): Europe↔US biz <b>57.5K</b> (Finnair), US↔Japan biz <b>60K</b> (JAL)",
    "Qatar Qsuites US↔DOH: <b>70K</b> Avios OW (Avios move freely BA↔IB↔QR↔AY)",
    "Virgin→ANA: US–Japan biz <b>52.5–60K</b> / First <b>72.5K</b> (round-trip bookings only)",
    "Aeroplan: no fuel surcharges + stopover za <b>5K</b>; TATL biz od <b>60-75K</b> (mírná devaluace 06/2026)",
    "Chase UR→Hyatt: Park Hyatt cat 1–8, <b>3.5K–45K</b> pts (still best cpp in points)",
]

# ── Rotating subscription hacks (1 per week, by ISO week) ──────────────────────
SUB_HACKS = [
    "Spotify Premium via SK/Slovakia pricing — <b>~€5.99</b> vs €10.99 (VPN + local payment)",
    "YouTube Premium via Turkey/India — <b>~€2–3/mo</b> vs €12.99 (family plan even cheaper)",
    "Adobe CC via India pricing — <b>~50–60% off</b> vs EU (regional billing arbitrage)",
    "Netflix via Turkey/Pakistan tier — <b>~€3–4/mo</b> for Standard (price varies, re-check)",
    "NordVPN/Surfshark — buy 2yr via Black Friday + stack cashback portal (~70% off)",
    "ChatGPT/Claude — annual vs monthly: ~2 months free; check edu/regional offers",
]

def weekly_pick(lst):
    wk = date.today().isocalendar()[1]
    return lst[wk % len(lst)]

ACTION_ITEMS = [
    "Check Flying Blue Promo Rewards (resets 1st of month) for biz EU↔US",
    "Scan for credit card welcome bonuses ≥75K before next big trip",
    # 2026-07-08: reworded — hard rule says no skate-career references in this
    # PUBLIC repo (the old text named the events directly).
    "Verify upcoming event/travel dates → set award alerts on those routes",
    "Re-run mistake-fare watch: ITA Matrix + Google Flights price-error patterns",
    "Review subscription stack — cancel/rotate anything not used this month",
]

def esc(s):
    """Escape dynamic text for Telegram HTML parse mode (2026-07-08 audit)."""
    return html.escape(str(s or ""), quote=False)

def send_telegram(text):
    if len(text) > 4096:
        text = text[:4050] + "\n\n<i>… zkráceno</i>"
    payload = json.dumps({"chat_id": CHAT_ID, "text": text,
                          "parse_mode": "HTML", "disable_web_page_preview": True}).encode()
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

    L = [f"💰 <b>ARBITRAGE WEEKLY DIGEST</b> — {esc(today)}",
         f"<i>Top-of-week scan: awardtravel · churning · flightdeals</i>", ""]

    if top:
        L.append(f"🔥 <b>BEST DEALS THIS WEEK</b> ({len(top)} of {len(scored)} relevant)")
        for i, (s, tags, d) in enumerate(top, 1):
            t = esc(d["title"][:120])
            tagstr = esc(" ".join(tags[:3]))
            url = html.escape(d.get("url", ""), quote=True)
            L.append(f'{i}. {t}\n   {tagstr} · <i>{esc(d["source"])}</i> · <a href="{url}">link</a>')
        L.append("")
    else:
        L.append("🔥 <b>BEST DEALS THIS WEEK</b>")
        L.append("<i>No high-relevance hits scored this week (feeds quiet or rate-limited).</i>")
        L.append("")

    L.append("🏆 <b>EVERGREEN AWARD SWEET SPOTS</b>")
    for sp in SWEET_SPOTS:
        L.append(f"• {sp}")
    L.append("")

    L.append("📺 <b>SUBSCRIPTION HACK OF THE WEEK</b>")
    L.append(f"• {weekly_pick(SUB_HACKS)}")
    L.append("")

    L.append("✅ <b>WEEKLY ACTION ITEMS</b>")
    for a in ACTION_ITEMS:
        L.append(f"☐ {esc(a)}")
    L.append("")
    L.append("<i>Stay predatory. — Arbitrage Life</i>")

    msg = "\n".join(L)
    print(msg)
    print("-" * 50)
    send_telegram(msg)

if __name__ == "__main__":
    main()
