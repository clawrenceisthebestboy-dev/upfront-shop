# Up Front Shop

A Windows-native shop-management app for **Up Front Auto Repair** (Standish, ME). Built to replace QuickBooks for day-to-day estimates, invoices, inventory, time-clock, and monthly Profit & Loss reporting.

## What it does

**Jobs, estimates, invoices.** Create an estimate, itemize parts and labor, print it, then convert to an invoice when the work is approved. Every line shows internal cost, customer-facing price, line profit, and taxable flag.

**Tiered parts markup** (customer-facing). The app automatically marks up every part using the shop's tiered table:

| Cost band        | Multiplier | Approx. profit |
|------------------|-----------:|---------------:|
| $0 – $2.50       |   × 4.00   |     75.0 %     |
| $2.51 – $5.00    |   × 3.75   |     73.3 %     |
| $5.01 – $10.00   |   × 3.00   |     66.7 %     |
| $10.01 – $50.00  |   × 2.75   |     63.6 %     |
| $50.01 – $100.00 |   × 2.50   |     60.0 %     |
| $100.01 – $150.00|   × 2.20   |     54.5 %     |
| $150.01 – $200.00|   × 2.00   |     50.0 %     |
| $200.01 – $500.00|   × 1.85   |     46.0 %     |
| $500.01 and up   |   × 1.70   |     41.2 %     |

Enter the shop cost on any part line and the customer-facing price auto-fills from this table. **You can still override any price on any estimate or invoice.** The tiers themselves are editable in **Settings → Parts Markup** — you type the **target profit %** you want on each cost band (e.g. `63.6`) and the app derives the multiplier automatically.

**Labor rate** is editable per line. The shop default labor rate lives in **Settings → Rates & Defaults** and is filled in automatically when a new labor line is added, but you can change it on any individual job.

**Maine sales tax** (5.5 %) is applied only to taxable lines (parts); labor is not taxed.

**Payment methods** (updated April 2026)

Every estimate and invoice automatically includes a **3.5 % non-cash adjustment** across the entire invoice. That amount is disclosed as its own line on the printed invoice. Customers paying with **cash or check** receive a matching **3.5 % discount** that cancels the adjustment.

- **Card** — customer pays the listed (adjusted) total.
- **Check** — the 3.5 % discount is applied; customer pays the pre-adjustment total.
- **Cash** — the 3.5 % discount is applied, the invoice is printed stamped **PAID**, and the job is **deleted from the database** per shop policy. The printed PAID copy is the only record afterward — keep it in the safe.
- **Unpaid** — open invoice / estimate. The PDF still shows the adjustment so the sticker price is transparent.

**Inventory & vendors.** Parts list with SKU, description, vendor, shop cost, auto-computed sell price, on-hand, reorder point, and a warning flag when stock drops below reorder. Parts consumed by a paid invoice are decremented automatically.

**Customers & vehicles.** Full CRUD with search. Each vehicle tracks year/make/model/trim, VIN, plate, color, mileage, inspection sticker expiration, and notes.

**Time clock.** Techs clock in/out against a job with an hourly wage; the clocked time feeds into the labor-cost side of the monthly P&L.

**Reminders.** Upcoming inspections, oil changes, follow-ups. "Scan vehicles for inspection expiration" creates reminders automatically for any vehicle with a sticker expiring in the next 60 days.

**Monthly Profit & Loss.** Generate a month's P&L PDF with parts profit and labor profit **broken out separately** (Josh's requirement — parts profit from markup vs. labor profit from timeclocked wages). Enter cash sales externally since cash jobs are deleted from the DB after printing.

**Printing.** Regular 8.5×11 PDF invoices sent to any WiFi / network printer the Windows laptop can see. Pick the printer in **Settings → Printer**, or leave it on *(system default)*.

## Installing on the shop laptop

1. Download **UpFrontShopSetup.exe** from the release ZIP (see below).
2. Double-click it, click through the installer (admin prompt once).
3. Start menu → "Up Front Shop". The app will create its SQLite database at
   `%APPDATA%\UpFrontShop\shop.db` on first launch.
4. Open **Settings → Printer**, pick the shop's WiFi printer, click **Save**.
5. Open **Settings → Shop Info** and confirm phone / address / footer on the invoice.

That's it — you can create a new estimate from the **Jobs / Invoices** tab.

### Where the data lives

| Thing                  | Path                                        |
|------------------------|---------------------------------------------|
| SQLite database        | `%APPDATA%\UpFrontShop\shop.db`             |
| Generated PDFs         | `%APPDATA%\UpFrontShop\invoices\`           |

To back up: copy the `%APPDATA%\UpFrontShop\` folder to a USB stick or OneDrive.

## Developing / building from source

### Run locally (any OS, for dev)

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

Unit tests (no GUI required):

```bash
python -m unittest discover -s tests -v
```

### Build the Windows installer

Build on a Windows 10/11 box with:

- **Python 3.11 or 3.12** (64-bit) on PATH
- **Inno Setup 6** — [https://jrsoftware.org/isdl.php](https://jrsoftware.org/isdl.php)

Then from a Command Prompt:

```bat
cd upfront-shop
build\build.bat
```

After the script finishes you'll have:

- `dist\UpFrontShop\UpFrontShop.exe` — portable app folder (zip and copy anywhere)
- `dist\UpFrontShopSetup.exe` — the **one-file installer** you can host on a web link for Josh to download on the shop laptop off-site.

Drop `UpFrontShopSetup.exe` into any file host (Google Drive, Dropbox, your website) and share the download link.

## Project layout

```
upfront-shop/
├── main.py                     # Qt entry point
├── requirements.txt
├── app/
│   ├── db.py                   # SQLite schema + settings
│   ├── repo.py                 # CRUD helpers
│   ├── markup.py               # Tiered markup table
│   ├── tax.py                  # Maine sales tax
│   ├── pricing.py              # Line-item math, totals, surcharge/discount
│   ├── reports.py              # Monthly P&L (parts vs. labor profit)
│   ├── invoice_pdf.py          # ReportLab invoice / estimate / PAID
│   ├── printer.py              # Windows print (Shell verb + SumatraPDF)
│   └── ui/
│       ├── main_window.py
│       ├── jobs_tab.py
│       ├── job_editor.py
│       ├── customers_tab.py
│       ├── inventory_tab.py
│       ├── timeclock_tab.py
│       ├── reports_tab.py
│       ├── reminders_tab.py
│       ├── settings_tab.py
│       └── widgets.py
├── tests/
│   └── test_core.py            # 14 unit tests
└── build/
    ├── upfront.spec            # PyInstaller
    ├── installer.iss           # Inno Setup
    └── build.bat               # one-shot Windows build
```

## Policy notes baked into the app

- **Cash-paid invoices are deleted from the database** after printing and inventory decrement. The paper copy is the only record (shop policy). Monthly cash totals are entered manually on the P&L tab.
- **Maine sales tax applies to parts only.** Labor lines are not taxed.
- **Non-cash adjustment** of 3.5 % is added after tax on every invoice automatically. **Cash or check payment** earns a matching 3.5 % discount that cancels the adjustment. Both rates are editable in Settings → Rates & Defaults.
- **Inventory** is decremented only when an invoice is marked paid (card/check) or closed out in cash.
