# Nordex order pulse

Scrapes the [Nordex News Archive](https://www.nordex-online.com/en/news-media/blog/) every day, uses an LLM to pull out firm orders, groups them by the quarter they were **announced**, and publishes a dashboard on GitHub Pages. Runs entirely on free tiers.

**Purpose:** an early, running feel for how the current quarter is going, not a reconciliation with the official order intake (that comes in the quarterly report). The dashboard opens on the current quarter and shows:
- MW and number of firm orders announced so far, with day X of 92 and days left
- the same figure for last quarter and for the same quarter last year **at the same day of the quarter** (so day 42 is compared with day 42, not with a full quarter)
- a cumulative chart by day of quarter for those three quarters
- breakdowns by country, turbine platform and customer, the order list, and quarterly history for context

```
GitHub Actions (daily cron)
  └─ scraper/run.py
       1. fetch.py    WordPress REST API of nordex-online.com (HTML archive as fallback)
                      -> cleaned text per release in data/releases/<id>.json
                      -> cheap prefilter: only "Incoming Orders" / order-like titles go to the LLM
       2. extract.py  GitHub Models (free, uses GITHUB_TOKEN) -> JSON validated by Pydantic
                      results are cached, so each release is parsed once
       3. build.py    quarterly rollup + double-count guards -> docs/data/deals.json + deals.csv
  └─ commit data, deploy docs/ to GitHub Pages
```

## What is extracted

Per order: **MW** (plus whether it is approximate and the exact wording), **country**, **customer**, **turbine platform**, and when available turbine count, wind farm, and when it was firmed. Missing fields stay empty ("Not disclosed"); nothing is guessed.

## Quarter logic

A deal belongs to the quarter its press release was **published**, even if the text says it was firmed earlier (e.g. "at the end of 2025" announced in January 2026 counts in 2026-Q1). The firmed period is still stored and shown in the table.

## Double counting and approximate figures

| Case | Handling |
|---|---|
| Quarterly / annual order-intake releases | Never counted as deals. Their GW figure is shown as "Nordex reported intake" for comparison. |
| Framework, "up to X MW", conditional agreements | Not counted. If the same release also has firm orders, only the firm part counts. |
| Same release posted twice (ad hoc + corporate news) | Counted once. |
| Release says the order was announced before | Excluded. |
| Same customer or wind farm, same country, MW within 2%, within 12 months | Later one excluded as a likely repeat. |
| Roundups ("414 MW in France, Belgium and Portugal") | One row per separable order; the parts must add up to the headline total, otherwise a warning is logged. |
| "approx.", "more than", "nearly", "around" | Counted, flagged `mw_approx`, shown separately in the quarterly chart and marked * in the table. |

Every excluded row stays in the data with its reason (tick "Show excluded rows" on the dashboard). To correct the LLM by hand, add an entry to `data/overrides.json`.

## Password protection (public repo)

The repo is public, so nothing readable is ever committed:
- The dashboard data is published only as `docs/data/deals.enc.json`, encrypted with AES-256-GCM. The key comes from your password (PBKDF2-SHA256, 600k iterations), and the browser decrypts it after the password is entered.
- The pipeline's cache of parsed releases is stored only as `data/state.enc`, encrypted with the same password.
- `.gitignore` plus two guard checks in the workflow stop the run if a plaintext data file would be committed or published. The run also refuses to start if the `DASHBOARD_PASSWORD` secret is missing.

Use a long passphrase (e.g. four or five random words). The encrypted file is public, so a short password could be guessed offline. The code and the repo name are public; only the data is protected.

To change the password: update the secret, delete `data/state.enc` in the repo, and run the workflow with *Max LLM calls* 140. Everything is then re-parsed and re-encrypted.

## Setup in the browser (about 10 minutes)

1. Create a new **public** repository with a neutral name (e.g. `order-pulse`). Don't add a README.
2. Click **uploading an existing file**. Drag in everything inside this folder, including the hidden `.github` folder (Mac: Cmd + Shift + . shows it), then commit.
3. **Settings > Secrets and variables > Actions > New repository secret**: name `DASHBOARD_PASSWORD`, value your passphrase. Do this BEFORE the first run.
4. **Settings > Actions > General > Workflow permissions: Read and write**, then Save.
5. **Settings > Pages > Source: GitHub Actions.**
6. **Actions > Daily Nordex orders > Run workflow**, set *Max LLM calls* to `140` for the first backfill. If the dashboard shows a yellow "pending" note, run it again the next day, or let the daily schedule finish it.
7. The dashboard is at `https://<your-username>.github.io/<repo-name>/`. Enter the passphrase once per device.

Optional repo variables (Settings > Secrets and variables > Actions > Variables):
- `BACKFILL_FROM` first date to scrape when starting (default `2024-01-01`)
- `LLM_MODEL` default `openai/gpt-4.1-mini`

### Using another free LLM instead
Any OpenAI-compatible endpoint works. For Google Gemini: add secret `LLM_API_KEY`, variable `LLM_BASE_URL = https://generativelanguage.googleapis.com/v1beta/openai/`, variable `LLM_MODEL = gemini-2.5-flash`.

## Running locally

```bash
pip install -r requirements.txt
export GITHUB_TOKEN=<a fine-grained PAT with "Models: read">
python scraper/run.py
python -m http.server -d docs 8000   # open http://localhost:8000 (without DASHBOARD_PASSWORD the data stays unencrypted locally)
python tests/test_pipeline.py        # offline test, no network or LLM needed
```

## Notes

- Scheduled workflows in public repos pause after 60 days without repo activity. The daily data commit (including `data/last_run.txt`) keeps it active.
- Free LLM tiers have daily request caps; `MAX_LLM_CALLS` (default 40 per run) keeps each run well under them. Normal days only have 0 to 3 new order releases.
- After changing the extraction prompt, run the workflow with *Re-parse ALL cached releases* ticked.
