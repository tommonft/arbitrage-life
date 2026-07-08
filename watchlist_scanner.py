#!/usr/bin/env python3
"""
🎯 WATCHLIST SCANNER — Tom Monfret · Arbitrage Life
Queries Travelpayouts API daily for specific routes/dates, alerts via Telegram
when price drops below threshold or below 7-day rolling average.

Watchlists live in watchlist.json (Tom edits there).
Price history accumulates in watchlist_prices.json (auto-managed).
"""

import html
import json
import os
import sys
import time
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, date, timedelta
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()
WATCHLIST_FILE = SCRIPT_DIR / "watchlist.json"
PRICES_FILE    = SCRIPT_DIR / "watchlist_prices.json"

BOT_TOKEN   = os.environ.get("BOT_TOKEN", "")
CHAT_ID     = os.environ.get("CHAT_ID", "")
TP_TOKEN    = os.environ.get("TRAVELPAYOUTS_TOKEN", "")
SERPAPI_KEY = os.environ.get("SERPAPI_KEY", "").strip()

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; Arbitrage-Life Watchlist Scanner)",
    "Accept":     "application/json",
}

# ── Travelpayouts queries ─────────────────────────────────────────────────────
# We use the public v2 latest-prices endpoint. Requires a free token (sign up at
# travelpayouts.com → marketing tools → API access).
# If token missing, scanner runs in "config-check" mode (logs config, no queries).

def query_travelpayouts(origin: str, destination: str, depart: str, ret: str, currency: str = "EUR"):
    """Query Travelpayouts for best price on a specific route + date combo.
    Returns (price, airline_code, found_at) or (None, None, None) if not found."""
    if not TP_TOKEN:
        return None, None, None

    # v1/prices/cheap supports origin/destination/depart_date/return_date
    params = {
        "origin":        origin,
        "destination":   destination,
        "depart_date":   depart,
        "return_date":   ret,
        "currency":      currency.lower(),
        "token":         TP_TOKEN,
    }
    url = "https://api.travelpayouts.com/v1/prices/cheap?" + urllib.parse.urlencode(params)
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
        # Response shape: { success: true, data: { "DEST_CODE": { "0": {price, airline, ...}, "1": {...} } } }
        if not data.get("success"):
            return None, None, None
        dest_block = data.get("data", {}).get(destination, {})
        if not dest_block:
            return None, None, None
        # Pick cheapest entry across all variants
        cheapest = None
        for variant in dest_block.values():
            p = variant.get("price")
            if p is None:
                continue
            if cheapest is None or p < cheapest[0]:
                cheapest = (p, variant.get("airline", "?"), variant.get("found_at", ""))
        return cheapest if cheapest else (None, None, None)
    except urllib.error.HTTPError as e:
        print(f"  [HTTP {e.code}] {origin}→{destination} {depart}/{ret}")
        return None, None, None
    except Exception as e:
        print(f"  [ERROR] {origin}→{destination} {depart}/{ret}: {e}")
        return None, None, None

# ── SerpApi Google Flights fallback (added 2026-07-08, Fable 5) ──────────────
# WHY: Travelpayouts is a CACHE of prices other Aviasales users searched.
# Thin routes (PRG→ASU) are searched by almost nobody → cache is empty →
# 19 runs produced zero data. SerpApi asks Google Flights LIVE, where a price
# always exists. Free tier = 250 searches/month; our budget below uses ~186.
#
# BUDGET STRATEGY (do not exceed free tier!):
#   - SerpApi fires ONLY when Travelpayouts returned nothing for the watch
#   - exactly 1 query per watch per run (2 watches × 3 runs/day × 31 d ≈ 186/mo)
#   - the (destination, depart, return) combo ROTATES deterministically between
#     runs, so over ~2 weeks the whole date window gets sampled
SERPAPI_MAX_PER_WATCH = 1

def _serpapi_combos(origins, dests, dep_win, ret_win):
    """Representative combos: primary origin × each dest × 3×3 date grid."""
    def edges(win):
        s = datetime.fromisoformat(win[0]).date()
        e = datetime.fromisoformat(win[1]).date()
        mid = s + (e - s) / 2
        return sorted({s.isoformat(), mid.isoformat(), e.isoformat()})
    combos = []
    for d in dests:
        for dep in edges(dep_win):
            for ret in edges(ret_win):
                combos.append((origins[0], d, dep, ret))
    return combos

