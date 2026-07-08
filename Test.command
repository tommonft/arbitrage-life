#!/bin/bash
# ═══════════════════════════════════════════════════════════
#  TEST — Smoke testy pro Arbitrage Life
#  Tom: dvojklik → proběhnou kontroly → ✅ = můžeš pustit Ship.command
#  Nic neposílá, nic nemaže, nepotřebuje internet ani hesla.
# ═══════════════════════════════════════════════════════════

cd "$(dirname "$0")"
clear
python3 smoke_test.py
echo ""
echo "Press Enter to close..."
read
