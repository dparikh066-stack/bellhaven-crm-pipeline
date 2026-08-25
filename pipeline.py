"""Daily pipeline entry point: scrape the Bellhaven website, pull the CRM
roster, compute proposals, and upsert them into the local review queue.
Never writes to the CRM itself -- see apply.py / the review app for that.
Safe to run repeatedly: see store.upsert_proposals for the idempotency logic.
"""
import json
import sys
import uuid
from datetime import datetime, timezone

import crm_client
import matcher
import scraper
import store


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")


def run():
    run_id = uuid.uuid4().hex[:12]
    started_at = now_iso()
    print(f"[{started_at}] run {run_id}: starting")

    store.init_db()

    print("Scraping Bellhaven website...")
    locations = scraper.scrape_all()
    with open("data/locations.json", "w", encoding="utf-8") as f:
        json.dump(locations, f, indent=2)
    print(f"  {len(locations)} locations scraped")

    print("Fetching CRM accounts...")
    accounts = crm_client.list_all_accounts()
    print(f"  {len(accounts)} accounts fetched")

    print("Matching...")
    proposals = matcher.build_proposals(locations, accounts)
    persistable = [p for p in proposals if p["change_type"] != "no_op"]

    now = now_iso()
    new_count, auto_resolved = store.upsert_proposals(persistable, run_id, now)
    finished_at = now_iso()

    store.record_run(
        run_id, started_at, finished_at,
        len(locations), len(accounts), len(persistable), new_count, auto_resolved,
    )

    no_op_count = len(proposals) - len(persistable)
    print(f"[{finished_at}] run {run_id}: done")
    print(f"  {len(persistable)} proposals ({new_count} new, {auto_resolved} auto-resolved since last run)")
    print(f"  {no_op_count} locations already an exact match with no changes needed")
    pending = len(store.list_proposals(status="pending"))
    print(f"  {pending} proposals now pending review -- run the review app to approve/reject them")


if __name__ == "__main__":
    run()
