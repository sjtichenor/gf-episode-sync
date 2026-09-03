# GF Episode Sync

Pulls new podcast episodes from RSS feeds into the Airtable **Full Episodes** table
(Good Future Media base, `appxCYu0Tfwc6h7X7`).

Runs hourly on Render as the cron job **Episode sync (RSS to Airtable)**
(`crn-dacs24nqj5pc739g7i3g`).

## How it works

1. Reads the **Shows** table for records with **Auto-Add Episodes** checked and an
   **RSS Feed URL** set.
2. Fetches each feed and compares every entry's feed-assigned GUID against the
   **Feed GUID** column already in Full Episodes.
3. Creates a Full Episodes record for anything new, linked back to its Show.

Dedupe is on **Feed GUID**, so re-running never creates duplicates. Do not edit
that column by hand.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `AIRTABLE_API_KEY` | — | Airtable PAT. Also accepts `AIRTABLE_TOKEN`, `AIRTABLE_PAT`, `AIRTABLE_ACCESS_TOKEN`. Needs `data.records:read` and `data.records:write` on the base. |
| `AIRTABLE_BASE_ID` | `appxCYu0Tfwc6h7X7` | Target base. |
| `EPISODE_LOOKBACK_DAYS` | `30` | Ignore episodes older than this. `0` means the entire back catalog. |
| `MAX_NEW_EPISODES_PER_SHOW` | `25` | Per-show cap per run. Keeps a first run from dumping a 1,500-episode archive. |
| `DRY_RUN` | unset | `1` logs what would be created without writing. |

## Local run

```bash
python -m venv .venv && ./.venv/bin/pip install -r requirements.txt
AIRTABLE_API_KEY=pat... DRY_RUN=1 ./.venv/bin/python episodes/sync_episodes.py
```

## Notes

- Feeds carry deep archives (Breaking Points 1,667 entries, 20VC 1,504). The
  lookback window and per-show cap are what keep the first run sane.
- A show whose feed has gone quiet simply adds nothing; it is not an error.
- One failing feed does not stop the others. The job exits non-zero if any feed
  failed, so Render's failure notification still fires.
