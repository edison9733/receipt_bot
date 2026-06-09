# 🧾 Telegram Receipt Bot — Malaysian Tax Edition

> **Author:** [@edison9733](https://github.com/edison9733) &nbsp;•&nbsp; **Sponsored by Brainard** 💚

Snap a receipt in Telegram. The bot reads it, decides if it's a **tax Relief** or a
general **Expense**, files the photo into the matching **Google Drive** folder, and
logs a tidy row into the right **Google Sheets** tab — auto-totalled for your **LHDN
Form B / Form BE** filing.

```
  📲 Telegram photo
        │
        ▼
  🔍 OCR (Tesseract)  ──►  🧠 DeepSeek AI: Relief vs Expense + category + amounts
        │
        ├──►  📁 Google Drive   →  Receipts / {Relief|Expenses} / {Category}/receipt.jpg
        └──►  📊 Google Sheets   →  Relief tab  •  Expenses tab  •  auto Summary
```

Everything lands in **your own** Google account (you stay the owner of every file).
The tax-relief categories are **fact-checked line-by-line** against the official
LHDN YA 2025 list — see the [reference table](#-tax-relief-reference-ya-2025-fact-checked).

---

## ✨ What it does

- **One tap.** Send a photo; get back a clean summary in seconds.
- **AI sorting.** DeepSeek classifies Relief vs Expense and picks the exact category.
- **Auto-filed in Drive.** Two-level folders: `Relief/Medical…`, `Expenses/Food & Beverage…`.
- **Auto-totalled Sheet.** A Summary tab sums each category and shows relief left to claim.
- **Auto-growing rows.** Long text wraps and the row grows in height — never overflows neighbours.
- **Most-used first.** Dropdowns are ordered common → rare, so you never scroll.
- **Runs forever.** A `systemd` service keeps it alive across reboots.
- **No secrets in the repo.** OAuth keys and tokens stay on your machine only.

---

## ✅ What you'll need (one-time accounts)

| You need | Where | Cost |
|---|---|---|
| A Mac | for OrbStack (or any Linux server — see [alt](#-alternative-run-on-a-cloud-server)) | — |
| Telegram account | the app you already use | free |
| Google account | Sheets + Drive | free |
| DeepSeek API key | <https://platform.deepseek.com> | a few cents/month (optional*) |

\*Without a DeepSeek key the bot still runs using an offline keyword fallback — just less accurate.

> Throughout this guide: **On your Mac:** = run in macOS Terminal. **Inside the VM:** =
> run after you've opened the Linux machine with `orb -m receiptbot`.

---

## Part 1 — 🤖 Telegram bot token

1. Open Telegram and search for **@BotFather**.
2. Send `/newbot`, pick a name and a username ending in `bot`.
3. BotFather replies with a token like `123456789:AA...`. **Copy it** → this is your `TELEGRAM_TOKEN`.

---

## Part 2 — 🧠 DeepSeek API key *(recommended, optional)*

1. Sign up at <https://platform.deepseek.com>.
2. Add a little credit (classification costs ~RM0.01 per receipt).
3. Go to **API Keys → Create**, copy the `sk-...` key → this is your `DEEPSEEK_API_KEY`.

---

## Part 3 — ☁️ Google Cloud project (OAuth keys)

This lets the bot write to *your* Drive and Sheets. All in the browser:

1. Go to <https://console.cloud.google.com> → **Create Project** → name it `ReceiptBot`.
2. **Enable APIs.** Open **APIs & Services → Library**, then enable both:
   - **Google Drive API**
   - **Google Sheets API**
3. **Consent screen.** Go to **APIs & Services → OAuth consent screen**:
   - User type: **External** → Create.
   - App name `ReceiptBot`, your email for support + developer fields → Save.
   - **Audience / Test users → Add users →** add **your own Gmail**. (Keeps it in "Testing"; that's fine forever.)
4. **Create the key.** Go to **APIs & Services → Credentials → Create Credentials → OAuth client ID**:
   - Application type: **Desktop app** → Create.
   - Click **Download JSON**. Rename the file to **`client_secret.json`** and keep it handy.

> 🔒 `client_secret.json` is a secret. Never commit it. The `.gitignore` already blocks it.

---

## Part 4 — 📊 Create the Google Sheet (get `SHEET_ID`)

1. Go to <https://sheets.new> → a blank spreadsheet opens.
2. Rename it `Receipt Tracker` (top-left).
3. Look at the URL: `docs.google.com/spreadsheets/d/`**`THIS_LONG_ID`**`/edit`.
4. **Copy that ID** → this is your `SHEET_ID`. (Leave the sheet empty — `setup_sheets.py` builds it later.)

---

## Part 5 — 📁 Create the Google Drive folder (get `DRIVE_FOLDER_ID`)

1. Go to <https://drive.google.com> → **New → New folder** → name it `Receipts`.
2. Double-click to open it.
3. Look at the URL: `drive.google.com/drive/folders/`**`THIS_ID`**.
4. **Copy that ID** → this is your `DRIVE_FOLDER_ID`.

You now have **5 values** copied: `TELEGRAM_TOKEN`, `DEEPSEEK_API_KEY`, `SHEET_ID`,
`DRIVE_FOLDER_ID`, and the `client_secret.json` file. Keep them for Part 9.

---

## Part 6 — 🐳 Install OrbStack + create the Linux VM

OrbStack runs a fast, lightweight Linux machine on your Mac.

**Install OrbStack on your Mac:**
```bash
brew install orbstack
```
*(No Homebrew? Download from <https://orbstack.dev> and drag to Applications.)*

**Create an Ubuntu machine named `receiptbot`:**
```bash
orb create ubuntu receiptbot
```

**Open a shell inside that machine:**
```bash
orb -m receiptbot
```
Your prompt changes — you're now **inside the VM**. Everything below runs here.

---

## Part 7 — ⚙️ Install the bot inside the VM

**Update the package list:**
```bash
sudo apt update
```

**Install Python, Git, and the OCR engine:**
```bash
sudo apt install -y python3-venv python3-pip git tesseract-ocr
```

**Download the bot into `~/receiptbot`:**
```bash
git clone https://github.com/edison9733/receipt_bot.git ~/receiptbot
```

**Go into the folder:**
```bash
cd ~/receiptbot
```

**Create an isolated Python environment:**
```bash
python3 -m venv venv
```

**Turn the environment on:**
```bash
source venv/bin/activate
```

**Install all Python dependencies:**
```bash
pip install -r requirements.txt
```

---

## Part 8 — 🔑 One-time Google login (creates `token.json`)

**Copy your OAuth key from the Mac into the VM:**
```bash
cp /Users/$USER/Downloads/client_secret.json ~/receiptbot/
```
*(OrbStack shares your Mac files. If your Mac/VM usernames differ, use the full Mac path.)*

**Start the one-time login:**
```bash
python authorize.py
```

It prints a URL. **Open that URL in your Mac's browser**, sign in, and approve Drive +
Sheets access. OrbStack forwards the login port automatically, so it just works. When it
says *"authentication flow has completed,"* it has written **`token.json`** — you never log
in again (it auto-refreshes).

---

## Part 9 — 📝 Configure your secrets (`/etc/receiptbot.env`)

**Copy the template into place:**
```bash
sudo cp ~/receiptbot/receiptbot.env.template /etc/receiptbot.env
```

**Auto-fix the file paths to your username:**
```bash
sudo sed -i "s/apple/$USER/g" /etc/receiptbot.env
```

**Open it and paste your 4 values:**
```bash
sudo nano /etc/receiptbot.env
```
Fill in `TELEGRAM_TOKEN`, `DEEPSEEK_API_KEY`, `SHEET_ID`, `DRIVE_FOLDER_ID`.
Save with **Ctrl-O, Enter**, exit with **Ctrl-X**.

**Lock the file down (it holds secrets):**
```bash
sudo chmod 600 /etc/receiptbot.env
```

---

## Part 10 — 🏗️ Build the Google Sheet (run once)

**Load your settings, then build the three tabs:**
```bash
set -a && source /etc/receiptbot.env && set +a && python setup_sheets.py
```

It prints a link and creates the **Expenses**, **Relief**, and **Summary** tabs —
colour-coded, with dropdowns and auto-totals. Re-runnable any time (it's idempotent).

---

## Part 11 — 🧪 Test it

**Run the bot in the foreground:**
```bash
set -a && source /etc/receiptbot.env && set +a && python bot.py
```

Now open Telegram, message your bot `/start`, then **send a receipt photo**. Watch it
reply with a summary, appear in your Sheet, and file the image in Drive.
Press **Ctrl-C** to stop the test.

---

## Part 12 — ♾️ Run forever (auto-start on boot)

**Install the background service:**
```bash
sudo cp ~/receiptbot/receiptbot.service /etc/systemd/system/receiptbot.service
```

**Auto-fix the username in the service:**
```bash
sudo sed -i "s/apple/$USER/g" /etc/systemd/system/receiptbot.service
```

**Tell systemd to read the new file:**
```bash
sudo systemctl daemon-reload
```

**Start it now and on every boot:**
```bash
sudo systemctl enable --now receiptbot
```

**Check it's running:**
```bash
systemctl status receiptbot
```

**Watch live logs (Ctrl-C to leave):**
```bash
journalctl -u receiptbot -f
```

🎉 **Done.** Send receipts any time — the bot is always on.

---

## 📲 Daily usage

- `/start` — welcome message.
- `/help` — quick help.
- **Send a photo** (or an image file) of any receipt → it's OCR'd, classified, filed, and logged.
- Open your Google Sheet → the **Summary** tab shows totals and how much relief you have left.

---

## 📚 Tax relief reference (YA 2025, fact-checked)

Verified line-by-line on **2026-06-09** against the official LHDN
*"Tax Relief — Resident Individual, Year Assessment 2025"* infographic
(updated 19 Jan 2026):

- 📄 <https://www.hasil.gov.my/media/muob0jyz/tax-relief-ya-2025.pdf>
- 🔗 <https://www.hasil.gov.my/en/individual/individual-life-cycle/income-declaration/tax-reliefs/>

These personal reliefs apply to **both Form B (business income)** and **Form BE
(employment)** — they're identical; Form B simply adds business sections on top.
Categories are listed **most-used → least-used** (matching the bot's dropdowns).

| # | Relief category | Max (RM) | Notes |
|--:|---|--:|---|
| 1 | Lifestyle (Books / Computer / Internet) | 2,500 | books, PC/phone/tablet, internet, self-dev courses |
| 2 | Medical (Self / Spouse / Child) | 10,000 | serious illness, fertility, vaccination, dental |
| 3 | Life Insurance + EPF | 7,000 | private: EPF ≤4,000 + life ≤3,000; pensioner: life ≤7,000 |
| 4 | SOCSO / EIS | 350 | PERKESO (SOCSO + EIS combined) |
| 5 | Self Education Fees | 7,000 | tertiary; upskilling courses sub-capped at 2,000 |
| 6 | Sports Equipment & Activities | 1,000 | gear, facility/competition fees, gym membership |
| 7 | Education & Medical Insurance | 4,000 | self / spouse / child |
| 8 | PRS / Deferred Annuity | 3,000 | Private Retirement Scheme + deferred annuity |
| 9 | Medical Check-up / Mental Health | 1,000 | **sub-limit inside** the 10,000 Medical cap |
| 10 | Parents / Grandparents Medical | 8,000 | treatment/care; full check-up sub-limit 1,000 |
| 11 | Childcare / Kindergarten | 3,000 | TASKA/TADIKA, child ≤6, shared by spouses |
| 12 | SSPN Net Deposit | 8,000 | net savings, shared by spouses |
| 13 | EV Charging / Food Waste Composter | 2,500 | home EV charger + composting machine |
| 14 | Breastfeeding Equipment | 1,000 | female taxpayer, child ≤2, once per 2 years |
| 15 | First Home Loan Interest | 7,000 | house ≤500k: 7,000; 500k–750k: 5,000 (SPA 2025–2027) |
| 16 | Child Below 18 | 2,000 | per unmarried child under 18 |
| 17 | Child 18+ in Education | 8,000 | diploma+ (MY) / degree+ (overseas); else 2,000 |
| 18 | Spouse / Alimony | 4,000 | spouse with no income / alimony paid |
| 19 | Self / Individual Relief | 9,000 | automatic (individual & dependent relatives) |
| 20 | Disabled Individual | 7,000 | additional, OKU-certified self |
| 21 | Disabled Spouse | 6,000 | additional, disabled husband/wife |
| 22 | Disabled Child | 8,000 | +8,000 more if 18+ in diploma+/degree+ study |
| 23 | Basic Support Equipment (Disabled) | 6,000 | for disabled self/spouse/child/parent |
| 24 | Child Disability Assessment / Early Intervention | 6,000 | **sub-limit inside** the 10,000 Medical cap (child ≤18) |
| — | Other Relief | no cap | catch-all bucket for anything else |

> ⚠️ **Not tax advice.** Limits and rules change — always confirm on
> [hasil.gov.my](https://www.hasil.gov.my) or with a licensed tax agent before filing.
> To change a category or amount, edit **`categories.py`** only (it's the single source of
> truth), then re-run `setup_sheets.py`.

---

## 🔁 Updating the bot later

**Inside the VM:**
```bash
cd ~/receiptbot && git pull && source venv/bin/activate && pip install -r requirements.txt
```

**Restart the service to load changes:**
```bash
sudo systemctl restart receiptbot
```

If you edited categories, rebuild the Sheet:
```bash
set -a && source /etc/receiptbot.env && set +a && python setup_sheets.py
```

---

## 🆘 Troubleshooting

| Symptom | Fix |
|---|---|
| Bot doesn't reply | `systemctl status receiptbot` and `journalctl -u receiptbot -f` to see the error. |
| `SHEET_ID is not set` | You forgot to load env. Use the full `set -a && source … && python …` command. |
| `client_secret.json not found` | Re-copy it into `~/receiptbot/` (Part 8). |
| OCR returns nothing | Use a sharper, well-lit photo; confirm `tesseract --version` works. |
| Drive `get()` 404 in logs | Harmless — the `drive.file` scope can't *read* your folder's metadata but *can* file into it. |
| Categories look wrong | Edit `categories.py`, then re-run `setup_sheets.py`. |
| Token expired / revoked | Delete `token.json` and re-run `python authorize.py`. |

---

## 🔐 Security notes

- **Never commit** `client_secret.json`, `token.json`, `service_account.json`, or your real
  `/etc/receiptbot.env`. The included [`.gitignore`](.gitignore) blocks all of them.
- The bot uses the **least-privilege** `drive.file` scope — it can only touch files **it**
  creates, never the rest of your Drive.
- To restrict who can use the bot, set `AUTHORIZED_USERS` (comma-separated Telegram user IDs)
  in `/etc/receiptbot.env`. Leave it unset = anyone who finds the bot can use it.
- `chmod 600` on `token.json` and `/etc/receiptbot.env` keeps them readable only by you.

---

## ☁️ Alternative: run on a cloud server

No Mac? The exact same steps work on any Ubuntu/Debian VPS (DigitalOcean, AWS, etc.) —
**skip Part 6**, SSH into your server, and start at **Part 7**. For the one-time login in
Part 8, run `authorize.py` on any computer with a browser, then copy the resulting
`token.json` up to the server's `~/receiptbot/` folder.

---

## 🗂️ What's in this repo

| File | Purpose |
|---|---|
| `bot.py` | The Telegram bot: OCR → classify → Drive → Sheets. |
| `categories.py` | **Single source of truth** for all categories & relief limits. |
| `setup_sheets.py` | Builds/rebuilds the colour-coded Google Sheet (run once). |
| `authorize.py` | One-time Google login that writes `token.json`. |
| `requirements.txt` | Pinned Python dependencies. |
| `receiptbot.service` | systemd unit to run the bot 24/7. |
| `receiptbot.env.template` | Copy to `/etc/receiptbot.env` and fill in your secrets. |
| `.gitignore` | Keeps every secret out of Git. |

---

## 🙌 Credits

- **Author:** [@edison9733](https://github.com/edison9733)
- **Sponsored by Brainard** 

---

## 📄 License & disclaimer

Provided as-is for personal use. This tool helps you **organise** receipts; it is **not**
tax, accounting, or legal advice. You are responsible for the accuracy of your own LHDN
filing. Always verify current reliefs at <https://www.hasil.gov.my>.
