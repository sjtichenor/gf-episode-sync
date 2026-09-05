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
    MAX_PAGE_IMAGE_FETCHES     Cap on episode-page fetches per run when looking
                               for cover art. Default 60, which keeps a run
                               short; the rest are picked up next hour.
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
F_SHOW_YOUTUBE = "YouTube Channel"

# Full Episodes
F_EP_TITLE = "Episode Title"
F_EP_AIR_DATE = "Air Date"
F_EP_NUMBER = "Episode Number"
F_EP_LINK = "Episode Page"
F_EP_SHOW = "Show"
F_EP_GUID = "Feed GUID"
F_EP_DESC = "Episode Description"
F_EP_ART = "Episode Art"
F_EP_YOUTUBE = "YouTube Link"
F_EP_LENGTH = "Episode Length"

API_ROOT = "https://api.airtable.com/v0"
TOKEN_VARS = (
    "AIRTABLE_API_KEY",
    "AIRTABLE_TOKEN",
    "AIRTABLE_PAT",
    "AIRTABLE_ACCESS_TOKEN",
)

LOOKBACK_DAYS = int(os.environ.get("EPISODE_LOOKBACK_DAYS", "30"))
MAX_NEW_PER_SHOW = int(os.environ.get("MAX_NEW_EPISODES_PER_SHOW", "25"))
PAGE_IMAGE_BUDGET = int(os.environ.get("MAX_PAGE_IMAGE_FETCHES", "60"))
YOUTUBE_BUDGET = int(os.environ.get("MAX_YOUTUBE_THUMBNAIL_CHECKS", "60"))
YT_TITLE_THRESHOLD = float(os.environ.get("YOUTUBE_TITLE_MATCH", "0.5"))
YT_DAY_WINDOW = int(os.environ.get("YOUTUBE_MATCH_DAYS", "7"))
DRY_RUN = os.environ.get("DRY_RUN", "").strip() in ("1", "true", "True", "yes")

USER_AGENT = "GoodFutureMedia-EpisodeSync/1.0 (+https://goodfuturemedia.com)"
# YouTube serves its channel pages differently to non-browser agents.
BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)


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


def entry_link(entry):
    """
    Somewhere to send a director who wants to hear the episode.

    Prefer the episode's own page. Plenty of feeds omit <link> entirely, but the
    enclosure -- the audio file itself -- is required for the feed to be valid,
    so it is always there. It is not a page, but it plays, which is what mining
    actually needs.
    """
    link = (entry.get("link") or "").strip()
    if link:
        return link
    for enclosure in entry.get("enclosures") or []:
        href = (enclosure.get("href") or "").strip()
        if href:
            return href
    return ""


def entry_duration(entry):
    """
    Run time in seconds from itunes:duration, or None.

    Publishers use three shapes for this tag -- "3600", "60:00" and "1:00:00" --
    and all three appear across our feeds, so parse by counting colons rather
    than assuming one. Measured 2026-09-05: 13,396 of 13,398 items across all 21
    feeds carry it, so a blank here is worth noticing.
    """
    raw = (entry.get("itunes_duration") or "").strip()
    if not raw:
        return None
    try:
        parts = [float(p) for p in raw.split(":")]
    except ValueError:
        return None
    if not parts or any(p < 0 for p in parts):
        return None
    seconds = 0.0
    for part in parts:            # h:mm:ss, mm:ss or plain seconds
        seconds = seconds * 60 + part
    # A few feeds emit 0 or something absurd; treat those as no value.
    return int(seconds) if 0 < seconds < 24 * 3600 else None


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


OG_IMAGE_RE = re.compile(
    r"""<meta[^>]+(?:property|name)=["'](?:og:image(?::secure_url)?|twitter:image)["']"""
    r"""[^>]+content=["']([^"']+)""",
    re.I,
)
OG_IMAGE_RE_REVERSED = re.compile(
    r"""<meta[^>]+content=["']([^"']+)["']"""
    r"""[^>]+(?:property|name)=["'](?:og:image(?::secure_url)?|twitter:image)["']""",
    re.I,
)


