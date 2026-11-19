# Internship scanner

> ## 📌 iPhone setup (pinned)
> The same guide is on the dashboard: tap **📱 Setup guide** on the lock screen or in ⚙︎ Settings
> (`/internship-scanner/setup.html`).
>
> **Dashboard as an app**
> 1. Open the dashboard link in **Safari**.
> 2. Tap **Share** (□↑) → **Add to Home Screen** → **Add**.
> 3. Open **Internships** from the home screen, enter your dashboard password and keep "Remember on this device" ticked.
>
> **Notifications**
> 1. Install **ntfy** from the App Store.
> 2. Tap **+** and type your topic, exactly the `NTFY_TOPIC` secret. Leave the server as ntfy.sh.
> 3. Tap **Subscribe**, then **Allow** notifications. If you missed the prompt: Settings → Notifications → ntfy.
>
> **Sync statuses with your computer** (free GitHub token, one for all devices)
> 1. github.com → Settings → Developer settings → Fine-grained tokens → **Generate new token**.
> 2. Choose: expiration 1 year · only repo `internship-scanner-state` · Contents: Read and write.
> 3. In the dashboard: ⚙︎ → repo `<username>/internship-scanner-state` + paste the token → **Test & sync now** → **Save**.

Every morning at 07:00 (Paris time) GitHub runs a scan of company career pages for
**short (≤ 3 months) business internships in Paris / La Défense / 92-93-94**.
It ranks matches 0–100 and publishes them to a password-protected dashboard that
works on your phone and computer. It also sends a push notification for each strong
new match.

- **Dashboard:** `https://<your-github-username>.github.io/internship-scanner/` (lowercase).
  Install it like an app: on iPhone tap *Share → Add to Home Screen*; on Android tap
  *⋮ → Install app*; in desktop Chrome/Edge click the install icon in the address bar.
- **Privacy:** the offers, your scores and the "Why I fit" lines are encrypted
  (AES-256) before they're committed. Only someone with your dashboard password can
  read them. Your profile lives in a GitHub *secret*, never in the code. Your
  statuses and notes live in a separate **private** repo.

---

## Daily use

| I want to… | Do this |
|---|---|
| See new offers | Open the dashboard; **NEW** badges and the "New today" counter |
| Track an offer | Change its status (New → To review → Applied → Interview → Rejected / Not interested) and type a note; both sync to your other devices |
| Search LinkedIn / Indeed | *Search elsewhere* tab: one click per role, pre-filtered to Paris + internship + last 24h |
| Check a source failed | A yellow banner appears at the top; details in the *Sources* tab |

## Run a scan manually

1. Open the repo on github.com → **Actions** tab.
2. Click **Daily internship scan** in the left list.
3. Click **Run workflow** → **Run workflow** (green button).
4. After ~5–10 minutes, refresh the dashboard.

## Change filters, keywords or weights

Everything is in **`config.yaml`**. On github.com, open the file and click the ✏️ pencil
icon. Make your change, then click **Commit changes**. The next run uses it.

- **Dates:** `dates:`. Earliest/latest start, maximum months.
- **Minimum pay:** `pay: min_monthly_eur`.
- **What gets shown (two gates):** `relevance:`.
  1. The **company** must be in a target sector (`relevance: sectors`): start-up / fintech,
     venture capital, private equity, asset management, M&A / banking, insurance, consulting.
     Large corporates (`corporate`) only show strategy / investment / finance roles.
     Known firms get their sector and fame `tier` from `companies:` and `relevance: known_firms`;
     unknown companies are recognised from the offer text (`sector_keywords`) or hidden.
  2. The **role** must name a target function (`relevance: functions`). Engineering, quant and
     marketing roles (and support, HR, legal) are always hidden (`excluded_roles`).
- **How much you learn:** `relevance: learning`. Concrete tasks (models, valuation, due
  diligence, market studies...) and direct work with founders / partners raise the score;
  grunt work (cold calling, data entry, CRM updates, admin, "assistant" titles) and
  buzzword-heavy offers with no concrete tasks lower it. Sales / operations / accounting roles
  are kept but capped at 55.