def _serpapi_pick(combos):
    """Deterministic rotation: different combo each run (3 runs/day)."""
    idx = (date.today().toordinal() * 3 + datetime.utcnow().hour // 8) % len(combos)
    return combos[idx]

def query_serpapi(origin: str, destination: str, depart: str, ret: str, currency: str = "EUR"):
    """One LIVE Google Flights lookup via SerpApi.
    Returns (price, airline, source_label) or (None, None, None)."""
    if not SERPAPI_KEY:
        return None, None, None
    params = {
        "engine":       "google_flights",
        "departure_id": origin,
        "arrival_id":   destination,
        "outbound_date": depart,
        "return_date":  ret,
        "type":         "1",          # round trip
        "currency":     currency.upper(),
        "hl":           "en",
        "api_key":      SERPAPI_KEY,
    }
    url = "https://serpapi.com/search.json?" + urllib.parse.urlencode(params)
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
        return parse_serpapi(data)
    except urllib.error.HTTPError as e:
        print(f"  [SerpApi HTTP {e.code}] {origin}→{destination} {depart}/{ret}")
        return None, None, None
    except Exception as e:
        print(f"  [SerpApi ERROR] {origin}→{destination}: {e}")
        return None, None, None

def parse_serpapi(data: dict):
    """Extract the cheapest option from a SerpApi Google Flights response.
    Separated from the network call so smoke tests can verify it offline."""
    options = (data.get("best_flights") or []) + (data.get("other_flights") or [])
    best = None
    for opt in options:
        p = opt.get("price")
        if p is None:
            continue
        if best is None or p < best[0]:
            legs = opt.get("flights") or [{}]
            airline = legs[0].get("airline", "?")
            best = (int(p), airline, "google_flights")
    if best:
        return best
    # fallback: aggregate insight when option list is empty
    lowest = (data.get("price_insights") or {}).get("lowest_price")
    if lowest:
        return int(lowest), "?", "google_flights"
    return None, None, None

# ── Telegram ──────────────────────────────────────────────────────────────────
# 2026-07-08 (Fable 5 audit): parse_mode Markdown → HTML + html.escape on
# dynamic strings (same reasoning as arbitrage_scanner.py — legacy Markdown
# breaks on "_"/")" and the message is silently lost).
def esc(s):
    return html.escape(str(s or ""), quote=False)

def send_telegram(text: str):
    if not BOT_TOKEN or not CHAT_ID:
        print("  [WARN] BOT_TOKEN / CHAT_ID not set — skipping Telegram")
        return False
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    if len(text) > 4000:
        text = text[:4000] + "\n\n<i>… zkráceno</i>"
    payload = json.dumps({
        "chat_id":    int(CHAT_ID),
        "text":       text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }).encode("utf-8")
    try:
        req = urllib.request.Request(url, data=payload,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            j = json.loads(resp.read().decode())
            return bool(j.get("ok"))
    except Exception as e:
        print(f"  [Telegram] {e}")
        return False

# ── Date helpers ──────────────────────────────────────────────────────────────
def daterange(start: str, end: str):
    """Yield ISO date strings from start to end inclusive."""
    s = datetime.fromisoformat(start).date()
    e = datetime.fromisoformat(end).date()
    cur = s
    while cur <= e:
        yield cur.isoformat()
        cur += timedelta(days=1)

# ── Persistence ───────────────────────────────────────────────────────────────
def load_watchlist():
    """Load watchlist config. Supports v1 (watches key) and v2 (flights/hotels/cars/miles)."""
    if not WATCHLIST_FILE.exists():
        print(f"[!] {WATCHLIST_FILE} not found")
        sys.exit(1)
    with open(WATCHLIST_FILE) as f:
        cfg = json.load(f)
    # v1 → just watches dict
    if "watches" in cfg:
        return cfg["watches"]
    # v2 → return flights dict (only flights are scanned by THIS scanner)
    return {k: v for k, v in cfg.get("flights", {}).items() if not k.startswith("_")}

def load_prices():
    if not PRICES_FILE.exists():
        return {}
    try:
        with open(PRICES_FILE) as f:
            return json.load(f)
    except Exception:
        return {}

def save_prices(prices):
    with open(PRICES_FILE, "w", encoding="utf-8") as f:
        json.dump(prices, f, indent=2, ensure_ascii=False)

def avg_recent(history: list, days: int = 7):
    """Return rolling average price over last N days (None if not enough data)."""
    if not history:
        return None
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    recent = [h for h in history if h.get("date", "") >= cutoff]
    if len(recent) < 2:
        return None
    prices = [h["price"] for h in recent if h.get("price")]
    if not prices:
        return None
    return sum(prices) / len(prices)

# ── Main scan ─────────────────────────────────────────────────────────────────
def scan_watch(watch_id: str, watch: dict, prices: dict):
    label    = watch.get("label", watch_id)
    origins  = watch.get("origin_codes", ["PRG"])
    dests    = watch.get("destination_codes", [])
    dep_win  = watch.get("depart_window", [])
    ret_win  = watch.get("return_window", [])
    currency = watch.get("currency", "EUR")
    alert_eur = watch.get("alert_below_eur")
    alert_pct = watch.get("alert_below_avg_pct", 15)

    print(f"\n═══ Watch: {label} ═══")
    print(f"  Origins: {origins} → Destinations: {dests}")
    print(f"  Depart window: {dep_win}, Return window: {ret_win}")

    # Guard against malformed config (2026-07-08, Fable 5 audit):
    # a missing/short window used to raise IndexError deep in the loop.
    if len(dep_win) < 2 or len(ret_win) < 2 or not dests:
        print(f"  [SKIP] Watch '{label}' has incomplete config "
              f"(need depart_window[2], return_window[2], destination_codes)")
        return

    best_overall = None   # (price, origin, dest, dep, ret, airline)
    queries = 0

    for o in origins:
        for d in dests:
            for dep in daterange(dep_win[0], dep_win[1]):
                for ret in daterange(ret_win[0], ret_win[1]):
                    queries += 1
                    price, airline, found_at = query_travelpayouts(o, d, dep, ret, currency)
                    time.sleep(0.25)   # stay well under TP's 300 req/min limit
                    if price is None:
                        continue
                    if best_overall is None or price < best_overall[0]:
                        best_overall = (price, o, d, dep, ret, airline)

    print(f"  Queries sent: {queries}")

    via = "travelpayouts"
    if best_overall is None and SERPAPI_KEY:
        # ── SerpApi fallback: TP cache is empty for this route (typical for
        # thin routes like PRG→ASU). One LIVE Google Flights query per run,
        # rotating through the date window. Budget note at top of file.
        combo = _serpapi_pick(_serpapi_combos(origins, dests, dep_win, ret_win))
        o, d, dep, ret = combo
        print(f"  ↪ Travelpayouts empty → SerpApi live lookup: {o}→{d} {dep}/{ret}")
        price, airline, src = query_serpapi(o, d, dep, ret, currency)
        if price is not None:
            best_overall = (price, o, d, dep, ret, airline)
            via = "google_flights"

    if best_overall is None:
        print("  No prices returned (token missing or no data)")
        return

    price, o, d, dep, ret, airline = best_overall
    print(f"  ✓ Best: {o}→{d} {dep}/{ret} = {currency} {price} ({airline}) via {via}")

    # Update history
    if watch_id not in prices:
        prices[watch_id] = {"history": []}
    entry = {
        "date":   datetime.now().isoformat(),
        "price":  price,
        "currency": currency,
        "route":  f"{o}→{d}",
        "depart": dep,
        "return": ret,
        "airline": airline,
        "via":    via,     # "travelpayouts" (cache) vs "google_flights" (live)
    }
    prices[watch_id]["history"].append(entry)
    # Keep 90 most-recent entries
    prices[watch_id]["history"] = prices[watch_id]["history"][-90:]

    # Alert logic
    alerts = []
    if alert_eur is not None and price <= alert_eur:
        alerts.append(f"under your threshold {currency} {alert_eur}")
    avg = avg_recent(prices[watch_id]["history"][:-1], days=7)   # exclude the just-added entry
    if avg and price <= avg * (1 - alert_pct / 100.0):
        alerts.append(f"{alert_pct}% below 7-day avg ({currency} {avg:.0f})")

    # ALERT DEDUP (2026-07-08, Fable 5 audit): the scanner runs 3× daily —
    # once a price sat below the threshold it re-alerted every single run.
    # Now we re-alert only if the price dropped ≥3 % below the last alerted
    # price OR the last alert is older than 3 days (gentle reminder).
    if alerts:
        last = prices[watch_id].get("last_alert") or {}
        last_price = last.get("price")
        last_date  = last.get("date", "")
        three_days_ago = (datetime.now() - timedelta(days=3)).isoformat()
        is_better  = last_price is None or price <= last_price * 0.97
        is_stale   = last_date < three_days_ago
        if not (is_better or is_stale):
            print(f"  (alert suppressed — already alerted at {currency} {last_price} on {last_date[:16]})")
            alerts = []

    if alerts:
        sky = (f"https://www.skyscanner.com/transport/flights/"
               f"{o.lower()}/{d.lower()}/{dep.replace('-','')[2:]}/{ret.replace('-','')[2:]}/")
        msg = (
            f"🎯🎯🎯 <b>WATCHLIST HIT</b> 🎯🎯🎯\n\n"
            f"<b>{esc(label)}</b>\n\n"
            f"<b>Route:</b> {esc(o)} → {esc(d)}\n"
            f"<b>Dates:</b> {esc(dep)} → {esc(ret)}\n"
            f"<b>Price:</b> {esc(currency)} {price}\n"
            f"<b>Airline:</b> {esc(airline)}\n\n"
            f"<i>Trigger: " + esc(" · ".join(alerts)) + "</i>\n\n"
            f'<a href="{html.escape(sky, quote=True)}">Search Skyscanner</a>'
        )
        send_telegram(msg)
        prices[watch_id]["last_alert"] = {"date": datetime.now().isoformat(), "price": price}
        print(f"  🎯 ALERT sent: {' · '.join(alerts)}")
    else:
        print(f"  (no alert — price OK; avg {avg if avg else 'n/a'})")

def main():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] Watchlist scanner starting...")
    if not TP_TOKEN:
        print("[!] TRAVELPAYOUTS_TOKEN missing. Will log config but skip queries.")
        print("    Add as GitHub Secret to enable live pricing.")
    watches = load_watchlist()
    print(f"  Loaded {len(watches)} watches")
    prices = load_prices()
    for wid, w in watches.items():
        try:
            scan_watch(wid, w, prices)
        except Exception as e:
            print(f"  [ERROR scanning {wid}] {e}")
    save_prices(prices)
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Done.")

if __name__ == "__main__":
    main()
