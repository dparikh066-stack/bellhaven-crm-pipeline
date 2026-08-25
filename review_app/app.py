"""Local review app. A reviewer sees every proposed CRM change with its
supporting evidence and can approve or reject it. Nothing reaches the CRM
until a human clicks Approve.

Run with:  python -m review_app.app
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, redirect, render_template_string, request, url_for

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import apply as apply_mod
import crm_client
import pipeline
import store

app = Flask(__name__)

CLASSIFICATION_LABELS = {
    "confident_match": ("Confident match (field sync)", "#2E5D50"),
    "needs_fix": ("Needs fix", "#C9A227"),
    "new_location": ("No CRM account yet", "#1c6fb0"),
    "orphan": ("No longer on website", "#a33"),
    "ambiguous": ("Ambiguous -- pick one", "#8a4b9e"),
    "duplicate": ("Duplicate", "#a33"),
    "duplicate_needs_review": ("Possible duplicate (has billing history)", "#a33"),
}

BASE = """
<!doctype html>
<html><head>
<title>Bellhaven CRM Review</title>
<style>
  body { font-family: -apple-system, Segoe UI, Arial, sans-serif; background: #F7F5EF; color: #222; margin: 0; }
  header { background: #2E5D50; color: #fff; padding: 16px 24px; display: flex; justify-content: space-between; align-items: center; }
  header a { color: #fff; text-decoration: none; margin-left: 16px; font-size: 13px; }
  .wrap { max-width: 1100px; margin: 0 auto; padding: 24px; }
  .summary { display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 20px; }
  .pill { background: #fff; border: 1px solid #ddd; border-radius: 20px; padding: 6px 14px; font-size: 13px; }
  .card { background: #fff; border: 1px solid #E4DFD2; border-radius: 6px; padding: 16px 18px; margin-bottom: 14px; }
  .badge { display: inline-block; font-size: 11px; color: #fff; border-radius: 3px; padding: 3px 9px; margin-right: 8px; font-weight: 600; }
  .title { font-size: 16px; margin: 6px 0; }
  .note { color: #555; font-size: 13.5px; margin: 8px 0; line-height: 1.5; }
  table.diff { border-collapse: collapse; width: 100%; margin: 10px 0; font-size: 13px; }
  table.diff th, table.diff td { border: 1px solid #eee; padding: 5px 9px; text-align: left; vertical-align: top; }
  table.diff th { background: #FAF7F0; }
  .changed { background: #fff6d8; }
  .btns { margin-top: 10px; }
  button { border: none; border-radius: 4px; padding: 8px 16px; font-size: 13px; cursor: pointer; margin-right: 8px; }
  .approve { background: #2E5D50; color: #fff; }
  .reject { background: #eee; color: #333; }
  .runbtn { background: #C9A227; color: #222; padding: 8px 16px; border-radius: 4px; text-decoration: none; font-size: 13px; }
  .muted { color: #888; font-size: 12px; }
  .group-label { font-size: 12px; color: #8a4b9e; font-weight: 600; margin: 18px 0 4px; }
  .flash { background: #eaf6ea; border: 1px solid #b7dbb7; padding: 10px 14px; border-radius: 4px; margin-bottom: 16px; font-size: 13px; }
</style>
</head><body>
<header>
  <div><b>Bellhaven CRM Review</b></div>
  <div><a href="{{ url_for('index') }}">Pending</a><a href="{{ url_for('decided') }}">Decided History</a></div>
</header>
<div class="wrap">{{ body|safe }}</div>
</body></html>
"""


def render(body):
    return render_template_string(BASE, body=body)


def diff_table(evidence, proposed_changes):
    loc = evidence.get("location")
    acct = evidence.get("account")
    rows = []
    if loc and acct:
        field_map = [
            ("Name", "name", "name"),
            ("Street", "billing_street", "street"),
            ("City", "billing_city", "city"),
            ("State", "billing_state", "state"),
            ("Zip", "billing_zip", "zip"),
            ("Care type", "care_type", None),
            ("Phone", "phone", "phone"),
            ("Parent", "parent_name", None),
        ]
        for label, acct_key, loc_key in field_map:
            current = acct.get(acct_key, "")
            website = loc.get(loc_key, "") if loc_key else (", ".join(loc.get("care_offerings", [])) if acct_key == "care_type" else "")
            changed_key = {"name": "name", "billing_street": "billing_street", "billing_city": "billing_city",
                           "billing_state": "billing_state", "billing_zip": "billing_zip",
                           "care_type": "care_type", "phone": "phone", "parent_name": "parent_id"}[acct_key]
            is_changed = changed_key in proposed_changes
            rows.append((label, current, website if loc_key or acct_key == "care_type" else "(website has no field here)", is_changed))
        html = ['<table class="diff"><tr><th>Field</th><th>Current (CRM)</th><th>Proposed (website)</th></tr>']
        for label, current, website, is_changed in rows:
            cls = ' class="changed"' if is_changed else ""
            html.append(f"<tr{cls}><td>{label}</td><td>{current}</td><td>{website}</td></tr>")
        html.append("</table>")
        return "".join(html)
    return f'<pre style="white-space:pre-wrap;font-size:12px;background:#FAF7F0;padding:8px;border-radius:4px;">{json.dumps(evidence, indent=2, default=str)}</pre>'


def render_card(p, show_actions=True):
    label, color = CLASSIFICATION_LABELS.get(p["classification"], (p["classification"], "#555"))
    title_bits = []
    if p.get("evidence", {}).get("location"):
        title_bits.append(p["evidence"]["location"]["name"])
    if p.get("evidence", {}).get("account"):
        title_bits.append(f"CRM: {p['evidence']['account']['name']}")
    title = " -> ".join(title_bits) if title_bits else (p.get("location_slug") or "; ".join(p["account_ids"]))

    parts = [f'<div class="card">']
    parts.append(f'<span class="badge" style="background:{color}">{label}</span>')
    parts.append(f'<span class="muted">{p["change_type"]}</span>')
    parts.append(f'<div class="title">{title}</div>')
    parts.append(f'<div class="note">{p["note"]}</div>')
    parts.append(diff_table(p["evidence"], p["proposed_changes"]))
    if p["change_type"] in ("create_account", "chow_split") or "new_account" in p.get("proposed_changes", {}):
        na = p["proposed_changes"].get("new_account", p["proposed_changes"])
        parts.append(f'<pre style="white-space:pre-wrap;font-size:12px;background:#FAF7F0;padding:8px;border-radius:4px;">New account: {json.dumps(na, indent=2)}</pre>')
    if p["status"] != "pending":
        parts.append(f'<div class="muted">Status: <b>{p["status"]}</b>{(" -- " + p["decision_note"]) if p.get("decision_note") else ""} ({p.get("decided_at","")})</div>')
    if show_actions and p["status"] == "pending":
        parts.append(f'''<div class="btns">
            <form style="display:inline" method="post" action="{url_for('approve', proposal_id=p["id"])}">
                <button class="approve" type="submit">Approve</button>
            </form>
            <form style="display:inline" method="post" action="{url_for('reject', proposal_id=p["id"])}">
                <button class="reject" type="submit">Reject</button>
            </form>
        </div>''')
    if show_actions and p["status"] == "rejected":
        parts.append(f'''<div class="btns">
            <form style="display:inline" method="post" action="{url_for('reopen', proposal_id=p["id"])}">
                <button class="reject" type="submit">Reopen for review</button>
            </form>
        </div>''')
    parts.append("</div>")
    return "".join(parts)


@app.route("/")
def index():
    pending = store.list_proposals(status="pending")
    flash = request.args.get("flash", "")
    run_info = store.last_run()

    counts = {}
    for p in pending:
        counts[p["classification"]] = counts.get(p["classification"], 0) + 1
    summary = "".join(f'<span class="pill">{CLASSIFICATION_LABELS.get(k,(k,""))[0]}: {v}</span>' for k, v in counts.items())

    body = []
    if flash:
        body.append(f'<div class="flash">{flash}</div>')
    body.append('<div style="display:flex;justify-content:space-between;align-items:center;">')
    body.append(f'<h2 style="margin:0;">Pending review ({len(pending)})</h2>')
    body.append(f'<form method="post" action="{url_for("run_now")}"><button class="runbtn" type="submit">Run pipeline now</button></form>')
    body.append('</div>')
    if run_info:
        body.append(f'<div class="muted">Last run {run_info["id"]} at {run_info["started_at"]}: {run_info["locations_scraped"]} locations, {run_info["accounts_seen"]} accounts, {run_info["proposals_new"]} new proposals, {run_info["proposals_auto_resolved"]} auto-resolved.</div>')
    body.append(f'<div class="summary">{summary}</div>')

    if not pending:
        body.append('<p class="muted">No pending proposals. Run the pipeline, or check Decided History.</p>')

    # ambiguous groups rendered together
    grouped = {}
    singles = []
    for p in pending:
        if p["ambiguous_group"]:
            grouped.setdefault(p["ambiguous_group"], []).append(p)
        else:
            singles.append(p)

    for group_key, items in grouped.items():
        body.append(f'<div class="group-label">Choose one: {group_key}</div>')
        for p in items:
            body.append(render_card(p))

    for p in singles:
        body.append(render_card(p))

    return render("".join(body))


@app.route("/decided")
def decided():
    all_p = store.list_proposals()
    decided_list = [p for p in all_p if p["status"] != "pending"]
    flash = request.args.get("flash", "")
    body = []
    if flash:
        body.append(f'<div class="flash">{flash}</div>')
    body.append(f'<h2>Decided history ({len(decided_list)})</h2>')
    if not decided_list:
        body.append('<p class="muted">Nothing decided yet.</p>')
    for p in decided_list:
        body.append(render_card(p, show_actions=True))
    return render("".join(body))


@app.route("/proposals/<int:proposal_id>/approve", methods=["POST"])
def approve(proposal_id):
    p = store.get_proposal(proposal_id)
    now = pipeline.now_iso()
    if p is None or p["status"] != "pending":
        return redirect(url_for("index", flash="That proposal is no longer pending."))
    try:
        result = apply_mod.apply_proposal(p)
    except crm_client.CrmError as e:
        return redirect(url_for("index", flash=f"CRM API error applying proposal {proposal_id}: {e}"))
    store.set_status(proposal_id, "approved", json.dumps(result), now)
    flash = f"Approved proposal {proposal_id}: {json.dumps(result)}"
    if p["ambiguous_group"]:
        siblings = store.get_siblings(p["ambiguous_group"], proposal_id)
        for s in siblings:
            store.set_status(s["id"], "rejected", f"Auto-superseded by approval of proposal {proposal_id}.", now)
        if siblings:
            flash += f" (auto-rejected {len(siblings)} alternative(s) in the same group)"
    return redirect(url_for("index", flash=flash))


@app.route("/proposals/<int:proposal_id>/reject", methods=["POST"])
def reject(proposal_id):
    p = store.get_proposal(proposal_id)
    now = pipeline.now_iso()
    if p is None or p["status"] != "pending":
        return redirect(url_for("index", flash="That proposal is no longer pending."))
    store.set_status(proposal_id, "rejected", "Rejected by reviewer.", now)
    return redirect(url_for("index", flash=f"Rejected proposal {proposal_id}."))


@app.route("/proposals/<int:proposal_id>/reopen", methods=["POST"])
def reopen(proposal_id):
    p = store.get_proposal(proposal_id)
    now = pipeline.now_iso()
    if p is None or p["status"] != "rejected":
        # Only rejected proposals can be reopened -- an "approved" one already
        # made a real CRM write, and re-approving it later would apply that
        # write a second time (there's no delete/merge to undo it with).
        return redirect(url_for("decided", flash="Only rejected proposals can be reopened."))
    store.reopen_proposal(proposal_id, now)
    return redirect(url_for("index", flash=f"Reopened proposal {proposal_id} for review."))


@app.route("/run-now", methods=["POST"])
def run_now():
    pipeline.run()
    return redirect(url_for("index", flash="Pipeline run complete."))


if __name__ == "__main__":
    store.init_db()
    app.run(debug=True, port=5000)
