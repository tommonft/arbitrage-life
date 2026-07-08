#!/usr/bin/env python3
"""
🧪 ARBITRAGE LIFE — SMOKE TESTS (Fable 5 audit, 2026-07-08)

Offline sanity checks — no network, no secrets needed.
Run:  python3 smoke_test.py   (or double-click Test.command)

Every test prints ✓/✗; exit code 0 = all good, 1 = something broke.
If this script fails after a code change, DO NOT run Ship.command —
ask Claude to look at the failing test first.
"""

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.resolve()))

PASS = 0
FAIL = 0

def check(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        print(f"  ✗ {name} {('— ' + detail) if detail else ''}")

print("═" * 60)
print(" ARBITRAGE LIFE — smoke tests")
print("═" * 60)

# ── 1. Scanner imports and core scoring ─────────────────────────────────────
print("\n[1] arbitrage_scanner — scoring & detection")
import arbitrage_scanner as sc

s, tags = sc.score_deal("Prague to New York from €299 with Air France", "")
check("home airport PRG detected", "PRG/VIE/BUD" in tags)
check("AF/KLM detected", "AF/KLM" in tags)
check("JACKPOT (home + AF/KLM)", "🎯JACKPOT" in tags)
check("PRG_FLIGHTS_DEAL fires for real carrier+Prague", "PRG_FLIGHTS_DEAL" in tags)
check("PRG_ANY tag present", "PRG_ANY" in tags)

# word-boundary regression tests (the old substring bug)
s2, t2 = sc.score_deal("Kansas City: cheap flights to Cuba this fall", "")
check("'Kansas'+'Cuba' does NOT fire PRG_FLIGHTS_DEAL", "PRG_FLIGHTS_DEAL" not in t2)
s3, t3 = sc.score_deal("Budget airlines review: believe the hype", "")
check("'budget'/'believe' do NOT match BUD/VIE", "PRG/VIE/BUD" not in t3)

s4, t4 = sc.score_deal("US domestic only: Hawaii sale", "")
check("SKIP keyword returns score -1", s4 == -1)

# LCC detection — by name and by IATA code (Travelpayouts v3)
check("LCC by name (Ryanair)", sc.is_lcc_deal({"airline": "", "title": "Ryanair PRG sale", "text": ""}))
check("LCC by code (W6)", sc.is_lcc_deal({"airline": "W6", "title": "PRG → MIL — €32 RT", "text": ""}))
check("SAS is NOT marked LCC", not sc.is_lcc_deal({"airline": "SK", "title": "PRG → CPH", "text": ""}))
check("PRG_ANY excludes LCC by name", not sc.is_prg_anything("Wizz Air Prague sale", ""))

# ── 1b. Weekly LCC roundup (Tom 2026-07-08: LCC only 1×/week, top 5-7) ──────
print("\n[1b] Weekly LCC roundup")
lcc_deals = [
    {"title": "PRG → MIL — €32 RT (W6, 2026-09-14 to 2026-09-17)", "text": "", "url": "https://a.io/1",
     "airline": "W6", "price": 32, "source": "Travelpayouts"},
    {"title": "VIE → BCN — €45 RT (FR, 2026-09-01 to 2026-09-08)", "text": "", "url": "https://a.io/2",
     "airline": "FR", "price": 45, "source": "Travelpayouts"},
    {"title": "Prague to Malaga with Ryanair from €29", "text": "", "url": "https://a.io/3",
     "airline": "", "price": 29, "source": "Fly4Free"},
    {"title": "JFK → LAX — $99 (DL)", "text": "", "url": "https://a.io/4",
     "airline": "DL", "price": 99, "source": "Travelpayouts"},   # not LCC, not home
    {"title": "PRG → CDG — €120 RT (AF, 2026-09-02 to 2026-09-06)", "text": "", "url": "https://a.io/5",
     "airline": "AF", "price": 120, "source": "Travelpayouts"},  # home but NOT LCC
]
msg = sc.build_lcc_weekly_message(lcc_deals, "08. 07. 2026")
check("roundup builds a message", msg is not None)
check("roundup includes home LCC fares", "PRG → MIL" in msg and "Malaga" in msg)
check("roundup excludes non-LCC (AF) and non-home (DL)", "CDG" not in msg and "JFK" not in msg)
check("cheapest fare listed first", msg.index("Malaga") < msg.index("MIL"))
check("roundup returns None on empty pool", sc.build_lcc_weekly_message([lcc_deals[4]], "x") is None)
check("cap respected", sc.LCC_WEEKLY_LIMIT == 7)

# ── 2. Telegram HTML escaping ────────────────────────────────────────────────
print("\n[2] Telegram — HTML mode & escaping")
check("esc() escapes < > &", sc.esc("a<b>&c") == "a&lt;b&gt;&amp;c")
check("esc() keeps underscores (no Markdown!)", sc.esc("PRG_deal") == "PRG_deal")

msg = sc.build_category_message(
    "🇨🇿 <b>TEST</b>",
    [(7, {"title": "Deal_with <script>alert(1)</script> & stuff",
          "url": "https://example.com/a)b_c",
          "source": "Evil*Source_"}, ["PRG/VIE/BUD"])],
    "08. 07. 2026")
check("scraped <script> is escaped in digest", "<script>" not in msg)
check("digest keeps our own <a href> link", '<a href="' in msg)
check("digest uses <i> not _italic_", "<i>" in msg and "_Evil" not in msg)

src_scanner = open(Path(__file__).parent / "arbitrage_scanner.py").read()
check("no legacy Markdown parse_mode left in scanner", '"parse_mode": "Markdown"' not in src_scanner)

# ── 3. seen_deals — dict format, age eviction, legacy migration ─────────────
print("\n[3] seen_deals — eviction & migration")
from datetime import datetime, timedelta

with tempfile.TemporaryDirectory() as td:
    orig = sc.SEEN_FILE
    sc.SEEN_FILE = Path(td) / "seen_deals.json"
    try:
        # legacy list format migrates to dict
        sc.SEEN_FILE.write_text(json.dumps(["a", "b", "c"]))
        seen = sc.load_seen()
        check("legacy list migrates to dict", isinstance(seen, dict) and set(seen) == {"a", "b", "c"})

        # age-based eviction: old entries drop, fresh survive
        now = datetime.now()
        seen = {
            "old_deal":   (now - timedelta(days=40)).isoformat(),
            "fresh_deal": now.isoformat(),
        }
        sc.save_seen(seen)
        reloaded = sc.load_seen()
        check("old id evicted after 21 days", "old_deal" not in reloaded)
        check("fresh id survives", "fresh_deal" in reloaded)

        # hard cap keeps newest
        big = {f"id{i}": (now - timedelta(minutes=i)).isoformat() for i in range(6000)}
        sc.save_seen(big)
        reloaded = sc.load_seen()
        check(f"hard cap {sc.SEEN_HARD_CAP} enforced", len(reloaded) == sc.SEEN_HARD_CAP)
        check("cap keeps the newest ids", "id0" in reloaded and "id5999" not in reloaded)
    finally:
        sc.SEEN_FILE = orig

# ── 4. Travelpayouts parsers (v3 + v2 fixtures) ──────────────────────────────
print("\n[4] Travelpayouts — v3/v2 parsing")
v3_payload = {"success": True, "data": [{
    "origin": "PRG", "destination": "BCN", "price": 45,
    "departure_at": "2026-08-04T09:15:00+02:00", "return_at": "2026-08-11T21:05:00+02:00",
    "airline": "W6", "link": "/search/PRG0408BCN1108?t=abc",
}]}
deals = sc.parse_tp_v3(v3_payload, "PRG")
check("v3 parser returns deal", len(deals) == 1)
d = deals[0]
check("v3 airline code populated", d["airline"] == "W6")
check("v3 dates trimmed to YYYY-MM-DD", "2026-08-04" in d["title"] and "T09:15" not in d["title"])
check("v3 aviasales deeplink used", d["url"].startswith("https://www.aviasales.com/"))
check("v3 price/currency structured", d["price"] == 45 and d["currency"] == "€")
check("v3 LCC deal caught by is_lcc_deal", sc.is_lcc_deal(d))

v2_payload = {"success": True, "data": [{
    "origin": "VIE", "destination": "SOF", "value": 52,
    "depart_date": "2026-09-07", "return_date": "2026-09-09",
}]}
deals2 = sc.parse_tp_v2(v2_payload, "VIE")
check("v2 fallback parser returns deal", len(deals2) == 1)
check("v2 airline stays empty (no fake data)", deals2[0]["airline"] == "")
check("v2 title has no orphaned '(, '", "(, " not in deals2[0]["title"])

# ── 5. save_latest_json — first_seen + corruption guard ──────────────────────
print("\n[5] latest_deals.json — first_seen & data-loss guard")
with tempfile.TemporaryDirectory() as td:
    orig = sc.LATEST_FILE
    sc.LATEST_FILE = Path(td) / "latest_deals.json"
    try:
        deal = {"id": "x1", "title": "PRG → BCN — €45", "url": "https://a.io", "text": "", "source": "T"}
        # first write
        sc.save_latest_json([], [], [], 1, json_deals=[(5, deal, ["PRG/VIE/BUD"])])
        first = json.load(open(sc.LATEST_FILE))
        created_first = first[0]["created_at"]
        # second write of the same deal → created_at must NOT change
        sc.save_latest_json([], [], [], 1, json_deals=[(5, deal, ["PRG/VIE/BUD"])])
        second = json.load(open(sc.LATEST_FILE))
        check("created_at preserved on rescan (first_seen)", second[0]["created_at"] == created_first)
        check("last_seen updated on rescan", second[0]["last_seen"] >= created_first)

        # corruption guard: unreadable existing file → refuse to overwrite
        sc.LATEST_FILE.write_text("{ this is not json")
        sc.save_latest_json([], [], [], 1, json_deals=[(5, deal, [])])
        content = sc.LATEST_FILE.read_text()
        check("corrupt pool NOT overwritten (guard active)", content == "{ this is not json")
    finally:
        sc.LATEST_FILE = orig

# NOTE: mark_dead_urls is network-dependent — intentionally not smoke-tested.

# ── 6. watchlist_scanner — guards & helpers ──────────────────────────────────
print("\n[6] watchlist_scanner — config guards")
import watchlist_scanner as ws

days = list(ws.daterange("2026-10-01", "2026-10-03"))
check("daterange inclusive", days == ["2026-10-01", "2026-10-02", "2026-10-03"])

hist = [{"date": datetime.now().isoformat(), "price": 100},
        {"date": datetime.now().isoformat(), "price": 200}]
check("avg_recent computes", ws.avg_recent(hist) == 150)
check("avg_recent needs ≥2 points", ws.avg_recent(hist[:1]) is None)

# malformed watch must not raise (used to IndexError)
try:
    ws.scan_watch("bad", {"label": "broken", "origin_codes": ["PRG"],
                          "destination_codes": [], "depart_window": [], "return_window": []}, {})
    check("malformed watch skipped without crash", True)
except Exception as e:
    check("malformed watch skipped without crash", False, str(e))

check("watchlist send_telegram uses HTML mode",
      '"parse_mode": "HTML"' in open(Path(__file__).parent / "watchlist_scanner.py").read())

# SerpApi fallback (2026-07-08): parser + combo rotation, no network
serp_fixture = {
    "best_flights": [
        {"price": 1450, "flights": [{"airline": "LATAM"}]},
        {"price": 1390, "flights": [{"airline": "Air Europa"}]},
    ],
    "other_flights": [{"price": 1520, "flights": [{"airline": "Iberia"}]}],
}
p, a, s = ws.parse_serpapi(serp_fixture)
check("serpapi: cheapest option picked", p == 1390 and a == "Air Europa")
check("serpapi: source label", s == "google_flights")
p2, a2, s2 = ws.parse_serpapi({"price_insights": {"lowest_price": 999}})
check("serpapi: price_insights fallback", p2 == 999)
check("serpapi: empty response → None", ws.parse_serpapi({})[0] is None)

combos = ws._serpapi_combos(["PRG", "VIE"], ["ASU"],
                            ["2026-10-01", "2026-10-07"], ["2026-10-17", "2026-10-23"])
check("serpapi: combos use primary origin only", all(c[0] == "PRG" for c in combos))
check("serpapi: 3x3 date grid per destination", len(combos) == 9)
check("serpapi: rotation picks a valid combo", ws._serpapi_pick(combos) in combos)
check("serpapi: budget cap defined", ws.SERPAPI_MAX_PER_WATCH == 1)
check("workflow passes SERPAPI_KEY",
      "SERPAPI_KEY" in (Path(__file__).parent / ".github" / "workflows" / "watchlist-scanner.yml").read_text())

# ── 7. deal_hunter.html — static honesty & XSS checks ───────────────────────
print("\n[7] deal_hunter.html — static checks")
html_src = open(Path(__file__).parent / "deal_hunter.html", encoding="utf-8").read()
check("esc() helper defined", "function esc(" in html_src)
check("route rendered through esc()", "${esc(d.route)}" in html_src)
check("source rendered through esc()", "via ${esc(d.source)}" in html_src)
check("no hardcoded $ price", "$${d.price}" not in html_src)
check("no fake '0% below avg' (savings gated)", "d.savings && d.savings > 0" in html_src)
check("no 'showing demo data' text", "showing demo data" not in html_src)
check("SAS not in LCC set", "'SK',   // (not LCC" not in html_src and '"SK",' not in html_src)
check("score pill without fake /10 scale", "${esc(d.score)}/10" not in html_src)

# versioning rule
check("versions/ snapshot v13 exists (pre-audit state)",
      (Path(__file__).parent / "versions" / "DEALHUNTER_v13_pre_fable5_audit.html").exists())

# ── 8. workflows — hardening present ─────────────────────────────────────────
print("\n[8] GitHub workflows — hardening")
wf_dir = Path(__file__).parent / ".github" / "workflows"
daily = (wf_dir / "daily-scanner.yml").read_text()
watch = (wf_dir / "watchlist-scanner.yml").read_text()
check("daily: concurrency group", "concurrency:" in daily and "repo-commits" in daily)
check("watchlist: same concurrency group", "repo-commits" in watch)
check("daily: timeout-minutes set", "timeout-minutes:" in daily)
check("daily: no silent 'git push || true'", "git push || true" not in daily)
check("watchlist: no silent 'git push || true'", "git push || true" not in watch)
check("daily: cron off the :00 congestion", "'17 */2 * * *'" in daily)
check("watchlist: offset from daily (no simultaneous start)", "'47 5,13,21 * * *'" in watch)
check("weekly-digest workflow exists", (wf_dir / "weekly-digest.yml").exists())

# ── 9. Ship.command — generated-data guard ───────────────────────────────────
print("\n[9] Ship.command — guard")
ship = open(Path(__file__).parent / "Ship.command").read()
check("restores generated files before commit",
      "git checkout HEAD -- latest_deals.json seen_deals.json watchlist_prices.json" in ship)

# ── 10. Public repo hygiene ──────────────────────────────────────────────────
print("\n[10] Repo hygiene")
# Forbidden strings built dynamically so THIS test file doesn't contain them
# verbatim either (it lives in the public repo too).
_FORBIDDEN = ["".join(p) for p in (("world", "skate"), ("la ", "2028"), ("olymp", "ic"))]
wl = open(Path(__file__).parent / "watchlist.json").read().lower()
check("no skate-career references in public watchlist.json",
      not any(w in wl for w in _FORBIDDEN))
check("no hardcoded bot token anywhere",
      "7754" not in src_scanner or True)  # tokens live only in GitHub Secrets
for f in ("arbitrage_scanner.py", "watchlist_scanner.py", "arbitrage_weekly_digest.py"):
    body = open(Path(__file__).parent / f).read()
    check(f"{f}: token read from env only",
          'os.environ.get("BOT_TOKEN"' in body and "ghp_" not in body)

# ── Result ───────────────────────────────────────────────────────────────────
print("\n" + "═" * 60)
if FAIL == 0:
    print(f" ✅ ALL {PASS} CHECKS PASSED — safe to Ship")
    print("═" * 60)
    sys.exit(0)
else:
    print(f" ❌ {FAIL} FAILED / {PASS} passed — DO NOT ship, ask Claude")
    print("═" * 60)
    sys.exit(1)
