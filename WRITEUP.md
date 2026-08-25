# Bellhaven CRM Pipeline — Writeup

## What this is

A daily pipeline that scrapes Bellhaven Senior Living's website, compares it
against the CRM sandbox, and proposes CRM fixes for a human to review and
approve. Nothing writes to the CRM without a click in the review app.

Files:
- `scraper.py` — pulls every community from `/communities` (paginated) *and*
  the homepage promo banner, which linked a just-announced community
  (Findlay) that hadn't made it into the paginated directory yet. Relying on
  pagination alone silently drops it.
- `crm_client.py` — thin wrapper over the CRM API.
- `matcher.py` — pure function `(locations, accounts) -> proposals`. All the
  matching/classification logic lives here; no I/O, so it's easy to reason
  about and re-run.
- `store.py` — SQLite ledger (`data/pipeline.db`) that makes re-runs safe.
- `pipeline.py` — the daily entry point: scrape, fetch, match, upsert.
- `apply.py` — turns an approved proposal into the actual CRM API call(s).
- `review_app/app.py` — the reviewer UI (`python -m review_app.app`,
  http://127.0.0.1:5000).
- `schedule/crontab.example`, `.github/workflows/daily-pipeline.yml` —
  schedule configs (not live, per the assignment).

## Setup

```
pip install -r requirements.txt
$env:BELLHAVEN_CRM_TOKEN = "your-token-here"   # PowerShell
# export BELLHAVEN_CRM_TOKEN=your-token-here   # bash

python pipeline.py          # scrape + match, populate the review queue
python -m review_app.app    # open http://127.0.0.1:5000 and review
```

`BELLHAVEN_CRM_TOKEN` is required (no default) so the token never has to
live in the repo.

## How matching works

For each scraped location, I score every CRM account on street similarity,
name similarity, and exact zip/city/state matches (`matcher.score_pair`).
Two independent "is this the same facility" tests are applied on top of the
raw score, because the two failure modes in this data are different:

- **address-confirmed**: zip matches and the street reads the same
  (handles "875 Elm Street" vs "875 Elm St").
- **identity-confirmed**: zip+city+name are all strong even if the street is
  stale (a PO box on file — Ashtabula) or the zip itself is wrong (a
  transposed digit — Portsmouth, 45626 vs 45662).

From there:
- If one confirmed account is already parented under Bellhaven with a
  matching name → **confident match** (still checked field-by-field for
  drift — stale phone numbers turned out to be extremely common in this
  data, and I proposed syncing every one).
- If a confirmed account exists but the parent or name is wrong → **needs
  fix** (see CHOW handling below).
- If multiple accounts sit at the same address and *none* is already the
  correct Bellhaven record → **ambiguous**. I did not try to guess a winner
  here (see the Kettering case below) — I emit one proposal per candidate,
  tagged into a shared group, so a human picks exactly one and the app
  auto-rejects the rest.
- If nothing matches → **new location**, propose creating the account.
- Any *other* CRM account sitting at an already-matched address becomes a
  **duplicate** proposal (`duplicate_of_account` + `Inactive`) — unless it
  carries real revenue *and* outstanding AR, in which case it's flagged for
  human review instead of auto-deactivated. I extended the CHOW SOP's
  billing caution to this case too: the SOP only says not to move a live
  account's parent, but silently deactivating one seemed like the same kind
  of risk, so I applied the same rev+AR check before ever touching status.
- Any Bellhaven-parented account that no location claims → **orphan**
  (`Needs Review`, never auto-`Inactive` — closing an account is a real
  business decision I didn't think a scraper should make unattended,
  especially since one of the two orphans found, Sandusky, has $130k
  lifetime revenue and $5.2k outstanding AR).

## The CHOW SOP

Implemented literally: before re-parenting an existing account, check
`lifetime_revenue` and `outstanding_ar`. If both are > 0, leave that account
completely alone (only `chow_current_account` gets set), create a new
account under the correct parent, and point the old one at the new one. This
fired for two real cases — Marietta and Tiffin, both under Cedar Trail
Communities with real billing history. Everything else with a wrong parent
(Findlay, Lima, Zanesville) had `outstanding_ar = 0` and was re-parented
directly.

One second-order effect worth calling out: after a CHOW split, the old and
new accounts sit at the same address, so my duplicate-detection pass finds
the *old* account again on the next run. Because it still has revenue + AR,
it doesn't get auto-marked a duplicate — it gets flagged for review instead,
and I rejected that flag on both accounts, since the SOP explicitly says to
leave the old account exactly as it is. This is expected pipeline behavior,
not a bug, but it's the kind of thing a reviewer needs to recognize rather
than reflexively approve.

## Data quality issues found and how each was handled

| Issue | Example | Resolution |
|---|---|---|
| Stale phone numbers | ~13 accounts | synced from website |
| Abbreviated/reformatted street | Toledo, Marion, Ashtabula, ... | synced from website |
| Stale billing address (PO box on file) | Ashtabula | synced physical address from website |
| Transposed zip digit | Portsmouth (45626 → 45662) | corrected |
| Outdated facility name after rebrand | Chesterton, Chagrin Falls, Willow Creek/Portage, Grove City, Ashland | renamed to match website |
| Wrong parent, no billing history | Findlay, Lima | re-parented directly |
| Wrong parent, real revenue + AR | Marietta, Tiffin | CHOW split (old preserved, new created) |
| Exact duplicate account, same address | Owosso (×2), plus stale pre-acquisition records at Port Clinton, Erie, and Monroe | marked `duplicate_of_account` + `Inactive` |
| Multiple same-address accounts, no clear survivor | **Kettering** — three unrelated pre-acquisition records (Harborview, Cedar Trail, and an unparented one), none Bellhaven-branded | left pending — see below |
| Account still active, no longer on website | Alliance, Coldwater, Sandusky | flagged `Needs Review` (not auto-closed) |
| New community, no CRM account | Batavia, Union Square, Carlisle, Amberly Manor (Hudson) | created |
| Name collision, unrelated facility | "Amberly Manor" also exists in CRM as an unrelated Juniper Point account in Colorado Springs | correctly *not* matched — different state entirely; new account created for the Hudson, OH one instead |

### Kettering: left unresolved, deliberately

Three different CRM accounts sit at 3313 Wilmington Pike — "Kettering Care
Centre" (Harborview), "Kettering Nursing & Rehabilitation" (unparented), and
"Kettering Senior Campus" (Cedar Trail) — and none of them is already
correctly named or parented for Bellhaven. All three have zero revenue and
zero AR, so there's no billing signal to break the tie, and nothing in the
scraped data indicates which pre-acquisition entity is the one that's
supposed to continue as "Bellhaven of Kettering." Auto-picking one risked
silently misattributing history to the wrong legal entity. I generated all
three as mutually-exclusive alternatives in the review app and left them
pending rather than guess — this is a case that genuinely needs a person
with more context (e.g., corporate development) to resolve, not a heuristic.

## Idempotency

`matcher.build_proposals` is a pure function of current CRM + website state.
Every run regenerates the *entire* proposal set from scratch, but
`store.upsert_proposals` is what makes re-runs safe: each proposal gets a
deterministic `dedupe_key`; a proposal that already has a decision
(`approved`/`rejected`) is never touched again, only its `last_seen_run_id`
is bumped. A `pending` proposal the matcher no longer produces (because
someone fixed it by hand, or a prior approval already resolved it) gets
auto-closed as `auto_resolved`. Verified live: re-running the pipeline after
approving 33 proposals produced only 2 genuinely new items (see the CHOW
side-effect above) and correctly left the approved/rejected ones alone.

## Known artifact

While testing `create_account`'s response shape I created one disposable
test record (`ZZZ_PIPELINE_TEST_DELETE_ME`, status `Inactive`, clearly
noted). The API has no delete, so it remains in the sandbox — harmless, but
flagging it here rather than leaving it unexplained.

## What I'd do differently with more time

- The name/address fuzzy-matching thresholds in `matcher.py` are hand-tuned
  against this dataset. A production version would want a labeled
  match/no-match set to validate thresholds against, rather than eyeballing
  score distributions.
- `care_type` is a single-select CRM field but the website lists multiple
  care offerings for a few communities (e.g. Erie: Assisted Living *and*
  Memory Support). I map to the first offering and drop the rest — a real
  fix would probably mean asking CRM for a multi-value field.
- The SQLite ledger works for ~120 accounts; the GitHub Actions workflow
  commits it back to the repo to persist state between scheduled runs, which
  is a reasonable stopgap but not what I'd choose at real scale (a hosted
  DB would remove the git-commit-as-database hack).

## Time spent

This was built end-to-end by Claude Code (an AI coding agent) working
autonomously in a single session, rather than a human directing an AI tool
turn-by-turn — so the "~2 focused hours" framing doesn't map cleanly onto
wall-clock time the way it would for a human using AI assistance. Worth
being upfront about that distinction when you note actual time for
submission.
