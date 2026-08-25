"""Matching + classification logic: links scraped Bellhaven website locations
to CRM accounts and turns the result into a list of proposed CRM changes.

Classification buckets (per the assignment spec):
  - confident_match : right account, already correctly parented/named. May still
                      carry small field-sync proposals (phone/address/care type).
  - needs_fix       : right account exists but parent and/or name is wrong.
  - new_location    : no plausible CRM account exists yet -> propose create.
  - orphan          : CRM account currently under the Bellhaven parent that no
                      longer appears on the scraped website.
  - ambiguous       : two or more CRM accounts sit at the same address, none of
                      them already correctly Bellhaven-branded -> can't safely
                      auto-pick a winner, so every candidate is proposed as a
                      mutually exclusive alternative for a human to choose.
  - duplicate       : a second CRM account at the same address as an already-
                      confirmed match (or ambiguous winner) -> propose marking
                      it a duplicate, unless it carries real billing history.

CHOW (change-of-ownership) SOP: whenever a location's proposal would move an
EXISTING account to a different parent, check lifetime_revenue and
outstanding_ar first. If the account has revenue history AND outstanding AR
> 0, don't touch its parent -- create a new account under the correct parent
and set chow_current_account on the old one to point at the new account's id.
Otherwise, re-parent the existing account directly.

The same revenue/AR caution is applied (by extension, not explicitly required
by the SOP) before ever marking an account Inactive as a duplicate: if it has
real revenue + outstanding AR, we don't silently deactivate it -- we flag it
for human review instead so nothing with live billing gets steamrolled.
"""
import difflib
import re

BELLHAVEN_PARENT_NAME = "Bellhaven Senior Living (Parent Account)"

# Vocabulary differs between the website's care-offering badges and the CRM's
# single-select care_type field. Mapping inferred from confidently-matched pairs.
CARE_TYPE_MAP = {
    "assisted living": "Assisted Living",
    "memory support": "Memory Care",
    "short-term rehabilitation & nursing": "Skilled Nursing",
}

STREET_ABBR = {
    "street": "st", "avenue": "ave", "road": "rd", "drive": "dr",
    "boulevard": "blvd", "lane": "ln", "west": "w", "east": "e",
    "north": "n", "south": "s", "parkway": "pkwy",
}


def norm_street(s):
    s = (s or "").lower().strip()
    s = re.sub(r"[^a-z0-9 ]", "", s)
    words = [STREET_ABBR.get(w, w) for w in s.split()]
    return " ".join(words)


def norm_name(s):
    s = (s or "").lower()
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    words = [w for w in s.split() if w not in ("the", "of", "at", "a", "-")]
    return " ".join(words)


def map_care_type(offerings):
    """Website care-offering badges (possibly several) -> single CRM care_type.
    Uses the first badge as primary; extra offerings are surfaced in evidence
    so the reviewer can decide whether to note them, since CRM only holds one.
    """
    for o in offerings or []:
        mapped = CARE_TYPE_MAP.get(o.strip().lower())
        if mapped:
            return mapped
    return offerings[0] if offerings else ""


def score_pair(loc, acct):
    street_sim = difflib.SequenceMatcher(None, norm_street(loc["street"]), norm_street(acct.get("billing_street"))).ratio()
    name_sim = difflib.SequenceMatcher(None, norm_name(loc["name"]), norm_name(acct.get("name"))).ratio()
    zip_match = loc["zip"] == acct.get("billing_zip")
    city_match = loc["city"].strip().lower() == (acct.get("billing_city") or "").strip().lower()
    state_match = loc["state"] == acct.get("billing_state")
    combined = 0.4 * street_sim + 0.25 * name_sim + 0.2 * zip_match + 0.1 * city_match + 0.05 * state_match
    return {
        "street_sim": round(street_sim, 3),
        "name_sim": round(name_sim, 3),
        "zip_match": zip_match,
        "city_match": city_match,
        "state_match": state_match,
        "combined": round(combined, 3),
    }


def is_address_confirmed(s):
    """Same physical address: zip matches and the street reads the same."""
    return s["zip_match"] and s["street_sim"] >= 0.75


