"""Applies an approved proposal to the CRM. Called only from the review app's
approve action -- nothing in this pipeline ever writes to the CRM without a
human clicking approve first.
"""
import crm_client


def apply_proposal(p):
    ct = p["change_type"]
    changes = p["proposed_changes"]

    if ct == "create_account":
        result = crm_client.create_account(changes)
        return {"created_account_id": result["account_id"]}

    if ct in ("update_fields", "mark_duplicate", "flag_review"):
        account_id = p["account_ids"][0]
        crm_client.update_account(account_id, changes)
        return {"updated_account_id": account_id}

    if ct == "chow_split":
        created = crm_client.create_account(changes["new_account"])
        new_id = created["account_id"]
        old_id = p["account_ids"][0]
        crm_client.update_account(old_id, {"chow_current_account": new_id})
        return {"created_account_id": new_id, "chow_old_account_id": old_id}

    if ct == "ambiguous_choice":
        if "new_account" in changes:
            created = crm_client.create_account(changes["new_account"])
            new_id = created["account_id"]
            old_id = p["account_ids"][0]
            crm_client.update_account(old_id, {"chow_current_account": new_id})
            return {"created_account_id": new_id, "chow_old_account_id": old_id}
        account_id = p["account_ids"][0]
        crm_client.update_account(account_id, changes)
        return {"updated_account_id": account_id}

    raise ValueError(f"Unknown change_type: {ct}")
