"""
Sync new podcast episodes from RSS feeds into the Airtable "Full Episodes" table.

Reads every record in the Shows table that has "Auto-Add Episodes" checked and an
"RSS Feed URL", pulls the feed, and creates a Full Episodes record for any episode
we have not already logged. Episodes are deduped on "Feed GUID", the unique id the
feed itself assigns to each episode, so re-running is safe.

Run hourly as a Render cron job:
    python episodes/sync_episodes.py

Environment:
    AIRTABLE_API_KEY   Airtable personal access token (also accepts
                       AIRTABLE_TOKEN / AIRTABLE_PAT / AIRTABLE_ACCESS_TOKEN)
    AIRTABLE_BASE_ID   Base id, defaults to the Good Future Media base
    EPISODE_LOOKBACK_DAYS      Ignore episodes older than this. Default 30.
                               Set to 0 to consider a show's entire back catalog.
    MAX_NEW_EPISODES_PER_SHOW  Safety cap per show per run. Default 25.
    DRY_RUN                    "1" to log what would be created without writing.
"""

import os
import sys
import time
import logging
from datetime import datetime, timedelta, timezone

import feedparser
import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("sync_episodes")

# --- Airtable ---------------------------------------------------------------

BASE_ID = os.environ.get("AIRTABLE_BASE_ID", "appxCYu0Tfwc6h7X7")
SHOWS_TABLE = "tblKMC5hDmmc7YsVW"
EPISODES_TABLE = "tblHBczQjSraq5hWe"

# Shows
F_SHOW_NAME = "Show Name"
F_RSS_URL = "RSS Feed URL"
F_AUTO_ADD = "Auto-Add Episodes"

# Full Episodes
F_EP_TITLE = "Episode Title"
F_EP_AIR_DATE = "Air Date"
F_EP_NUMBER = "Episode Number"
F_EP_LINK = "Full Episode Link"
F_EP_SHOW = "Show"
F_EP_GUID = "Feed GUID"

API_ROOT = "https://api.airtable.com/v0"
TOKEN_VARS = (
    "AIRTABLE_API_KEY",
    "AIRTABLE_TOKEN",
    "AIRTABLE_PAT",
    "AIRTABLE_ACCESS_TOKEN",
)

LOOKBACK_DAYS = int(os.environ.get("EPISODE_LOOKBACK_DAYS", "30"))
MAX_NEW_PER_SHOW = int(os.environ.get("MAX_NEW_EPISODES_PER_SHOW", "25"))
DRY_RUN = os.environ.get("DRY_RUN", "").strip() in ("1", "true", "True", "yes")

USER_AGENT = "GoodFutureMedia-EpisodeSync/1.0 (+https://goodfuturemedia.com)"


def get_token():
    for var in TOKEN_VARS:
        value = os.environ.get(var)
        if value:
            return value.strip()
    raise SystemExit(
        "No Airtable token found. Set one of: " + ", ".join(TOKEN_VARS)
    )


class Airtable:
    def __init__(self, token, base_id):
        self.base_id = base_id
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }
        )

    def _request(self, method, table, **kwargs):
        url = f"{API_ROOT}/{self.base_id}/{table}"
        for attempt in range(5):
            resp = self.session.request(method, url, timeout=30, **kwargs)
            if resp.status_code == 429:
                # Airtable allows 5 req/sec per base; back off and retry.
                time.sleep(1.5 * (attempt + 1))
                continue
            if resp.status_code >= 500:
                time.sleep(2 * (attempt + 1))
                continue
            resp.raise_for_status()
            return resp.json()
        resp.raise_for_status()

    def list_records(self, table, fields=None, formula=None):
        records, offset = [], None
        while True:
            params = {"pageSize": 100}
            if fields:
                params["fields[]"] = fields
            if formula:
                params["filterByFormula"] = formula
            if offset:
                params["offset"] = offset
            payload = self._request("GET", table, params=params)
            records.extend(payload.get("records", []))
            offset = payload.get("offset")
            if not offset:
                return records
            time.sleep(0.25)

    def create_records(self, table, records):
        created = []
        for i in range(0, len(records), 10):  # Airtable caps at 10 per request
            chunk = records[i : i + 10]
            payload = self._request(
                "POST",
                table,
                json={"records": [{"fields": f} for f in chunk], "typecast": False},
            )
            created.extend(payload.get("records", []))
            time.sleep(0.25)
        return created


# --- Feed parsing -----------------------------------------------------------


