#!/usr/bin/env python3
"""Sync Woodpecker prospects marked INTERESTED into GoHighLevel (LeadConnector).

For each interested prospect:
  1. Skip it if a GHL contact with that email already carries the sync tag
     (so contacts are never overwritten twice and workflows don't re-fire).
  2. Upsert the contact (create or update by email).
  3. Add the sync tag. Adding a tag doesn't remove existing ones, so it can
     trigger a GHL workflow ("Contact Tag added").

Environment variables:
  WOODPECKER_API_KEY   required
  GHL_TOKEN            required (Private Integration Token, contacts.write + contacts.readonly)
  GHL_LOCATION_ID      required
  GHL_TAG              optional, default "woodpecker-interested"
  WOODPECKER_CAMPAIGNS optional, comma-separated campaign IDs to limit the sync

Usage:
  python scripts/woodpecker_to_ghl.py            # sync
  python scripts/woodpecker_to_ghl.py --dry-run  # list what would be sent, write nothing
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

WOODPECKER_URL = "https://api.woodpecker.co/rest/v1/prospects"
GHL_BASE = "https://services.leadconnectorhq.com"
GHL_VERSION = "2021-07-28"
USER_AGENT = "veth-woodpecker-ghl-sync/1.0"


def env(name, default=None, required=True):
    value = os.environ.get(name, default)
    if required and not value:
        sys.exit(f"Missing environment variable {name}")
    return value


def http(method, url, headers, body=None, retries=3):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Accept": "application/json", "User-Agent": USER_AGENT, **headers}
    if data is not None:
        headers["Content-Type"] = "application/json"
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read()
                return json.loads(raw) if raw.strip() else None
        except urllib.error.HTTPError as e:
            # Retry on rate limits and server errors.
            if e.code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(2 ** (attempt + 1))
                continue
            detail = e.read().decode(errors="replace")[:500]
            raise RuntimeError(f"{method} {url} -> HTTP {e.code}: {detail}") from None


def fetch_interested(api_key, campaigns):
    """Yield unique prospects marked INTERESTED in any campaign."""
    seen = set()
    page = 1
    while True:
        params = {"interested": "INTERESTED", "per_page": 500, "page": page, "sort": "+id"}
        if campaigns:
            params["campaigns_id"] = campaigns
        url = f"{WOODPECKER_URL}?{urllib.parse.urlencode(params)}"
        batch = http("GET", url, {"x-api-key": api_key}) or []
        if isinstance(batch, dict):  # Woodpecker returns an object on errors / no results
            if batch.get("status", {}).get("status") == "ERROR":
                raise RuntimeError(f"Woodpecker error: {batch}")
            break
        for p in batch:
            # A prospect interested in N campaigns appears N times.
            if p.get("id") in seen or not p.get("email"):
                continue
            seen.add(p["id"])
            yield p
        if len(batch) < 500:
            break
        page += 1


def ghl_headers(token):
    return {"Authorization": f"Bearer {token}", "Version": GHL_VERSION}


def existing_contact(token, location_id, email):
    q = urllib.parse.urlencode({"locationId": location_id, "email": email})
    res = http("GET", f"{GHL_BASE}/contacts/search/duplicate?{q}", ghl_headers(token)) or {}
    return res.get("contact")


def to_ghl_contact(p, location_id):
    fields = {
        "locationId": location_id,
        "email": p.get("email"),
        "firstName": p.get("first_name"),
        "lastName": p.get("last_name"),
        "phone": p.get("phone"),
        "companyName": p.get("company"),
        "website": p.get("website"),
        "address1": p.get("address"),
        "city": p.get("city"),
        "state": p.get("state"),
        "source": "Woodpecker",
    }
    return {k: v for k, v in fields.items() if v}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="show what would be synced without writing to GHL")
    args = ap.parse_args()

    wp_key = env("WOODPECKER_API_KEY")
    token = env("GHL_TOKEN")
    location_id = env("GHL_LOCATION_ID")
    tag = env("GHL_TAG", "woodpecker-interested", required=False) or "woodpecker-interested"
    campaigns = env("WOODPECKER_CAMPAIGNS", required=False)

    created = skipped = failed = 0
    for p in fetch_interested(wp_key, campaigns):
        email = p["email"].strip().lower()
        try:
            existing = existing_contact(token, location_id, email)
            if existing and tag in (existing.get("tags") or []):
                skipped += 1
                continue
            if args.dry_run:
                print(f"[dry-run] would sync {email} ({p.get('company') or '-'})")
                created += 1
                continue
            res = http("POST", f"{GHL_BASE}/contacts/upsert", ghl_headers(token), to_ghl_contact(p, location_id))
            contact_id = (res or {}).get("contact", {}).get("id")
            if not contact_id:
                raise RuntimeError(f"upsert returned no contact id: {res}")
            http("POST", f"{GHL_BASE}/contacts/{contact_id}/tags", ghl_headers(token), {"tags": [tag]})
            print(f"synced {email} -> {contact_id}")
            created += 1
        except Exception as e:  # keep going; report at the end
            failed += 1
            print(f"FAILED {email}: {e}", file=sys.stderr)

    verb = "would sync" if args.dry_run else "synced"
    print(f"Done: {verb} {created}, already in GHL {skipped}, failed {failed}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
