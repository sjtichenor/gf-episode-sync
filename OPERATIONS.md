# Operations & context

Everything about this system that isn't obvious from the code: why it works the
way it does, what will break it, and what is still outstanding.

Last updated 2026-09-04.

---

## The one thing most likely to break this

**The sync addresses Airtable fields by name.** Renaming any of these in the
Airtable UI breaks the next run with `UNKNOWN_FIELD_NAME`, and nothing warns you
first:

| Table | Fields the sync writes or reads by name |
| --- | --- |
| Shows (`tblKMC5hDmmc7YsVW`) | Show Name, RSS Feed URL, Auto-Add Episodes |
| Full Episodes (`tblHBczQjSraq5hWe`) | Episode Title, Air Date, Episode Number, Episode Page, Show, Feed GUID, Episode Description, Episode Art, **YouTube Link** |

This already happened once: renaming *Full Episode Link* to *Episode Page* broke
it until the constant was updated in the same breath.

`YouTube Link` joined that list on 2026-09-04, when the YouTube thumbnail became
the primary image source — the sync only reads it, never writes it, but renaming
it silently stops every episode getting its thumbnail.

Everything else on Full Episodes — Miner, Mining Status, Director, Client
Account, and the rest — is untouched by the sync and safe to rename.

Table *ids* are used rather than names, so renaming a table is safe. The Social
Media Accounts table was renamed to Channels with no effect.

---

## What runs where

