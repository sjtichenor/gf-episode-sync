"""
Sync new podcast episodes from RSS feeds into the Airtable "Full Episodes" table.

Reads every record in the Shows table that has "Auto-Add Episodes" checked and an
"RSS Feed URL", pulls the feed, and records any episode we have not already logged.
Episodes are deduped on "Feed GUID", the unique id the feed itself assigns to each
episode, so re-running is safe.

Producers often create a Full Episodes record before the episode is published --
a placeholder titled with the guest's name, carrying an Episode Number but no
links. When the episode later shows up in the feed, this script claims that
placeholder and fills it in, rather than creating a second record for the same
episode. See claim_placeholder() for how the match is made.

Run hourly as a Render cron job:
    python episodes/sync_episodes.py

Environment:
    AIRTABLE_API_KEY   Airtable personal access token (also accepts
                       AIRTABLE_TOKEN / AIRTABLE_PAT / AIRTABLE_ACCESS_TOKEN)
    AIRTABLE_BASE_ID   Base id, defaults to the Good Future Media base
    EPISODE_LOOKBACK_DAYS      Ignore episodes older than this. Default 30.
                               Set to 0 to consider a show's entire back catalog.
    MAX_NEW_EPISODES_PER_SHOW  Cap on newly created records per show per run.
                               Default 25. Placeholder claims are never capped --
                               they add no rows.
    DRY_RUN                    "1" to log what would happen without writing.
"""

import os
import re
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
F_EP_LINK = "Episode Page"
F_EP_SHOW = "Show"
F_EP_GUID = "Feed GUID"
F_EP_DESC = "Episode Description"
F_EP_ART = "Episode Art"

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

    def update_records(self, table, updates):
        """updates: list of (record_id, fields). Leaves untouched fields alone."""
        updated = []
        for i in range(0, len(updates), 10):
            chunk = updates[i : i + 10]
            payload = self._request(
                "PATCH",
                table,
                json={
                    "records": [{"id": rid, "fields": f} for rid, f in chunk],
                    "typecast": False,
                },
            )
            updated.extend(payload.get("records", []))
            time.sleep(0.25)
        return updated


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


TAG_RE = re.compile(r"<[^>]+>")


def _image_href(obj):
    if not obj:
        return None
    image = obj.get("image")
    if isinstance(image, dict) and image.get("href"):
        return image["href"].strip()
    itunes = obj.get("itunes_image")
    if isinstance(itunes, dict) and itunes.get("href"):
        return itunes["href"].strip()
    return None


def entry_image(entry, feed):
    """
    Square cover art for the episode, falling back to the show's own artwork.

    Most feeds set per-episode artwork on the item (measured at ~72% of items
    across our shows), and podcast art is square by spec -- 3000x3000 in
    practice -- so the fallback never changes the shape of the image. That
    matters because an Airtable gallery takes its cover from one field: if the
    episode has no art of its own we still want something there rather than a
    hole in the grid.

    YouTube thumbnails were considered and rejected: they are 16:9 or 4:3, so
    mixing them in would give every card a different shape.
    """
    return _image_href(entry) or _image_href(feed.get("feed"))


def entry_description(entry):
    """
    Show notes for the episode, HTML stripped.

    Worth capturing because this is where the guest is actually named, and
    named in a way that separates them from the host -- "Bill Maher sits down
    with Brian Williams", "Ed Elson is joined by John Mowrey". Episode titles
    are not a reliable source: they name the host as often as the guest, and
    plenty of titles have no person in them at all.
    """
    raw = ""
    for key in ("summary", "subtitle", "description"):
        value = entry.get(key)
        if value:
            raw = value
            break
    if not raw:
        content = entry.get("content")
        if isinstance(content, list) and content:
            raw = content[0].get("value", "")
    if not raw:
        return None
    text = TAG_RE.sub(" ", raw)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&")
    text = text.replace("&lt;", "<").replace("&gt;", ">").replace("&#39;", "'")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    # Airtable long-text caps around 100k; feeds occasionally paste whole transcripts.
    return text[:50000] if text else None


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


def load_episode_index(at):
    """
    Two views of Full Episodes:

    known_guids  every Feed GUID already logged, so we never duplicate an episode.
    placeholders {(show_record_id, episode_number): record_id} for records that
                 have no Feed GUID yet -- rows a producer created ahead of
                 publication. These are what a published episode can claim.
    incomplete   {guid: (record_id, missing)} for logged episodes that predate
                 a field we now capture. Lets a later run repair them without a
                 separate migration.
    """
    known_guids = set()
    placeholders = {}
    incomplete = {}
    duplicates = set()

    for record in at.list_records(
        EPISODES_TABLE,
        fields=[F_EP_GUID, F_EP_SHOW, F_EP_NUMBER, F_EP_DESC, F_EP_ART],
    ):
        fields = record.get("fields", {})
        guid = (fields.get(F_EP_GUID) or "").strip()
        if guid:
            known_guids.add(guid)
            missing = set()
            if not (fields.get(F_EP_DESC) or "").strip():
                missing.add(F_EP_DESC)
            if not fields.get(F_EP_ART):
                missing.add(F_EP_ART)
            if missing:
                incomplete[guid] = (record["id"], missing)
            continue

        number = fields.get(F_EP_NUMBER)
        shows = fields.get(F_EP_SHOW) or []
        if number is None or not shows:
            # Nothing to match on. Left alone; a new record will be created.
            continue

        key = (shows[0], int(number))
        if key in placeholders:
            # Two placeholders claiming the same episode: ambiguous, so match
            # neither and let a human sort it out.
            duplicates.add(key)
            continue
        placeholders[key] = record["id"]

    for key in duplicates:
        placeholders.pop(key, None)
        log.warning(
            "More than one placeholder for show %s episode %s. "
            "Not matching either; resolve by hand.",
            key[0],
            key[1],
        )

    return known_guids, placeholders, incomplete


