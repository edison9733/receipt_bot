# 🧾 Telegram Receipt Bot — Malaysian Tax Edition

> **Author:** [@edison9733](https://github.com/edison9733) &nbsp;•&nbsp; **Sponsored by Brainard**

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

**One hosted bot, many users.** Each person connects **their own** Google account and
pastes **their own** DeepSeek key — every file lands in *their* Drive, owned by *them*.
No install, no VM, no copying IDs. The tax-relief categories are **fact-checked
line-by-line** against the official LHDN YA 2025 list — see the
[reference table](#-tax-relief-reference-ya-2025-fact-checked).

---

> ### 📌 Scope of This Tool — Year of Assessment (YA) 2025
>
> This tool is designed exclusively to assist with the **organisation and categorisation
> of receipts for the Year of Assessment (YA) 2025**, which covers the basis period
> **1 January 2025 to 31 December 2025**. It supports the preparation of the Malaysian
> individual income tax return submitted to the **Inland Revenue Board of Malaysia
> (IRBM / Lembaga Hasil Dalam Negeri, LHDN)** in **2026** via the
> **MyTax e-Filing portal** at [mytax.hasil.gov.my](https://mytax.hasil.gov.my).
>
> | Form | Applicable to | e-Filing deadline |
> |---|---|---|
> | **Form B** | Individuals with business or self-employment income | **30 June 2026** |
> | **Form BE** | Individuals with employment income only | **30 April 2026** |
>
> All tax-relief categories and limits implemented in this tool reflect the **YA 2025
> schedule** as published by LHDN under the Income Tax Act 1967 (ITA 1967). This tool
> is **not applicable** to YA 2024 or any prior year of assessment.
>
> 🗄️ **Record retention:** LHDN requires supporting documents (receipts, invoices) to be
> kept for **7 years** from the end of the year of assessment. Keeping the original images
> in Google Drive helps you meet this obligation.

---

## ✨ What it does

- **One tap.** Send a photo; get back a clean summary in seconds.
- **AI sorting.** DeepSeek classifies Relief vs Expense and picks the exact category.
- **Auto-filed in Drive.** Two-level folders: `Relief/Medical…`, `Expenses/Food & Beverage…`.
- **Auto-totalled Sheet.** A Summary tab sums each category and shows relief left to claim.
- **Auto-growing rows.** Long text wraps and the row grows in height — never overflows neighbours.
- **Most-used first.** Dropdowns are ordered common → rare, so you never scroll.
- **One command to start.** `docker run ...` is the entire install — baked-in OCR (Tesseract), auto-generated encryption key, Google OAuth client already baked in by the operator. No OrbStack, no VM, no Python.
- **Your data stays yours.** Files are created in *your* Google account; the bot only ever
  touches files **it** created (least-privilege `drive.file` scope). Stored secrets are
  **encrypted at rest** on your own machine's named Docker volume.

---

## 🚀 Quickstart — one command

> ### Install
>
> **Prerequisite:** Install **Docker Desktop** → https://www.docker.com/products/docker-desktop/ — open it once and leave it running.
>
> ---
>
> **1. Create your Telegram bot.** In Telegram, open **@BotFather**, then send:
> ```
> /newbot
> ```
> Reply with any name, then a username ending in `bot`. Copy the token it gives you (looks like `123456789:AAE...`).
>
> ---
>
> **2. Start the bot.** Paste this into Terminal (macOS/Linux) or PowerShell (Windows), replacing `PASTE_TELEGRAM_TOKEN`:
> ```
> docker run -d --name receiptbot --restart unless-stopped --pull always -p 8080:8080 -v receiptbot:/app/data -e TELEGRAM_TOKEN=PASTE_TELEGRAM_TOKEN ghcr.io/edison9733/receipt-bot:latest
> ```
>
> ---
>
> **3. Connect Google.** In Telegram, message **your new bot**:
> ```
> /start
> ```
> ```
> /connect
> ```
> Tap the link → choose your Google account → **Continue** past the "Google hasn't verified this app" screen → **Allow**.
>
> ---
>
> **4. Add your DeepSeek key.** Get one at https://platform.deepseek.com (sign in → **API keys** → **Create**). Then in Telegram send:
> ```
> /setkey sk-PASTE_DEEPSEEK_KEY
> ```
>
> ---
>
> **Done.** Send a receipt photo.
>
> **Update later:** rerun the command in step 2 (it auto‑pulls the newest version; your data is kept).
>
> **Stop / remove:** `docker rm -f receiptbot`

**Even shorter — installer scripts** (verify Docker is running, prompt for token, start the container):
- macOS / Linux: `curl -fsSL https://raw.githubusercontent.com/edison9733/receipt_bot/main/install.sh | bash`
- Windows PowerShell: `irm https://raw.githubusercontent.com/edison9733/receipt_bot/main/install.ps1 | iex`

> No DeepSeek key? The bot still runs with an offline keyword fallback (just less accurate).
> You can add one any time with `/setkey`.

### 📲 Commands

| Command | What it does |
|---|---|
| `/start` | Welcome + where you are in setup. |
| `/connect` | Link your Google account; auto-creates your sheet + folder. |
| `/setkey sk-...` | Save your DeepSeek key (encrypted; the message is deleted). |
| `/status` | Show your connection, sheet link, and key status. |
| `/disconnect` | Revoke Google access and erase your stored data. |
| *(send a photo)* | OCR → classify → file in Drive → log to your Sheet. |

---

## 🛠️ Host it yourself (one-time, for operators)

You do a small **one-time** setup *once, ever* — then any number of users just `/connect`
and `/setkey`. Nothing here is per-user.

### What you'll need

| You need | Where | Cost |
|---|---|---|
| Telegram bot token | [@BotFather](https://t.me/BotFather) | free |
| A Google Cloud project + **Web** OAuth client | <https://console.cloud.google.com> | free |
| A managed host with HTTPS + a volume | Railway / Render / Fly.io / Cloud Run | ~a few $/mo (free tiers exist) |
| A DeepSeek key *(optional, shared)* | <https://platform.deepseek.com> | a few cents/receipt |

### 1 — Telegram bot token
In Telegram, message **@BotFather** → `/newbot` → pick a name + a username ending in `bot`.
Copy the `123456789:AA…` token → this is `TELEGRAM_TOKEN`.

### 2 — Google Cloud project + OAuth client (the only "real" step)
All in the browser at <https://console.cloud.google.com>:

1. **Create a project** → name it `ReceiptBot`.
2. **Enable APIs** (APIs & Services → Library): enable **Google Drive API** *and*
   **Google Sheets API**. *(The bot calls the Sheets API to build the sheet, so it must be
   enabled — but the only OAuth **scope** you request is the non-sensitive `drive.file`.)*
3. **OAuth consent screen** (APIs & Services → OAuth consent screen):
   - User type **External** → Create.
   - Fill app name + your support/developer emails.
   - **Scopes → Add** the single scope `…/auth/drive.file` (it's listed as *non-sensitive*).
   - **Publish app → "In production".** ⚠️ Leaving it in *Testing* makes Google **revoke every
     refresh token after 7 days** — users would have to reconnect weekly. Publishing fixes that.
     Unverified + in production works fine for **personal-use apps under 100 users** (users just
     click through a one-time *"Google hasn't verified this app"* screen). Because you only use
     the non-sensitive `drive.file` scope, removing that warning later is the **light**
     verification path — no costly CASA security audit.
4. **Create credentials → OAuth client ID → Application type: Web application.**
   - Under **Authorized redirect URIs**, add exactly: `https://YOUR-HOST/oauth2callback`
     (must match your `BASE_URL`).
   - Copy the **Client ID** → `GOOGLE_CLIENT_ID` and **Client secret** → `GOOGLE_CLIENT_SECRET`.

### 3 — Generate an encryption key
Secrets (Google refresh tokens + DeepSeek keys) are encrypted at rest. Generate one key
**once** and keep it safe (losing it means everyone must reconnect):
```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```
→ this is `FERNET_KEY`.

### 4 — Deploy the container
A [`Dockerfile`](Dockerfile) is included — it bakes in `tesseract-ocr`, so **nobody installs
anything**. Deploy the image to any managed host that gives you HTTPS and keeps it alive
(**Railway / Render / Fly.io / Cloud Run** all work — the platform replaces `systemd`).

- **Mount a persistent volume at `/app/data`** so the encrypted SQLite datastore survives
  redeploys (otherwise users must reconnect after each deploy).
- Set the environment variables below (see [`.env.example`](.env.example)):

| Var | Value |
|---|---|
| `TELEGRAM_TOKEN` | from BotFather |
| `BASE_URL` | your public HTTPS URL, no trailing slash (e.g. `https://receiptbot.up.railway.app`) |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | your Web OAuth client |
| `FERNET_KEY` | the key from step 3 |
| `DB_PATH` | `/app/data/receiptbot.db` (matches the mounted volume) |
| `SHARED_DEEPSEEK_KEY` | *(optional)* a key **you** fund for users who haven't run `/setkey` |
| `AUTHORIZED_USERS` | *(optional)* comma-separated Telegram IDs to restrict access |

That's it. The same app serves the Telegram bot (polling) **and** the `/oauth2callback`
endpoint on one process. Open your bot in Telegram and run `/connect` to verify.

> **Telegram webhooks** are a clean Phase-2 swap (cheaper than polling on a hosted box);
> polling works fine for the first cut.

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
**✦ = new or increased for YA 2025.**

| # | Relief category | Max (RM) | Notes |
|--:|---|--:|---|
| 1 | Lifestyle (Books / Computer / Internet) | 2,500 | books, PC/phone/tablet, internet, self-dev courses |
| 2 | Medical (Self / Spouse / Child) | 10,000 | umbrella cap — the four sub-caps below count toward this |
| 3 | Medical Check-up / Mental Health | 1,000 | **sub-cap inside 10,000**; incl. self-test kits & monitoring devices |
| 4 | Vaccination | 1,000 | **sub-cap inside 10,000** |
| 5 | Dental Treatment | 1,000 | **sub-cap inside 10,000**; examination & treatment |
| 6 | Life Insurance + EPF | 7,000 | EPF ≤4,000 + life/takaful ≤3,000; pensioner may use full 7,000 |
| 7 | SOCSO / EIS | 350 | PERKESO (SOCSO + EIS combined) |
| 8 | Self Education Fees | 7,000 | tertiary; upskilling courses sub-capped at 2,000 |
| 9 | Sports Equipment & Activities | 1,000 | ✦ up from 500; gear, facility/competition fees, gym |
| 10 | Education & Medical Insurance | 4,000 | ✦ up from 3,000; self / spouse / child |
| 11 | PRS / Deferred Annuity | 3,000 | Private Retirement Scheme + deferred annuity (to YA2030) |
| 12 | Parents / Grandparents Medical | 8,000 | treatment/care; full check-up & vaccination sub-limit 1,000 |
| 13 | Childcare / Kindergarten | 3,000 | TASKA/TADIKA, child ≤6, one parent per child |
| 14 | SSPN Net Deposit | 8,000 | net savings, one parent per child (to YA2027) |
| 15 | EV Charging / Food Waste Composter | 2,500 | ✦ home EV charger + composting machine (YA2025–2027) |
| 16 | Breastfeeding Equipment | 1,000 | female taxpayer, child ≤2, once per 2 years |
| 17 | First Home Loan Interest | 7,000 | ✦ house ≤500k: 7,000; 500k–750k: 5,000 (SPA 2025–2027, 3 YAs) |
| 18 | Child Below 18 | 2,000 | per unmarried child under 18 |
| 19 | Child 18+ Pre-University | 2,000 | A-Level / cert / matriculation / prep, full-time |
| 20 | Child 18+ Tertiary (Diploma / Degree) | 8,000 | diploma+ (MY) / degree+ (overseas), full-time |
| 21 | Child Learning Disability / Early Intervention | 6,000 | ✦ **sub-cap inside 10,000**; up from 4,000 (child ≤18) |
| 22 | Spouse / Alimony | 4,000 | spouse with no income / alimony paid |
| 23 | Self / Individual Relief | 9,000 | automatic (individual & dependent relatives) |
| 24 | Disabled Individual | 7,000 | ✦ up from 6,000; OKU-certified self |
| 25 | Disabled Spouse | 6,000 | ✦ up from 5,000; disabled husband/wife |
| 26 | Disabled Child | 8,000 | ✦ up from 6,000 (base) |
| 27 | Disabled Child 18+ Higher Education | 8,000 | additional — stacks on base → up to 16,000 |
| 28 | Basic Support Equipment (Disabled) | 6,000 | for disabled self / spouse / child / parent |
| — | Other Relief | no cap | catch-all bucket for anything else |

> ⚠️ **Not tax advice.** Limits and rules change — always confirm on
> [hasil.gov.my](https://www.hasil.gov.my) or with a licensed tax agent before filing.
> To change a relief, cap or expense mapping, edit **`tax_config.py`** (the single source of
> truth — verified against the LHDN YA 2025 schedule); **`categories.py`** is a thin adapter
> over it. The formatting/auto-totals are rebuilt for each user automatically on `/connect`.

---

## 📦 Business expenses → Form B (Part N) boxes

For **Form B** filers, every expense category rolls up into a Part N income-statement box.
The **Summary** tab totals your spending by box, so the figures transfer straight onto the
return — and the bot prints the target box on each expense receipt's reply.

| Form B box | Income-statement line | Expense categories |
|---|---|---|
| **N5** | Purchases & cost of production | Groceries\* |
| **N17** | Rental / lease | Rent |
| **N21** | Travelling and transport | Transportation, Travel |
| **N24** | Other expenses | Food & Beverage, Communication, Utilities, Office Supplies, Subscriptions, Entertainment, Professional Services, Other |
| **CAPITAL** | Capital allowance *(not an N-box)* | Equipment & Software |

> \*Groceries are personal unless they are trading stock / raw material (then N5).
> Deductibility follows **ITA 1967 s.33** (wholly & exclusively for business); **s.39**
> disallows private and capital items. Computers, machinery and enduring software are
> **capital allowances** — claimed separately, never as an N-box expense.

---

## 🔁 Updating

**Users (self-hosters):** just rerun the same `docker run` command from step 2 — `--pull always`
fetches the newest image automatically. Your encrypted datastore (the named volume `receiptbot`)
is preserved and your Google connection stays valid.

**Operator (to ship a new build):** push to `main`. The GitHub Actions workflow builds a new
image, injects the baked-in OAuth client, and pushes `ghcr.io/edison9733/receipt-bot:latest`.
The next time any user runs the step-2 command they get the new image.

---

## 🔐 Security notes

- **Owner-lock.** The first person to send `/start` to your bot is auto-bound as the sole
  owner — everyone else is silently ignored. Set `OWNER_ID=<your Telegram id>` at run time
  to skip auto-bind and pin yourself explicitly.
- **Encrypted datastore.** The Google refresh token and DeepSeek key are **Fernet-encrypted
  at rest** on your named Docker volume (`receiptbot`). The key is auto-generated on first
  start and never leaves your machine.
- **Limited blast radius.** The bot uses only the least-privilege `drive.file` scope — it can
  touch **only the files it created**, never the rest of your Drive.
- `/setkey` **deletes** the message after reading, so your key isn't left in chat history.
- `/disconnect` revokes the Google token and erases your stored row.
- The Docker image bakes in the operator's OAuth client (ID + secret). These are injected at
  build time from CI secrets — they are **not** in the source code.

---

## 🧑‍💻 Run it for just yourself (self-host / developer)

Prefer to run a single-user copy on your own machine instead of hosting for others? The
original single-tenant path still ships in this repo: `authorize.py` (desktop Google login →
`token.json`), `setup_sheets.py` (run once to build your sheet from env `SHEET_ID`),
`receiptbot.env.template`, and `receiptbot.service` (systemd). You create your own OAuth
client (Desktop type) and set `SHEET_ID` / `DRIVE_FOLDER_ID` yourself. This is good for a
developer audience; for non-technical users, the Docker one-command install above is the way.

---

## 🆘 Troubleshooting

| Symptom | Fix |
|---|---|
| Bot doesn't respond at all | Check `docker logs receiptbot`. Make sure `TELEGRAM_TOKEN` is correct. |
| `/connect` gives "isn't fully set up" | The prebuilt image should have the OAuth client baked in. If you built it yourself, set `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET`. |
| Google OAuth redirect mismatch | The Web client's **Authorized redirect URI** must be exactly `http://localhost:8080/oauth2callback`. |
| Logged out after ~7 days | The consent screen is still in **Testing** — the operator must publish it to **production**. |
| "Google did not return a refresh token" | Run `/disconnect`, then `/connect` again (forces fresh consent). |
| OCR returns nothing | Use a sharper, well-lit photo; Tesseract is already in the image. |
| Bot replies to wrong person / ignores me | `/start` from **your** Telegram account before anyone else (owner auto-bind). Or set `OWNER_ID=<your id>` at run time. |
| Data lost after `docker rm -f receiptbot` | Use `--rm` only for disposable containers. The named volume `receiptbot` persists across `docker restart` and `docker run` reruns; data is lost only if you delete the volume. |
| Categories look wrong | The pre-built image has the current categories baked in. Pull the latest image (`--pull always`) to get updates. |

---

## 🗂️ What's in this repo

| File | Purpose |
|---|---|
| `app.py` | Entry point — Telegram bot (polling) + `/oauth2callback` web endpoint. |
| `bot.py` | Telegram handlers + per-receipt processing; owner-lock on first `/start`. |
| `_bootstrap.py` | **First import** in `app.py` — auto-generates `FERNET_KEY` + sets `BASE_URL` default. |
| `db.py` | Encrypted SQLite datastore (Fernet at rest) + owner-lock `settings` table. |
| `gauth.py` | Google web OAuth flow, signed `state`, refresh-token creds, revoke. |
| `provision.py` | Auto-creates + formats each user's sheet & Receipts folder on `/connect`. |
| `tax_config.py` | **Single source of truth** — LHDN YA 2025 reliefs, caps & Form B boxes. |
| `categories.py` | Thin adapter over `tax_config.py` (the names bot & sheet import). |
| `setup_sheets.py` | Builds/rebuilds the Slate-Professional Sheet (`build_sheet()`, reused by provisioning). |
| `Dockerfile` | Python 3.12 + `tesseract-ocr`; OAuth client baked in at build time via `ARG`. |
| `.github/workflows/docker.yml` | CI: build + push to `ghcr.io/edison9733/receipt-bot` on every `main` push. |
| `install.sh` | macOS/Linux one-liner: check Docker, prompt for token, start container. |
| `install.ps1` | Windows PowerShell equivalent. |
| `.env.example` | Hosted-operator config template. |
| `requirements.txt` | Pinned Python dependencies. |
| `authorize.py`, `receiptbot.service`, `receiptbot.env.template` | Legacy manual-install path (developer self-host). |
| `.gitignore` | Blocks secrets, `.env` files, and the `data/` volume directory. |

---

## 🙌 Credits

- **Author:** [@edison9733](https://github.com/edison9733)
- **Sponsored by Brainard**

---

## 📄 License & disclaimer

Provided as-is for personal use. This tool helps you **organise** receipts; it is **not**
tax, accounting, or legal advice. You are responsible for the accuracy of your own LHDN
filing. Always verify current reliefs at <https://www.hasil.gov.my>.
