#!/bin/bash
# ═══════════════════════════════════════════════════════════
#  INSTALL WORKFLOWS — jednorázový krok po Fable 5 auditu
#
#  Proč tento soubor existuje: GitHub Actions workflow soubory
#  (.github/workflows/*.yml) mají přístup k secrets, takže je
#  vzdálené nástroje záměrně nesmí zapisovat přímo. Tento skript
#  je zkopíruje z FABLE5_HANDOFF/OUTPUTS/workflows/ — spouštíš
#  ho TY, vědomě, dvojklikem. Pak stačí Ship.command.
# ═══════════════════════════════════════════════════════════

cd "$(dirname "$0")"
clear
echo "Instaluji workflow soubory..."
echo ""

SRC="FABLE5_HANDOFF/OUTPUTS/workflows"
DST=".github/workflows"

if [ ! -d "$SRC" ]; then
    echo "❌ Složka $SRC nenalezena."
    echo "Press Enter to close..."; read; exit 1
fi

mkdir -p "$DST"
for f in daily-scanner.yml watchlist-scanner.yml weekly-digest.yml; do
    if [ -f "$SRC/$f" ]; then
        cp "$SRC/$f" "$DST/$f"
        echo "  ✓ $f"
    else
        echo "  ✗ $f chybí v $SRC"
    fi
done

echo ""
echo "✅ Hotovo. Teď spusť Test.command a pak Ship.command."
echo ""
echo "Press Enter to close..."
read
