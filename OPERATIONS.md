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
| Shows (`tblKMC5hDmmc7YsVW`) | Show Name, RSS Feed URL, Auto-Add Episodes, **YouTube Channel** |
| Full Episodes (`tblHBczQjSraq5hWe`) | Episode Title, Air Date, Episode Number, Episode Page, Show, Feed GUID, Episode Description, Episode Art, **YouTube Link**, **Episode Length** |

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

## Other automations in this base

Not part of the sync, but they run against the same tables and will confuse a
future reader.

**Log Video Status Changes** (`wfls7VH9JeCqDCil1`) keeps `Video Status Logs`
(`tblnPcYMXNYwLkpYD`): on a Video Status change it finds the row with no End
Time, stamps it, and opens a new one.

It failed intermittently until 2026-09-05 with "Received invalid inputs" on the
Update step. The cause is that **Find records reports Success when it matches
nothing** — its documented output is "always an array, even if zero records
match". The Update step took its Record ID from
`map(records, propertyGetter("id"))`, which is an empty list when nothing
matched, so the update ran with no row id.

That happens for any video with no open log: **2,997 of 5,478 videos have no log
row at all**, since they predate the logging automation. And because a failed
action halts the run, the new log was never created either — so those videos
could never start being logged.

Fixed by wrapping the Update in a conditional on `length(records) > 0`. Note two
Airtable constraints that force the shape: a `conditionalGroup` must be the
**last** node in its list, so Create record has to be duplicated into both
branches rather than following the group; and `array` dataType only supports
contains/isEmpty style operators, so the test is on `length` as a number.

---

## Revisions per person

Added 2026-09-06. Counts how often a video was sent back for more edits, and
attributes it to the editor and the director.

The chain deliberately adds **no fields to the status log**:

| Table | Field | What it does |
| --- | --- | --- |
| Video Status Logs | `Is Revision` (`fldXH7NdTSzUJLlbB`) | 1 when the row is a revision |
| Videos | `Revisions` (`fldKo9z83Fb5JB1AQ`) | SUM of the above |
| Team | `Revisions as Editor` (`fld8ZehOgfWskgRO5`) | SUM via the Editor link |
| Team | `Revisions as Director` (`fldrn9r0J6wvJD5PA`) | SUM via the Director link |
| Team | `Revisions per 100 Videos (Editor / Director)` | the rate, which is the number worth reading |

Attribution runs through the video's *current* Editor and Director rather than a
snapshot on the log, which is sound only because Spencer confirmed videos are
never reassigned — same director and editor start to finish. The payoff is that
it covers all 3,381 historical revisions instead of only future ones. If a video
ever were reassigned, its past revisions would move to the new person.

**Two traps:**

- **The status was renamed.** 754 rows say "Awaiting Revision" (up to January
  2026) and 2,627 say "Needs More Edits". `Is Revision` counts both; counting
  only the current name undercuts by about a fifth.
- **Raw counts mislead, badly.** Jaymark Parba leads on raw revisions (444) but
  is mid-pack per video; Daren Jay Salazar has 126 and the best rate on the team
  (34 per 100 against a spread up to 243). Always read the rate.

Rates are expressed per 100 videos because `create_field` makes formula fields
with zero decimal places and there is no option to change it, so a per-video
ratio would silently round 0.34 to 0.

**Also worth knowing:** Videos has a formula computing time in
`"Awaiting Revision"` (`fldzRVASuQML9UocO`), but the Videos status field has no
such option — only the log does. It always returns blank.

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

### Videos derive their Show, they do not store it

Added 2026-09-07. Videos had no Show field; Spencer asked whether to add a
direct link or rely on the existing ones. Neither existing path covers the
catalogue on its own, so `Show` is a formula over two lookups:

- `Show (from Full Episode)` (`fld0uqrZQ0Nb01iLY`) — **authoritative.** A clip's
  show is a fact about its episode, not an independent attribute. Only 151 of
  5,513 videos are linked to an episode, so it is mostly empty today.
- `Show (from Channel)` (`fld5DYQaGBPpk5xs6`) — **fallback.** Valid only because
  11 of the 34 channels carry a single show each (BG2, 20VC, All-In, Trading
  Places, ThursdAI, David Weisburd, Pirate Wires, The First, 5 Year Frontier and
  the two Solana channels).
- `Show` (`fldKDD0we1AXdTWHn`) — prefers the episode, falls back to the channel,
  blank when genuinely unknown.

**A second editable Show link was deliberately not added.** Two writable sources
of truth drift apart, and the derived one is right whenever it is populated.

**Do not link an aggregator channel to a Show.** Good Politics, Good Crypto,
Good History, Good Billionaires and the rest are Good Future's own output
brands, carrying clips cut from many source podcasts — Good Politics alone holds
1,016 videos, including "Friedberg predicts socialism will overtake the USA,
Nate Silver Reacts", which is an All-In clip. Linking such a channel to one show
would make `Show (from Channel)` assert that every clip on it came from that
show. Their emptiness is load-bearing.

Coverage the day it was built: **3,071 of 5,513 videos (56%)** filled with no
manual work. The remaining 2,442 are on aggregator channels and need the clip
linked to its episode — the same job the transcript matching does, which also
yields the episode itself rather than only the show.

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

### YouTube Links, in two tiers

**First: the link the publisher put in the feed.** Many shows include the
episode's YouTube URL in the episode description. That is exact and needs no
matching, so it runs first, inside the feed loop.

It needs one guard. Publishers also put *standing* links in every description —
Theo Von's outro music video, This Week in Startups' promo — so taking the first
YouTube link in a description gives all 59 Theo Von episodes the same video.
`feed_boilerplate_videos` therefore discards any id that appears on more than
one episode in the feed. Measured across 22 feeds: **301 episodes carry a link,
but only 196 carry one that is actually theirs.** Theo Von goes from 59 to 1,
This Week in Startups from 54 to 12.

Shows where this works well: Conversations with Tyler 57/60, Pod Save the World
55/60, Pod Save America 48/60.

**Second, for the rest: match the channel's uploads feed.**

### YouTube Links use the Data API, with the public feed as fallback

`YouTube Channel` on Shows (`fldGzPNoD9LwSobL4`) takes a handle, URL or `UC...`
id. The sync resolves it to a channel id — the id is in the channel page HTML,
so that step needs no key.

`YOUTUBE_API_KEY` **is set on `Episode sync v2`** (confirmed from the run at
2026-09-07 16:01, which logs `Data API key: present`). Until that day nothing in
this repo used it: links came only from the public uploads feed, which returns
about **15 videos per channel**. That cap was the whole problem — a channel that
posts five clips a day buries its full episodes within a day or two, so older
episodes could never match no matter how good their title was.

The sync now pages the uploads playlist (`UU` + the channel id minus `UC`) at 1
quota unit per 50 videos. `search.list` costs 100 units per call against a
10,000/day default and is **not used anywhere**. No key, a bad key and an
exhausted quota all fall back to the public feed; all three were verified.

Quota is bounded three ways, because the first version was not and it showed:

- Paging **stops once a page runs older than the oldest episode still missing a
  link**. Without this Breaking Points read 2,000 videos in one run, spent the
  entire 40-page budget, and left all 15 other shows on the public feed.
- What is left is **shared between the shows that still need it**, so the first
  channel read cannot starve the rest.
- A global `MAX_YOUTUBE_API_PAGES` (120) caps a single run.

Steady state is cheap: a show with no unlinked episodes is skipped before any
request. The cost is the one-time backfill.

### A video must run about as long as the episode, not just 30 minutes

Only full episodes are worth mining, and a clip can share enough words with the
episode title to score a match, so length is what separates them. Durations come
from `videos.list` (1 unit per 50 ids); the public feed carries none.

A flat 30-minute floor is the obvious rule and it is **wrong for this catalogue**
— these are real full episodes, measured 2026-09-07 from `Episode Length`:

| Show | Real episodes under 30 min |
| --- | --- |
| Making Sense with Sam Harris | 23:32, 24:00, 25:32 — 3 of the 4 on file |
| Talking Tokens | 11:02, 13:39, 28:48 |
| This Week in Startups | 17:54, 21:05, 24:50 |
| Prof G Markets | 4:15, 27:53 |
| The Diary Of A CEO | 18:35, 25:56 |

So the video is compared against **that episode's own `Episode Length`** and has
to be within a fifth of it (`YOUTUBE_LENGTH_RATIO`, 0.8). The flat floor applies
only where the feed never gave a length.

This was not theoretical. The 2026-09-07 16:00 run, before the rule shipped,
linked Breaking Points' 41:38 episode of 8/20 to `CT3E1ZBOMiY`, a **19:43
segment** — and then took that segment's thumbnail as the episode art. Ratio
0.47, comfortably rejected now. Both fields were cleared by hand; the art
refills from the feed because backfill repairs an empty `Episode Art`.

### Select options can be added by the API, via typecast

`update_field` cannot touch a single-select's choices — its `options` accepts a
formula and nothing else. But **writing a value with `typecast: true` creates
the option**. That is how `Highest` was added to both `Shows → Mining Priority`
and `Full Episodes → Mining Priority Override` on 2026-09-07, without the UI:
write the new name to one record with typecast, then restore that record's old
value. The choice stays; the record is unchanged.

Two things the API cannot control this way, so they stay UI jobs:

- The option lands at the **end** of the picker, not in rank order.
- It gets an arbitrary colour. Both `Highest` options came out `blueLight2`,
  **the same blue as `Low`** — worth recolouring so the top and bottom of the
  scale do not look alike.

Neither affects sorting: the `Mining Priority` formula maps to `1 - Highest` …
`5 - Don't Mine`, and it already handled `Highest` before the option existed.

### What the API actually bought, measured

First run with deep paging and the length rule, 2026-09-07 17:00 — **39 links in
one pass**, against 6 the hour before:

| Show | Linked | Videos read |
| --- | --- | --- |
| The Morning Meeting | 22 | 300 |
| This Week in Startups | 7 | 50 |
| All-In | 4 | 50 |
| This Past Weekend w/ Theo Von | 3 | 50 |
| Club Random with Bill Maher | 3 | 50 |

Six of the 22 Morning Meeting links were checked against the real videos: length
ratios 0.95–0.97 and titles matching the episode titles. They are the archived
livestreams, which is what the show's full episodes are.

The budget also spread as intended — no channel took more than 300 videos, where
Breaking Points alone had taken 2,000.

### A show set to Don't Mine is skipped for YouTube links

Breaking Points was set to `Don't Mine` on 2026-09-07 at Spencer's request: it
publishes segments rather than full episodes, so there is nothing to link, and
looking anyway spends quota and can only produce a wrong link — which it did.
`load_shows` now carries the show's `Mining Priority` and `fill_youtube_links`
skips `Don't Mine` shows outright.

Episodes for such a show still sync into the table. Only the YouTube work stops.

### The 30-minute floor does not govern Sam Harris

Worth writing down, because the obvious worry is wrong. Making Sense puts only
the first ~20 minutes on YouTube behind a paywall, so it looks like the show a
length floor would hurt. It is not: the floor applies **only** to episodes whose
own length the feed never gave us, and all 113 of those belong to four shows —
How I Invest (78), Trading Places (30), BG2Pod (4), Pod Save America (1). None
is Making Sense.

His episodes carry lengths of 23:32, 24:00 and 25:32 — the feed publishes the
same free cut — so the ratio rule governs him, and a ~20-minute video against a
23:32 episode scores 0.85, above the 0.8 threshold. The floor stays at 30
minutes because the four shows it does govern are all long-form, and lowering it
would only widen the window for a clip to match.

### Short feed items are mostly not full episodes

Checked 2026-09-07, after Spencer doubted a 17-minute This Week in Startups:

| Show | What the short items actually are |
| --- | --- |
| This Week in Startups | side series — "Wilson Sonsini Startup Legal Basics", "AI Basics", not the flagship |
| The Diary Of A CEO | titled "Most Replayed Moment: …" — clips published into the feed |
| Prof G Markets | "Prof G Markets Is Taking A Break — You Should Too", an announcement |
| Making Sense | #489/#490/#491, the numbered episodes, free paywall cuts |
| Talking Tokens, Trading Places | genuinely short episodes of a short-form show |

He was right and an earlier version of this doc oversold them as full episodes.

### The Morning Meeting's full episodes are archived livestreams

Its `/videos` tab is almost entirely clips — 29 of 30 run under 16 minutes. The
full episodes live on `/streams`, where 29 of 30 run about an hour. Verified
2026-09-07: **archived livestreams do appear in the uploads playlist** (4 of the
15 most recent uploads were streams), so no separate lookup is needed — the
duration rule is the whole fix.

Their feed titles and stream titles are the same headlines, near-exact matches
("Democrat Abdul El-Sayed Slammed for \"Non-Apology\"…" appears verbatim in
both). The earlier measurement of "1 of 8" was never a titling problem; the
clips were simply crowding the episodes out of the 15-video window.

### Superseded: links from the uploads feed alone

`YouTube Channel` on Shows (`fldGzPNoD9LwSobL4`) takes a handle, URL or `UC...`
id. The sync resolves it to a channel id — the id is in the channel page HTML,
so no key is needed — then reads
`youtube.com/feeds/videos.xml?channel_id=...`, which needs no key and no quota
and returns the ~15 most recent uploads. For an hourly sync filling episodes
published in the last few weeks, 15 is plenty. **The Data API is not used**, and
its quota (`search.list` costs 100 units against a 10,000/day default) is a good
reason to keep it that way. The API would only be needed to reach deeper than
those 15.

A match needs both a strong title overlap and a date within 7 days, because a
wrong video is worse than none: it looks right, and it would then produce the
wrong thumbnail too. Measured 2026-09-05 against recent episodes:

| Show | Matched | Note |
| --- | --- | --- |
| BG2Pod | 6 of 6, all 1.00 | titles identical |
| All-In | 4 of 6, 0.92+ | two had no video that week |
| Breaking Points | **0** | correctly refused |

Breaking Points is the important row: it re-cuts and re-titles segments for
YouTube, so the video genuinely is not the episode. Shows like that should be
left with no channel.

Thirteen shows have a channel as of 2026-09-05. Three were added after Spencer
supplied host names, each verified by scoring the channel's titles against the
show's own feed rather than trusting the handle:

| Show | Channel | Recent match rate |
| --- | --- | --- |
| Conversations with Tyler | Mercatus Center | 5/5 at 1.00 |
| Founders | David Senra's channel, not @FoundersPodcast (which has no uploads) | 2/5 |
| ThursdAI | @altryne, the host's channel | 1/5 |

**Never guess a channel handle.** Every handle guessed while building this
landed somewhere useless: `@pivotpod` is "JPivots" with one unrelated video, and
`@ThisWeekinStartups` is a **fossil channel whose last upload is June 2011**,
titled "This Week in Startups has Moved!" — the show changed channels fifteen
years ago, it did not leave YouTube. Those misses were then written up here as
facts about the shows, which was wrong twice over. A wrong channel fails
silently and looks exactly like a show that re-titles its videos, so it is
expensive to diagnose and easy to rationalise. Ask for the URL.

All 18 shows have a channel as of 2026-09-07, the last five supplied by Spencer
from his browser and each verified against its own feed before saving:

| Show | Channel | Recent episodes matched |
| --- | --- | --- |
| This Week in Startups | This Week in Startups (`UCkkhmBW…`) | 5/8 at 1.00 |
| The Morning Meeting | 2WAY (`UCq7OKQb…`) | 1/8 |
| Pivot | Pivot with Kara Swisher and Scott Galloway | 0/8 |
| EconTalk | EconTalk | 0/8 |
| Breaking Points | Breaking Points | 0/8 |

The three zeros are **a verified property of those channels, not a guess**: they
post segments under their own headlines rather than the full episode under its
feed title.

For **Breaking Points** this is settled and needs no further work. Measured
2026-09-07: its channel posts **5 videos a day of 10–30 minutes** (14, 13, 30,
10, 18, 14 for the six most recent) while its feed episodes run a median of **54
minutes**. Each show is cut into roughly five topic segments, so there is no
full-episode video in existence to link. Nothing about the matcher can change
that, and a future reader should not spend time trying.

The channels stay stored anyway. They cost one request an hour, the threshold
means a non-match produces nothing rather than something wrong, and if any of
these shows ever posts a full episode it will link on the next run.

**A thought worth keeping for later:** for a show that segments like this, the
segments are arguably *more* useful to a miner than a full episode would be —
they are already cut by topic. That would be a different field holding several
videos per episode, not the single `YouTube Link`, so it is a feature rather
than a fix.

Because this runs before the art pass, an episode that gets a link also gets its
thumbnail in the same run.

**A trap worth not repeating.** The first version resolved the channel id by
fetching the channel page and taking the first `"channelId"` in the HTML — even
when the URL already contained the id. A channel page mentions other channels,
so this silently resolved **4 of 6 stored channels to somebody else's**, and
Conversations with Tyler and Founders were matched against the wrong uploads
entirely. Nothing failed loudly; they simply never matched, which is easy to
mistake for "the show re-titles its videos". A `/channel/UC...` URL is now
trusted as-is with no fetch, and a handle resolves via the page's own
`<link rel="canonical">`.

The saving grace is that a wrong channel produces *no* matches rather than wrong
ones, because the titles do not align — the same property that makes the
threshold safe.

**YouTube throttles bursts by returning 200 with an empty feed**, not an error,
so an empty uploads list is retried once before being believed, and channels are
fetched a second apart. Beware when testing by hand: hammering the uploads feed
makes healthy channels look dead.

### Two art fields: landscape and square

`Episode Art` (`fldSGEgzNTZAME4IE`) is the primary — the YouTube thumbnail when
there is one, otherwise the square art. `Episode Art (Square)`
(`fldVVebI3fb19x4fq`) is always the square version, whatever `Episode Art`
happens to hold.

The split exists because YouTube thumbnails are 16:9 and podcast art is square,
and both are wanted: the landscape one for an interface, the square one for
gallery grids and anywhere tiles must be uniform. Before this there was one
field, so making YouTube primary meant the square version was simply lost.

The sync writes both on create, backfills either when missing, and
`upgrade_youtube_art` deliberately touches **only** `Episode Art` — so an
episode gaining a video keeps its square copy.

97 legacy rows were backfilled by hand on 2026-09-05, since backfill cannot
reach rows with no Feed GUID. Where `Episode Art` already held square art it was
copied across; where it held a YouTube thumbnail the square version was
recovered from the feed by episode number. Copying an Airtable attachment to
another field in the same base works by passing its own URL — verified, the copy
came back 1080x1080 at the identical byte size.

### Episode Length comes from the feed, not YouTube

`itunes:duration` is on **13,396 of 13,398 items across all 21 feeds** — 99.98%
— so there is no reason to ask YouTube for it. Stored in `Episode Length`
(`fld4Pl9XjwPnV2l2Q`, duration, h:mm:ss).

Publishers use three shapes for that tag and all three appear in our feeds:
`3600`, `60:00` and `1:00:00`. `entry_duration` parses by counting colons rather
than assuming a format, and rejects zero or anything over 24 hours, since a few
feeds emit junk.

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

**That override was added on 2026-09-05**, as anticipated, for the case where one
interview is worth jumping on. Three fields now, and the split matters:

| Field | Type | Who sets it |
| --- | --- | --- |
| `Mining Priority (from Show)` (`fld0sSkrGcxg1KLXd`) | lookup | nobody — inherited |
| `Mining Priority Override` (`fldQXtJWL4eNlaBkL`) | single select | a person, per episode, only when it differs |
| `Mining Priority` (`fld6rh4X1MyDhfyv0`) | formula | nobody — this is what interfaces use |

The formula takes the override when set and the show's value otherwise, so an
episode follows its show unless someone deliberately says otherwise, and there
is still one source of truth per show. It outputs `1 - High` / `2 - Medium` /
`3 - Low` so it sorts by urgency instead of alphabetically, matching the
`0 - Quick Repost` / `1 - Basic` convention already used in Videos.

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

### Linking clips to their full episodes

Videos has a link to Full Episodes (`flda34XvSlQaFXapj`). On 2026-09-04, 112
clips were linked automatically and the rest was measured before anyone was
hired to do it by hand. The measurement is the useful part:

- **5,478 videos**, of which 351 carry an Episode Number on a channel that maps
  to a show.
- **Videos link to Channels, Full Episodes link to Shows**, and a channel does
  not identify a source. Client channels are 1:1 (David Weisburd -> How I
  Invest, 141 videos) but GF-owned channels aggregate: Good Politics has 1,002
  videos cut from many different shows. Only a person watching the clip can say
  which show it came from.
- Only **6 shows** have both a channel and full episodes — 10X (71 episodes),
  Trading Places (36), 20VC (13), All-In (10), ThursdAI (6), BG2 (5).
- Matching on Show + Episode Number gave **112 exact matches and zero
  ambiguous** (10X 77, BG2 35). Trading Places, 20VC, All-In and ThursdAI
  contributed none: either their clips carry no number or their episode records
  do not.

**The reason hand-linking the rest would mostly fail:** only **76 of 332 full
episodes have an air date before 2026**, because the sync's 30-day lookback
means everything else is from the last few weeks. The clips are from 2022-2025.
For most clips the episode record simply does not exist, so a person would spend
their time discovering absence, not linking.

The work that would actually unlock this is therefore **not** manual linking —
it is importing the back catalogue for those shows first, then re-running the
match. 239 clips already carry a number with no episode record to match
(All-In 150, BG2 49, 10X 40); those become free matches the moment the archive
exists. Whether that works per show depends on the feed carrying
`itunes:episode` — All-In's current records have no numbers, so test before
promising.

### Matching clips to episodes by transcript

Tested 2026-09-05. A clip's transcript should be a substring of its episode's,
which is a far stronger signal than titles or dates. The testing is worth
keeping because the result is nuanced.

**Exact substring matching does not work.** The two transcripts come from
different ASR engines, so wording differs: only 18 of 130 twelve-word probes
from a clip appeared verbatim in its own episode's transcript.

**Bag-of-words does not work either**, for short clips on a single-topic show.
A 91-word clip of generic VC talk ranked 32nd of 425, because its vocabulary is
shared by the whole archive.

**4-gram containment works, with a large margin.** A 170-word clip scored 0.529
against its true episode and 0.035 against the next best — the noise floor sits
near 0.01-0.04, so a true match stands roughly 15x above it. Use a threshold and
a three-way outcome: matched / no confident match / conflicts with the existing
episode number. Never take the top score as a match on its own.

**It also audits existing data.** Two clips both carried Episode Number 47. The
first matched E47 at 0.529 and the phrase "superlatives" appears in E47 and
nowhere else in 425 episodes. The second scored at noise against every episode,
and its distinctive phrase "weirdly the easiest" appears in none of them — so
its episode number is wrong. Some of the 112 number-based links are therefore
wrong too, and this method finds them.

**Run end to end on 10X, 2026-09-05.** All 141 clips on the David Weisburd
channel, scored against 419 usable episode transcripts:

| Outcome | Clips |
| --- | --- |
| matched, agrees with the existing Episode Number | 100 |
| matched, had no number before | 10 |
| **matched, contradicts the number** | **0** |
| no confident match | 12 |
| transcript missing or under 40 words | 19 |

Zero contradictions across 100 overlapping cases is the real result: the
number-based links written earlier are corroborated, not undermined. An earlier
note here claimed some were probably wrong — that was overstated. The one
suspicious clip is *unverifiable* (its content is in no episode in the archive),
which is not the same as provably mis-numbered.

Acting on it added 39 links, taking Videos from 112 linked to **151**. Those 39
needed 14 episodes that were not in the table — but **9 of the 14 already
existed as unnumbered rows** (Chris Dion, James Langer, Victor Mayer and the
rest, which are E114-E122). Creating all 14 would have duplicated them. Only 5
were genuinely new. Check for unnumbered rows of the same show before creating
anything from a feed.

**The limit is input, not method.** Transcripts in the feed, measured:

Re-measured 2026-09-05 using the **real feed URLs from the Shows table**. An
earlier version of this table was wrong because several URLs were guessed and
404'd, and a 404 was recorded as "no transcripts":

| Show | Items | With `podcast:transcript` |
| --- | --- | --- |
| **Breaking Points** | 1,668 | **all of them** (4,992 tags, ~3 formats each) |
| 10X / How I Invest | 425 | **425** |
| Diary Of A CEO | 880 | 147 |
| Trading Places | 48 | 31 |
| Conversations with Tyler | 299 | 2 |
| 20VC, All-In, BG2, Club Random, EconTalk, Founders, Making Sense, Pivot, Pod Save America, Pod Save the World, Prof G Markets, Talking Tokens, The Huddle, The Morning Meeting, Theo Von, This Week in Startups, ThursdAI | — | 0 |

Breaking Points' 1,668 items are full shows, not segments — median 70 minutes,
1,412 of them over 45 — because they publish two or three a day. But the earlier
claim here that they are "a main source for Good Politics" was an inference that
was never measured, and Spencer says they are clipped only occasionally. Which
shows the Good Politics clips actually come from is still unmeasured.

**YouTube is not a route to transcripts for these.** The Data API's
`captions.download` requires OAuth *as the video's owner*, so an API key cannot
fetch captions for shows GF does not own — which is exactly the set needed. The
old `video.google.com/timedtext` endpoint now returns 200 with an empty body.
Caption URLs are still embedded in the watch page HTML, so scraping works, but
that is against YouTube's terms and breaks whenever the page changes. Prefer the
RSS transcripts, which are published deliberately for this purpose.

For shows with neither, the episode side has to be transcribed with ASR. That is
cheap next to a person, and the clip side already has transcripts on 3,493 of
5,478 videos.

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
  broadcast), Monitoring the Situation (X only), Genfinity, Solana (called
  Solana Ecosystem Calls until 2026-09-21), The First (client that never
  launched).
- **10X Capital Podcast was renamed "How I Invest with David Weisburd."** Its
  feed was not dead, just abandoned. Switched on 2026-09-05: the Shows record is
  renamed and now points at
  `https://feeds.podcastai.com/LaVYz9xBOj9Q4toB4HfKrC.xml`, a continuation
  carrying E1-E425 with the original numbering intact. Auto-Add is on, so new
  episodes import hourly; its Mining Priority is "Don't Mine", so they arrive
  without being queued for anyone.
- BG2's feed has not published in 83 days.
- Roughly 107 rows predate the sync and have no Feed GUID. All are older than
  the lookback window, so they neither match nor duplicate anything — but they
  *would* be re-created as new rows if `EPISODE_LOOKBACK_DAYS` were ever set
  to 0.

**Parked by decision:**

- Deleting the 108 `Video Type = Full Episode` rows from the Videos table.
  Verified 2026-09-05, and the case against has got stronger:
  - **28 of them carry two social posts each with real view counts** — Nik
    Talreja 19,200, Sim Desai 17,823, Shri Bashyam 16,546 and so on. These are
    the Trading Places full episodes. Deleting the row breaks those Post links.
  - **Team stats roll up from the Videos link** (`fld5keLdkNCErvCcu`): four
    counts of videos edited, four rollups of views as editor, and the editing
    hours total. Deleting 108 rows lowers those numbers for Dean Jeffer Xyre
    Rivera, Michael II, Jackridz Reyes and Chris P Madden, who edited them.

  The real question is whether an editor's stats should count full episodes they
  cut, or only clips. Recommendation: **do not delete.** 108 rows out of 5,478
  cost nothing, Full Episodes is already the canonical record, the clips are
  linked to it, and deletion is irreversible while tidiness is not urgent.