def is_identity_confirmed(s):
    """Same facility even if one field is stale (e.g. a PO-box billing street,
    or a transposed zip digit) -- name/city/state carry enough signal alone."""
    if s["zip_match"] and s["city_match"] and s["name_sim"] >= 0.85:
        return True
    if s["name_sim"] >= 0.95 and s["street_sim"] >= 0.85 and s["city_match"] and s["state_match"]:
        return True
    return False


def resolve_bellhaven_parent(accounts):
    for a in accounts:
        if a["name"] == BELLHAVEN_PARENT_NAME and not a["parent_id"]:
            return a
    raise RuntimeError(f"Could not find parent account named {BELLHAVEN_PARENT_NAME!r}")


def needs_chow_split(account):
    """CHOW SOP: preserve the old account (don't reparent it) only when it has
    BOTH revenue history AND currently-outstanding AR."""
    return (account.get("lifetime_revenue") or 0) > 0 and (account.get("outstanding_ar") or 0) > 0


def field_diffs(loc, acct):
    """Field-level sync proposals for an already-identified match: name,
    address, phone, care_type -- whatever differs from the scraped source."""
    diffs = {}
    if norm_name(loc["name"]) != norm_name(acct.get("name")):
        diffs["name"] = loc["name"]
    if norm_street(loc["street"]) != norm_street(acct.get("billing_street")):
        diffs["billing_street"] = loc["street"]
    if loc["city"].strip().lower() != (acct.get("billing_city") or "").strip().lower():
        diffs["billing_city"] = loc["city"]
    if loc["state"] != acct.get("billing_state"):
        diffs["billing_state"] = loc["state"]
    if loc["zip"] != acct.get("billing_zip"):
        diffs["billing_zip"] = loc["zip"]
    mapped_care = map_care_type(loc["care_offerings"])
    if mapped_care and mapped_care != acct.get("care_type"):
        diffs["care_type"] = mapped_care
    site_phone = loc.get("phone") or ""
    if site_phone and site_phone != (acct.get("phone") or ""):
        diffs["phone"] = site_phone
    return diffs


def new_account_payload(loc, parent_id):
    return {
        "name": loc["name"],
        "parent_id": parent_id,
        "billing_street": loc["street"],
        "billing_city": loc["city"],
        "billing_state": loc["state"],
        "billing_zip": loc["zip"],
        "care_type": map_care_type(loc["care_offerings"]),
        "phone": loc.get("phone") or "",
        "status": "Active",
    }


