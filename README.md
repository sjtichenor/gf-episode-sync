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
3. For anything new, either **claims a pre-created placeholder** (see below) or
   creates a fresh Full Episodes record linked back to its Show.

Dedupe is on **Feed GUID**, so re-running never creates duplicates. Do not edit
that column by hand.

## Pre-created episodes

Producers often add a Full Episodes row before the episode is published -- titled
with the guest's name or "title TBC", carrying an **Episode Number** but no links.
When that episode later appears in the feed, the sync fills in the existing row
rather than creating a second one, so clips already attached stay attached.

The match is **Show + Episode Number**, against rows that have no Feed GUID yet.
Title is deliberately not used: placeholder titles are guest names, never the
published title. On a claim, the sync writes Feed GUID, Air Date, Full Episode
Link, and **overwrites the placeholder title** with the published one.

Consequences worth knowing:

- Set the **Episode Number** on a placeholder or it cannot be matched, and you
  will get a duplicate row when the episode publishes.
- Shows whose feeds carry no episode numbers (ThursdAI, 20VC, Diary of a CEO,
  Breaking Points, Prof G Markets, Founders, Lightspeed, Talking Tokens, The
  Huddle, The Morning Meeting) can never be matched. Placeholders for these are
  left alone and a separate row is created; reconcile by hand.
- If two placeholders share a show and episode number, neither is matched and a
  warning is logged.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `AIRTABLE_API_KEY` | — | Airtable PAT. Also accepts `AIRTABLE_TOKEN`, `AIRTABLE_PAT`, `AIRTABLE_ACCESS_TOKEN`. Needs `data.records:read` and `data.records:write` on the base. |
| `AIRTABLE_BASE_ID` | `appxCYu0Tfwc6h7X7` | Target base. |
| `EPISODE_LOOKBACK_DAYS` | `30` | Ignore episodes older than this. `0` means the entire back catalog. |
| `MAX_NEW_EPISODES_PER_SHOW` | `25` | Cap on newly created rows per show per run. Keeps a first run from dumping a 1,500-episode archive. Claims of pre-created rows are never capped, since they add no rows. |
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
- Roughly 107 rows predating this job have no Feed GUID. They are all older than
  the lookback window, so they neither match nor duplicate anything today. They
  would be re-created as new rows if you ever set `EPISODE_LOOKBACK_DAYS=0`.
- One failing feed does not stop the others. The job exits non-zero if any feed
  failed, so Render's failure notification still fires.