## Taking over the contractor's automations (started 2026-09-08)

Farhan Afridi (`fafridi047@gmail.com`, GitHub `Farhan5217`) built 17 of the 18
Render services. His two repos are **private and Spencer has no access** —
verified: 404 unauthenticated and 404 as `sjtichenor`. Render stores only a
pointer to a repo, never browsable source.

### The code is on disk now

Pulled over SSH from the running instances (Render → Account Settings → SSH
Public Keys; key `~/.ssh/render`, wired via `~/.ssh/config`). Render SSH is
only offered on web services and workers, not cron jobs — but the two live
non-cron services happened to cover both repos:

| Local copy | Source | Contents |
| --- | --- | --- |
| `~/Projects/gf-airtable-automation` | `webhook`, `/opt/render/project/src`, branch `whook` | 16 Python files, 7,038 lines — all 9 live services |
| `~/Projects/gf-dropbox-automation` | `spencer-dropbox-automation-background`, `/app` | `main.py` (219 lines): openai + moviepy + dropbox, the transcription pipeline |

`.git` was deliberately not copied, so these have no history and no remote.
`.env_old` was deliberately left on the webhook box — almost certainly a
credential dump — and should be inspected by Spencer, never pulled into a repo.

**Not yet committed anywhere.** Before the first commit, the two hardcoded
tokens have to go (next section).

### One real secret was in the source

`tiktok/sync_tiktok_posts.py:15` and `tiktok/sync_tiktok_followers.py:14` read
`os.getenv('AIRTABLE_PERSONAL_ACCESS_TOKEN', '<live token>')` — a working
Airtable PAT as the fallback. The fallback also fails silently: a missing env var
quietly keeps using the stale token instead of erroring. Every other flagged
match was a false alarm (table ids, base ids, API base URLs). The Dropbox repo is
clean. Fix: `os.environ[...]` with no default.

The token turned out to be **Farhan's own** (issued under his Airtable account)
so it cannot be revoked by Spencer — it dies when Farhan is removed from the base.

### Airtable is decoupled — verified 2026-09-08 19:30 UTC

A service account, **`automations@goodfuturemedia.com` ("GF Automations")**, was
created as a Google Group (not an alias — a group outlives any one member), added
to the base, and issued a PAT scoped to `data.records:read/write` +
`schema.bases:read`, this base only. Spencer pasted it into all ten services.

Proof: Posts records modified 19:28–19:30 are attributed to GF Automations. The
18:00 run had still shown Farhan because **a cron job reads its environment when
the run starts** — that run began 18:00:39, before the paste landed. Cron jobs
also do **not** record env changes as deploys (web services do), so deploy
history cannot confirm a paste on a cron; only a fresh run can.

**Removing Farhan from the Airtable base is now safe** (kills his token, nothing
depends on it) — but see Meta below before removing him from anything else.

### Where the social syncs actually write

Not Videos. `Posts` (`tblMpYJQjbb5yuKfC`, 11,275 records, one per platform post)
and `Channels`. Videos links to Posts via `fld9ifiDP9LQvdijH`. Posts has
`lastModifiedBy` (`fldMpe7Zlt3ad0EPR`) and `lastModifiedTime`
(`fld8PraNw2sT3RhAI`), which is how identity was verified. Note Airtable records
no modification when a write sets the same values, so a script "successfully
updating" a record with unchanged view counts leaves no fingerprint.

### The other credentials, and who owns them

| Credential | Owner | Status |
| --- | --- | --- |
| `YOUTUBE_API_KEY` | **Spencer** — GCP project "Social Media Stats" in the goodfuturemedia.com org, key created 2025-07-11, Farhan never in IAM | Already independent; Google keys belong to the project, not a person |
| `TWITTER_BEARER_TOKEN` | **Spencer** — developer app under his X account | Regenerated 2026-09-08 and re-pasted; a bearer token needs no login, which is why Farhan could hold it without the password |
| `META_USER_ACCESS_TOKEN`, `FACEBOOK_PAGES` (page tokens baked into env) | **Farhan** — his personal Facebook user, granted admin on the Pages | **Removing his Meta admin = instant FB + IG outage.** Fix: Business Manager System User, reuse Spencer's own "GF data fetcher" app; not started |
| `TIKTOK_CLIENT_KEY/SECRET`, `TIKTOK_ACCOUNTS` (per-account access + refresh tokens) | **Farhan** — his TikTok developer app; each account was authorised via his OAuth link | Fix: own developer app (needs TikTok review, days–weeks) then re-authorise every account; not started |

### TikTok has a clock on it regardless of Farhan

`refresh_access_token` updates the rotated tokens **in memory only** and never
persists them; every run reuses the original refresh token from `TIKTOK_ACCOUNTS`.
TikTok refresh tokens expire 365 days after issue. The oldest accounts were
authorised around September 2025. When each one lapses, that account's sync
fails until someone re-does the login flow, with no warning. All accounts were
still refreshing successfully at 12:01 UTC on 2026-09-08. The rebuild must
persist the rotated refresh token (to Airtable) so it never ages out.

### Remaining order of work

1. Strip the two hardcoded tokens; `git init` both local copies under `sjtichenor`.
2. Submit Spencer's own TikTok developer app — the long pole.
3. Meta: System User in Business Manager, mint page tokens, replace env vars.
4. Re-authorise each TikTok account through the new app.
5. Rebuild services into Render under Spencer's repos, in parallel, then cut over.
6. Last: swap the workspace GitHub credential (one credential, bound to Farhan;
   swapping it early breaks auto-deploy on all 17 of his services), then remove
   him from Airtable, Meta and Render.

### TikTok developer app — form values (draft could not be saved without a demo video)

Organization **Good Future Media**, app **Good Future Media Analytics**, created
2026-09-08 at developers.tiktok.com under Spencer's login. Domain
`goodfuturemedia.com` verified by DNS TXT (covers all subdomains). TikTok
validates the demo video on *Save*, not only on *Submit*, so the form cannot be
saved until the OAuth flow exists to record. Values entered, for re-entry:

| Field | Value |
| --- | --- |
| Category | Business |
| Description | Reads our own accounts' follower counts and video performance into an internal Airtable dashboard |
| Terms of Service URL | https://goodfuturemedia.com/terms/ |
| Privacy Policy URL | https://goodfuturemedia.com/privacy/ |
| Platforms | Web only |
| Web/Desktop URL | https://goodfuturemedia.com |
| Products | Login Kit only (Display API is no longer a separate tile; its scopes sit under Login Kit) |
| Scopes | user.info.basic (automatic), user.info.profile, user.info.stats, video.list |
| Redirect URI | `https://api.goodfuturemedia.com/tiktok/callback` — exact-match; the code must use this string |

Explanation text (967/1000 chars) is in the conversation of 2026-09-08 and
maps each scope to the fields the code reads. The demo video must be recorded
against **Sandbox** (TikTok requires sandbox for first-time approval) and must
show the real website domain.

The site and its DNS are on WordPress.com (Atomic; nameservers ns1–3.wordpress.com;
site id 230609993). `api.goodfuturemedia.com` will be a CNAME there to the Render
service that hosts the callback.

### `gf-api` — the first service under Spencer's own repo (2026-09-08)

Render web service **`gf-api`** (`srv-dag7ohtbedkc73fq9elg`, starter plan,
`https://gf-api-6nbe.onrender.com`) deploys `sjtichenor/gf-airtable-automation`
(public; tokens stripped and history verified clean) and runs
`uvicorn tiktok_auth:app`. It is meant to sit at **`api.goodfuturemedia.com`**
(CNAME at WordPress.com to `gf-api-6nbe.onrender.com`, plus the custom domain
added on the service in Render).

What it does: the TikTok Login Kit flow under Spencer's own developer app.
`/tiktok/login?key=…` → TikTok consent → `/tiktok/callback` swaps the code for
tokens, reads the profile and latest videos (the app-review demo), and writes the
token set **Fernet-encrypted** to the new `TikTok Auth` table
(`tblkAwVZQWrsXH8Ee`), keyed on `open_id` + environment. The ciphertext is
useless without `TOKEN_ENCRYPTION_KEY`, which exists only in Render. Losing that
key means re-authorising every account.

Environment (non-secret ones were set at creation):

| Variable | Set by | Value |
| --- | --- | --- |
| `TIKTOK_ENVIRONMENT` | done | `Sandbox` now; `Production` once TikTok approves the app |
| `TIKTOK_REDIRECT_URI` | done | `https://api.goodfuturemedia.com/tiktok/callback` |
| `AIRTABLE_BASE_ID`, `TIKTOK_AUTH_TABLE_ID` | done | the base and the TikTok Auth table |
| `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET` | Spencer | the **sandbox** pair from the TikTok portal for now |
| `AUTH_LINK_SECRET` | Spencer | random; `python3 -c "import secrets;print(secrets.token_urlsafe(32))"` |
| `TOKEN_ENCRYPTION_KEY` | Spencer | Fernet key; `python3 -c "import os,base64;print(base64.urlsafe_b64encode(os.urandom(32)).decode())"` |
| `AIRTABLE_PERSONAL_ACCESS_TOKEN` | Spencer | the GF Automations PAT |

`/health` lists any of the five that are missing, so a half-configured service
says so instead of failing at login time.

Why not PKCE: TikTok's docs make `code_verifier` mobile/desktop-only; the web
flow uses `state` (10-minute TTL, in memory — fine for one instance). Why
encrypt into Airtable rather than a Redis: no new paid infrastructure, base
collaborators cannot read the tokens, and the sync can write the **rotated**
refresh token back — the docs say a refresh may return a new one that must
replace the old, which is exactly what the contractor's code never did.

Lesson from the first push: `.gitignore` had no trailing newline, so an
appended pattern glued onto the last line and ignored nothing; a 2,644-file venv
went into a public repo and had to be rewritten out. Always `printf` the whole
file or check the final newline before appending.

### First TikTok login under our own app — 2026-09-08 21:54 UTC

Worked end to end on the first try: consent → token exchange → profile and
10 videos rendered → tokens encrypted → row `recl6nJMuj6kSitXW` in `TikTok Auth`
for `good.conspiracies` (Sandbox, all four scopes, refresh valid to
2027-09-08). Server logged one line and nothing sensitive.
`api.goodfuturemedia.com` serves a valid certificate (Google Trust Services).

Spencer recorded the flow and submitted the Production app for TikTok review
the same evening. **After the upload, `AUTH_LINK_SECRET` must be rotated** — the
login link's `?key=` is visible in the video. While review is pending, the
sandbox pair stays on `gf-api`; on approval, swap in the production client
key/secret and set `TIKTOK_ENVIRONMENT=Production`.

Next for TikTok: rebuild `tiktok/sync_tiktok_*.py` to read rows from
`TikTok Auth`, decrypt with `load_tokens`, refresh, and **write the rotated
refresh token back** (re-encrypted) — the piece that ends the 365-day cliff.
Then re-authorise each remaining account through the login link (up to 10 as
sandbox target users; unlimited once production is approved).

### Meta cutover, 2026-09-08 — partial, with an incident to repair

