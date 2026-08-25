"""Thin client for the Bellhaven CRM sandbox API."""
import json
import os
import urllib.request
import urllib.error
import urllib.parse

BASE = "https://analyst-assessment-production.up.railway.app/api/v1"
TOKEN = os.environ["BELLHAVEN_CRM_TOKEN"]


class CrmError(RuntimeError):
    def __init__(self, status, body):
        super().__init__(f"CRM API error {status}: {body}")
        self.status = status
        self.body = body


def _request(method, path, params=None, json_body=None):
    url = f"{BASE}{path}"
    if params:
        qs = urllib.parse.urlencode({k: v for k, v in params.items() if v not in (None, "")})
        if qs:
            url = f"{url}?{qs}"
    data = None
    headers = {"Authorization": f"Bearer {TOKEN}"}
    if json_body is not None:
        data = json.dumps(json_body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else None
    except urllib.error.HTTPError as e:
        raise CrmError(e.code, e.read().decode("utf-8", "replace")) from None


def list_accounts(q="", city="", state="", zip="", street="", parent_id="", page=1, page_size=200):
    return _request(
        "GET",
        "/accounts",
        params={
            "q": q, "city": city, "state": state, "zip": zip,
            "street": street, "parent_id": parent_id,
            "page": page, "page_size": page_size,
        },
    )


def list_all_accounts(**kwargs):
    """Fetch every page of accounts (handles server-side pagination)."""
    kwargs.setdefault("page_size", 200)
    page = 1
    out = []
    while True:
        resp = list_accounts(page=page, **kwargs)
        data = resp.get("data", [])
        out.extend(data)
        total = resp.get("total", len(out))
        if len(out) >= total or not data:
            break
        page += 1
    return out


def get_account(account_id):
    return _request("GET", f"/accounts/{account_id}")


def create_account(fields):
    return _request("POST", "/accounts", json_body=fields)


def update_account(account_id, fields):
    return _request("PATCH", f"/accounts/{account_id}", json_body=fields)


def list_contacts(account_id="", q="", page=1, page_size=200):
    return _request("GET", "/contacts", params={"account_id": account_id, "q": q, "page": page, "page_size": page_size})


def me():
    return _request("GET", "/me")