class PageImageFinder:
    """
    Pulls an episode's cover art off its own web page via og:image.

    Worth the extra request because some feeds set the *show* logo on every
    item -- Breaking Points is the clearest case, one identical image across
    every episode -- while their episode pages carry a distinct image per
    episode. Without this those shows are a wall of identical tiles in a
    gallery view.

    Budgeted rather than unlimited: a first backfill would otherwise fetch a
    page for every artless episode in one run. Whatever is skipped is picked
    up on a later run, since a record is only ever filled in once.
    """

    def __init__(self, budget):
        self.budget = budget
        self.cache = {}
        self.fetched = 0

    def __call__(self, url):
        if not url:
            return None
        if url in self.cache:
            return self.cache[url]
        if self.budget <= 0:
            return None
        self.budget -= 1
        image = None
        try:
            resp = requests.get(
                url,
                timeout=12,
                headers={"User-Agent": USER_AGENT},
                stream=True,
            )
            if resp.ok:
                head = resp.raw.read(200_000, decode_content=True)
                text = head.decode("utf-8", "replace")
                match = OG_IMAGE_RE.search(text) or OG_IMAGE_RE_REVERSED.search(text)
                if match:
                    image = match.group(1).strip() or None
            resp.close()
            self.fetched += 1
        except Exception:
            image = None
        self.cache[url] = image
        return image


def _same_image(a, b):
    """Same image ignoring query strings -- CDNs vary ?t= and ?size= per request."""
    if not a or not b:
        return False
    return a.split("?", 1)[0] == b.split("?", 1)[0]


def entry_image(entry, feed, page_image=None):
    """
    Square cover art for the episode, falling back to the show's own artwork.

    Most feeds set per-episode artwork on the item (measured at ~72% of items
    across our shows), and podcast art is square by spec -- 3000x3000 in
    practice -- so the fallback never changes the shape of the image. That
    matters because an Airtable gallery takes its cover from one field: if the
    episode has no art of its own we still want something there rather than a
    hole in the grid.

    Order is: the item's own art, then the episode page's og:image, then the
    show's art.

    Note the test for the first tier. Several feeds set an item-level image
    that is simply the show logo again -- Breaking Points does this on every
    episode -- which is indistinguishable from having no art of its own once
    it is on screen. Treating that as "no art" is what lets the page tier run
    and find the distinct image those shows publish on the web.

    YouTube thumbnails were considered and rejected: they are 16:9 or 4:3, so
    mixing them in would give every card a different shape, and only a third
    of episodes have a YouTube link to derive one from.
    """
    own = _image_href(entry)
    show = _image_href(feed.get("feed"))
    if own and not _same_image(own, show):
        return own
    if page_image is not None:
        from_page = page_image((entry.get("link") or "").strip())
        if from_page:
            return from_page
    return own or show


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
        SHOWS_TABLE, fields=[F_SHOW_NAME, F_RSS_URL, F_AUTO_ADD, F_SHOW_YOUTUBE]
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
                "youtube": (fields.get(F_SHOW_YOUTUBE) or "").strip(),
            }
        )
    return shows


YOUTUBE_ID_RE = re.compile(
    r"""(?:youtu\.be/|/embed/|/shorts/|/live/|[?&]v=)([A-Za-z0-9_-]{11})"""
)


def youtube_id(link):
    """The 11-character video id from any of YouTube's URL shapes."""
    m = YOUTUBE_ID_RE.search(link or "")
    return m.group(1) if m else None


def youtube_art_filename(video_id):
    """Marks an attachment as already being this video's thumbnail."""
    return f"yt-{video_id}.jpg"


def youtube_thumbnail(video_id):
    """
    The thumbnail URL for a video, or None when there is no real image.

    YouTube answers for *every* id, serving a tiny grey placeholder when the
    video is gone, so a 200 proves nothing and the size is what distinguishes
    them. This matters here: Trading Places' channel was banned and all 28 of
    its links are dead, and a placeholder would look like art while being a
    grey rectangle.
    """
    for quality in ("maxresdefault", "hqdefault"):
        url = f"https://img.youtube.com/vi/{video_id}/{quality}.jpg"
        try:
            resp = requests.get(url, timeout=20, headers={"User-Agent": USER_AGENT})
        except requests.RequestException:
            return None
        if resp.status_code == 200 and len(resp.content) > 8000:
            return url
    return None


UC_RE = re.compile(r"(UC[\w-]{22})")
TITLE_STOP = set(
    "the a an and or of to in is it that this for on with as at by be we you i our".split()
)


