#!/bin/bash
# ═══════════════════════════════════════════════════════════
#  SHIP — Deploy changes to GitHub + Vercel automatically
#  Tom Monfret · Arbitrage Life
#
#  Jak to použít:
#    1) Dvojklik na tento soubor v Finderu (nebo z Docku)
#    2) Otevře se Terminal, sám provede push, ukáže výsledek
#    3) Když uvidíš "✅ Shipped!", zavři okno (Cmd+W)
#    4) Vercel auto-deployne do ~30 sekund
#       URL: https://arbitrage-life.vercel.app/deal_hunter.html
# ═══════════════════════════════════════════════════════════

cd "$(dirname "$0")"
clear

echo "═══════════════════════════════════════════════════════════"
echo "   🚀  SHIP — Arbitrage Life"
echo "═══════════════════════════════════════════════════════════"
echo ""

# Step 1 — stash any local edits (safety, won't lose anything)
echo "1/5 ▸ Saving any local edits aside (stash)..."
STASH_OUTPUT=$(git stash --include-untracked 2>&1)
if echo "$STASH_OUTPUT" | grep -q "Saved working"; then
    STASH_CREATED=true
    echo "      ✓ Stash created"
else
    STASH_CREATED=false
    echo "      ✓ Nothing to stash"
fi

# Step 2 — pull latest from GitHub
echo ""
echo "2/5 ▸ Pulling latest from GitHub..."
if ! git pull --rebase origin main 2>&1 | tail -3; then
    echo ""
    echo "❌ Pull failed. Conflict or network issue."
    echo "   Stash kept safe — run 'git stash pop' to restore your edits."
    echo ""
    echo "Press Enter to close..."
    read
    exit 1
fi
echo "      ✓ Up to date with main"

# Step 3 — pop stash if we made one
if [ "$STASH_CREATED" = true ]; then
    echo ""
    echo "3/5 ▸ Restoring your local edits..."
    if ! git stash pop 2>&1 | tail -3; then
        echo ""
        echo "⚠️  Stash pop had conflicts. Your edits are saved in stash."
        echo "   Run 'git stash list' to see, 'git stash apply' to retry."
        echo ""
        echo "Press Enter to close..."
        read
        exit 1
    fi
    echo "      ✓ Edits restored"
else
    echo ""
    echo "3/5 ▸ No stashed edits to restore — skipping"
fi

# Step 3.5 — PROTECT GENERATED DATA (added 2026-07-08, Fable 5 audit)
# latest_deals.json / seen_deals.json / watchlist_prices.json are produced by
# GitHub Actions in the cloud. Local copies on this Mac can be stale or
# degraded (the local backup scanner has no network access) — shipping them
# once overwrote the live 500-deal feed with 6 deals. Never ship local
# versions of these files; GitHub's are always the source of truth.
echo ""
echo "3.5/5 ▸ Protecting generated data files (kept from GitHub)..."
git checkout HEAD -- latest_deals.json seen_deals.json watchlist_prices.json 2>/dev/null
echo "      ✓ latest_deals.json / seen_deals.json / watchlist_prices.json restored from GitHub state"

# Step 4 — stage + commit if there are changes
echo ""
echo "4/5 ▸ Staging + committing changes..."
git add -A
if git diff --staged --quiet; then
    # Fix 2026-07-08 (Fable 5): even with no NEW changes there may be older
    # committed-but-unsent work waiting (e.g. a previous push failed on auth).
    UNPUSHED=$(git rev-list --count origin/main..HEAD 2>/dev/null || echo 0)
    if [ "$UNPUSHED" -gt 0 ]; then
        echo "      ⚠ No new changes, but $UNPUSHED unsent commit(s) waiting — sending now..."
    else
        echo "      ✓ Nothing to ship — local state matches remote"
        echo ""
        echo "═══════════════════════════════════════════════════════════"
        echo "   No new changes detected. Already up to date."
        echo "═══════════════════════════════════════════════════════════"
        echo ""
        echo "Press Enter to close..."
        read
        exit 0
    fi
else
    TIMESTAMP=$(date '+%Y-%m-%d %H:%M')
    git commit -m "Update — $TIMESTAMP" > /dev/null
    CHANGED=$(git diff --stat HEAD~1 HEAD | tail -1)
    echo "      ✓ Committed: $CHANGED"
fi

# Step 5 — push to GitHub
echo ""
echo "5/5 ▸ Pushing to GitHub..."
if ! git push 2>&1 | tail -3; then
    echo ""
    echo "❌ Push failed. Check network or credentials."
    echo "   Your commit is local — try again later with this script."
    echo ""
    echo "Press Enter to close..."
    read
    exit 1
fi

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "   ✅  SHIPPED!"
echo ""
echo "   Vercel will auto-deploy in ~30 seconds."
echo "   URL: https://arbitrage-life.vercel.app/deal_hunter.html"
echo ""
echo "   Refresh your mobile bookmark to see changes."
echo "═══════════════════════════════════════════════════════════"
echo ""
echo "Closing in 5 seconds..."
sleep 5