- **Repo:** `github.com/sjtichenor/gf-episode-sync` (public, so Render can clone
  it without a credential — the Render workspace's GitHub connection is bound to
  a contractor's account and cannot see repos under `sjtichenor`).
- **Service:** Render cron `Episode sync v2 (RSS to Airtable)`,
  `crn-dacvhe5g1s2s73ee6lng`, hourly at `0 * * * *`.
- **Superseded:** the original `Episode sync (RSS to Airtable)`
  (`crn-dacs24nqj5pc739g7i3g`) pointed at the contractor repo and never had the
  script. Suspended; safe to delete.

Environment variables live on the service and are **per service** — a key set on
another Render service is invisible here.

---

## Decisions, and the evidence behind them

Each of these was measured before being built. The measurements are worth
keeping because they are the reason not to redo the work differently.

### Episodes dedupe on the feed's own GUID

Not on title or date. Titles change after publication; dates shift with
timezones. Re-running is therefore safe, and a first run can be capped without
risk of duplicates on the catch-up run.

`EPISODE_LOOKBACK_DAYS` (default 30) and `MAX_NEW_EPISODES_PER_SHOW` (default 25)
exist because feeds carry deep archives — Breaking Points 1,667 items, 20VC
1,504. Without them a first run would import thousands of episodes.

### Producers' placeholder rows are claimed, not duplicated

Producers create a Full Episodes row before publication, titled with the guest's
name and carrying an Episode Number but no links. When the episode appears in
the feed the sync fills that row in rather than creating a second one.

Matching is on **Show + Episode Number only**. Titles are useless here: the
placeholder says "Phil Haslett" or "TP Episode 28 (title TBC)" while the
published title is something else entirely. Episode numbers are on every
placeholder.

Shows whose feeds carry no episode numbers (ThursdAI, 20VC, Diary of a CEO,
Breaking Points, Prof G Markets, Founders, Lightspeed, Talking Tokens, The
Huddle, The Morning Meeting) can never be matched this way — a placeholder for
those gets a separate row, to be merged by hand.

### Guests come from the description, never the title

Extracting guest names from episode titles was measured across 1,016 episodes:
**30% hit rate, roughly half of those wrong.** It returned hosts (Bill Maher for
Club Random, where he is the host and Brian Williams the guest) and non-people
("Most Replayed Moment", "Two Giants", "Hide Club", "Geopolitical Expert").
Feeding that into the Contacts CRM would create garbage that is expensive to
clean out.

Descriptions are a different story: **every item across all 26 feeds has one**,
and they name the guest in a form that separates them from the host — "Bill
Maher sits down with Brian Williams", "Sam Harris speaks with James Kirchick",
"Ed Elson is joined by John Mowrey".

So the sync stores `Episode Description`, and extraction is done by an Airtable
"Generate content" field reading Show + Episode Title + Episode Description.

**Never let that field write into the Guests link.** Guests points at Contacts,
which carries VIP flags and client relationships. Detected names belong in their
own text field; link only exact matches to existing Contacts, and never
auto-create a Contact.

### Episode art: YouTube first, then three square tiers

Order: **the YouTube thumbnail** → the item's own feed art → the episode page's
`og:image` → the show's art.

YouTube was made primary on 2026-09-04 at Spencer's request. It is a deliberate
trade: the thumbnail is the image the team actually designed for that episode,
and that was judged worth more than a uniform grid. The earlier reasoning
against it (below) was about card shape, and still describes the cost.

Two things make this safe, and both are load-bearing:

- **A dead video falls through instead of overwriting.** YouTube answers for
  *every* id, serving a small grey placeholder when the video is gone, so a 200
  proves nothing — response size is the only thing that separates a real
  thumbnail from a placeholder. All 28 Trading Places links are dead after their
  channel ban; without the size check, every one would have been replaced with a
  grey rectangle.
- **It runs as its own pass, not inside the feed loop**, so it reaches the
  pre-sync rows with no Feed GUID, which is most of what has a YouTube link.

A newly created episode has no YouTube link yet, so it takes feed art at
creation and is upgraded on a later run once someone adds one. Art already named
`yt-<id>.jpg` is skipped without a network call, so the steady-state cost is
near zero. `MAX_YOUTUBE_THUMBNAIL_CHECKS` (default 60) caps the rest.

As applied to the 104 rows with a link: **76 took a YouTube thumbnail, 28 kept
what they had** — the whole Trading Places set. The grid is now mixed rather
than uniformly square.

The square tiers below still run, and are what every episode without a video
gets:

- Podcast art is square by spec, 3000×3000 in practice, so the fallback never
  changes the shape of a card. An Airtable gallery takes its cover from **one**
  field, so a fallback is what stops a third of the grid being holes.
- 72% of feed items carry their own image (735 of 1,016 measured).
- The middle tier exists because several feeds set an item image that is just
  the show logo again — Breaking Points does this on every episode. That is
  indistinguishable from having no art once it is on screen. So item art only
  counts as the episode's own **when it differs from the show art**; otherwise
  the page is tried. Breaking Points goes from 1 distinct image across 4
  episodes to 4.
- Page fetches are budgeted (`MAX_PAGE_IMAGE_FETCHES`, default 60/run) so a
  first backfill does not fetch a page for every artless episode at once.

**The original argument against YouTube thumbnails**, kept because it is the
cost being accepted rather than a mistake: they are 1280×720 or 480×360, so
mixing them with square art gives cards different shapes, and only 104 of 332
episodes have a link — all older than the mining interface's 30-day window, so
they do not change what directors see each morning. Overridden deliberately on
2026-09-04 in favour of showing the image made for each episode.

### Episode Page falls back to the audio file

Many feeds omit `<link>` on their items — measured across 32 feeds and 18,417
items, **32% (5,959) had no page link**, and for some shows it is every single
item (Joe Rogan, Rolling Stone Music Now, Plain English, Kara Swisher).

The enclosure — the audio file — is required for a feed to be valid, so it is
always present. Measured: **zero of 18,417 items had neither.** So when there is
no page, `Episode Page` gets the media URL. It is not a page, but it plays,
which is what mining actually needs, and it is what moves an episode from
`Mineable? = No` to yes.

### Backfill lives in the sync, not in migrations

When a field is added, existing rows predate it. Rather than a one-off
migration, `load_episode_index` records which logged episodes are missing any
field we now capture, and `plan_for_show` repairs them when it next sees that
GUID in a feed. Deliberately **not** subject to the lookback window — the point
is to reach old rows. Self-limiting, since a row is only backfilled once.

Adding a new field to the sync means adding it to the `missing` set, and it
repairs itself over the following runs.

**The limit of this, and it is a real one:** backfill matches on Feed GUID, so
it only ever reaches rows the sync itself created. The 107 rows imported before
the sync existed have no GUID and will *never* be repaired by it, no matter how
many fields are added. Verified 2026-09-04: of the 107 episodes with no Episode
Art, **all 107 have no Feed GUID** — every synced episode already had art. Those
rows need a separate one-off fix, or hand editing.

### Shows and Channels are separate tables

Shows = what we clip **from** (sources). Channels = where we publish **to**
(destinations). 18 of 34 channels are GF-owned (Good Politics, The Techno
Optimist, Steelman…). About 8 names appear in both because for a client we both
clip their show and run their channels — that overlap is real, not a modelling
error. Linked via the `Channels` field on Shows.

### Do not trust a filtered count without checking it

On 2026-09-04 a `list_records_for_table` call filtering Shows on
`Relationship isAnyOf ["selJwPIc75HInQFsr"]` returned `totalRecordCount: 0` for
a value four records actually hold. That wrong number was reported as fact and
written into this document, and it nearly led to deleting a select option that
was in use. Listing the field unfiltered and counting gave the right answer.

When a count drives a decision — especially a destructive one — list and count
rather than filter.

### Mining priority lives on the show, not the episode

`Mining Priority` (High / Medium / Low) is a field on **Shows**
(`fld5uPh0EBeZXEDY8`). Full Episodes sees it through a read-only lookup of the
same name (`fld0sSkrGcxg1KLXd`) via the Show link.

This is deliberate and Spencer's call, 2026-09-04: *"I don't think we're going
to have time to be picking which full episode specifically are high priority,
it's more about certain shows."* One value per show sets the priority for every
episode of it at once, and nobody has to triage 332 rows.

An episode-level `Mining Priority` did exist and was never used — zero of 332
records ever had a value — so nothing was migrated. It survives as
"Mining Priority (old - safe to delete)" only because the API cannot delete
fields.

The cost of this design, worth knowing before someone asks for it back: there is
now no way to mark a *single* episode as unusually worth mining. If that need
appears, add a separate episode-level override rather than reviving the old
field, and make the interface prefer the override when set — otherwise two
fields with the same name compete and neither reads as authoritative.

**A gap this leaves:** `Relationship` on Shows carries a "Don't Mine" option,
which is the bottom of this same scale living in the field that otherwise
describes the commercial relationship. Four shows use it — TED Talks Daily,
Fintech TV, PBS News Hour and The Playbook Podcast (Politico), all outlets with
zero episodes and no client link. They are *not* former clients; the real ones
are 10X Capital Podcast and 20VC, both already marked as such.

The fix is to move that signal to Mining Priority and set those four to
Watchlist. **Order matters:** add "Don't Mine" to Mining Priority and set the
four shows *before* deleting the Relationship option, because deleting a select
choice clears every cell using it.

### Mining status is separate from Video Status

`Video Status` = "we are editing this full episode", only meaningful for the 107
episodes GF produced. `Mining Status` / `Miner` = "someone is cutting clips from
this". Different axes; overloading either corrupts both.

Airtable has no record locking. Two directors can claim the same episode within
the same moment and last write wins silently. The interface hides episodes that
already have a Miner, which handles nearly all of it, but do not design as
though exclusivity is guaranteed.

---

## Numbers, as last measured (2026-09-04)

- 332 episodes, 38 shows, 21 shows with Auto-Add enabled
- 225 episodes carry a Feed GUID (synced); the rest predate the sync
- 107 episodes are GF-produced (Video Status = Video Shipped)
- 31 episodes still have no Episode Page, all of them no-GUID placeholder or
  legacy rows. The 17:00 run on 2026-09-04 backfilled 94 — every GUID-carrying
  row that was missing one — so the enclosure fallback is confirmed working
  end to end
- 5 episodes have no Episode Art, down from 107. The other 102 were filled on
  2026-09-04 with genuine per-episode art, not show logos: 96 square and 6 at
  16:9 (see below)
- 61 distinct images across the 100 most recent episodes, measured *before* the
  og:image tier shipped. Not yet re-measured: the first run after it deployed
  fetched only 1 page, because art was already complete on every GUID-carrying
  row. The tier only affects episodes synced from now on, so its value rests on
  the pre-ship Breaking Points test (1 distinct image across 4 episodes -> 4)
- 104 episodes have a YouTube Link
- Zero episodes have a transcript

---

## Open items

**In the Airtable UI (cannot be done through the API):**

- Delete `Claimed By` and `Claimed By (User)` — redundant with `Miner`. Nothing
  references them. Airtable's API has no delete-field endpoint.
- Delete `Mining Priority (old - safe to delete)` on Full Episodes — the
  episode-level field, superseded by the lookup from Shows. Never held data.
- Fill in `Mining Priority` on Shows. It is empty on all 74; until it is set,
  the lookup shows nothing and cannot sort the interface.
- Delete `Active` on Shows — its job is covered by `Relationship` (now including
  Former Client) and `Auto-Add Episodes`. Only 2 of 74 rows were ever set.
- Create the `Guest (detected)` Generate-content field, **auto-generation off**
  until descriptions have backfilled, then test on ~20 records across Club
  Random, 20VC, Breaking Points and 10X before running it broadly. Watch the
  plan's AI credits.

**Code, not yet written:**

- YouTube matching. `YOUTUBE_API_KEY` is set on the service. The hard part is
  not the key but deciding which video corresponds to an episode; scope the
  search per channel using the (currently empty) `YouTube Channel` field on
  Shows, and check match quality on a few shows first. A wrongly matched video
  is worse than no image, because it looks correct.
- Optionally have the sync stamp a "last episode seen" date per show, which
  gives the dormancy signal the `Active` checkbox was meant to provide, without
  anyone maintaining it.

### Legacy art came from two sources, never the show logo

The 107 pre-sync rows were filled on 2026-09-04 without touching the show logo:

- **Trading Places (24)** from Dropbox. Every episode folder holds
  `06 - Thumbnail/Finished Thumbnails/EP## Square Thumbnail*.png` — the team
  makes a **square** cut alongside the 16:9 YouTube one, so these drop into a
  gallery beside podcast art with no shape mismatch. Ingested via
  `download_link` temporary URLs, which Airtable fetches and rehosts, so their
  single-use expiry does not matter. Verified 1080x1080.
- **10X / How I Invest (70)** from the renamed feed, which carries distinct art
  on 424 of 425 items. 62 matched on episode number, 8 more by guest name.

**Matching had to be by number, never by guest.** Alex Edelson, Ron Diamond and
Hunter Somerville each appear twice in the feed at numbers different from ours.
Where a row was only a guest name, the match was confirmed by finding that name
in the feed item's description.

### YouTube thumbnails, used only where nothing square exists

Six rows took a 16:9 YouTube thumbnail (`img.youtube.com/vi/<id>/maxresdefault.jpg`,
no API key needed) because no square alternative exists for them: the five
BG2Pod episodes, whose feed sets no per-episode art on any of 44 items, and
"Ron Diamond #2". These come from the YouTube Link already on the record, so
there is no matching to get wrong.

This does not contradict rejecting YouTube thumbnails for the gallery. That
decision was about *replacing* square art and making every card a different
shape. Here the alternative was an empty cell, and a 16:9 tile beats a hole.
The ratio is 96 square to 6 at 16:9, so the grid still reads as square.

Two more were filled from Dropbox after a closer look: EP01 David Zhou has no
file named "Square" but does have a **"David Zhou Spotify Thumbnail"**, which is
1080x1080 — Spotify episode art is square, so that naming is worth checking
whenever a "Square" file is missing. EP31's folder ("EP31 -") is unambiguous by
number despite the row still being titled TBC.

### Trading Places YouTube links are dead

Their channel was banned and the show moved to a new one. Every TP link tested
returned no thumbnail — EP01, EP14, EP19, EP20, EP28, five for five, not the two
originally noted. Assume the ~100 YouTube links on TP rows are all dead until
someone re-points them at the new channel. This also means `Mineable?` counts a
YouTube link that no longer resolves.

The 5 still empty, all needing a human:

- **Trading Places (4)** — Dropbox and Airtable disagree and the YouTube links
  are dead, so there is no third source to break the tie. Airtable #14 is
  "Michael Burry" but Dropbox EP14 is "Thanksgiving Episode"; there are *two*
  EP19 folders (Nate & Karin, Noel Moldvai) against Airtable's #19 Nathan
  Lustig; #20 2NDARY Roundtable's own folder holds no square thumbnail while an
  "EP20 Square Thumbnail" file sits inside the EP19 Noel Moldvai folder; and
  #28 is titled TBC with its thumbnail named for Shri Bashyam, who is #29.
  These cluster around the missing #18 (James Riney), which Dropbox *does* have
  a folder and thumbnail for — the likely root cause is that off-by-one.
- **The First (1)** — no Show link at all, and the client never launched.

**Data gaps found along the way:**

- **TP Episode #18 (James Riney)** has published YouTube and Twitter posts but
  no Full Episodes row. That is why Trading Places numbering jumps 17 → 19.
- Two Trading Places YouTube links resolve to nothing — `EkfIrBVHx9A` (#1 David
  Zhou) and `A5OECZTpEqI` (#7 Turner Novak) return no thumbnail and no title.
- Five shows will never sync: Squawk Box (CNBC publishes no feed for the
  broadcast), Monitoring the Situation (X only), Genfinity, Solana Ecosystem
  Calls, The First (client that never launched).
- **10X Capital Podcast was renamed "How I Invest with David Weisburd."** Its
  feed was not dead, just abandoned. The live feed is
  `https://feeds.podcastai.com/LaVYz9xBOj9Q4toB4HfKrC.xml` — a continuation
  carrying E1-E425 with the original numbering intact, so old episodes still
  resolve by number. The Shows record still points at the old dead feed
  (`ZxTOyNz8AEfEo1okVWwEXC.xml`); switching it resumes syncing, and with
  Auto-Add already on that starts importing new episodes immediately.
- BG2's feed has not published in 83 days.
- Roughly 107 rows predate the sync and have no Feed GUID. All are older than
  the lookback window, so they neither match nor duplicate anything — but they
  *would* be re-created as new rows if `EPISODE_LOOKBACK_DAYS` were ever set
  to 0.

**Parked by decision:**

- Deleting the 108 `Video Type = Full Episode` rows from the Videos table.
  Before doing it: 28 of them carry social posts with real view counts, and
  Team-level editor stats (Videos Edited, Total Views as Editor, the 100k+/1M+
  counts) all roll up from Videos and will drop. Decide first whether those
  stats should count full episodes.
