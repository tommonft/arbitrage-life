#!/usr/bin/env python3
"""
🎯 WATCHLIST SCANNER — Tom Monfret · Arbitrage Life
Queries Travelpayouts API daily for specific routes/dates, alerts via Telegram
when price drops below threshold or below 7-day rolling average.

Watchlists live in watchlist.json (Tom edits there).
Price history accumulates in watchlist_prices.json (auto-managed).
"""

import json
import os
import sys
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

# ── Telegram ──────────────────────────────────────────────────────────────────
def send_telegram(text: str):
    if not BOT_TOKEN or not CHAT_ID:
        print("  [WARN] BOT_TOKEN / CHAT_ID not set — skipping Telegram")
        return False
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    if len(text) > 4000:
        text = text[:4000] + "\n\n_...zkráceno_"
    payload = json.dumps({
        "chat_id":    int(CHAT_ID),
        "text":       text,
        "parse_mode": "Markdown",
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
    if not WATCHLIST_FILE.exists():
        print(f"[!] {WATCHLIST_FILE} not found")
        sys.exit(1)
    with open(WATCHLIST_FILE) as f:
        return json.load(f).get("watches", {})

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

    best_overall = None   # (price, origin, dest, dep, ret, airline)
    queries = 0

    for o in origins:
        for d in dests:
            for dep in daterange(dep_win[0], dep_win[1]):
                for ret in daterange(ret_win[0], ret_win[1]):
                    queries += 1
                    price, airline, found_at = query_travelpayouts(o, d, dep, ret, currency)
                    if price is None:
                        continue
                    if best_overall is None or price < best_overall[0]:
                        best_overall = (price, o, d, dep, ret, airline)

    print(f"  Queries sent: {queries}")

    if best_overall is None:
        print("  No prices returned (token missing or no data)")
        return

    price, o, d, dep, ret, airline = best_overall
    print(f"  ✓ Best: {o}→{d} {dep}/{ret} = {currency} {price} ({airline})")

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

    if alerts:
        msg = (
            f"🎯🎯🎯 *WATCHLIST HIT* 🎯🎯🎯\n\n"
            f"*{label}*\n\n"
            f"*Route:* {o} → {d}\n"
            f"*Dates:* {dep} → {ret}\n"
            f"*Price:* {currency} {price}\n"
            f"*Airline:* {airline}\n\n"
            f"_Trigger: " + " · ".join(alerts) + "_\n\n"
            f"[Search Skyscanner](https://www.skyscanner.com/transport/flights/{o.lower()}/{d.lower()}/{dep.replace('-','')[2:]}/{ret.replace('-','')[2:]}/)"
        )
        send_telegram(msg)
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