def plan_for_show(show, known_guids, placeholders, incomplete, cutoff):
    """
    Work out what this show's feed implies.

    Returns (claims, creates, backfills):
        claims    [(record_id, fields, guid, label)] placeholders to fill in
        creates   [(air_date, guid, fields)]         genuinely new episodes
        backfills [(record_id, fields)]              existing rows missing data
    """
    feed = fetch_feed(show["url"])
    if feed.bozo and not feed.entries:
        raise RuntimeError(f"could not parse feed: {feed.bozo_exception}")

    claims, creates, backfills = [], [], []

    for entry in feed.entries:
        guid = entry_guid(entry)
        if not guid:
            continue
        if guid in known_guids:
            # Already logged. It may still predate a field we now capture --
            # deliberately not subject to the lookback window, since the point
            # is to repair old rows.
            entry_needs = incomplete.pop(guid, None)
            if entry_needs:
                record_id, missing = entry_needs
                repair = {}
                if F_EP_DESC in missing:
                    description = entry_description(entry)
                    if description:
                        repair[F_EP_DESC] = description
                if F_EP_ART in missing:
                    image = entry_image(entry, feed)
                    if image:
                        repair[F_EP_ART] = [{"url": image}]
                if repair:
                    backfills.append((record_id, repair))
            continue

        air_date = entry_air_date(entry)
        if cutoff and (air_date is None or air_date < cutoff):
            # No trustworthy date, or older than the window we care about.
            continue

        fields = {
            F_EP_TITLE: entry_title(entry),
            F_EP_GUID: guid,
        }
        if air_date:
            fields[F_EP_AIR_DATE] = air_date.strftime("%Y-%m-%d")
        if entry.get("link"):
            fields[F_EP_LINK] = entry["link"].strip()
        number = entry_number(entry)
        if number is not None:
            fields[F_EP_NUMBER] = number
        description = entry_description(entry)
        if description:
            fields[F_EP_DESC] = description
        image = entry_image(entry, feed)
        if image:
            fields[F_EP_ART] = [{"url": image}]

        # Does a producer-created placeholder already stand for this episode?
        # Only episode number is trustworthy here: placeholder titles are guest
        # names or "title TBC", never the published title.
        key = (show["id"], number) if number is not None else None
        if key is not None and key in placeholders:
            record_id = placeholders.pop(key)
            claims.append((record_id, fields, guid, f"ep {number}"))
            continue

        fields[F_EP_SHOW] = [show["id"]]
        creates.append((air_date, guid, fields))

    # Oldest first, so episode order in Airtable reads naturally.
    creates.sort(key=lambda c: c[0] or datetime.min.replace(tzinfo=timezone.utc))

    if len(creates) > MAX_NEW_PER_SHOW:
        log.warning(
            "%s: %d new episodes found, capping at %d this run. "
            "Re-run or raise MAX_NEW_EPISODES_PER_SHOW to catch up.",
            show["name"],
            len(creates),
            MAX_NEW_PER_SHOW,
        )
        creates = creates[-MAX_NEW_PER_SHOW:]

    return claims, creates, backfills


def main():
    at = Airtable(get_token(), BASE_ID)

    cutoff = None
    if LOOKBACK_DAYS > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)

    shows = load_shows(at)
    if not shows:
        log.info("No shows have Auto-Add Episodes enabled. Nothing to do.")
        return 0

    known_guids, placeholders, incomplete = load_episode_index(at)
    log.info(
        "Syncing %d show(s). %d episode(s) logged, %d placeholder(s) awaiting "
        "publication. Lookback: %s. Dry run: %s.",
        len(shows),
        len(known_guids),
        len(placeholders),
        f"{LOOKBACK_DAYS}d" if cutoff else "all time",
        DRY_RUN,
    )

    total_created, total_claimed, total_backfilled, failures = 0, 0, 0, []

    for show in shows:
        try:
            claims, creates, backfills = plan_for_show(
                show, known_guids, placeholders, incomplete, cutoff
            )
        except Exception as exc:  # one bad feed must not stop the rest
            log.error("%s: feed failed (%s) — %s", show["name"], show["url"], exc)
            failures.append(show["name"])
            continue

        if backfills:
            if not DRY_RUN:
                at.update_records(EPISODES_TABLE, backfills)
            total_backfilled += len(backfills)
            log.info(
                "%s: backfilled %d existing episode(s).",
                show["name"],
                len(backfills),
            )

        if not claims and not creates:
            if not backfills:
                log.info("%s: up to date.", show["name"])
            continue

        for record_id, fields, guid, label in claims:
            if DRY_RUN:
                log.info(
                    "%s: WOULD CLAIM placeholder %s (%s) -> %s",
                    show["name"],
                    label,
                    record_id,
                    fields[F_EP_TITLE],
                )
            else:
                at.update_records(EPISODES_TABLE, [(record_id, fields)])
                known_guids.add(guid)
            log.info(
                "%s: filled in pre-created %s — %s",
                show["name"],
                label,
                fields[F_EP_TITLE],
            )
            total_claimed += 1

        if creates:
            batch = [fields for _, _, fields in creates]
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
                known_guids.update(guid for _, guid, _ in creates)
            total_created += len(batch)
            log.info("%s: added %d episode(s).", show["name"], len(batch))

    log.info(
        "Done. %d episode(s) added, %d pre-created record(s) filled in, "
        "%d existing record(s) backfilled. %d feed(s) failed.",
        total_created,
        total_claimed,
        total_backfilled,
        len(failures),
    )
    if failures:
        log.error("Failed feeds: %s", ", ".join(failures))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