def build_proposals(locations, accounts):
    """Core matching pass. Returns a list of proposal dicts (see pipeline.py
    for the exact schema each change_type produces). Pure function of its
    inputs -- no I/O, no side effects -- so it's trivial to test and it's
    naturally idempotent: same CRM+website state in, same proposals out.
    """
    bh_parent = resolve_bellhaven_parent(accounts)
    bh_parent_id = bh_parent["account_id"]

    proposals = []
    claimed_account_ids = set()  # accounts already "spoken for" by a location match

    # Pass 1: match every scraped location against the CRM roster.
    location_results = []  # (loc, classification, anchor_account_or_None, candidates)
    for loc in locations:
        scored = []
        for a in accounts:
            s = score_pair(loc, a)
            scored.append((a, s))
        scored.sort(key=lambda pair: -pair[1]["combined"])

        address_confirmed = [(a, s) for a, s in scored if is_address_confirmed(s)]
        identity_confirmed = [(a, s) for a, s in scored if is_identity_confirmed(s)]
        # union, de-duplicated, preserving score order
        seen_ids = set()
        confirmed = []
        for a, s in address_confirmed + identity_confirmed:
            if a["account_id"] not in seen_ids:
                seen_ids.add(a["account_id"])
                confirmed.append((a, s))
        confirmed.sort(key=lambda pair: -pair[1]["combined"])

        if not confirmed:
            location_results.append((loc, "new_location", None, []))
            continue

        # Is there already a candidate correctly parented+named under Bellhaven?
        anchor = None
        for a, s in confirmed:
            if a["parent_id"] == bh_parent_id and s["name_sim"] >= 0.85:
                anchor = (a, s)
                break

        if anchor is None and len(confirmed) >= 2:
            # Multiple plausible same-address accounts, none already the
            # correct Bellhaven record -> can't safely auto-pick. Ask a human.
            location_results.append((loc, "ambiguous", None, confirmed))
            continue

        if anchor is None:
            anchor = confirmed[0]

        anchor_acct, anchor_score = anchor
        claimed_account_ids.add(anchor_acct["account_id"])
        others = [(a, s) for a, s in confirmed if a["account_id"] != anchor_acct["account_id"]]
        classification = "confident_match" if (
            anchor_acct["parent_id"] == bh_parent_id and anchor_score["name_sim"] >= 0.85
        ) else "needs_fix"
        location_results.append((loc, classification, (anchor_acct, anchor_score), others))

    # Pass 2: turn location_results into proposals.
    for loc, classification, anchor, others in location_results:
        if classification == "new_location":
            proposals.append({
                "change_type": "create_account",
                "classification": "new_location",
                "location_slug": loc["slug"],
                "account_ids": [],
                "proposed_changes": new_account_payload(loc, bh_parent_id),
                "evidence": {"location": loc, "top_candidates": []},
                "note": f"No CRM account found matching {loc['name']!r} ({loc['street']}, {loc['city']} {loc['state']} {loc['zip']}). Proposing a new account under Bellhaven Senior Living.",
            })
            continue

        if classification == "ambiguous":
            group_key = f"ambiguous:{loc['slug']}"
            for a, s in others:
                chow = needs_chow_split(a)
                proposals.append({
                    "change_type": "ambiguous_choice",
                    "classification": "ambiguous",
                    "location_slug": loc["slug"],
                    "account_ids": [a["account_id"]],
                    "ambiguous_group": group_key,
                    "needs_chow": chow,
                    "proposed_changes": (
                        {"new_account": new_account_payload(loc, bh_parent_id)} if chow
                        else {"name": loc["name"], "parent_id": bh_parent_id, **{k: v for k, v in field_diffs(loc, a).items() if k not in ("name",)}}
                    ),
                    "evidence": {"location": loc, "account": a, "score": s, "sibling_account_ids": [x["account_id"] for x, _ in others]},
                    "note": (
                        f"{len(others)} different CRM accounts sit at {loc['street']}, {loc['city']} {loc['state']} {loc['zip']} "
                        f"and none is already the correctly-branded Bellhaven record. This is one candidate ({a['name']!r}, "
                        f"currently under {a['parent_name'] or 'no parent'!r}) to become {loc['name']!r} under Bellhaven. "
                        + ("Has revenue+outstanding AR, so a NEW account would be created and this one preserved via chow_current_account. " if chow else "")
                        + "Approve at most one of these alternatives; approving one auto-rejects the others."
                    ),
                })
            continue

        # confident_match or needs_fix: we have an anchor account.
        anchor_acct, anchor_score = anchor
        diffs = field_diffs(loc, anchor_acct)
        parent_wrong = anchor_acct["parent_id"] != bh_parent_id

        if parent_wrong:
            if needs_chow_split(anchor_acct):
                proposals.append({
                    "change_type": "chow_split",
                    "classification": "needs_fix",
                    "location_slug": loc["slug"],
                    "account_ids": [anchor_acct["account_id"]],
                    "proposed_changes": {
                        "new_account": new_account_payload(loc, bh_parent_id),
                    },
                    "evidence": {"location": loc, "account": anchor_acct, "score": anchor_score},
                    "note": (
                        f"{anchor_acct['name']!r} is currently under {anchor_acct['parent_name']!r} but matches "
                        f"{loc['name']!r} on the Bellhaven site. It has lifetime_revenue={anchor_acct['lifetime_revenue']} "
                        f"and outstanding_ar={anchor_acct['outstanding_ar']} (both > 0), so per the CHOW SOP the old "
                        f"account is left alone and a new account is created under Bellhaven, linked via chow_current_account."
                    ),
                })
            else:
                changes = {"parent_id": bh_parent_id, **diffs}
                proposals.append({
                    "change_type": "update_fields",
                    "classification": "needs_fix",
                    "location_slug": loc["slug"],
                    "account_ids": [anchor_acct["account_id"]],
                    "proposed_changes": changes,
                    "evidence": {"location": loc, "account": anchor_acct, "score": anchor_score},
                    "note": (
                        f"{anchor_acct['name']!r} is currently under {anchor_acct['parent_name']!r} but matches "
                        f"{loc['name']!r} on the Bellhaven site. No outstanding AR / no revenue history, so re-parenting "
                        f"the existing account directly (no CHOW split needed)."
                    ),
                })
        elif diffs:
            proposals.append({
                "change_type": "update_fields",
                "classification": classification,
                "location_slug": loc["slug"],
                "account_ids": [anchor_acct["account_id"]],
                "proposed_changes": diffs,
                "evidence": {"location": loc, "account": anchor_acct, "score": anchor_score},
                "note": f"{anchor_acct['name']!r} already correctly under Bellhaven; syncing {', '.join(diffs)} from the website.",
            })
        else:
            proposals.append({
                "change_type": "no_op",
                "classification": "confident_match",
                "location_slug": loc["slug"],
                "account_ids": [anchor_acct["account_id"]],
                "proposed_changes": {},
                "evidence": {"location": loc, "account": anchor_acct, "score": anchor_score},
                "note": f"{anchor_acct['name']!r} matches {loc['name']!r} exactly. No changes needed.",
            })

        # Duplicate candidates: other CRM accounts sitting at the same address.
        for a, s in others:
            if a["account_id"] in claimed_account_ids:
                continue
            claimed_account_ids.add(a["account_id"])
            if needs_chow_split(a):
                explanation = (
                    f"Daily Bellhaven sync: sits at the same address as {anchor_acct['name']!r} "
                    f"(account {anchor_acct['account_id']}), which is already the correct match for "
                    f"{loc['name']!r}. Looks like a stale duplicate, but has lifetime_revenue={a['lifetime_revenue']} "
                    f"and outstanding_ar={a['outstanding_ar']}, so NOT auto-marked a duplicate -- needs human review."
                )
                proposals.append({
                    "change_type": "flag_review",
                    "classification": "duplicate_needs_review",
                    "location_slug": loc["slug"],
                    "account_ids": [a["account_id"]],
                    "proposed_changes": {"status": "Needs Review", "note": explanation},
                    "evidence": {"location": loc, "account": a, "score": s, "matched_account_id": anchor_acct["account_id"]},
                    "note": explanation,
                })
            else:
                explanation = (
                    f"Daily Bellhaven sync: duplicate of account {anchor_acct['account_id']} "
                    f"({anchor_acct['name']!r}), which is the correct match for {loc['name']!r} at this address. "
                    f"No revenue/AR on this account, so marked Inactive."
                )
                proposals.append({
                    "change_type": "mark_duplicate",
                    "classification": "duplicate",
                    "location_slug": loc["slug"],
                    "account_ids": [a["account_id"]],
                    "proposed_changes": {"duplicate_of_account": anchor_acct["account_id"], "status": "Inactive", "note": explanation},
                    "evidence": {"location": loc, "account": a, "score": s, "matched_account_id": anchor_acct["account_id"]},
                    "note": explanation,
                })

    # Pass 3: orphans -- Bellhaven-parented accounts no location claimed.
    for a in accounts:
        if a["parent_id"] == bh_parent_id and a["account_id"] not in claimed_account_ids and a["status"] != "Inactive":
            explanation = (
                f"Daily Bellhaven sync: under Bellhaven Senior Living in the CRM but no longer appears on the "
                f"Bellhaven website ({len(locations)} communities scraped). "
                f"lifetime_revenue={a['lifetime_revenue']}, outstanding_ar={a['outstanding_ar']}. "
                + ("Has real billing history -- do not deactivate without billing team sign-off. " if (a['lifetime_revenue'] or a['outstanding_ar']) else "")
                + "Flagged for human review rather than assuming closure/divestiture."
            )
            proposals.append({
                "change_type": "flag_review",
                "classification": "orphan",
                "location_slug": None,
                "account_ids": [a["account_id"]],
                "proposed_changes": {"status": "Needs Review", "note": explanation},
                "evidence": {"account": a},
                "note": explanation,
            })

    return proposals
