# Veth automations

## Woodpecker → GoHighLevel sync

`scripts/woodpecker_to_ghl.py` copies every Woodpecker prospect marked **Interested**
into GoHighLevel as a contact (source `Woodpecker`) and tags it `woodpecker-interested`.
Contacts that already have the tag are skipped, so each lead is sent once.

Runs every 30 minutes via `.github/workflows/woodpecker-to-ghl.yml`, or manually from the Actions tab.

**Setup (repo Settings → Secrets and variables → Actions):**

| Secret | Value |
|---|---|
| `WOODPECKER_API_KEY` | Woodpecker → Marketplace → Integrations → API keys |
| `GHL_TOKEN` | GHL Private Integration Token (scopes: contacts read + write) |
| `GHL_LOCATION_ID` | GHL sub-account (location) ID |

Optional variables: `GHL_TAG` (default `woodpecker-interested`), `WOODPECKER_CAMPAIGNS` (comma-separated campaign IDs).

Local run: `WOODPECKER_API_KEY=… GHL_TOKEN=… GHL_LOCATION_ID=… python scripts/woodpecker_to_ghl.py --dry-run`

**First run:** Actions → "Woodpecker → GoHighLevel sync" → Run workflow → tick *Dry run* → check the log, then run again without it.