def channel_id_from(value):
    """
    A channel id from whatever someone pasted: a UC... id, a handle, or a URL.

    Handles and /c/ URLs have to be resolved by fetching the page, because only
    the id works with the uploads feed. The id is right there in the HTML, so
    this needs no API key.
    """
    value = (value or "").strip()
    if not value:
        return None
    direct = UC_RE.search(value)
    if direct and "youtube.com" not in value.split(direct.group(1))[0][-30:]:
        return direct.group(1)
    if value.startswith("@"):
        value = f"https://www.youtube.com/{value}"
    if "youtube.com" not in value:
        return None
    try:
        resp = requests.get(value, timeout=25, headers={"User-Agent": BROWSER_UA})
        resp.raise_for_status()
    except requests.RequestException:
        return None
    found = re.search(r'"(?:externalId|channelId)":"(UC[\w-]{22})"', resp.text)
    return found.group(1) if found else None


def channel_uploads(channel_id):
    """
    The channel's recent uploads: [(title, video id, published date)].

    Uses the public uploads feed rather than the Data API. That feed needs no
    key and no quota, and its ~15 most recent videos are plenty for a sync that
    runs hourly and only fills episodes published in the last few weeks. The API
    would only be needed to reach deeper history.
    """
    url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    try:
        resp = requests.get(url, timeout=30, headers={"User-Agent": BROWSER_UA})
        resp.raise_for_status()
    except requests.RequestException:
        return []
    out = []
    for entry in feedparser.parse(resp.content).entries:
        vid = (entry.get("yt_videoid") or "").strip()
        published = entry_air_date(entry)
        if vid and entry.get("title"):
            out.append((entry["title"], vid, published))
    return out


def title_key(title):
    """Comparable words from a title, ignoring numbering and trailing series tags."""
    t = re.sub(r"\|.*$", "", title or "")
    t = re.sub(r"^\s*E?\d+[:.\-]\s*", "", t)
    return {w for w in re.findall(r"[a-z0-9]{3,}", t.lower()) if w not in TITLE_STOP}


def fill_youtube_links(at, shows):
    """
    Give episodes their YouTube Link by matching the show's uploads feed.

    Matching needs both a strong title overlap and a nearby date, because a
    wrong video is worse than none: it looks right, and it would then also
    produce the wrong thumbnail.

    Measured 2026-09-05: BG2 matched 6 of 6 recent episodes and All-In 4 of 6,
    all at 0.92 or better. Breaking Points matched none at any threshold, and
    should not — it publishes re-cut segments under new titles, so the video is
    genuinely not the episode. Shows like that should be left without a channel.
    """
    channels = [(s, (s.get("youtube") or "").strip()) for s in shows]
    channels = [(s, c) for s, c in channels if c]
    if not channels:
        return 0

    wanted = {}
    for record in at.list_records(
        EPISODES_TABLE,
        fields=[F_EP_SHOW, F_EP_TITLE, F_EP_AIR_DATE, F_EP_YOUTUBE],
    ):
        f = record.get("fields", {})
        if (f.get(F_EP_YOUTUBE) or "").strip():
            continue
        linked = f.get(F_EP_SHOW) or []
        if not linked or not f.get(F_EP_TITLE):
            continue
        wanted.setdefault(linked[0], []).append(
            (record["id"], f[F_EP_TITLE], (f.get(F_EP_AIR_DATE) or "")[:10])
        )

    updates = []
    for show, raw in channels:
        episodes = wanted.get(show["id"]) or []
        if not episodes:
            continue
        channel_id = channel_id_from(raw)
        if not channel_id:
            log.warning("%s: could not read a channel id from %r.", show["name"], raw)
            continue
        uploads = channel_uploads(channel_id)
        if not uploads:
            log.warning("%s: no uploads returned for %s.", show["name"], channel_id)
            continue

        matched = 0
        for record_id, title, air in episodes:
            key = title_key(title)
            if not key:
                continue
            best, best_video = 0.0, None
            for vid_title, vid, published in uploads:
                other = title_key(vid_title)
                if not other:
                    continue
                if air and published:
                    if abs((published.date() - datetime.strptime(air, "%Y-%m-%d").date()).days) > YT_DAY_WINDOW:
                        continue
                score = len(key & other) / len(key | other)
                if score > best:
                    best, best_video = score, vid
            if best >= YT_TITLE_THRESHOLD and best_video:
                updates.append(
                    (record_id, {F_EP_YOUTUBE: f"https://www.youtube.com/watch?v={best_video}"})
                )
                matched += 1
        if matched:
            log.info("%s: matched %d episode(s) to YouTube.", show["name"], matched)

    if updates and not DRY_RUN:
        at.update_records(EPISODES_TABLE, updates)
    return len(updates)