def fetch_feed(url):
    """Fetch a feed with a real user agent. Some hosts 403 feedparser's default."""
    resp = requests.get(
        url,
        timeout=45,
        headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, */*"},
    )
    resp.raise_for_status()
    return feedparser.parse(resp.content)


def entry_guid(entry):
    """Stable unique id for an episode, preferring the feed's own guid."""
    for key in ("id", "guid"):
        value = entry.get(key)
        if value:
            return str(value).strip()
    # Fall back to the media URL, then the page link, then the title.
    for enclosure in entry.get("enclosures") or []:
        if enclosure.get("href"):
            return enclosure["href"].strip()
    return (entry.get("link") or entry.get("title") or "").strip()


def entry_air_date(entry):
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return None
    return datetime(*parsed[:6], tzinfo=timezone.utc)


def entry_number(entry):
    raw = entry.get("itunes_episode")
    if raw is None:
        return None
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return None


def entry_title(entry):
    title = (entry.get("title") or "").strip()
    return title[:1000] if title else "(untitled episode)"


# --- Sync -------------------------------------------------------------------


def load_shows(at):
    shows = []
    for record in at.list_records(
        SHOWS_TABLE, fields=[F_SHOW_NAME, F_RSS_URL, F_AUTO_ADD]
    ):
        fields = record.get("fields", {})
        if not fields.get(F_AUTO_ADD):
            continue
        url = (fields.get(F_RSS_URL) or "").strip()
        if not url:
            log.warning(
                "%s has Auto-Add Episodes on but no RSS Feed URL, skipping.",
                fields.get(F_SHOW_NAME, record["id"]),
            )
            continue
        shows.append(
            {
                "id": record["id"],
                "name": fields.get(F_SHOW_NAME) or record["id"],
                "url": url,
            }
        )
    return shows


def load_known_guids(at):
    """Every Feed GUID already in Full Episodes, so we never create a duplicate."""
    guids = set()
    for record in at.list_records(EPISODES_TABLE, fields=[F_EP_GUID]):
        guid = (record.get("fields", {}).get(F_EP_GUID) or "").strip()
        if guid:
            guids.add(guid)
    return guids


def new_episodes_for_show(show, known_guids, cutoff):
    """Return field dicts for episodes in this show's feed we have not logged."""
    feed = fetch_feed(show["url"])
    if feed.bozo and not feed.entries:
        raise RuntimeError(f"could not parse feed: {feed.bozo_exception}")

    candidates = []
    for entry in feed.entries:
        guid = entry_guid(entry)
        if not guid or guid in known_guids:
            continue

        air_date = entry_air_date(entry)
        if cutoff and air_date and air_date < cutoff:
            continue
        if cutoff and air_date is None:
            # No date we can trust; skip rather than backfill an unknown archive.
            continue

        fields = {
            F_EP_TITLE: entry_title(entry),
            F_EP_GUID: guid,
            F_EP_SHOW: [show["id"]],
        }
        if air_date:
            fields[F_EP_AIR_DATE] = air_date.strftime("%Y-%m-%d")
        if entry.get("link"):
            fields[F_EP_LINK] = entry["link"].strip()
        number = entry_number(entry)
        if number is not None:
            fields[F_EP_NUMBER] = number

        candidates.append((air_date, guid, fields))

    # Oldest first, so episode order in Airtable reads naturally.
    candidates.sort(key=lambda c: c[0] or datetime.min.replace(tzinfo=timezone.utc))

    if len(candidates) > MAX_NEW_PER_SHOW:
        log.warning(
            "%s: %d new episodes found, capping at %d this run. "
            "Re-run or raise MAX_NEW_EPISODES_PER_SHOW to catch up.",
            show["name"],
            len(candidates),
            MAX_NEW_PER_SHOW,
        )
        candidates = candidates[-MAX_NEW_PER_SHOW:]

    return candidates


def main():
    at = Airtable(get_token(), BASE_ID)

    cutoff = None
    if LOOKBACK_DAYS > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)

    shows = load_shows(at)
    if not shows:
        log.info("No shows have Auto-Add Episodes enabled. Nothing to do.")
        return 0

    known_guids = load_known_guids(at)
    log.info(
        "Syncing %d show(s). %d episode(s) already logged. Lookback: %s. Dry run: %s.",
        len(shows),
        len(known_guids),
        f"{LOOKBACK_DAYS}d" if cutoff else "all time",
        DRY_RUN,
    )

    total_created, failures = 0, []

    for show in shows:
        try:
            candidates = new_episodes_for_show(show, known_guids, cutoff)
        except Exception as exc:  # one bad feed must not stop the rest
            log.error("%s: feed failed (%s) — %s", show["name"], show["url"], exc)
            failures.append(show["name"])
            continue

        if not candidates:
            log.info("%s: up to date.", show["name"])
            continue

        batch = [fields for _, _, fields in candidates]
        if DRY_RUN:
            for fields in batch:
                log.info(
                    "%s: WOULD CREATE %s (%s)",
                    show["name"],
                    fields[F_EP_TITLE],
                    fields.get(F_EP_AIR_DATE, "no date"),
                )
        else:
            at.create_records(EPISODES_TABLE, batch)
            # Guard against the same guid appearing twice in one run.
            known_guids.update(guid for _, guid, _ in candidates)

        total_created += len(batch)
        log.info("%s: added %d episode(s).", show["name"], len(batch))

    log.info(
        "Done. %d episode(s) %s. %d feed(s) failed.",
        total_created,
        "would be added" if DRY_RUN else "added",
        len(failures),
    )
    if failures:
        log.error("Failed feeds: %s", ", ".join(failures))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
