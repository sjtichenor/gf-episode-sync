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
  broadcast), Monitoring the Situation (X only), Genfinity, Solana Ecosystem
  Calls, The First (client that never launched).
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