def upgrade_youtube_art(at, budget):
    """
    Point Episode Art at the episode's YouTube thumbnail wherever one exists.

    The YouTube thumbnail is the preferred image for an episode; feed art, the
    page's og:image and the show logo are fallbacks for when there is no video.

    This is a pass of its own rather than part of the feed loop, because it has
    to reach rows the feed cannot match -- the pre-sync imports with no Feed
    GUID, which is most of what has a YouTube link. It is also why newly created
    episodes are unaffected at creation: nobody has added a link yet, so they
    take feed art now and get upgraded on a later run.

    Rows whose art is already `yt-<id>.jpg` are skipped without a network call,
    so the steady-state cost is near zero.
    """
    updates, checked, dead = [], 0, []

    for record in at.list_records(
        EPISODES_TABLE, fields=[F_EP_YOUTUBE, F_EP_ART, F_EP_TITLE]
    ):
        fields = record.get("fields", {})
        video_id = youtube_id((fields.get(F_EP_YOUTUBE) or "").strip())
        if not video_id:
            continue

        wanted = youtube_art_filename(video_id)
        current = fields.get(F_EP_ART) or []
        if any((a.get("filename") or "") == wanted for a in current):
            continue  # already this video's thumbnail

        if checked >= budget:
            log.info(
                "YouTube art: budget of %d checks reached, remainder next run.",
                budget,
            )
            break
        checked += 1

        url = youtube_thumbnail(video_id)
        if not url:
            # Kept as one summary line rather than a warning each: 28 of these
            # are Trading Places' banned channel and will fail every run, and
            # per-episode warnings would bury anything that actually matters.
            dead.append(fields.get(F_EP_TITLE) or record["id"])
            continue

        updates.append(
            (record["id"], {F_EP_ART: [{"url": url, "filename": wanted}]})
        )

    if updates and not DRY_RUN:
        at.update_records(EPISODES_TABLE, updates)
    if checked:
        log.info(
            "YouTube art: %d checked, %d updated, %d link(s) with no thumbnail.",
            checked,
            len(updates),
            len(dead),
        )
    if dead:
        sample = ", ".join(t[:40] for t in dead[:5])
        log.info(
            "YouTube art: no thumbnail for %d episode(s), existing art kept — %s%s",
            len(dead),
            sample,
            ", …" if len(dead) > 5 else "",
        )
    return len(updates)


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
        fields=[
            F_EP_GUID,
            F_EP_SHOW,
            F_EP_NUMBER,
            F_EP_DESC,
            F_EP_ART,
            F_EP_LINK,
            F_EP_LENGTH,
        ],
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
            if not (fields.get(F_EP_LINK) or "").strip():
                missing.add(F_EP_LINK)
            if not fields.get(F_EP_LENGTH):
                missing.add(F_EP_LENGTH)
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


def plan_for_show(show, known_guids, placeholders, incomplete, cutoff, page_image):
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
                    image = entry_image(entry, feed, page_image)
                    if image:
                        repair[F_EP_ART] = [{"url": image}]
                if F_EP_LINK in missing:
                    link = entry_link(entry)
                    if link:
                        repair[F_EP_LINK] = link
                if F_EP_LENGTH in missing:
                    seconds = entry_duration(entry)
                    if seconds:
                        repair[F_EP_LENGTH] = seconds
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
        link = entry_link(entry)
        if link:
            fields[F_EP_LINK] = link
        seconds = entry_duration(entry)
        if seconds:
            fields[F_EP_LENGTH] = seconds
        number = entry_number(entry)
        if number is not None:
            fields[F_EP_NUMBER] = number
        description = entry_description(entry)
        if description:
            fields[F_EP_DESC] = description
        image = entry_image(entry, feed, page_image)
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

    page_image = PageImageFinder(PAGE_IMAGE_BUDGET)
    total_created, total_claimed, total_backfilled, failures = 0, 0, 0, []
    total_yt_links = fill_youtube_links(at, shows)
    total_youtube = upgrade_youtube_art(at, YOUTUBE_BUDGET)

    for show in shows:
        try:
            claims, creates, backfills = plan_for_show(
                show, known_guids, placeholders, incomplete, cutoff, page_image
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
        "%d existing record(s) backfilled, %d linked to YouTube, "
        "%d given YouTube art. %d episode page(s) fetched for art. "
        "%d feed(s) failed.",
        total_created,
        total_claimed,
        total_backfilled,
        total_yt_links,
        total_youtube,
        page_image.fetched,
        len(failures),
    )
    if failures:
        log.error("Failed feeds: %s", ", ".join(failures))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
