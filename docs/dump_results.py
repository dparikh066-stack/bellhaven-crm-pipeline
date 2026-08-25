import json
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.chdir(os.path.join(os.path.dirname(__file__), ".."))
import store

CLASS_LABEL = {
    "confident_match": "Confident match",
    "needs_fix": "Needs fix",
    "new_location": "New location",
    "orphan": "Orphan",
    "duplicate": "Duplicate",
    "duplicate_needs_review": "Dup (has AR)",
    "ambiguous": "Ambiguous",
}


def account_label(p):
    ev = p["evidence"]
    if ev.get("location"):
        return ev["location"]["name"]
    if ev.get("account"):
        return ev["account"]["name"]
    return p.get("location_slug") or ", ".join(p["account_ids"])


def summarize_change(p):
    ct = p["change_type"]
    pc = p["proposed_changes"]
    if ct == "create_account":
        return f"Created new account under Bellhaven ({pc.get('billing_city')}, {pc.get('billing_state')})"
    if ct == "chow_split":
        na = pc["new_account"]
        return f"CHOW split: old preserved, new account created under Bellhaven ({na['billing_city']})"
    if ct == "mark_duplicate":
        return f"Marked duplicate of {pc.get('duplicate_of_account')}, status -> Inactive"
    if ct == "flag_review":
        return f"status -> {pc.get('status')}"
    if ct == "ambiguous_choice":
        return "Ambiguous alternative (renamed + re-parented if approved)"
    if ct == "update_fields":
        fields = [k for k in pc if k not in ("note",)]
        return "Updated: " + ", ".join(fields)
    return str(pc)


rows = []
for p in store.list_proposals():
    if p["status"] not in ("approved", "rejected"):
        continue
    rows.append({
        "id": p["id"],
        "name": account_label(p),
        "classification": CLASS_LABEL.get(p["classification"], p["classification"]),
        "change_type": p["change_type"],
        "summary": summarize_change(p),
        "status": p["status"],
        "result": p["decision_note"],
    })

print(json.dumps(rows, indent=2))
print(f"\nTOTAL: {len(rows)} decided proposals", file=sys.stderr)
