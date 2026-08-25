"""SQLite-backed proposal store. This is what makes daily re-runs safe:
matcher.build_proposals() is a pure function of current CRM+website state, so
every run regenerates the full proposal set from scratch; upsert_proposals()
is what actually makes re-runs idempotent by keying on a deterministic
dedupe_key and never touching a proposal that's already been decided.
"""
import json
import sqlite3
from contextlib import closing

DB_PATH = "data/pipeline.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS proposals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dedupe_key TEXT UNIQUE NOT NULL,
    change_type TEXT NOT NULL,
    classification TEXT NOT NULL,
    location_slug TEXT,
    account_ids TEXT NOT NULL,
    ambiguous_group TEXT,
    proposed_changes TEXT NOT NULL,
    evidence TEXT NOT NULL,
    note TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    decision_note TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    decided_at TEXT,
    last_seen_run_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    locations_scraped INTEGER,
    accounts_seen INTEGER,
    proposals_generated INTEGER,
    proposals_new INTEGER,
    proposals_auto_resolved INTEGER
);
"""


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    with closing(_connect()) as conn:
        conn.executescript(SCHEMA)
        conn.commit()


def dedupe_key_for(p):
    ct = p["change_type"]
    slug = p.get("location_slug") or ""
    ids = ",".join(sorted(p.get("account_ids") or []))
    if ct == "create_account":
        return f"create:{slug}"
    if ct == "chow_split":
        return f"chow:{slug}:{ids}"
    if ct == "ambiguous_choice":
        return f"ambiguous:{slug}:{ids}"
    if ct == "mark_duplicate":
        return f"duplicate:{ids}:{p['proposed_changes'].get('duplicate_of_account')}"
    if ct == "flag_review" and p["classification"] == "orphan":
        return f"orphan:{ids}"
    if ct == "flag_review":
        return f"duprev:{ids}:{p['evidence'].get('matched_account_id')}"
    if ct == "update_fields":
        return f"update:{slug}:{ids}"
    if ct == "no_op":
        return f"noop:{slug}:{ids}"
    return f"{ct}:{slug}:{ids}"


def upsert_proposals(proposals, run_id, now):
    """Insert new proposals, refresh still-pending ones, leave decided ones
    alone, and auto-close any pending proposal the matcher no longer produces
    (the underlying condition resolved itself -- e.g. someone fixed it by
    hand, or an earlier approval already changed the CRM state).
    """
    new_count = 0
    seen_keys = set()
    with closing(_connect()) as conn:
        for p in proposals:
            key = dedupe_key_for(p)
            seen_keys.add(key)
            row = conn.execute("SELECT status FROM proposals WHERE dedupe_key = ?", (key,)).fetchone()
            if row is None:
                conn.execute(
                    """INSERT INTO proposals
                       (dedupe_key, change_type, classification, location_slug, account_ids,
                        ambiguous_group, proposed_changes, evidence, note, status,
                        created_at, updated_at, last_seen_run_id)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)""",
                    (
                        key, p["change_type"], p["classification"], p.get("location_slug"),
                        json.dumps(p.get("account_ids") or []), p.get("ambiguous_group"),
                        json.dumps(p["proposed_changes"]), json.dumps(p["evidence"], default=str),
                        p["note"], now, now, run_id,
                    ),
                )
                new_count += 1
            elif row["status"] == "pending":
                conn.execute(
                    """UPDATE proposals SET
                       proposed_changes = ?, evidence = ?, note = ?, updated_at = ?, last_seen_run_id = ?
                       WHERE dedupe_key = ?""",
                    (json.dumps(p["proposed_changes"]), json.dumps(p["evidence"], default=str),
                     p["note"], now, run_id, key),
                )
            else:
                # already approved/rejected -- just bump last_seen so we know it's
                # still relevant, but never touch its content or status again.
                conn.execute("UPDATE proposals SET last_seen_run_id = ? WHERE dedupe_key = ?", (run_id, key))
        # auto-resolve stale pending proposals no longer produced this run
        auto_resolved = 0
        pending_rows = conn.execute("SELECT dedupe_key FROM proposals WHERE status = 'pending'").fetchall()
        for r in pending_rows:
            if r["dedupe_key"] not in seen_keys:
                conn.execute(
                    "UPDATE proposals SET status = 'auto_resolved', decision_note = ?, decided_at = ?, updated_at = ? WHERE dedupe_key = ?",
                    ("Condition no longer detected on a later pipeline run.", now, now, r["dedupe_key"]),
                )
                auto_resolved += 1
        conn.commit()
    return new_count, auto_resolved


def record_run(run_id, started_at, finished_at, locations_scraped, accounts_seen, proposals_generated, proposals_new, proposals_auto_resolved):
    with closing(_connect()) as conn:
        conn.execute(
            """INSERT INTO runs (id, started_at, finished_at, locations_scraped, accounts_seen,
               proposals_generated, proposals_new, proposals_auto_resolved)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (run_id, started_at, finished_at, locations_scraped, accounts_seen,
             proposals_generated, proposals_new, proposals_auto_resolved),
        )
        conn.commit()


def list_proposals(status=None):
    with closing(_connect()) as conn:
        if status:
            rows = conn.execute("SELECT * FROM proposals WHERE status = ? ORDER BY id", (status,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM proposals ORDER BY id").fetchall()
        return [_row_to_dict(r) for r in rows]


def get_proposal(proposal_id):
    with closing(_connect()) as conn:
        row = conn.execute("SELECT * FROM proposals WHERE id = ?", (proposal_id,)).fetchone()
        return _row_to_dict(row) if row else None


def get_siblings(ambiguous_group, exclude_id):
    with closing(_connect()) as conn:
        rows = conn.execute(
            "SELECT * FROM proposals WHERE ambiguous_group = ? AND id != ? AND status = 'pending'",
            (ambiguous_group, exclude_id),
        ).fetchall()
        return [_row_to_dict(r) for r in rows]


def set_status(proposal_id, status, decision_note, now):
    with closing(_connect()) as conn:
        conn.execute(
            "UPDATE proposals SET status = ?, decision_note = ?, decided_at = ?, updated_at = ? WHERE id = ?",
            (status, decision_note, now, now, proposal_id),
        )
        conn.commit()


def reopen_proposal(proposal_id, now):
    """Undo a reject/approve decision -- puts the proposal back in the
    pending queue for reconsideration. Note this only reverses the local
    review-queue record; it does NOT undo any CRM write an 'approve' already
    made (there's no delete/merge in the CRM API to undo it with)."""
    with closing(_connect()) as conn:
        conn.execute(
            "UPDATE proposals SET status = 'pending', decision_note = NULL, decided_at = NULL, updated_at = ? WHERE id = ?",
            (now, proposal_id),
        )
        conn.commit()


def last_run():
    with closing(_connect()) as conn:
        row = conn.execute("SELECT * FROM runs ORDER BY started_at DESC LIMIT 1").fetchone()
        return dict(row) if row else None


def _row_to_dict(row):
    d = dict(row)
    d["account_ids"] = json.loads(d["account_ids"])
    d["proposed_changes"] = json.loads(d["proposed_changes"])
    d["evidence"] = json.loads(d["evidence"])
    return d
