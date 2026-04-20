# Up Front Shop — macOS DMG Build Guide

This is the Mac companion to `GITHUB-BUILD-GUIDE.md`. The workflow file
`.github/workflows/build-macos.yml` is already wired up; all you have to do is
make sure it runs and download the DMG.

## What you'll get

After a successful run, the Actions page will have an artifact named
**`UpFrontShop-macOS-arm64`** containing:

- `UpFrontShop-1.4.0-arm64.dmg` — drag-to-Applications installer
- `UpFrontShop-1.4.0-arm64.dmg.sha256.txt` — hash for verification

The DMG is an **Apple Silicon** build (M1 / M2 / M3 / M4). It will not run on
Intel Macs.

## Install on your Mac

1. Double-click `UpFrontShop-1.4.0-arm64.dmg`. Finder opens the disk image.
2. Drag **Up Front Shop** onto the **Applications** folder shortcut.
3. Eject the disk image.
4. Open Applications → Up Front Shop.

### First launch — bypass Gatekeeper

Because the DMG is not signed with an Apple Developer ID, macOS will say
"UpFrontShop cannot be opened because the developer cannot be verified."
That's a one-time thing:

1. Open Finder → Applications.
2. **Right-click** Up Front Shop → **Open**.
3. Click **Open** in the dialog.

After that, regular double-clicks work forever.

If you ever want Gatekeeper to stop warning entirely, get an Apple Developer ID
($99/yr), set the `APPLE_ID` / `APPLE_TEAM_ID` / `APPLE_APP_PASSWORD` secrets
on GitHub, and uncomment the codesign/notarize steps in `build-macos.yml`.
(Not done today — Josh is running it himself on his own Mac.)

## Picking the printer

Up Front Shop prints through the Mac's CUPS system:

1. Add your shop printer in **System Settings → Printers & Scanners**. If it's
   on WiFi, macOS usually finds it via Bonjour on its own.
2. In Up Front Shop, go to the **Settings** tab.
3. Click **Refresh list** in the "Receipt / invoice printer" box. Every printer
   you added in System Settings shows up here.
4. Pick your shop printer. Click **Save**.

## Where your shop data lives on macOS

- Database: `~/Library/Application Support/UpFrontShop/shop.db`
- Logo & assets: `~/Library/Application Support/UpFrontShop/assets/`
- Invoice PDFs: `~/Library/Application Support/UpFrontShop/invoices/`

To back up: copy that whole `UpFrontShop/` folder.

## Running a local build (optional, if you prefer not to use GitHub Actions)

If you'd rather build on your Mac directly:

```bash
# One-time setup
brew install create-dmg
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt pyinstaller==6.9.0

# Build
bash build/build-mac.sh
```

The script produces `dist/UpFrontShop.app` and `dist/UpFrontShop-1.4.0.dmg`.