- **Score weights:** `weights:` (role & learning / company / clarity / dates / language; must add up to 1).
- **Notification threshold:** `notifications: min_score` (default 75).

Keywords ignore capitals and accents ("stratégie" = "strategie").
After editing, the **Tests** workflow runs automatically. If it shows a red ✗,
open it to see which rule your change affected.

## Add a company

Add one line under `companies:` in `config.yaml`:

```yaml
  - {name: Alma, type: fintech, tier: 2}
```

`type` (sector) is one of `fintech, startup, vc, private_equity, asset_management,
investment_bank, bank, insurance, consulting, corporate`; `tier` is 1 (household name),
2 (well known) or 3 (smaller).
The next run auto-detects the company's job platform (Greenhouse, Lever, Ashby, Workable,
Teamtailor, Workday…). If it can't find it, the company still appears as a link in
*Search elsewhere*. You can help detection with either of:

```yaml
  - {name: Alma, type: fintech, careers_url: "https://alma.eu/careers"}
  - {name: Sanofi, type: corporate, ats: workday, id: "https://sanofi.wd3.myworkdayjobs.com/SanofiCareers"}
```

## Notifications (ntfy)

Strong new matches (score ≥ `min_score`) arrive as one notification each. Each shows the
title, company and score, and tapping it opens the offer.

**Phone (iPhone or Android):**
1. Install the free **ntfy** app (App Store / Google Play).
2. Tap **+**, enter your topic name, the same text as the `NTFY_TOPIC` secret, and **Subscribe**.
3. Allow notifications when asked.

**Desktop:**
1. Open <https://ntfy.sh/app> in Chrome, Edge or Firefox.
2. Click **Subscribe to topic**, enter the same topic, then **Subscribe**.
3. Click **Grant now** to allow browser notifications. Keep a tab open, or install the
   page as an app from the address bar, so notifications keep arriving.

Treat the topic name like a password: anyone who knows it can read the notifications.
Use something long and random.

## Secrets (repo → Settings → Secrets and variables → Actions)

| Secret | Required | What |
|---|---|---|
| `DASHBOARD_PASSWORD` | yes | Password for the dashboard (the data is encrypted with it) |
| `PROFILE_YAML` | yes | Your profile (contents of `profile.local.yaml`) for "Why I fit" |
| `NTFY_TOPIC` | yes | Your ntfy topic name |
| `ANTHROPIC_API_KEY` | optional | Better mission summaries and "Why I fit" via Claude Haiku |
| `FT_CLIENT_ID` / `FT_CLIENT_SECRET` | optional | France Travail API: all employers posting in France |
| `ADZUNA_APP_ID` / `ADZUNA_APP_KEY` | optional | Adzuna API: aggregates thousands of job boards and companies (free key at developer.adzuna.com) |

## Sources & rules

- **Company career pages** through their public, documented job APIs: Greenhouse,
  Lever, Ashby, Workable, Teamtailor, Workday, SmartRecruiters and SuccessFactors
  (RSS), plus Amazon's public job search. robots.txt is respected. Each site gets at
  most about one request per second, with a clear user agent.
- **Not scanned:** LinkedIn and Indeed (their terms forbid it, so you get links instead).
  Welcome to the Jungle's terms (§10) also forbid automated extraction, so it gets search links too.
  SmartRecruiters' robots.txt blocks bots, so that adapter is off.
- **France Travail and Adzuna:** optional, each turns on when its secrets exist. These
  two aggregators cover companies that aren't in `config.yaml`, so offers from
  unknown startups are found too, and scored on their content.

## Running locally (optional)

```
pip install -r requirements.txt
python -m pytest -q                         # tests
set DASHBOARD_PASSWORD=...                  # PowerShell: $env:DASHBOARD_PASSWORD="..."
python -m scanner.run --no-notify --report  # full run + summary
python -m scanner.detect_ats --force        # re-detect every company's job platform
```
