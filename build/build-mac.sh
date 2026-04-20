#!/usr/bin/env bash
# Up Front Shop — macOS local build script.
#
# Produces:
#   dist/UpFrontShop.app
#   dist/UpFrontShop-1.4.0.dmg
#
# Requirements (install once):
#   brew install create-dmg
#   python3.12 -m venv .venv && source .venv/bin/activate
#   pip install -r requirements.txt pyinstaller==6.9.0
#
# Usage:
#   bash build/build-mac.sh
#
# CI (GitHub Actions) runs the equivalent steps in .github/workflows/build-macos.yml.

set -euo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$HERE"

echo "==> Running unit tests"
python -m unittest discover -s tests -v

echo "==> Building UpFrontShop.app with PyInstaller"
pyinstaller --clean --noconfirm build/upfront-mac.spec

APP="$HERE/dist/UpFrontShop.app"
if [[ ! -d "$APP" ]]; then
  echo "ERROR: $APP not produced" >&2
  exit 1
fi
echo "    -> $APP"

DMG="$HERE/dist/UpFrontShop-1.4.0.dmg"
rm -f "$DMG"

echo "==> Building $(basename "$DMG")"
if command -v create-dmg >/dev/null 2>&1; then
  create-dmg \
    --volname "Up Front Shop" \
    --window-size 540 360 \
    --icon-size 100 \
    --icon "UpFrontShop.app" 140 180 \
    --app-drop-link 400 180 \
    --no-internet-enable \
    "$DMG" \
    "$APP"
else
  # Fallback: plain hdiutil DMG. Still drag-to-Applications compatible, just
  # without the pretty background.
  STAGING="$(mktemp -d)"
  cp -R "$APP" "$STAGING/"
  ln -s /Applications "$STAGING/Applications"
  hdiutil create -volname "Up Front Shop" -srcfolder "$STAGING" \
    -ov -format UDZO "$DMG"
  rm -rf "$STAGING"
fi

echo "==> Computing SHA-256"
shasum -a 256 "$DMG" | tee "$DMG.sha256.txt"

echo "Done."
echo "  App: $APP"
echo "  DMG: $DMG"
