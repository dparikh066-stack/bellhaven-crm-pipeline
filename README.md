# Bellhaven CRM Pipeline

Daily pipeline that scrapes the Bellhaven Senior Living website, compares it
against the Bellhaven CRM sandbox, and proposes fixes (re-parenting,
renames, duplicates, new accounts, CHOW splits) for a human to review in a
local app. Nothing writes to the CRM until a reviewer clicks Approve.

See **[WRITEUP.md](WRITEUP.md)** for the full reasoning: how matching works,
how the change-of-ownership (CHOW) SOP is implemented, the data-quality
issues found in this dataset and how each was resolved, and one case
(Kettering) deliberately left for human judgment instead of auto-resolved.

## Quick start

```
pip install -r requirements.txt
```

```powershell
$env:BELLHAVEN_CRM_TOKEN = "your-token-here"   # PowerShell
```
```bash
export BELLHAVEN_CRM_TOKEN=your-token-here     # bash
```

```
python pipeline.py          # scrape the site, pull the CRM, populate the review queue
python -m review_app.app    # open http://127.0.0.1:5000 and approve/reject
```

`BELLHAVEN_CRM_TOKEN` is required (no default baked into the code).

## Project layout

| File | Purpose |
|---|---|
| `scraper.py` | Pulls every community from the website (paginated directory + homepage banner links) |
| `crm_client.py` | Thin wrapper over the CRM API |
| `matcher.py` | Pure `(locations, accounts) -> proposals` matching/classification logic, including the CHOW SOP |
| `store.py` | SQLite proposal ledger — makes daily re-runs idempotent |
| `pipeline.py` | Daily entry point: scrape → fetch → match → upsert proposals |
| `apply.py` | Turns an approved proposal into the actual CRM write(s) |
| `review_app/` | Local Flask app where a human reviews evidence and approves/rejects |
| `schedule/crontab.example` | Example cron entry for the daily run |
| `.github/workflows/daily-pipeline.yml` | Equivalent GitHub Actions schedule |
| `WRITEUP.md` | Design rationale, SOP handling, data-quality findings |

## Re-running safely

`pipeline.py` can be run any number of times. Proposals are deduplicated by
a deterministic key, so a decision a reviewer already made (approve or
reject) is never re-shown; only genuinely new or still-unresolved items
appear in the queue.