**Finding:** the Facebook sync under Farhan's tokens had been silently dead for
weeks. The 12:00 UTC run skipped all 771 posts ("Could not determine the owner
of post … with any configured token"); the top Facebook view counts were last
written in June–July. "Last successful run" only meant exit code 0.

**What was done:** the Business already owned a System User named "Farhan"
(id 61579881404400 — Meta allows one Admin system user, so it was reused, not
replaced). All Pages, Instagram accounts and the GF Data Fetch app were assigned
to it; a never-expiring token was generated with the five permissions the token
dialog offered (`pages_show_list`, `pages_read_engagement`, `instagram_basic`,
`instagram_manage_insights`, `business_management`); `FACEBOOK_PAGES` was rebuilt
from `/me/accounts` and pasted with `META_USER_ACCESS_TOKEN` on Facebook,
Instagram and webhook.

**Incident:** the new page tokens resolve post ownership and likes, but
`/{post}/video_insights` returned 403 — it needs `read_insights` **and**
`pages_manage_engagement`, neither of which the app exposes yet. Farhan's code
treats a failed insights call as `views = 0` and writes it. The triggered run
**zeroed Views on 119 Facebook posts** (Posts table, lastModifiedBy GF
Automations, Views = 0) before Spencer cancelled it. Recoverable: once the two
permissions are on the token, a rerun writes current real counts.

Fixed in `sjtichenor/gf-airtable-automation` (`fb/main.py`, commits 65c14d4 +
9cb6fad): a failed insights call leaves Views out of the write. The running
Facebook service still deploys Farhan's repo, so that fix is not live there.

**Do not trigger the Facebook service again until** the app exposes
`read_insights` and `pages_manage_engagement` (App Dashboard → Use cases →
customize), a fresh system-user token carries all seven permissions, and
`FACEBOOK_PAGES` has been rebuilt from it. Instagram is unaffected by the
missing permissions (its insights use `instagram_manage_insights`).

### Facebook cutover, continued — 2026-09-09 00:00–00:20 UTC

`gf-facebook` (Render `crn-dag9ueek1f9s738cpckg`, our repo, schedule `0 */6`)
now replaces Farhan's Facebook cron, which is **suspended**. Its first real run
(00:11, build 05a8df3) had the new token with all seven permissions and page
tokens re-minted from it — and still wrote wrong data: `video_insights` returned
**200 with a body lacking `post_video_likes_by_reaction_type`**, so the old
default of 0 was written as Likes on **58 posts** ("Peter St. Onge" went from 38
likes to 0). Spencer suspended the job at ~00:20.

Running damage tally on Posts (Facebook rows modified by GF Automations):
Views = 0 on 119 posts (from the 22:34 run), Likes = 0 on 58 (from the 00:11
run). All recoverable by one correct run; nothing else was touched.

Code state in `sjtichenor/gf-airtable-automation` (`fb/main.py`), all after
the 00:11 run started and therefore not yet exercised: Views and Likes start
as unknown and are never written from a default; an empty insights body is
logged (bodies never contain tokens) and treated as a failure; a post with no
obtainable like count is skipped; `FB_MAX_POSTS=N` caps a run for testing and
prints the raw insights body. `PYTHONUNBUFFERED=1` is set so logs stream.

**Two operational traps learned tonight:**
- Render's GitHub credential is Farhan's, so pushes to Spencer's repos do
  **not** auto-deploy (build log says "we don't have access to your repo, but
  we'll try to clone it anyway"). Every push needs `trigger_deploy` or a
  dashboard deploy until the credential is swapped.
- A deploy does not stop an in-progress cron run, and neither did "Cancel run"
  reliably; **Settings → Suspend Cron Job** did. Runs of the contractor's code
  buffer stdout, so logs arrive minutes late — check Airtable, not logs, to see
  what a run is writing.

Next: unsuspend, `Trigger Run` with `FB_MAX_POSTS=3`, read the raw insights
body, fix whatever it shows (metric name, video vs post id, or access level),
then remove the cap and run in full.

### Facebook views: root cause found and fixed — 2026-09-09 02:30 UTC

An `FB_PROBE` run asked Meta about one reel seven ways under the new page
token. The answer: `/{video}/video_insights` returns **`{"data": []}`** —
HTTP 200, no error — whenever `post_video_likes_by_reaction_type` is in the
metric list. Alone, `fb_reels_total_plays` answers correctly (17,357), and the
video node's `views` field returns the identical number. The reaction metric
is the poison pill; it is not on Meta's deprecation list and produces no error,
which is why the contractor's code failed silently for months (the earlier
"could not determine owner" failure sat in front of it).

`fb/main.py` (commit c10fcef) now reads
`/{video}?fields=views,likes.summary(true),created_time` — one request per post
instead of two, halving load on the app's hourly quota — with
`video_insights?metric=fb_reels_total_plays` as the fallback for plays. Verified
on a capped run: "Garret Langley TED Flock 4" went from Views 0 / Likes 0 to
**17,358 / 31** in Airtable at 02:29:24. The full run repairs the rest.

Resolved by Spencer, 2026-09-09: the two skipping pages are **expected**.
**ThursdAI** — Good Future has no Facebook agency access at all; nothing to
pull. **Trading Places** — agency access covers their Instagram only; the
Facebook Page was never set up on their side. Both skip cleanly (never zeroed).

Consequence for the Instagram cutover: `insta_sync.py` discovers accounts
*through Facebook Pages* (`/me/accounts` → page → `instagram_business_account`),
so an Instagram account we can reach but whose Page we cannot — Trading Places
— will not be found that way. The rebuilt Instagram sync needs a second
discovery path via the Business's Instagram accounts
(`/{business-id}/instagram_accounts`, plus owned ones) before it can be trusted
for that account.

**Daily data-health audit** (`followers/health.py`, run by gf-follower-snapshot
at the end of every 09:00 UTC run; added 2026-09-23 after the US In Common
incident). For every **active** channel, on every platform it has a profile
URL for:

| Check | Means | Severity |
|---|---|---|
| `NO ROW` | nothing in Follower Logs for 2+ days (Instagram/TikTok/YouTube/Facebook only — X and Threads have no daily source) | act |
| `DIVERGES` | the Channels follower field is >5% off Social Blade's latest row — the platform sync that writes Channels is broken while Social Blade is fine. **The dashboards cannot see this one** because they read the logs; the Airtable interface reads the field. | act |
| `FLAT` | the last 3 logged counts are identical (accounts ≥100 only) | look |
| `NO FIELD` | profile listed, follower field never written | look |

`DIVERGES` only trusts rows whose Notes start "Social Blade" — a row the
snapshot copied out of the Channels field cannot contradict it, which is
why BG2 and Solana Facebook did *not* fire the day their fields were fixed.
The report prints every day. When anything is at "act" severity and
`HEALTH_ALERT` is not `0`, the job exits **3** after all its writes, so
Render sends the cron-failed email — deliberately, it is the only push
channel until `SLACK_BOT_TOKEN` exists. So **a gf-follower-snapshot failure
email now means "open the log, read the DATA HEALTH block"**, not that the
snapshot broke. `HEALTH_IGNORE="Good Politics/Instagram;Steelman/*"` mutes
accepted cases (`;` or `,` separated, `*` for every platform).

**Frozen fields are filled from Social Blade** (`fill_from_socialblade` in
`snapshot_followers.py`, same commit series, 2026-09-23). A `DIVERGES` finding
whose Social Blade row is from today or yesterday gets that figure written
into the Channels follower field, so the Airtable interface stops showing a
number the official API stopped updating. A reachable account is overwritten
by the platform sync later the same day (better figure, small gap); a muted
pair is never touched. A filled finding drops to "look", so it does not send
the email but the log still says the official sync is lagging.
An **empty** field with a Social Blade row behind it (`NO FIELD`) is filled
the same way — ThursdAI's Instagram and TikTok and Solana Clipped's TikTok
had months of daily rows that nothing ever copied across. A Social Blade
row up to **three days old** is accepted (it skips the odd day on small
accounts). `SB_FILL_CHANNELS=0` disables it. Dry-run 2026-09-23, seven
writes: Good Politics IG 128,220 → 150,567; Solana TikTok 2,406 → 7,085;
Solana Clipped TikTok → 19; ThursdAI IG → 6,733, TikTok → 440; Weights &
Biases IG → 1,845, TikTok → 587. Weights & Biases was not asked for but
falls under the same rule (empty field, Social Blade has it).

**Consequence for the mute list:** once the fill exists, a `DIVERGES` or
`NO FIELD` that Social Blade can fill never alerts, so the only reasons
left to mute something are (a) Social Blade's own number is untrusted
(Oliver Wyman TikTok reads 2,463, suspiciously US In Common's figure) or
(b) Social Blade cannot see it and nobody cares. `HEALTH_IGNORE` on
gf-follower-snapshot is therefore `Oliver Wyman/*;ThursdAI/Facebook`
(Solana/TikTok came off the list 2026-09-23 so it gets filled). Mute means
*do not touch*: no report, no email, no fill.

**ThursdAI's numbers were being entered by hand.** Instagram and TikTok are
now Social Blade's daily; YouTube (54,500, within 5% of Social Blade) is
left as entered unless it drifts; Facebook (`profile.php?id=` URL) and X
still have no source.

First audit, 2026-09-23, against live data — 5 to act on: **Good Politics
Instagram** Channels 128,220 vs Social Blade 150,567 (the IG sync cannot
reach real.good.politics, so the field is frozen — same class as US In
Common); **Solana TikTok** 2,406 vs 7,085 (TikTok sync not reaching
@solana); **Oliver Wyman TikTok** 25 vs 2,463 (one of the two sources is
looking at the wrong account — 2,463 is suspiciously US In Common's 9/21
figure); **Oliver Wyman Instagram** and **ThursdAI Facebook** never logged
(profile.php-style URLs Social Blade cannot resolve, and no Page token).
To look at: Solana YouTube flat at a round 95,500 (hand-typed, never
synced); Weights & Biases TikTok flat at 587.

**Facebook follower counts silently skip any channel whose name is not
typed exactly like its Page** (found 2026-09-22 when someone reported US In
Common not updating; fixed in commit 88694ab). `sync_facebook_followers` in
`fb/main.py` paired a Channels row with its `FACEBOOK_PAGES` entry by exact
string match on the name. Airtable says "US In Common", the Page says "US in
Common", so the account was left out of every run: the **Facebook Followers**
field sat at **1,455** while Social Blade had it at 9,380, and Instagram and
TikTok on the same row kept updating, which made it look like nothing was
wrong. Only 6 of the 12 pages in `FACEBOOK_PAGES` were matching at all. The
match now strips case and punctuation, and falls back to the Page id when the
channel's Facebook Profile URL carries one (Solana's does:
`facebook.com/139904812549092`, and its count had been stuck at 500).
Separate finding from the same log: the Page tokens for **Good Billionaires
and Good Crypto are dead** ("This Page access token belongs to a Page that is
not accessible", code 190) — regenerating `FACEBOOK_PAGES` from `/me/accounts`
would fix both, and is Spencer's paste. The cron is `0 */6 * * *`.
**Verified on the 22:16 UTC run:** 9 channels matched where 6 had before —
US In Common 1,455 → **9,834**, Solana 500 → **891**, BG2 1,427 → **1,587**
(BG2 matched through the Page-id fallback: its Page is "BG2 Clips"). The two
"Could not fetch follower count" lines are the dead tokens above.

**Settled 2026-09-21 (commit f28bb6b): the Business's Instagram edges do not
work, its Pages edge does.** With a system-user token for GF Automations and
`META_BUSINESS_ID=1651224375632743`, every Instagram edge on the Business node
is refused — `owned_instagram_accounts` and `instagram_accounts` return HTTP
400 "does not exist, cannot be loaded due to missing permissions, or does not
support this operation", and `client_instagram_accounts` is not a field at all
— while `owned_pages` **on the same business id succeeds**. So this was never a
scopes problem, and the two trips back to the token dialog chasing
`business_management` were wasted. `/me/businesses` also returns empty for a
system user, which is normal and not a signal.

So `add_business_instagram_accounts()` in `insta_sync.py` walks
`/{business}/owned_pages` with
`fields=name,access_token,instagram_business_account{id,username,followers_count}`
and reads the Instagram account off each Page, using the Page token the
business hands back. `/me/accounts` returns only the Pages the token
administers itself; `owned_pages` returns all 10 the business owns.

First real run, 2026-09-21 23:59 — **7 accounts reached**: @steelmandebate 339,
@us_in_common 7,984, @startup__academy 5,956, @legit.conspiracies 1,691,
@real.good.crypto 13, @bg2clips 7,797, @techno.optimist.prime 56,236. Three
owned Pages carry no Instagram account (Good Billionaires, Business School,
Good Future Media). Two of the eleven the Page route could never see are now
covered: **@legit.conspiracies and @real.good.crypto**.

**The other nine are out of reach by any token** — @real.good.politics,
@weightsandbiases, @goodbillies, @innovators_exchange, @10xpod,
@tech.totherescue, @altryne_ai, @all_in_stans, @piratewires. The Graph API only
reaches an Instagram Business account through a Facebook Page, and no Page the
business owns links to these. Fixing that is an Instagram-side job (link each
account to a Page) or a Business-settings one (bring the Page into the
business), not a code change.

**`META_USER_ACCESS_TOKEN` returned 403 on that same run** ("Token validation
failed: 403"), after three full manual runs inside 35 minutes — most likely an
app-level rate limit rather than an expiry, since the same token validated fine
at 23:31. The Page walk did nothing that run and the business route carried it
alone, which is the reason `sync_instagram_followers` no longer returns early
when `build_instagram_mapping` fails. Confirm against the next scheduled run
(`0 5 * * *` UTC) before treating the token as broken.

(Earlier note, superseded: posts on **two pages** skip with "Could not find valid access
token" — the rebuilt `FACEBOOK_PAGES` holds 12 pages, the first token's list
held 13. ThursdAI and Trading Places posts are the ones seen skipping. Assign
those Pages to the system user in Business Settings, regenerate the page list
from `/me/accounts`, paste, done. Likes/views on their posts stay untouched
until then (skipped, not zeroed).

`FB_PROBE` and `FB_MAX_POSTS` are cleared on `gf-facebook`; the code keeps both
for next time.

### Facebook repair run — 2026-09-09 02:32–03:15 UTC, and what it revealed

`gf-facebook` full run on the fixed code: **353 posts updated, 418 skipped, 0
errors, no rate-limit hits** (one call per post). Every view count zeroed
earlier tonight now holds a live number; the 9 Facebook posts still at 0 likes
have real play counts and are genuine zeros.

The 418 skips are concentrated, and all are "Could not find valid access
token" — the post's owner page is not among the pages the system-user token
can see:

| Channel | Skipped | Updated | Why |
| --- | --- | --- | --- |
| Good Politics | 189 | 0 | **the Facebook page was banned by Meta** (Spencer, 2026-09-09; Meta apparently read a political page run by a distributed team as a foreign operation). Nothing to fix; explains the 13 → 12 page count |
| ThursdAI | 155 | 0 | no Facebook access at all — expected |
| BG2 | 44 | 33 | posts live on two pages; one is not accessible |
| Trading Places | 25 | 0 | Instagram access only — expected |
| Steelman | 5 | 0 | **its Facebook pages (plural) were also banned** — expected |
| Techno Optimist / Good Conspiracies | 4 / 2 | 188 / 9 | stragglers; likely deleted posts |

**Facebook follower counts have never updated.** The followers pass matches
channels to pages by reading a Channels field called `Channel`; the primary
field is `Social Media Account`, so every channel read as blank and the pass
logged "Processing 0 channels with Facebook pages" — under Farhan's runs too.
Fixed in commit 00f5cd8 (field name). It still matches by exact page name
against the Channels name, so "BG2" vs "BG2 Clips" and "Solana" vs "Solana
Foundation" will not match; the durable fix is a `Facebook Page ID` field on
Channels and matching by id. The daily follower snapshot
(`followers/snapshot_followers.py`) copies whatever the syncs wrote, so until
this works Facebook follower history will be flat.

**Probe verdict (2026-09-09, The Techno Optimist reel 1313936917477249, runs
at 06:00, 06:24, 12:00 and 17:21 UTC):**

| Where asked | Metric | Answer |
|---|---|---|
| `/{video}` node | `views`, `likes.summary(true)`, `created_time` | work (views 17,358 = `fb_reels_total_plays`) |
| `/{video}/video_insights` | `fb_reels_total_plays` | 17,358 |
| `/{video}/video_insights` | `blue_reels_play_count` | 12,707 = views minus replays, so not stored |
| `/{video}/video_insights` | `fb_reels_replay_count` | 4,651 |
| `/{video}/video_insights` | any grouping of the above, or `total_video_views` | `{"data": []}` — one metric per call |
| `/{page}_{video}/insights` | `post_video_avg_time_watched`, `post_video_view_time`, `post_video_retention_graph`, `post_video_views`, `post_reactions_by_type_total`, `post_clicks` | 400 code 200 subcode 1504029 "User doesn't have enough permissions to load insights" (the token has `read_insights`; these are retired Page-post video metrics, the API answers from v23.0) |
| `/{page}_{video}/insights` | `post_video_followers`, `post_video_social_actions` | 200, empty data with paging — exist, but not populated for Reels |
| `/{page}_{video}/insights` | `post_impressions_unique` | 400 "must be a valid insights metric" |
| `/{page}_{video}` node | `shares,reactions.summary(true),comments.summary(true)` | 400 #10 needs Page Public Content Access |
| `/{video}/insights` | anything | 400 "nonexisting field" |

So for Reels the obtainable set is **views, likes, comments, replays**. Reach,
watch time, retention, shares are not available to this app for Reels; Reach
on Posts stays an Instagram-only number.

Build 4e29caa (live 17:43 UTC) stores them: `comments.summary(true)` is added
to the one node call (falls back to the old field list if Meta rejects it),
and one extra `video_insights` call per post fetches `fb_reels_replay_count`.
Posts gained **Replays** (`fldOGmgENcHmxfYxc`) and **Comments**
(`fld4LdxcL0Jy990Lk`); both are written only when Meta returned a number.
`FB_PROBE` was cleared at 17:42 UTC, so the 18:00 UTC scheduled run is the
first real run on this build. Verify it on Posts: Facebook rows whose
`Comments`/`Replays` filled and `Last Modified By` = GF Automations.

Trap found while probing: Meta's paging URLs carry the page access token, and
the probe printed response bodies to Render logs (06:00–17:21 runs). The
probe now redacts `access_token=` before printing. Anyone with Render log
access could have read page tokens from those runs; page tokens are minted
from the system-user token, and "Revoke tokens" on the system user
invalidates them when the time comes.

### TikTok cutover result — 2026-09-16 20:27 UTC

First production sign-in (good.conspiracies) worked end to end: token
refreshed, 30 posts updated in batches, followers 3,783 written. Followers
call had to be a GET (`/v2/user/info/`), fixed in e075fb5. The one-off
`TIKTOK_LOOKBACK_DAYS=-1` pass was set back to 120. Remaining accounts to
sign in (posts on file): good.politics 775, technooptimist 735,
tradingplacespod 291, bg2.clips 219, solanafndn 171, altryne 162,
steel.man.debates 133, free.business.school 96, startup__academy 78,
usincommon 69, solana 68, theallinpod 61, goodbillionaires 44,
solana.clipped 43, weights_biases 24, plus a handful of tiny ones. Farhan's
Instagram cron suspended 2026-09-16; his TikTok crons to suspend once the
big accounts are signed in.

### TikTok approved — production cutover — 2026-09-16

TikTok approved "Good Future Media Analytics" (Login Kit + Display API).
Cutover: (1) on gf-api replace `TIKTOK_CLIENT_KEY`/`TIKTOK_CLIENT_SECRET`
with the **Production** tab's keys and set `TIKTOK_ENVIRONMENT=Production`;
(2) each TikTok account signs in once at
`https://api.goodfuturemedia.com/tiktok/login?key=<AUTH_LINK_SECRET>` while
logged into that TikTok account (rows land in TikTok Auth with Environment
= Production; link each row's Channel field to its Channels record so
followers write to the right place, otherwise it falls back to matching the
handle in `TikTok Profile`); (3) new cron **gf-tiktok**
(`crn-dalfed5g1s2s73e4fq1g`, our repo, `0 */6 * * *`, `python
tiktok/sync_tiktok.py`) needs `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET`
(production), `TOKEN_ENCRYPTION_KEY` (same value as gf-api) and the Airtable
PAT pasted; non-secret vars set at creation; (4) after a clean run, suspend
Farhan's `Tiktok service (posts)` (`crn-d33gjvripnbc73e07pe0`) and `Tiktok
service (followers)` (`crn-d33gplfdiees739iil10`). The sync batches 20
videos per `/v2/video/query/` call, re-syncs posts within
`TIKTOK_LOOKBACK_DAYS` (120) plus any without Views, writes Views/Likes/
Comments and Date Posted (if empty), refreshes and re-encrypts tokens each
run. Accounts not signed in are listed in the log with their post counts.

### Instagram cutover and the cross-post double count — 2026-09-14/15

Instagram's `views` for a reel shared to Facebook includes the Facebook
plays (the app shows the split; the API does not). With the Facebook post
logged as its own record, a video's total counted those plays twice:
"Anatoly: Alpenglow is coming" showed 87k in Airtable against 47k real.
**Correction 2026-09-16:** the subtraction I first shipped was wrong. The
`views` media insight our copy of the sync requests is Instagram-only (a
cross-posted reel came back 5,194 here vs 116,580 on Facebook; Alpenglow
came back 6,605, matching the app). The combined figures were written by
Farhan's *main*-branch sync, which our copy (from his `whook` branch) does
not share. So the real fix is simply running our sync and suspending his.
The 2026-09-16 05:00 run had reduced/zeroed ~2,000 posts; each carried the
raw value in `Views incl. Facebook` (`fldbCL4AC0Q3gCs6Q`), and `IG_REPAIR=1`
on gf-instagram restores Views from it and clears it (run once, remove
the variable; the field can then be deleted). Also: the 2026-09-16 full
pass (`INSTAGRAM_LOOKBACK_DAYS=-1`) timed out at Render's 12-hour cron
limit around post 2,000 of 2,940 — posts without a username in the URL
cost ~30 s each in "searching across all accounts". Lookback is back to
120 days.

**Recurrence, 2026-09-23 — the same double count, by hand.** Colin kept
setting "All in 8/28 - Cancer Vaccine Patenting" (Startup Academy Instagram,
`recUQNunxEr6Ov742`) to 744,000 because that is what the Instagram app shows;
the sync wrote 249,928 back every morning. Both are "right": the app's figure
for a reel shared to Facebook is Instagram **plus** Facebook, and the
Facebook reel is its own row (`recWqktloG5MhJSTo`, 490,766). 249,928 +
490,766 = 740,694 ≈ 744,000. Hand-entering the app's number counts the
Facebook plays twice, so the video's total read 1.23M instead of ~741k. No
code change; the sync is correct. Rule for the team: **Airtable Views on an
Instagram post is Instagram only — if the app shows more, the difference is
already on the Facebook row.**

New cron **gf-instagram** (`crn-daka3ibm8hqs73drhcf0`, our repo,
`0 5 * * *`, `python insta/sync_insta.py`, starter) replaces Farhan's
`Instagram service (posts+followers)` (`crn-d2skb295pdvs739idln0`). The
script discovers Pages via `/me/accounts` on `META_USER_ACCESS_TOKEN`, so
that variable takes the Business system-user token; plus
`AIRTABLE_PERSONAL_ACCESS_TOKEN`. Non-secret vars set at creation. After the
first clean run, suspend Farhan's Instagram cron. Runs re-sync posts within `INSTAGRAM_LOOKBACK_DAYS` (now 120).

### Analytics dashboard — `api.goodfuturemedia.com/dashboard` (added 2026-09-09)

Lives in the gf-api service (`srv-dag7ohtbedkc73fq9elg`), code under
`dashboard/` in `sjtichenor/gf-airtable-automation`, mounted into the FastAPI
app in `tiktok_auth.py`. Spencer asked for a site with more design freedom
than Airtable interfaces.

- **Data**: `dashboard/data.py` pulls Shows, Channels, Videos, Posts, Follower
  Logs, Team and Client Accounts every `DASHBOARD_REFRESH_SECONDS` (900) in a
  background thread, by **field id** (`returnFieldsByFieldId`), so renaming a
  field in Airtable does not break it; adding a table or field means editing
  the id maps at the top of that file. One snapshot is kept in memory; the
  first build after a deploy takes ~100 s (11k posts at Airtable's 5 req/s),
  during which `/dashboard/api/data` answers 503 and the page shows
  "warming up". A refresh failure keeps the last good snapshot and is shown
  by `/dashboard/api/status`.
- **Deploys and the loading screen**: a new instance starts empty and builds
  its snapshot (~60–90 s with the parallel pulls; was 200 s serial).
  `/dashboard/ready` returns 503 until it has one; gf-api's **Health Check
  Path** must be `/dashboard/ready` so Render keeps the old instance serving
  meanwhile. The gate lifts after the first failed attempt or five minutes,
  so a bad Airtable token cannot wedge deploys. Without the health check
  path every deploy shows "Loading analytics" for a minute or two.
- **Drill-down** (2026-09-16): KPI tiles, chart bars/slices and account
  rows open a drawer listing the posts behind the number (`openDrill` in
  `index.html`; Chart.js `onClick` via the `clickable()` helper). Client
  pages hide the "dated by log entry" and median subtitles.
- **Auth** (`dashboard/auth.py`; Google sign-in added 2026-09-24):
  - **Team = Sign in with Google.** `GOOGLE_OAUTH_CLIENT_ID` /
    `GOOGLE_OAUTH_CLIENT_SECRET` on gf-api (Spencer's paste; OAuth client in
    the Workspace org, consent screen *Internal*, redirect URI
    `https://api.goodfuturemedia.com/dashboard/auth/google/callback`;
    `DASHBOARD_BASE_URL` overrides the host). Allowed = any address on
    `DASHBOARD_ALLOWED_DOMAIN` (default goodfuturemedia.com) **or** an email
    matching an Active row in the Team table (so a contractor on Gmail works
    if they are in the table; set someone Inactive and they are out). The
    session cookie `gf_dash` is signed JSON (email, name, exp) at path **`/`**
    for 30 days, so a team member is also let into every `/clients/…` page.
    Identity → Team row is resolved on each request by email, so adding a
    row later needs no new login. Flow: `/dashboard/auth/google` sets a
    signed 10-minute state cookie carrying the return path, Google redirects
    to `…/callback`, code → token → `openidconnect …/userinfo`; unverified or
    unknown emails bounce to the login page with a plain message.
  - **Shared password still works** (`DASHBOARD_PASSWORD`) and yields an
    anonymous team session; the pre-2026-09-24 bare-token cookie at
    `/dashboard` is still accepted, so the deploy logged nobody out. Ten
    wrong guesses from one address → ten-minute lockout.
  - **Admins**: `DASHBOARD_ADMINS` (default `spencer@goodfuturemedia.com`, which
    is the email on Spencer's Team row) may act as someone else on the
    mining board. Everyone else is themselves; a domain address with no Team
    row can sign in but is told to be added before it can claim.
  - **Clients are unchanged**: password only, no username, one cookie per
    slug. The check is now *client password for this slug **or** a team
    session*. `/dashboard/api/whoami` returns the resolved identity.
  - **Exec-only pages** (2026-09-24): `CLIENT_EXEC_ONLY` on gf-api lists
    slugs (currently `flock`) that a team session may open only with the
    **Exec** role — the Team table's Role field, which exactly Spencer and
    Chris P Madden carry. Any other signed-in colleague gets a 404 on the
    page, its login and its data, and the slug is left off `/dashboard/links`
    (with an "exec-only" note for execs). The client's own password is
    unaffected; the shared-password session counts as not-exec. Role is
    resolved per request from the snapshot, so changing it in Airtable takes
    effect within 15 minutes with no re-login. `DASHBOARD_EXECS` (emails) is
    a fallback for an address with no Team row; `DASHBOARD_EXEC_ROLE`
    (default `Exec`) names the role. Exec is about *seeing*; admin
    (`DASHBOARD_ADMINS`) is about *acting for someone* on the mining board —
    kept separate on purpose.
  - `DASHBOARD_SECRET` (optional) signs everything; without it the key
    derives from the passwords, so changing either logs everyone out.
  - Verified with an eleven-step TestClient run (no Google involved): login
    page + redirect, forged state bounced, team sign-in resolves to the Team
    row, opens a client page and its data, non-admin cannot claim as someone
    else, admin can, stranger refused with no cookie, domain address without
    a row gets in but cannot claim, shared password anonymous, old cookie
    still valid, logout clears.
- **Page**: `dashboard/index.html`, vanilla JS + Chart.js 4 from cdnjs, Inter
  from Google Fonts. Filters (show, account, editor, platform chips — shift-
  click isolates one — range, GF-owned) live in the URL, so "Copy link"
  shares a filtered view. Light/dark theme toggle remembered per browser.
- **Local layout work**: `DASHBOARD_FAKE_DATA=1` serves synthetic numbers and
  skips the login. `.claude/launch.json` in gf-episode-sync has a
  `gf-api-dashboard-fake` config on port 8765; headless Chrome screenshots
  were used to check it because the in-app browser tools were unavailable.
- Views on the page are lifetime totals per post as last synced; follower
  history starts 2026-09-09 (Follower Logs), so change columns read "no
  earlier snapshot" until there is a second day.
- **Team page** (`/dashboard/team`, `dashboard/activity.py`, `team.html`,
  added 2026-09-09 evening): who did what, derived from Video Status Logs —
  leaving Up For Grabs/Assigned = editor picked up/started; leaving Editing =
  finished draft (time in Editing recorded); leaving Needs More Edits /
  Awaiting Revision = revision started; leaving Internal Review = director
  approved or sent back; a post's created time = the social manager's action
  (Posted By is filled on every recent post). Days are in `DIGEST_TZ`
  (America/New_York). Cards per person with a heatmap, quiet badge, in-
  progress list; click a day for the event list; pipeline counts and stuck
  videos (thresholds in `STUCK_AFTER_DAYS`). Status logs are 25k+ rows, so
  the snapshot pulls only the last `DASHBOARD_ACTIVITY_DAYS` (120) plus open
  rows, via filterByFormula on the *names* "Start Time"/"End Time" — renaming
  those two fields breaks the pull. Caveat Spencer accepted: time in Editing
  is elapsed time, not hours worked.
- **Daily Slack digest** (`dashboard/slack.py`): yesterday per person
  (Friday–Sunday on Mondays), quiet people, pipeline, stuck videos. Posted to
  a group DM with Spencer and Chris Madden at `DIGEST_HOUR` (9) local on
  `DIGEST_DAYS` (12345) by a thread inside gf-api; a redeploy inside the
  9:00–9:10 window could send twice. Needs `SLACK_BOT_TOKEN` (bot scopes
  chat:write, im:write, mpim:write). Recipients: `DIGEST_SLACK_USER_IDS`, or
  `DIGEST_RECIPIENTS` names (default "Spencer Tichenor,Chris P Madden")
  resolved through the Team table's Slack ID field. Preview at
  `/dashboard/api/digest?date=YYYY-MM-DD`; `POST /dashboard/api/digest/send`
  sends now (both need the dashboard cookie).
- **Client dashboards** (`/clients/<show-slug>`, added 2026-09-10): the
  overview in client mode for one show, sent to the client with a password.
  `CLIENT_PASSWORDS` env var on gf-api holds `slug=password` pairs separated
  by `;` (slug = show name lower-cased, non-alphanumerics → `-`, e.g.
  `trading-places=…`). `client_view()` in `data.py` filters on the server:
  that show, channels linked to it, posts on those channels or cut from its
  episodes, their follower history; editor/director/poster/client-account
  fields are stripped before the response. Page hides nav, editor filter and
  table, GF-owned toggle, refresh; shows the show's name/logo and "Prepared
  by Good Future Media". Own cookie per client, signed with the shared secret
  plus that client's password, so changing one password logs out one client.
  A show with no `CLIENT_PASSWORDS` entry is a 404. A client can also be a
  set of accounts instead of a show: `CLIENT_GROUPS` on gf-api, e.g.
  `ffp=FFP:Steelman|US In Common` (slug = display name : channel names
  separated by `|`, entries separated by `;`); the view is exactly those
  channels, their posts and follower history. FFP (Steelman + US In Common)
  was the first, 2026-09-11. Both variables must carry the slug. Nicer link later: add
  `reports.goodfuturemedia.com` as a second custom domain on gf-api (CNAME at
  WordPress.com, then Render → Settings → Custom Domains).
- **Dashboard index** (`/dashboard/links`, `dashboard/links.html`, added
  2026-09-22, commit d6126d6): one page listing every dashboard we run, behind
  the team password, linked from the nav on the overview and team pages. The
  client rows are **generated from the live configuration** in
  `routes.py:_client_rows()` — `CLIENT_PASSWORDS` for which reports exist,
  `CLIENT_GROUPS` / `CLIENT_MATCHES` for how each one's clips are chosen (and
  the channel names behind a group, read back from the snapshot), plus
  `CLIENT_NO_FOLLOWERS`, `CLIENT_NO_SHOWS` and `CLIENT_VIDEO_ACCOUNTS` as
  caveats on the row. Nothing is hand-listed, so adding a client shows up on
  the next deploy. The page shares the `gf-theme` localStorage key with the
  other two, so the light/dark choice carries across. As of 2026-09-22 the
  live set was four client reports — trading-places, ffp, solana, flock — which
  was confirmed by probing `/clients/<slug>` across every show and client
  account name (303 = exists, 404 = no `CLIENT_PASSWORDS` entry).

- **BG2 client page** (`/clients/bg2`, added 2026-09-22): a CLIENT_GROUPS
  entry, `bg2=BG2:BG2` — the single "BG2" channel (@bg2clips on Instagram,
  TikTok, YouTube, Facebook and X), which links to the show "BG2Pod with Brad
  Gerstner and Bill Gurley" (315 videos). Defined by account rather than by
  show so the URL is `/clients/bg2` and not a slug of the show's full title.
  Logo comes from the channel's profile picture; there is no "BG2" record in
  Clients (the nearest is "Brad Gerstner"), so add one with a Logo attachment
  if a different mark is wanted. `CLIENT_GROUPS` on gf-api is now
  `ffp=FFP:Steelman|US In Common;solana=Solana:Solana|Solana Clipped;bg2=BG2:BG2`.
  The page 404s until Spencer adds `bg2=<password>` to `CLIENT_PASSWORDS`.

- **Favicons** (2026-09-23): `dashboard/static/` holds `favicon.svg`,
  `favicon.ico` (a 32px PNG in an ICO wrapper), `favicon-32.png` and
  `apple-touch-icon.png` (180px) — the brand dot with a white G. Served at
  the app root by routes in `tiktok_auth.py` (week-long cache header), so the
  API landing page and TikTok pages get them by default; the four dashboard
  pages and the login template link them explicitly. The PNGs were
  rasterised by a pure-Python script (no Pillow on the dev machine); to
  change the mark, edit `favicon.svg` and re-rasterise to match.

- **Mining board** (`/dashboard/mine`, `dashboard/mine.html`, added
  2026-09-23) replaces the Airtable "Available to Mine" interface (Director
  Tools → `pagIbKARIPGfbCePo`), which was a flat list of ~475 episodes with
  no playback, no claim, and no idea what had already been cut. What the
  data showed before building it: **Mining Status was blank on all 492
  episodes**, nothing had ever been marked Mined, only 13 had a Miner, 81
  episodes already had clips and still showed as available, and 159
  "Don't Mine" episodes were in the list. So the board **infers** state
  rather than trusting the fields: *taken* = Miner set and status not
  Mined/Skipped; *clipped* = `# of Clips` > 0 or status Mined. Full Episodes
  now rides along in the snapshot (`EP` map in `data.py`; `episodes` key;
  never reaches a client page). Page: pick your name once (Team table,
  remembered in `localStorage` as `gf-miner`), search across title / guest
  (the AI-detected field) / show / description, priority chips (Don't Mine
  off by default; shift-click isolates one), hide-taken and hide-clipped
  toggles (both on), date range (30 days default), cards grouped by
  priority and sorted newest first, inline YouTube player in a drawer when
  the episode has a link, else the episode page. Actions post to
  `/dashboard/api/mine/act` (`claim` / `start` / `release` / `mined` /
  `skip`), which PATCHes Full Episodes by **field id** (Miner, Mining
  Status, Claimed At) and mirrors the change into the snapshot so the next
  paint is right; the page re-reads every 30 s so a teammate's claim shows
  up. No record locking, same as the interface it replaces. **Identity is
  the shared team password plus a self-picked name** — fine internally,
  not an audit trail. Needs the gf-api Airtable token to have **write**
  scope on Full Episodes; the first real Claim proves it either way.
  `DASHBOARD_FAKE_DATA=1` serves 140 fake episodes for layout work.

- **Audience demographics** (2026-09-11): table `Audience Demographics`
  (`tblG4ElwziblQZM9E`): one row per account · platform · dimension (Age,
  Gender, Country, City) · segment · week (Monday). Written by
  `insta/demographics.py`, which runs inside the gf-facebook service on the
  first run of each Monday (UTC) or when `DEMOGRAPHICS_FORCE=1` is set on it.
  Source: Instagram `follower_demographics` (lifetime, total_value, one
  breakdown per call), which needs ≥100 followers. Accounts are discovered
  through `FACEBOOK_PAGES` page tokens (`instagram_business_account`), plus
  the Business's owned/client IG accounts when `META_SYSTEM_USER_TOKEN` and
  `META_BUSINESS_ID` are set (that path is what reaches Trading Places'
  Instagram, which has no Page). Matched to Channels by IG handle. The
  dashboard keeps each account's latest week and shows an Audience card
  (age, gender, top countries, top cities) on the overview and client
  pages, hidden when empty. **The gender chart is men vs women only**
  (2026-09-21): Instagram's `U` bucket, stored as segment "Unknown", is
  filtered out of that one chart so the doughnut reads as a ratio, and the
  percentages recompute over the two. It is typically 10-25% and is mostly
  business, brand and creator accounts rather than people who declined. It
  is still written to Airtable, and the count plus its share of all
  followers is in the info bubble beside the heading. The city-share
  denominator deliberately still uses the full gender total, so city
  percentages remain shares of all followers. Facebook/TikTok/YouTube demographics: not
  pulled (Facebook's are country/city only; TikTok has none via API).
- Not yet: YouTube
  retention, anything per-day for views (would need a Posts view log).

### `gf-follower-snapshot` — daily follower history (created 2026-09-09 06:15 UTC)

Render cron `crn-dagfipid0e5s73c9rcn0`, Spencer's repo, `0 9 * * *` (after the
overnight follower syncs), runs `followers/snapshot_followers.py`. Copies the six
per-platform follower fields on Channels into **Follower Logs**
(`tblsSv5OlermzmpZh`) — one row per channel per platform per day, `Previous
Count` from the latest earlier row, idempotent within a day, `SNAPSHOT_DATE` for
backfills. No platform API calls. Platform labels: Instagram, TikTok, X,
YouTube, Facebook, Threads.

First successful run 2026-09-09 17:21 UTC (manual trigger): 34 channels, 74
rows. The 09:00 UTC scheduled run that day failed with
`KeyError: 'AIRTABLE_PERSONAL_ACCESS_TOKEN'` — the token was not saved yet.
Facebook follower history will read flat until the Facebook followers pass
actually matches channels (see above).

Formulas on Follower Logs were changed so day one is not "Infinity": `Daily
Change` and `Percent Change` are blank when `Previous Count` is blank.

**Episode sync v2 exits 1 when any one feed fails** (seen 2026-09-19 09:02
UTC, one Render alert email): `This Past Weekend w/ Theo Von` returned
`ConnectionResetError(104, 'Connection reset by peer')` from
feeds.megaphone.fm. Every other run that day succeeded, and the 10:02 run
read the feed fine with nothing new, so no episode was missed. The job runs
hourly and is idempotent, so a transient blip on any of the feeds costs
nothing but still sends an alert. If these emails get noisy, the fix is to
exit non-zero only when a feed fails several runs in a row rather than once.

**SB_MODE left on for 11 days silently stopped the daily snapshot**
(2026-09-10 → 2026-09-21, found 2026-09-21 when Spencer noticed flat YouTube
and X lines for Trading Places). `snapshot_followers.py` ends with

    if __name__ == "__main__" and os.environ.get("SB_MODE"):
        socialblade_backfill.main(); sys.exit(0)

so the backfill runs **instead of** the snapshot, not alongside it. Social
Blade covers only Instagram, TikTok and Facebook, so for 11 days every
channel got zero YouTube, X and Threads rows: 15 YouTube rows and 12 X rows
existed in the whole table, all stamped 2026-09-09, the day of the seeding
run. Instagram and TikTok looked healthy throughout, which is why nothing
looked wrong until someone read a chart.

The counts themselves were never lost — Channels held current values the
whole time (Trading Places YouTube 116 → 123, X 2,227 → 2,226). Only the
per-day history is gone, and for X it is unrecoverable since Social Blade
does not carry X. YouTube history could be pulled back by adding `youtube`
to `SB_PLATFORMS`, which is not in the default list.

**Fix applied 2026-09-21 07:14 UTC:** `SB_MODE` set to the empty string on
gf-follower-snapshot (deploy `dep-daodif0ae00c73c3q900`). Empty is falsy in
Python, so the hook is skipped and `main()` runs, and a single-key merge
avoids pulling any other env var into context. Do not set it to "off" —
that is a non-empty string and would still trigger the backfill.

**Footgun closed the same day** (commit 620f150): the snapshot now always
runs, and a backfill, when SB_MODE is set, runs *after* it rather than in
place of it. A flag left on now costs Social Blade credits and log noise
instead of eleven days of data. Clearing SB_MODE when a backfill is done is
still the right habit, but forgetting no longer loses rows.

**Social Blade backfill** (`followers/socialblade_backfill.py`, 2026-09-10):
Spencer bought 100 Business API credits ($50). `SB_MODE=probe|run` on the
snapshot service runs the backfill instead of the daily snapshot (remove it
afterwards). API: `GET https://matrix.sbapis.com/b/{platform}/statistics?query=
{handle}&history=archive`, headers `clientid`/`token`; response `data.daily[]`
= one row per day (followers, following, media, avg_likes, avg_comments),
capped at 1,094 days. Cost: 0 credits for an untracked account (you only get
today, and tracking starts), 1–3 for one with history. X: every query 404s —
Social Blade dropped it. Facebook: vanity names only. First run 07:51 UTC:
55 profiles, 893 rows (thinned), 19 credits, 81 left; history only for
Trading Places IG (from 2026-07-17), All-In TikTok (2022-12), Solana IG
(2023-01), Weights & Biases IG (2023-08) and TikTok, Good Politics TikTok,
Oliver Wyman TikTok, The Techno Optimist IG. `SB_FULL=1` keeps every day;
`SB_ONLY=name,name` limits accounts. Rows carry Notes = "Social Blade
backfill".

**Trading Places Instagram, before Social Blade (2026-09-16):** Social Blade
only had this account from 2026-07-17. Spencer exported "Follows" from Meta
Business Suite (`tpp Follows on IG.csv`, UTF-16, one row per day
2025-10-10 → 2026-09-15, 11,761 follows total) and the summary showed 957
unfollows over the same span, with no daily unfollow series. The 280 rows
2025-10-10 → 2026-07-16 in Follower Logs are reconstructed: cumulative follows
minus unfollows spread pro rata (8.14% of each day's follows), anchored so the
series meets Social Blade's 9,646 on 2026-07-17 (it lands on 9,624 the day
before). Daily shape is right; individual days are approximate. Notes on those
rows = "Meta Insights backfill (follows export; unfollows pro rata)". Written
through the Airtable MCP with field ids (names are rejected on create), 50 per
call; a CSV copy of the same rows is in
`~/Desktop/temp/trading-places-instagram-follower-backfill.csv`. The dashboard
reads the whole Follower Logs table, so the client page picks it up on the next
15-minute refresh.

**Account Insights** (`tbl5tBiqrbwN3WgzT`, 2026-09-16): one row per account
per day with account-level Reach and Views — the numbers Business Suite shows
under Insights. Fields: Key ("<Channel> · Instagram · <date>"), Social Media
Account (link), Platform, Date, Reach, Views, Source. Trading Places
2025-10-11 → 2026-09-15 (340 rows) came from two Business Suite exports
(`TPP IG impressions.csv`, which is actually Reach, and `TPP IG Views .csv`;
UTF-16, `sep=,` header line, zero rows before the account existed dropped).
Going forward `insta/account_insights.py` runs at the end of every
gf-facebook run: `reach` as a `period=day` time series (30-day windows,
end_time minus 12 h = the day), `views` one `metric_type=total_value` call
per day, last `INSIGHTS_LOOKBACK_DAYS` (7) days, upsert by Key, Source
"Instagram Graph API". `INSIGHTS_DISABLE=1` skips it; set the lookback to
90 once to backfill an account Social Blade/Meta never covered. Accounts
match Channels by IG handle, same as demographics. Not verified against the
live API yet — check the next gf-facebook run's log for the
"📡 Instagram account insights" block.

**Videos has two rollups of post Views, and they mean different things**
(learned 2026-09-21). `fldBTytz2Zd8oUOKl` is the **SUM** across every post
that video became — the video's total views, and what the dashboard's video
drill-down shows. `fld8E161mTjNpn5iF` is the **MAX**, the best single post,
and it feeds the views-bonus formula (`fld5MbBSMRKuLhDaM`: $2 at 10k, $10 at
50k, up to $100 at 1M). Picking the wrong one silently understates a video.
Verified against the posts on three records, e.g. "How Flock Safety Was
Born": posts 38 + 6,090 + 1,087 + 1,123 = 8,338 = the SUM field, while the
MAX field reads 6,090. `fld3JS6ACIpCHGlYf` counts the posts.

These are lifetime totals for the video, whenever its posts went out, so the
drill-down total deliberately does not reconcile with the Views tile for the
selected date range. The drawer subtitle says as much.

**Three ways to define a client dashboard** (`dashboard/data.py`,
`client_view`). All three strip editor, director, poster and client
attribution before anything leaves the server.

1. **By show** — slug is the slugified show name. Gets that show, the
   channels linked to it, and posts on those channels or cut from its
   episodes.
2. **By accounts** — `CLIENT_GROUPS="ffp=FFP:Steelman|US In Common"`.
   Exactly those channels and their posts.
3. **By title word** — `CLIENT_MATCHES="flock=Flock:flock"` (added
   2026-09-21, for work where the Client field on Videos was never filled
   in). Every clip whose **title** carries that word, case-insensitive,
   wherever it ran. The post's own hook text is deliberately not searched,
   or anything using the word in passing would be swept in.

**A title-matched client gets post performance only, by design.** Flock's
88 posts all ran on The Techno Optimist, which has 2,704 posts in total, so
that account's followers and audience are not Flock's. `client_view` returns
no channels, no follower rows and no demographics for these, and nulls each
post's channel so a shared account is not disclosed to the client. The page
adapts: no Followers tile, no follower or accounts cards, a footer without
the counts it cannot report, and the "Views by account" card hidden because
with no accounts it collapses into a copy of the platform donut.

**Adding one needs two env vars on gf-api**, and the page 404s until both
are set: `CLIENT_MATCHES` (the selector, safe for me to set) and an entry in
`CLIENT_PASSWORDS` (`flock=<password>`, which Spencer sets himself — I never
handle credentials). The local fake-data preview in
`gf-episode-sync/.claude/launch.json` carries a `flock=Flock:clip 1` fixture
so this code path can be exercised without real data.

**Followers can be dropped from any client page** — `CLIENT_NO_FOLLOWERS`
on gf-api, a list of slugs separated by `;` or `,` (added 2026-09-21,
commit c4426a2; currently `solana`). Solana's accounts are posted to by
many people besides us, so the follower count there is not something the
client paid for and reads as a claim we did not make; the work they are
buying is views on our clips. The flag empties the follower rows only, so
the page falls back to exactly the shape a title-matched client gets —
Followers tile, followers-over-time, net-change and accounts cards all
hide themselves — while channels, posts, videos and the account filter
stay as they were. `.claude/launch.json` carries an `all-in` fixture for
this path.

**The Videos `Show` field is a formula and a bad selector.** It is
`IF({episode's show}, {episode's show}, {channel's show})`, and it misleads
in three separate ways, all of which bit the Solana page on 2026-09-21:

1. **It lies about provenance.** Not one of Solana's videos has an episode,
   so every one falls through to the channel and comes out labelled with the
   single show hanging off that account. Clips cut from conference talks,
   interviews and other people's podcasts all claimed to be from the same
   show. Nobody set that; the formula fell through to it.
2. **It joins with `", "` across channels.** A video on both Solana accounts
   reads `"Solana Ecosystem Calls, Solana Ecosystem Calls"`, which plain
   equality against the show name never matched. 71 videos vanished this way.
   **This was never Solana-specific** — any client whose videos sit on two of
   their channels lost them. Fixed in commit 4c908a9: the selector now splits
   the lookup on commas.
3. **It is empty when a video has neither an episode nor a channel.** 27 more
   Solana videos.

Together those dropped **94 of Solana's 419 videos** — its page showed 31 for
the last 90 days where Airtable counts 73.

**The same formula zeroed the Videos tile on the team overview** whenever it
was filtered to one account (fixed 2026-09-22, commit 61673ea). Videos were
matched to an account by comparing that account's show names against the
video's Show — and a blank or `"Show, Show"` value equals no show name, so
the tile read **0** next to 514 posts. A video has no account of its own:
posts now carry their `video` id and the page builds a video → accounts map
once per load from every post (not the range-filtered ones, or narrowing the
range would unlink a video from whoever posted it). The show filter takes
either route as well — the name, split on commas, or an account of that show
having posted the video.

**So a client's videos can be selected by the Client Account link instead** —
`CLIENT_VIDEO_ACCOUNTS="solana=Solana"` on gf-api (slug = Client Account
name(s), `|`-separated), commit 4c908a9. That is the field that actually
records whose work a video is. Show-name selection stays the default for
everyone else.

**A page can also carry work tagged to the client elsewhere** —
`CLIENT_ALSO_BY_CLIENT="ffp=FFP"` on gf-api (slug = Client Account name(s),
`|`-separated; added 2026-09-24). FFP is an account group (Steelman + US In
Common), but videos made for FFP sometimes go out on our own accounts;
they carry Client Account = FFP (151 videos as of 2026-09-24) and their posts
inherit it in the snapshot, so both are added on top of the account-based
selection. A post from one of our accounts has its `channel` blanked, same
as a show-based page, so the client sees the clip and its numbers but not
which of our accounts ran it. Not applied to title-matched clients. The
Dashboards page notes it on the row.

**The Show record was renamed** `Solana Ecosystem Calls` → `Solana`
(`recvWuv9KSV6qg15z`, 2026-09-21), so the label is at least true now. It was
safe: the record is a Watchlist bucket created 2026-09-03 with no Client
Account and no episodes — OPERATIONS already listed it among the five shows
that will never sync. Renaming makes `slugify()` give `solana`, colliding
with the CLIENT_GROUPS slug of the same name; harmless, because `client_view`
checks groups before shows.

**`CLIENT_NO_SHOWS`** (commit 6d880de; currently `solana`) still drops the
attribution on the client page, since one show name on every row is noise
even when true. It clears the show from every video and post *after*
selection (selection by show has to happen first or the list comes back
empty), empties the shows list so the Views-by-show card hides, and the
drawer's Show column renders only when a row actually carries one.

**Client drill-down shows Episode, not Show** (2026-09-24). Videos in the
snapshot carry `episode` — the title of the linked Full Episode
(`flda34XvSlQaFXapj`) — and the client Videos drawer shows that column in
place of Show; the team drawer keeps Show and adds Episode. Both columns
render only when some row has a value. Coverage is thin where clips come
from YouTube segments or client source files rather than a logged episode:
BG2 has 35 of 315 videos linked to an episode, all from 2024, so its
recent range shows no Episode column at all — which is the honest result
until someone links clips to episodes.

**The video Type column is gone from client pages** (same commit). Every
clip is a Vertical Clip, so the column told a client nothing. It stays on
the team page, where Horizontal Clip / Full Episode / Promo / Repackaged /
Reposted are real distinctions.

**Stacked-chart drill-downs and Chart.js interaction modes** (fixed
2026-09-21, commit cbaea83). "Views by week posted" sets
`interaction: {mode: 'index', intersect: false}` so its tooltip can list
every platform for a week. The side effect is that `onClick` is handed
*every* element at that x in dataset order, so the shared `clickable()`
helper taking `els[0]` always drilled into the first series — clicking the
TikTok band opened the Instagram posts. `clickable()` now re-resolves the
element under the cursor with
`getElementsAtEventForMode(e, 'nearest', {intersect: true})` and passes a
`precise` flag: a hit on a segment drills into that platform, a loose click
in the column opens the whole week. Clicking a zero-height segment opens
nothing, which is correct.

Only this chart read `datasetIndex`; the donut, posting volume and shows
charts use `el.index` alone and were unaffected, though the donut resolves
through the same new path (verified: arc midpoints, not `arc.x/arc.y`, which
is the doughnut's centre hole). **When testing chart clicks from the
console**, call `chart.options.onClick(evt, els, chart)` with a synthetic
event carrying `x`/`y` and `native.offsetX/offsetY`; a plain
`dispatchEvent(new MouseEvent(...))` does not reach Chart.js.

**Dashboard KPIs (2026-09-16, reach reversed 2026-09-19):** Comments tile
removed everywhere (the number was 0 for most posts and read as broken);
Videos (created in range) sits next to Posts; "Avg views / post" and the
Comments column are hidden on client pages.

Reach was added on 2026-09-16 and taken back out on 2026-09-19. **Only
Instagram writes reach.** Meta refuses the Facebook post metrics
(`post_impressions_unique` errors on permissions, same wall as the Reels
probe); TikTok's Display API exposes no reach field at all, only views,
likes, comments and shares; YouTube's unique-viewers needs OAuth, which is
off the table; X and LinkedIn have none. On Trading Places that is 288 of
1,577 posts, so a Reach tile sitting beside an all-platform Views number
reads either as broken or as total unique people. The KPI tile, the Reach
table column and the "Accounts reached" chart are gone, along with the
Account Insights pull in `dashboard/data.py`.

Nothing was deleted on the data side: the Account Insights table, its
imported history and `insta/account_insights.py` all stay, so reach keeps
accruing daily and the display can be restored from commit 0825599 if
Facebook page-level reach ever works. **Untested idea:** page-level daily
reach may be reachable even though post-level is not, since page insights
are a different permission and we already hold the page tokens. Worth a
probe before promising a client anything.

**account_insights.py verified live 2026-09-19** on the 18:54 UTC gf-facebook
run: 7 Instagram accounts (Steelman, US In Common, Startup Academy, BG2, The
Techno Optimist, Solana, Trading Places), "0 rows added, 49 refreshed" —
the upsert-by-Key works and reruns do not duplicate. Reach returns one fewer
day than views (6 vs 7) because the day-series metric drops the boundary
bucket; that is expected, not a fault.

**Interface:** dashboard page **Follower Growth** (`pagIIR9TGpRTk9idM`) in the
**Business Tools** interface (`pbdv8aZFxfOCfl5r7`), created 17:45 UTC as a
draft — not published, because publishing an interface also publishes any
other unpublished drafts in it. Section 1 tabs by platform with total
followers and net daily change over time; section 2 has an Account dropdown
and a date-range dropdown, the same two charts, and a grid of snapshots.
Edit at `https://airtable.com/appxCYu0Tfwc6h7X7/pagIIR9TGpRTk9idM/edit`,
then Publish. With one day of data every chart is a single point.

### Stripe → Airtable invoice sync — inside `gf-api` (added 2026-09-25)

Invoicing runs through Stripe, so the **Good Future Invoices** base
(`appQTaSN3LkKVBgPe`, table Invoices `tblx9X2kSBfNYIDvy`) is now written by
`invoicing/stripe_sync.py` in gf-airtable-automation rather than by a form.
It runs as a thread inside gf-api every `STRIPE_SYNC_SECONDS` (default 900),
first pass 90 s after boot, because gf-api is where the two keys were pasted
(`STRIPE_API_KEY`, a restricted key with Invoices read + Customers read;
`AIRTABLE_INVOICES_TOKEN`, a PAT scoped to that base only). It also runs as
`python -m invoicing.stripe_sync [--dry-run]` for a backfill from a laptop.

**Each pass** reads every Stripe invoice (about 100, one or two pages; the
endpoint has no updated-since filter and a full read is what makes it
self-healing) and every row in the table, then:

- new finalized invoice → new row: Name = Stripe number (SOL-0010 style — the
  same per-customer numbering the hand-entered rows already used), Client
  Account, Amount = `total`, Invoice Date = finalized date, Invoice PDF from
  Stripe's `invoice_pdf` URL (Airtable fetches it into a real attachment),
  Status, Stripe Invoice (dashboard link);
- existing row → Status, Stripe link and Amount follow Stripe; Client
  Account, dates and PDF are filled only if blank, so a hand correction sticks;
- drafts ignored; a voided invoice never seen before is not created; void /
  uncollectible on a known row shows in **Status**.

Rows are matched by the Stripe Invoice URL first, then by number against
Name. Rows with no Stripe counterpart are untouched.

**Two fields were added** to the table for this: **Status** (single select
Open/Paid/Void/Uncollectible, `fldjnMdhGDYAOwdAA`) and **Stripe Invoice**
(URL, `fldDpgq8PCrDuzBxc`). The Business Dashboard's Unpaid/Paid tabs still
key off Invoice Date Paid, which the sync fills from `paid_at`.

**Client Account names.** Stripe customer names are not the base's short
names. The sync learns prefix → Client Account from the rows already there
(SOL→Solana, PVC→Trading Places, BG→Brad Gerstner, AJC→FFP …);
`STRIPE_CLIENT_MAP="NEW=Client Name;…"` pins or adds one; an unknown prefix
falls back to the Stripe customer name and logs
`no Client Account mapping for prefix …` so someone adds it.

**Client Account may be text, a single select, or a link to Client Accounts
(`tblT6T1af3OzvTwh8`)** — the main base had it as a link and Spencer is
recreating that. The sync notices a link from the rows it reads (record ids
come back as a list), resolves them to names through the Client Accounts
primary field, and writes names as one-item lists; with `typecast: true`
Airtable resolves a name to the matching client record and creates one when
the client is new. The learned prefix map works on names either way.

**Ignored:** `STRIPE_IGNORE="SPEN-0001"` on gf-api — a $10,000 test invoice
Spencer sent himself in 2022 that Stripe holds as Uncollectible; without the
ignore it would sit in Revenue Per Client. Exact numbers or `PREFIX-*`.

**First pass, 2026-09-25 17:01 UTC:** 109 Stripe invoices, 88 rows; created
7 (SOL-0011, AJC-0003, PVC-0014 — the three issued since the base was split —
plus 10X-0008 and 724B8BBD-0001, two 2024 invoices never entered by hand,
20FUND-0003, a $900 20VC invoice open since 2022, and SPEN-0001, since
removed); updated all 88 with Status and the Stripe link, and filled paid
dates on the four rows moved over that morning (SOL-0010 paid 2026-09-21).

**Manual runs:** `POST /dashboard/api/stripe/sync` (admin session; `?dry=1`
plans without writing) returns the summary; `GET /dashboard/api/stripe/status`
shows the last pass and any error. Failures never stop the timer — the next
pass retries.

### Videos linked from the Invoices base via a synced table (2026-09-25)

Airtable links cannot cross bases, so the Invoices base's `Videos` column
came over in the split as comma-joined text. Fixed by syncing the main base's
Videos table in: view **Invoicing sync** on Videos (main base; no filter — a
filtered-out video would drop off its invoice, because the synced table
deletes rows hidden in the source) → synced table **Videos**
(`tblJtJXCw7uCKaHNR`) in Good Future Invoices, read-only, automatic sync,
fields Video Title, Total Editor Pay, Date Posted, Client Account (a real
link, thanks to the "change plain text fields to linked records" box on
creation), Video Status, Date Created, Show.

On Invoices: **Linked Videos** (`fldKuTbGYxsbnc3Wf`, link to the synced
table; Airtable did create the reciprocal **Invoices** field
`fld8y5qjAJnMGNhGD` on the synced side, so "uninvoiced" = that field empty)
and **Editor Cost** (`fld9NaowJlQySeAxC`, rollup SUM of Total Editor Pay over
Linked Videos). The old text `Videos` and the static `Editor Cost (manual)`
(`fldGfUPsL1aL3EBgi`) are left for Spencer to delete; the rollup matched the
manual figure on all 13 invoices that had links ($834 total).

Re-linking was done from the old table's real links, not the text: the 155
video ids from the main base were matched to synced rows by **Date Created**
(unique to the second — 155/155, no misses). A `Record ID` formula field
(`fldVoG4211Gs8QkHB`) was added to the main Videos table for this and is
worth adding to the sync view for next time; it was not needed in the end.

**Business Tools interface** (`pbdvOKCj1c8onoP4w`) now has **Uninvoiced
Videos** (`pagoWhs8N4SbYvLux`: synced Videos scoped to `Invoices` empty,
grouped by client, dropdowns for client / video status / posted date) and a
rebuilt **Invoices** page (`pag997vGBTwdftX7a`, replacing `pagbuLC0F1KFjPIMI`)
with Status, Linked Videos, Editor Cost and the Stripe link, rows coloured by
Status, tabs Unpaid (paid date empty and not void) / Paid / Void.

Only 13 of the 84 pre-split invoices ever had videos linked (the Brad
Gerstner / Oliver Wyman / Slice / PVC-0001 ones); the rest legitimately show
$0 editor cost.

### Team, Contracts and Team Months — pay lives in the Invoices base (2026-09-25)

The per-video `Base Pay` / `Performance Bonus` / `Total Editor Pay` formulas
on the main base's Videos table are the experimental ones; compensation now
lives in **Good Future Invoices**, which only the people who should see pay
can open.

- **Team** (`tblVtqKWu348fHzCk`) — one row per person, seeded and kept
  current by gf-api from the main base's Team table (name, email, roles,
  status, start date; matched on `Main base record`, `fld3tOjQK9eDPofDz`).
  Computed: **Current Monthly Base** (rollup of the contract in force),
  **Avg Videos / Month** (finished as editor over the last three complete
  months ÷ 3), **Avg Cost per Video** (base ÷ average). Notes is free text.
- **Contracts** (`tblH057iCn5HvkScX`) — hand-typed: Person, Start/End Date,
  Pay Plan (Flat monthly / Base + performance bonus / Per video / Hourly /
  Other), Monthly Base, Per-video Rate, Hourly Rate, Pay Notes, Contract
  File. A raise or scheme change is a *new* contract with the old one
  ended, so history stays. `Is Current` / `Base if Current` are helpers.
- **Team Months** (`tbldc73RXSYfxOE0U`) — written daily by
  `invoicing/team_months.py` inside gf-api (180 s after boot, then every
  `TEAM_MONTHS_SECONDS`, default 86400; from `TEAM_MONTHS_FROM`, default
  2024-01): per person per month, Videos Finished (editor, by Date Finished
  Editing), Videos Posted (editor, by the video's first post date), Videos
  Directed, and Base Pay from the contract in force on the 1st. Rows exist
  for any month with output or with a contract in force. **Bonus** and Notes
  are never written — type the bonus in until its rule is replicated.
  Cost per Video = (Base Pay + Bonus) ÷ Videos Finished. Rows are matched on
  Person + Month; the Key (`Name · YYYY-MM`) is display only.

Manual: `POST /dashboard/api/team-months/sync` (admin; `?dry=1`), status at
`GET /dashboard/api/team-months/status`. Uses the dashboard snapshot, so it
sees exactly what the Team page sees.

Interface pages in Business Tools: **Team & Pay** (people with their
contracts nested; tabs Active / Editors / Directors) and **Team Months**
(grid, Person and Month dropdowns).

Still to do, second step: write each video's estimated cost (its editor's
cost-per-video for the month it was finished) into a field on the main
base's Videos table so it syncs across and the invoice's Editor Cost rollup
sums it — replacing the Total Editor Pay formula the rollup reads today.

### AI Copywriter runs itself on the first transcript (2026-09-25)

The button-driven **AI Copywriter** (`wfl6mylWs1YZNYQv3`, trigger
`inputReceivedFromConnection`) now has a twin, **AI Copywriter (auto, first
run)** (`wflLTcQDipSDHjkUl`): trigger *record matches conditions* on Videos
with Transcript (`fldIgXa5EZCq9NF5O`) not empty AND the copy field
(`fld9EoWkILV5apHVU`) empty, same Opus prompt and same update. It fires once,
when a video first gets a transcript; the button remains the way to re-run
after editing Copywriting Notes. Created as a draft via the API — Spencer
turns it on in the UI. Records that already had a transcript when it was
switched on do not backfill (record-matches-conditions only fires on entering
the set).

**Team Months first pass, 2026-09-25 21:23 UTC:** 49 Team rows seeded, 280
person-months since 2024-01, 0 contracts (all Base Pay blank until contracts
are typed in).

### Mining board: client shows are assigned, execs can assign (2026-09-25)

Episodes of shows whose Relationship is **Client** (BG2Pod, Trading Places,
The First, Lenny's Podcast, ThursdAI, 5 Year Frontier today) sit in their own
**Client shows** section at the top of `/dashboard/mine`, ahead of the
priority groups, and are not up for grabs: only the show's usual miner can
claim one, everyone else sees "Assigned internally". The usual miner is the
new **Default Miner** link on Shows (`fldE0FjzekRf7Kh2u`, e.g. Courtland for
ThursdAI, Nick for Trading Places) — set it in Airtable, it shows as
"usually …" on the card and is preselected in the assign picker.

**Hide.** Execs get a small × in the top-right corner of every card (↺ on a
hidden card, visible with the "Show hidden" toggle on), with an instant
hover tooltip; hiding pops a toast with **Undo** for 7 s. It ticks **Hide from Mining Board** (`fld1SWYVBIN9ouRFr`, checkbox
on Full Episodes) and the episode leaves everyone's board. Non-execs see
"Ask Spencer or Chris" on a locked client-show card. Execs get **Unassign**
on a card someone else holds (a release in their name). All three are
`EXEC_ACTIONS` in routes.py; the API refuses them for non-execs.

Execs (Spencer, Chris — `is_exec`, the same rule as the Flock page) get an
**Assign… / Reassign…** button on every card, client or not: a picker with
Directors first, then everyone else. It posts `action: assign` with `who`;
the API refuses that action for anyone who is not exec or admin, and writes
the same fields as a claim (Miner, Mining Status = Claimed, Claimed At) in
the assignee's name. Snapshot: shows carry `default_miner(_id)`; episodes
carry `client`, `suggested`, `suggested_id`.

### Contractor Invoices — editors' and directors' invoices in the Invoices base (2026-09-25)

Every contractor invoice already arrives the same way: emailed to
**billing@goodfuturemedia.com** with `[BILLING]` in the subject and a PDF
attached (a Google group that lands in Spencer's inbox; he forwards each to
`goodfuture@qbodocs.com` for QuickBooks). Table **Contractor Invoices**
(`tblApcqbrnN31B6xP`) in Good Future Invoices: Invoice (label), Person →
Team, Invoice #, Period (first of the month covered), Amount, Hours, Clips,
Base, Bonus, Status (Received / Approved / Paid / Query), Received, Paid,
PDF, From, Subject, Email (Gmail link), Summary, Source (Email automation /
Backfill / Manual), Notes.

**Going forward** — automation **Contractor invoice received**
(`wflrrVTIsnlzJWGTm`, draft, in the Invoices base): trigger *email
received* at Airtable's own inbox address (prefix `gfm-contractor-invoices`;
the full address shows in the trigger in the UI). Steps: findRecords Team
where Email = sender → AI structured extraction from subject/body/attachment
names (person_name, invoice_number, period_month, amount, hours, clips,
base_pay, bonus, summary; "never guess an amount") → createRecord with
Status Received, Source Email automation. The API cannot map attachments
into a record, so **Spencer maps PDF ← trigger attachments in the UI**, then
turns it on, then adds the inbox address as a member of the billing@ group
(Google Admin → Groups → billing → Members). The AI reads the email, not the
PDF, so Amount stays blank when it is only on the PDF.

**Backfill, 2026-09-25:** 159 rows from Gmail, Sept 2025 → 2 Sept 2026
(the `[BILLING]` / billing@ era; earlier matches were Upwork and vendor
noise). Person linked for all but three senders who are not in Team (Oscar
Diaz, Ty Cox, Benjamin Hollinger — director test projects) plus Jimmy Loyloy
(manual data entry; add him to Team and link). Period from the subject's
month (an invoice dated the 1st–5th is the previous month's work);
invoice # from subject/snippet; Amount only where the email states a total
(15 rows, mostly Jaymark's hours/clips/base/bonus breakdowns); Status Paid
for anything received before 1 Sept 2026, Received after. Resends and
revisions are separate rows with a Note ("Revision of an earlier send"), so
a few people show two rows for one month (Vladimir ×4 for August, Carl ×3,
Alex/Celesti/Julius ×2) — delete the extras. Tax forms, IDs and Chris's
replies were excluded. No PDFs on backfilled rows; the Email link opens the
original.

Interface page **Contractor Invoices** in Business Tools: grid, tabs To pay
/ Paid / Needs a person.
