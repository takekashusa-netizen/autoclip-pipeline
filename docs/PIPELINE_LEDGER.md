# TakeKash Tools & Pipelines Ledger

Split out of the old CONTENT_LEDGER.md on 2026-09-26. Everything about tools, pipelines, scoring, publishing infrastructure, fixes and standing policies lives here; content tracking now lives in CONTENT_LEDGER.md.

## 📊 SEO RESEARCH — gaming category, 2026-09-15

Researched what actually drives top-ranked gaming videos on YouTube
generally (not just this channel) and checked it against this pipeline's
real code. Full writeup: `SEO_RESEARCH_2026.md`.

- Titles/descriptions/tags: already match current 2026 best practice
  (front-loaded keywords, researched length targets, real hashtags) — no
  change needed, verified against 6 external sources.
- **Confirmed gap: no custom thumbnail on either live publish path.**
  All 26 published videos are running YouTube's auto-picked frame. Two
  working thumbnail generators already exist in the codebase
  (`doctor.py::extract_thumbnail_for_window`, free/ffmpeg-based; and
  `lib/thumbnail_generator_ai.py`, DALL-E-based) but neither is called
  from `mcp_server.py` or `doctor.py`'s publish functions. Not wired in
  yet — needs a 15-30 min check on which job-file structure the
  interactive publish path's clips actually use before pointing the free
  extractor at the right files.
- Found and flagged (not fixed) a real gap in the third publish system,
  `lib/publish_scheduler.py`: no `content_type` tracked per queued item,
  so the same content-safety gate added after the apexnba2k2 incident
  can't be safely bolted on without guessing the genre — attempted it,
  caught that it would have false-blocked the correctly-labeled
  `interviewtest` content already sitting in that queue, reverted before
  shipping it.


## 🖼️ THUMBNAILS — gtaxlong1 batch (2026-09-15)

Picked up the confirmed gap from the SEO research above (no custom
thumbnail on any of the 26 live videos, both generators unwired).

**Real fixes shipped (not yet git-committed — see note below):**
- `doctor.py::determine_video_game` — was transcript-only, so it returned
  `None` for gtaxlong1 despite it being 100% Apex Legends (0 keyword
  hits in 8.3k chars of gameplay commentary — players rarely say the
  game's name out loud). Now also folds in the source VOD's own title
  (`raw/source_url.json` → "Apex Legends Ranked Gameplay"), which fixed it.
- `lib/thumbnail_generator_ai.py` — `build_dalle_prompt` and
  `add_text_overlay` both hardcoded "Apex Legends" / "APEX LEGENDS"
  regardless of the `game` argument passed in. Added a real `GAME_LABELS`
  map and wired both functions to use the actual detected game, so a
  future Warzone/NBA 2K/ARC Raiders job gets correctly branded instead of
  defaulting to Apex.

**Generated (free/ffmpeg path — no OPENAI_API_KEY or ANTHROPIC_API_KEY
set in this shell, so DALL-E art and AI-written titles were both
unavailable):** 14/14 real thumbnails for gtaxlong1, each a genuine
frame pulled at that window's real audio-transient peak (not a fixed
offset), branded "APEX LEGENDS" (verified correct), saved to
`thumbnails/gtaxlong1/window01..14_thumb.jpg`.

**Known limitation — not yet pushed live:** headline text on each
thumbnail is that window's real transcript hook line (from
`graphics/graphics-plan.json`), not the polished title already live on
YouTube. Tried to auto-match windows to the 31 published titles in the
section above by text similarity — only 2/14 matched with confidence
(window02 → "ALRIGHT, BUT..." clip, window12 → "GONNA SMELL IT OUT"
clip). No on-disk log records which window uploaded to which video ID
in order, so pushing the rest live risks a wrong thumbnail on the wrong
video. Left un-pushed pending window→video-ID confirmation.

**Flagged, not touched:** `apexnba2k2` / `interviewtest` (both process
the same source, youtu.be/UPTIAdG3REM — the Rainwater interview
discussing Mo3's death) are NOT gaming content. Ran the fixed game
detector against it as a test and it false-positived to "World of
Warcraft" (transcript contains casual "wow" as an exclamation, which
matches the `wow` keyword) — concrete confirmation of the
content-safety gap already flagged above. Excluded from thumbnail
generation entirely.

**Also noted, not acted on:** the repo has substantial pre-existing
uncommitted local changes (29 modified files, ~90 untracked files
including what look like SSH keys and OAuth tokens) unrelated to this
task — left as-is rather than bundling into a commit.

---

## 📊 SECURITY / INFRASTRUCTURE PASS — 2026-09-15

Follow-up to the SEO research and the flagged-but-unfixed content-safety
gap above. Root-caused and fixed the actual infrastructure, then used the
fixes to audit the real database.

**1. Local MCP server was silently starving itself.** `mcp_server.py`'s
`submit_clip_job` ran the fetch step as a blocking `subprocess.run(...,
timeout_sec=1800)` inside the server's single-threaded stdin loop —
contradicting its own docstring's claim that it "runs in the background."
Every call (even unrelated ones) could hang up to 30 minutes behind it.
Fixed by chaining fetch+clip into one detached `subprocess.Popen(["bash",
"-c", ...], start_new_session=True)` call. Confirmed working with a clean,
fast resubmit.

**2. No cross-job duplicate-URL protection existed.** Two full Twitch VOD
downloads of the same link could (and did) run side by side. Built
`lib/url_index.py` — a durable, atomically-written JSON index
(`source_url_index.json`) keyed by normalized URL, recording submit time,
resolution (title/duration/canonical id), and errors. Wired into
`mcp_server.py::tool_submit_clip_job` (blocks a resubmit of a URL that's
already fetching or done, unless `force=true`) and `lib/fetch_url.py`
(records the real resolved metadata once yt-dlp finishes).

**3. `verify_content_type` only ever checked `content_type == "gaming"`.**
A job declared `content_type="reaction"` got no check at all. Extended the
same high-confidence self-reference check (transcript literally says
"interview"/"podcast") to cover `"reaction"` too.

**4. `doctor.py::find_clip_metadata` was structurally broken for almost
everything.** It required `rough-cut/clips.json`, which exists for
exactly ONE job in the entire pipeline (`job1786627920`) — every other
best-windows job returned `None`, meaning `doctor.py`'s autonomous
auto-publish loop and `mcp_server.py`'s interactive publish tool couldn't
generate real metadata (or a thumbnail) for the vast majority of real
output. Added a free, deterministic fallback,
`find_best_windows_metadata()`, reading directly from
`best-windows/windows.json` + `rough-cut/script.json` — no paid API, no
new dependency. Also wired the pre-existing, free
`extract_thumbnail_for_window` (ffmpeg, real audio-transient peak) into
both publish paths, which this fix unblocks. Verified against
`gtaxlong1__window01`, `apexnba2k2__window01`, `job1788203913__window01`,
and the one real `clips.json` job (regression check).

**5. No duplicate-*publish* protection.** Fixed the duplicate-*download*
problem (#2) but nothing stopped the same source URL's clips from being
published to YouTube twice under two different job IDs (the exact
`job1788368131` / `job1788482095` situation below — same source, two
separate fetches). Added `check_duplicate_source_publish` /
`mark_source_published` to `lib/url_index.py` + `lib/youtube_publish.py`,
wired into all three publish paths (`mcp_server.py`, `doctor.py`,
`lib/publish_scheduler.py`).

**6. Real security hole found and closed: the content-safety gate failed
OPEN, not closed.** `verify_content_type` returned `True` (pass) for any
`content_type` other than exactly `"gaming"`/`"reaction"` — including
blank/`None`. `mcp_server.py` and `doctor.py` both happen to default
`content_type` to `"gaming"`, so they were incidentally protected, but
`lib/publish_scheduler.py`'s YouTube branch explicitly *skipped the gate
entirely* when a queued item had no `content_type` set. Since this
channel's real rule is unconditional — "no interviews on youtube just
gaming content or reaction videos" — changed `verify_content_type` to
fail CLOSED: a missing or off-menu `content_type` is now itself a
blocking reason, not a free pass. Removed the now-redundant (and
actually-wrong-in-practice, since it's youtube-only) skip in
`publish_scheduler.py` so the gate always runs. Verified: blank/`None`/
`"podcast"`/`"irl"` all now correctly blocked; real gaming/reaction
content (`gtaxlong1`, `job1786627920`, `job1786890425`) still passes; the
three disqualified jobs below stay blocked under *either* claimed
content_type.

**7. Database audit — `takekash.db` (Task #10/#15).** Used fix #4's new
metadata resolver plus each job's `raw/source_url.json` to check every
one of the 87 rows in `clips` against its REAL source. Result: **70 of 87
(80%)** are not gaming or reaction content at all —
  - **53 rows** (`job1788368131` ×11 windows, `job1788482095` ×36 windows
    — duplicate fetches of the same source) are the real YouTube video
    "Judge Joe Brown Holds Nothing Back on Don Lemon, Tyler Perry, Judge
    Mathis and the Epstein Files" — exactly the "judge" content flagged
    for removal. `content_type="gaming"` (doctor's default) correctly
    fails these via the transcript self-reference check.
  - **17 rows** (`apexnba2k2`) are the "Rainwater" street-culture
    interview about Mo3's death, already flagged (not acted on) in the
    SEO section above — same result: correctly fails the gate.
  - The remaining 17 rows (`job1786627920` ×16, `job1786890425` ×1 —
    "Slime Time!") pass the content-safety gate and have no evidence
    against them, but `detect_game()` found no known game name in their
    real transcript OR source title either — left `game` = NULL rather
    than guess one. This is the honest state of the "games played"
    column: it can't be backfilled from data that doesn't name the game.
  - **Corrected the database to match reality**, rather than leaving it
    silently wrong: `clips.status` set to `'disqualified'` for the 70
    rows above (was `'ready'`, indistinguishable from real content);
    `social_posts.status` set to `'blocked'` for all 135 rows tied to
    them (was a mix of `published`/`pending`/`error`), with each row's
    original status and any prior error preserved in `error_message` for
    forensics rather than overwritten.
  - **Caution on the 9 rows that showed `status='published'` for
    YouTube:** `publish_id` and `platform_post_id` are `NULL` on all 9,
    and `takekash.db` is confirmed (`lib/db.py::migrate_from_queue`) to
    be a one-way, insert-only mirror of a past `publish_schedule.json`
    snapshot — never read back by any live publish path — so
    `status='published'` here is not proof anything actually went out.
    Two of these nine (`job1788368131`/window07,
    `job1788482095`/window17 — the "TV Judge Exposes..." /
    "Judge Judy Explains..." titles) were already checked directly
    against YouTube Studio earlier this session and confirmed NOT live.
    The other seven were not individually re-checked against Studio this
    pass — flagged for the user, not asserted as fact.
  - **No live risk found**: the actual operative queue,
    `publish_schedule.json`, currently has zero YouTube items and zero
    entries referencing any of the disqualified job IDs. The 135 stale
    TikTok/Instagram/YouTube rows corrected above were dead data in a
    mirror table, not something that was about to go out.

**Not done this pass:** re-verifying the other 7 "published" YouTube rows
against Studio directly (Task #10, remainder); populating the `analytics`
table with real view/like/comment counts (Task #16, blocked on running
`fetch_youtube_stats.py` — new this pass, at the pipeline root — ON THE
MAC directly, since `oauth2.googleapis.com` isn't reachable from the
sandboxed device_bash VM); the recurring "optimizing data specialist"
system (Task #17, depends on #16).

---

## 🎮 GAME CATEGORIZATION — 2026-09-15 (follow-up)

Real fix for a real gap the audit above surfaced: `detect_game()` found
**zero** matches on every one of the 17 legitimate (non-disqualified)
clips — not because nothing was gaming content, but because streamers
essentially never say a game's name out loud mid-match. Researched each
job's actual source instead of guessing from its (sometimes misleading)
Twitch title:

- **`job1786627920`** (16 clips, Twitch VOD 2839814600, no title
  captured) — real transcript is dense with Apex-specific jargon: "ring
  countdown", "kill leader", "care package", "jump master", "recharging
  shields" — this is Apex Legends, confirmed by *style*, not name.
- **`job1786890425`** (1 clip, Twitch-titled **"Slime Time!"** — which
  sounds like Minecraft and would've been a bad guess) — real transcript
  is wall-to-wall soccer-match commentary: "short corner", "offside",
  "extra time", "the keeper", "penalty kick". This is EA Sports FC, not
  Minecraft. The Twitch title was not a reliable signal here.
- The two VODs submitted this session (`gtaxlong1` /
  `b951cc787dc7`) both carry the real Twitch title "Apex Legends Ranked
  Gameplay" — already correctly tagged once they clear the pipeline.

**Built a real style-signature detector** (`GAME_STYLE_SIGNATURES` in
`lib/youtube_publish.py`) as a third tier in `detect_game()`: literal
game-name keyword match (existing) still runs first, then falls back to
each game's own distinctive in-match phrases (Apex: ring/kill
leader/care package/jump master; Warzone: gulag/buy station/loadout
drop; EA Sports FC: short corner/offside/extra time/penalty kick; CoD
Zombies: pack a punch/perk-a-cola/mystery box; GTA Online:
Cayo Perico/heist setup/wanted level; Minecraft: nether/redstone/
enderman/slime chunk) — **requires 2+ distinct phrase hits** before
returning a game, so one ambiguous word can't trigger a false positive.

**Also fixed two real bugs in the existing literal-keyword tier while
verifying this against known-bad content** (the two judge-show
transcripts and the apexnba2k2 interview, run as a control group so the
new detector couldn't be validated only against content it was designed
to catch):
- Matching was plain substring (`keyword in text`), not word-bounded —
  `"rust"` was matching inside `"thrust"` and `"trust"`, producing a
  false "Rust" detection on **both** disqualified judge-show transcripts.
  Switched to `\b`-bounded regex matching.
- `"wow"`, `"2k"`, and `"lol"` were registered as bare, standalone
  keywords — all three are common enough as plain
  English/chat-shorthand (an exclamation, "$2k"/"2k views", laughing)
  that they produced real false positives even as whole-word matches
  (confirmed: `"wow"` false-positived to "World of Warcraft" on
  `apexnba2k2`'s interview transcript, twice, just from someone saying
  "wow" as an exclamation). Dropped the bare forms; kept the unambiguous
  full phrases ("world of warcraft", "nba 2k", "league of legends").

**Backfilled `clips.game`** for all 17 `status='ready'` rows with the
verified results above (16 × Apex Legends, 1 × EA Sports FC) — this is
now the honest, evidence-based state of the "games played" column:
every non-NULL value traces to real, specific jargon in that clip's own
transcript, and nothing was guessed from a job name or a Twitch title
alone (the "Slime Time!" case is the concrete reason why).

**Channel's real game roster** (from the channel's own public
About/panels, for reference — not all of these have appeared in the
clips DB yet): CoD Zombies, Call of Duty Warzone, GTA 5 (RP/Heists),
Minecraft, Apex Legends, and EA Sports FC (FC26). `GAME_STYLE_SIGNATURES`
above covers all six so future clips from any of them get a real
category even when the game is never named out loud.

---

## 📤 WIRED TO REAL PUBLISHING — 2026-09-15 (follow-up)

Real production + real queueing to actually act on the audit above, not
just leave it documented.

**Blocker found first:** none of the 126 TikTok/Instagram rows sitting
in `takekash.db` as `error`/`pending` for the disqualified clips could
actually be wired to real publishing as-is. 92 of them (the judge-show
jobs) have no rendered video at all — `export` never ran, confirmed no
`outputs/job1788482095*` or `outputs/job1788368131*` exists on disk. The
remaining 34 (`apexnba2k2`) had a real file, but it was the long-form
1920x1080 YouTube export, not short-form vertical — exactly the mismatch
`publish_scheduler.py`'s own docstring says it refuses to force.

**Rendered the real thing for `apexnba2k2`:** ran
`skills/clip-select/extract_best_windows.py --vertical` against the
existing (unchanged) `best-windows/windows.json`, reusing all already-
computed analysis (no re-transcription) — real 1080x1920 crops with the
GtaxZombies karaoke caption style burned in, output to
`outputs/apexnba2k2_vertical/apexnba2k2_window01.mp4` .. `_window17.mp4`
(the exact path the DB's `clip_path` already expected). 16/17 have real
burned-in captions; window 17 (a 720s outlier — the others are 300s) is
the plain vertical crop without the caption burn-in, because that
specific pass kept exceeding the available compute budget — a real,
usable video either way, just missing the text overlay on that one clip.

**Two real bugs fixed in `extract_best_windows.py` while doing this,
both found the hard way running it for real:**
- No resume support meant any interruption mid-batch forced redoing
  every already-finished window from scratch. Added resume — but the
  first version only checked file size (`> 100_000 bytes`), which is
  NOT proof of a finished file: an interrupted write is already well
  over 100KB before the moov atom (written last by libx264) exists,
  so every retry accepted a "moov atom not found" corrupt file as done
  and moved on. Confirmed directly: a full 17-window batch "completed"
  under the size-only check while EVERY file was actually truncated.
  Fixed by actually probing with ffprobe and only accepting a real,
  readable duration.
- The expensive crop-extract ffmpeg pass was getting redone on every
  retry even when only the (separately expensive) caption-burn pass
  needed another attempt. Now reuses a valid `.extracted.mp4` if one's
  already there.

**Wired the real, verified result into the live queue:** all 34
TikTok/Instagram `social_posts` rows for `apexnba2k2` (17 windows x 2
platforms), using their already-generated real titles/descriptions/
hashtags from the DB, enqueued via `publish_scheduler.py`'s own
`enqueue()` — not hand-built JSON — so the existing 2-3-slot/day
research-backed scheduling applies exactly like it does for
`interviewtest`. All 34 `video_path`s verified to exist before
enqueueing. Spread across Sep 15-21, `content_type="reaction"` (checked,
harmless here — the gate only runs on the YouTube branch and these are
tiktok/instagram only). The 92 judge-show rows remain un-wired — no
video exists for them yet, and rendering their long-unrun `export` step
is separate, not-yet-done work.

## 🎬 JUDGE-SHOW RENDER + WATERMARK + WIRE — 2026-09-15 (follow-up 2)

User asked to render the two remaining judge-show jobs (job1788368131,
job1788482095) vertical for TikTok/IG like apexnba2k2, watermark every
render with the GtaxZombies logo, and make watermarking a permanent
pipeline feature ("add that to the kit").

**Duplicate-source finding (job1788368131 skipped):** window-timestamp
comparison showed job1788368131 (11 windows) and job1788482095 (36
windows, same source youtu.be/17-bJxitjvg) are the same raw footage
re-segmented — job1788482095 is a finer-grained, complete superset
(e.g. job1788368131's single 490.0-1550.0 window is covered by several
of job1788482095's shorter windows). Rendering and posting both would
duplicate the same content across TikTok/Instagram. Rendered only
job1788482095; job1788368131 intentionally skipped as a confirmed dup.

**Logo asset:** already registered and real — `assets/asset_registry.json`
id=1, `assets/gtax_zombies_watermark.png` (180x180 RGBA, owned license).
No need to source a new one.

**Watermarking added to the kit (permanent, not one-off):**
`skills/clip-select/extract_best_windows.py` now overlays the logo
top-right (30px padding, scale 180px wide, alpha 0.85) on every window
it extracts, vertical or not, whenever the asset file exists —
`_build_extract_filter()` + `WATERMARK_PATH` / `_watermark_available()`.
Combined into the SAME ffmpeg pass as the crop/scale (via
`-filter_complex` with a second `-loop 1` logo input) instead of a
separate re-encode, to stay inside the tool-call time budget. Verified
visually on a real 5s test clip before running the full batch — logo
renders cleanly, correct size/position, no artifacts.

**Real perf bug fixed along the way:** `skills/rough-cut/ass_caption_burner.py`'s
caption-burn ffmpeg call had no `-c:v`/`-preset` at all, silently
defaulting to libx264's "medium" preset while the rest of the pipeline
uses "veryfast" — a real, unnecessary slowdown on every caption burn.
Added `-c:v libx264 -preset veryfast -pix_fmt yuv420p -color_range tv`
to match convention.

**Render result:** all 36 windows of job1788482095 extracted successfully,
zero failures, real 1080x1920, watermark burned into every one (16
also have burned-in karaoke captions via the word_groups path; the
rest fell back to plain watermarked+cropped video when word-level
timing wasn't available for that window — still real, publishable
clips, just without caption burn-in). Total ~1.3GB in
`outputs/job1788482095_vertical/`.

**Metadata + wiring:** 35 of 36 windows already had real title/
description/hashtags in `takekash.db`'s `social_posts` table from
earlier work — reused those. Window16 had no DB row (metadata was
never generated for it) and the AI metadata generator
(`generate_clip_metadata_scored`) needs `ANTHROPIC_API_KEY`, which
isn't set in this shell — wrote its title/description/hashtags
directly from its real transcript segment (the judge explaining the
2000 CA Supreme Court opinion + 2007 SCOTUS "Judge Alex" ruling on
binding TV arbitration under the 1928 Arbitration Act) rather than
leaving it unqueued or guessing. All 72 items (36 windows x
tiktok+instagram) enqueued via `publish_scheduler.enqueue()` with
`content_type=None` — matching the `interviewtest` precedent exactly
(judge-show/interview content is legitimate for TikTok/IG, per the
user's "disqualified is for tiktok instagram" correction; the
YouTube-only safety gate never runs on these). Scheduled Sep 21 -
Oct 3 2026, continuing the existing slot cadence after the apexnba2k2
batch.

**Real path bug found and fixed (affected apexnba2k2 too):** every
`video_path` enqueued from inside this sandboxed device-bridge shell —
both the 34 apexnba2k2 items from the prior session and all 72 new
judge-show items — got written with the sandbox VM's mount path
(`/sessions/<id>/mnt/autoclip-pipeline/...`) instead of the real Mac
path (`/Users/Apple/autoclip-pipeline/...`), because `os.getcwd()`
inside this bridge resolves to the VM mount, not the Mac's own
filesystem. That path is meaningless outside this bridge — every one
of these 106 queue items would have failed at actual publish time on
the Mac with a file-not-found error. Fixed by rewriting the prefix on
all 106 affected `video_path` values in `publish_schedule.json` and
re-verifying each file still resolves. Worth remembering for any
future device-bridge session that writes paths into this queue.

Queue total after this batch: 127 items.

## 🔁 APEXNBA2K2 RE-RENDER FOR WATERMARK — 2026-09-16

User asked to fix the apexnba2k2/watermark gap flagged above. Re-rendered
all 17 apexnba2k2 windows through the now-watermark-enabled
`extract_best_windows.py` (deleted the old un-watermarked outputs first
so the resume logic wouldn't skip them as already-done). 16 of 17 now
carry the GtaxZombies watermark + existing karaoke captions, matching
the judge-show batch.

**window17 (the 720s/12-min outlier) — watermark not applied, real
limitation, not silently dropped:** this same file was the one caption
burn-in couldn't finish on in the original render either. This time,
neither the combined crop+watermark single pass nor a plain
watermark-only overlay pass on an already-cropped file would complete
within the tool-call time budget, across 4 separate attempts (veryfast
and ultrafast presets, with and without audio re-encode) — the plain
crop alone consistently succeeds in one pass, so the stall is specific
to the overlay/loop filter graph on this particular file, not a general
slowdown. Shipped as the valid, correctly-cropped 1080x1920 clip
without the watermark rather than keep burning render cycles on it.
`publish_schedule.json`'s `apexnba2k2_window17_tiktok` /
`..._instagram` entries still point at the same real file path, so no
queue changes were needed — just flagging that this one clip (of the
now 53 real vertical clips across both jobs) ships unbranded. Worth a
look with more headroom (e.g. running the overlay pass directly on the
Mac outside this bridge) if it matters enough to chase further.

## 🔐 ADMIN DASHBOARD — takekash.com/admin.html — 2026-09-16

**Request:** "make this one system on the website strictly for admin like myself" → clarified to mean an owner-only dashboard for managing streams/content (jobs, publish queue, posts), not the overlay and not the customer product system.

**Architecture decision (user confirmed):** Snapshot sync, not a live backend. Rationale: takekash.com is a static Netlify site (no git remote — deployed via Netlify CLI direct-folder deploy, siteId af2e3c08-6d6b-44bf-a0d4-f56222453140) with no existing auth or backend data layer. The real data (takekash.db, publish_schedule.json) lives only on the Mac. A live backend would require standing up a hosted DB and a live write-path — real new infra and an ongoing sync/consistency burden. A snapshot avoids opening any port on the Mac and needs no new hosted service.

**Discovery along the way:** `command-center.html`, `job-status.html`, `pricing.html`, `privacy.html`, `terms.html`, `thumbnail-generator.html` at the site root are all Netlify's default 404 placeholder (4031 bytes, identical) — dead/unused files. The real site is a single-page app inside `index.html` (~1095 lines) with client-side routing (`showPage()`), and it already has real Command Center / Job Status / Pricing pages with **mocked/static demo content**, not live data — `startCheckout()` posts to `/api/create-checkout-session`, which doesn't exist yet (no Netlify Functions were deployed before this). Also found `lib/saas_auth.py` (PBKDF2 password hashing), `lib/saas_billing.py` (Stripe pay-per-clip credits), `lib/saas_db.py` (multi-user SQLite layer) already built in the pipeline repo — real scaffolding toward turning this into a multi-tenant product, separate from today's admin-dashboard work.

**Built:**
- `lib/export_admin_snapshot.py` — reads `takekash.db` (clips grouped into jobs by source folder, social_posts by status/platform) + `publish_schedule.json` (upcoming queue), writes a single JSON snapshot.
- `takekash-site-live/netlify/functions/admin-data/admin-data.mts` — Netlify serverless function; only serves the snapshot when request header `x-admin-key` matches the `ADMIN_KEY` env var (set in Netlify dashboard, not in the repo). Wrong/missing key → plain 401.
- `takekash-site-live/netlify/functions/admin-data/snapshot.json` — first real snapshot, generated today (87 clips, 152 social posts, 127 queue items across 5 jobs).
- `takekash-site-live/admin.html` — owner-only dashboard: password gate (key kept in sessionStorage per-tab only), then tiles + jobs table + upcoming-queue table + recent-posts table, all matching the site's existing dark/gold theme. Not linked from site nav; `noindex, nofollow`.
- `takekash-site-live/ADMIN-SETUP.txt` — one-time setup (set `ADMIN_KEY` env var in Netlify, then `netlify deploy --prod`) and the refresh workflow (re-run export script, redeploy) for future syncs.

**Verified:** Full gate → wrong-key (401, error shown) → correct-key → render flow tested locally with Playwright against a mock server serving the real snapshot data before shipping. Screenshots confirmed correct rendering of all sections.

**Not done here (separate, by design):** Wiring `/api/admin-data` requires a Netlify deploy from the user's own Mac terminal (the CLI login for the real takekash.com site isn't available from this session's sandboxed device bridge, and the Netlify MCP connector in this session turned out to be authenticated to a *different* Netlify account than the one hosting takekash.com — confirmed by comparing site IDs before writing anything, so it was never used against the real site). User needs to complete the two steps in ADMIN-SETUP.txt.

## 🔍 FULL-SYSTEM AUDIT — 2026-09-16

Ran a top-to-bottom check across the pipeline, takekash-site-live, and the new admin dashboard in response to "what else is needed for proper upgrade in every aspect." Full findings delivered to user as `system-audit.md`. Summary of what was found (not yet fixed, this was audit-only):

- **Security:** `youtube_client_secret.json` and `youtube_token.pickle` are tracked in git (committed, not just local) — `.gitignore` covers different paths (`skills/publish/...`) than where these actually live at repo root. Recommended rotating both regardless of repo visibility (couldn't confirm public/private from this session). `tiktok_token.json` will hit the same gap once OAuth is completed — flagged to gitignore it BEFORE running `lib/tiktok_oauth_flow.py`.
- **Publishing is currently blocked for TikTok/Instagram:** checked the live `publish_schedule.json` (not the DB mirror) — 2 items already failed: TikTok has no OAuth token yet (`tiktok_token.json` doesn't exist), Instagram has no env credentials set AND a deeper gap — Instagram's API needs a public URL per video (this pipeline only makes local files), so real hosting infra is needed before Instagram publish can work at all, on top of the 2-4 week Meta app review.
- **Git hygiene:** last commit 2026-08-14 — everything since (watermarking, caption-burn perf fix, publish_scheduler fixes, admin snapshot exporter) is uncommitted. Also hit a stale `.git/index.lock` in this sandboxed session (unclear if it also affects the real Mac shell — flagged for the user to check). Log files (`dashboard.log`, `watch.log`, `logs/doctor_auto_resume.log`) are tracked in git and probably shouldn't be.
- **DB vs. reality:** confirmed (again) that `social_posts` in `takekash.db` is a write-only mirror never read by live code. The 9 "blocked" judge-show YouTube rows have no `platform_post_id`, so there's no way to verify from the DB whether that content is actually still live on the real channel — this is exactly the still-open "audit DB vs real YouTube" task from earlier, now with a concrete reason it matters (content-safety, not just bookkeeping accuracy).
- **Storage:** `outputs/` is 7.1GB with no cleanup/archival policy.
- Carried forward as still-open: YouTube analytics backfill (must run on the real Mac, not this sandbox), the recurring optimization system (depends on analytics), and the pricing-model conflict from the product brief.

## 🔧 AUDIT FIXES APPLIED — 2026-09-16

Fixed what was safely fixable from this session; left anything needing your own accounts/credentials/interactive login untouched (listed below).

**Done:**
- Removed a stale `.git/index.lock` that was blocking all git commands.
- `.gitignore` now covers: `youtube_client_secret.json`, `youtube_token.pickle`, `tiktok_token.json` (pre-emptively, before OAuth ever runs), `.env`/`*.env`, all `*.log` + `logs/`, `.netlify/`, `*.bak*`, `takekash.db`.
- **Found a real OpenSSH private key (`450967` / `450967.pub`) sitting untracked at the repo root.** It was never committed (good), now gitignored so it can't be accidentally added later. This should really live in `~/.ssh/`, not inside a git-tracked project folder — recommend moving it.
- **Found `awesome-osint-arsenal/`, a separate git repo, nested inside this one.** Left untouched and gitignored — nested repos break `git add -A` semantics and it's unrelated third-party tooling, not pipeline code.
- Untracked (`git rm --cached`, files kept on disk) the two files that were actually committed with real credentials: `youtube_client_secret.json`, `youtube_token.pickle`.
- Committed everything else real that had piled up since the last commit (2026-08-14) — watermarking pipeline, `publish_scheduler.py` fixes, caption burner perf fix, the admin snapshot exporter, and the rest of `lib/` that had never been checked in. Commit `08700ca`. **Not pushed to GitHub** — that's your call, see below.

**Still needs you, specifically (couldn't be done from this session):**
- **Rotate the YouTube OAuth credentials** in Google Cloud Console — untracking the files doesn't erase them from git history (commit `7d09ea7` and others still have them). Real fix is revoking/regenerating, not just removing from tracking.
- **Decide whether to purge git history** of the old secret commits (a `git filter-repo`/BFG + force-push) — a real, somewhat destructive operation I won't do without you explicitly asking for it, since it rewrites shared history.
- **Push commit `08700ca` to GitHub** (`git push`) once you've glanced at it — I didn't have real GitHub auth from this sandboxed session to do it myself even if it were a "just do it" action.
- **Move the SSH key (`450967`/`450967.pub`) out of this folder.**
- TikTok OAuth, Instagram credentials + hosting, `ADMIN_KEY` in Netlify — all still need your own logins/accounts, per the earlier audit.
- YouTube analytics backfill (`fetch_youtube_stats.py`) — confirmed again this session that `oauth2.googleapis.com` is unreachable from this sandboxed bridge; has to run from your real Mac Terminal.

## 🔗 INSTAGRAM PUBLIC-URL FIX + TIKTOK CALLBACK PAGE — 2026-09-16

Follow-up on "fix all the problems when it comes to the url posted to the files being created" — user picked: fix the Instagram public-URL gap by hosting clips on takekash.com itself, and fix the dead TikTok oauth-callback page.

**Root cause confirmed, not assumed:** `lib/instagram_publish.py`'s `publish_reel()` already correctly requires a real public `video_url` (it says so in its own docstring — Instagram's API fetches the video, it doesn't accept upload). The actual bug was one level up: `lib/publish_scheduler.py` line 267 was passing `item["video_path"]` (a local Mac filesystem path) as that argument. Every Instagram item that ever reached this code path would have failed, credentials or not.

**Also found while verifying:** the 8 `interviewtest` batch items (both platforms) had a stale filename in `publish_schedule.json` — `interviewtest_window11.mp4` vs the real file `interviewtest__window11.final.mp4` (double underscore, `.final` suffix). Fixed all 21 affected entries (8 instagram + 13 tiktok/other-status) by matching against the real files on disk before rewriting.

**Built:**
- `lib/prepare_instagram_hosting.py` — copies every pending/approved Instagram clip into `../takekash-site-live/clips/<content_id>.mp4` and stamps `public_url` (`https://takekash.com/clips/<content_id>.mp4`) onto the queue item. Idempotent (skips files already correctly copied by size match), resumable (writes via `.partial` + atomic rename, flushes queue progress after every change — needed in practice, this took two passes to finish 2.6GB in this sandboxed session's 175s call limit).
- Fixed `lib/publish_scheduler.py`'s Instagram branch to use `item.get("public_url")` instead of the local path, and to raise a clear, actionable error (not a cryptic API failure) when an item has no `public_url` yet.
- `takekash-site-live/oauth-callback.html` — real landing page for TikTok's OAuth redirect (was a blank Netlify 404 before). Shows the authorization code in a copyable field (matching the existing manual-copy step documented in `lib/tiktok_oauth_flow.py`), or a clear error state if TikTok returned one. Verified both states render correctly with Playwright before shipping.

**Ran for real this session:** all 59 pending/approved Instagram items now have `public_url` set, and their clips (2.6GB total) are copied into `takekash-site-live/clips/`. **Not live yet** — Netlify only serves what's deployed; needs `netlify deploy --prod` from the user's real Mac Terminal before Instagram's API can actually fetch any of them.

**Still needs the user:** the deploy itself, plus everything from the original audit that was never about URLs (INSTAGRAM_ACCESS_TOKEN/USER_ID, Meta app review, TikTok OAuth token).

## 🩺 DOCTOR/DASHBOARD RELIABILITY FIXES — 2026-09-16

Found while doing a deeper pass after the security/URL fixes, per "find all other problems needed to be fixed."

### What was actually broken

1. **`doctor.py`'s false-positive resume loop (~3,338 occurrences in `dashboard.log`, likely running for weeks).** `any_job_needs_resuming()` only checked a job's top-level `steps.export.status`. For every job created via `clip_pipeline.sh` (the newer multi-window pipeline — 15 of them: apexnba2k2, gtaxlong1, interviewtest, job1786571638, and 11 others), the *parent* `job.json`'s `export` step is vestigial — the real export now happens per-window in each `<job>__windowNN/job.json`, which was correctly `done`. `resume_all.sh` already knows this (it checks `job.json`'s own `"managed_by": "clip_pipeline"` field and skips these with an explicit log line), but `doctor.py` never had that check, so it re-triggered `resume_all.sh --auto-approve` every ~10 minutes for jobs that were already fully finished. Not destructive — `resume_all.sh` correctly no-op'd each time — but pure waste, and noise that buried the *real* failure below in the log.

2. **The real, active failure hiding inside that noise: job `b951cc787dc7`** (5 clips, created 2026-09-15) — every clip finished every step except export, and every export attempt failed with `skills/finalize.sh: line 40: ffmpeg: command not found`, retried ~700 times each over ~24h. Root cause: `finalize.sh` (via `lib/common.sh`) calls `ffmpeg` by bare name, and launchd-invoked processes (the `com.takekash.dashboard` background service) don't inherit an interactive shell's `PATH` — Homebrew's `ffmpeg` was never on it. This never showed up running things by hand from a real Terminal, only via the background service.

3. **A second, compounding bug that let #2's `clip05` get stuck indefinitely:** `doctor.py` has a real, correct stale-lock detector (`check_stale_locks()` — checks whether the PID named in a job's `.lock` file is still alive via `os.kill(pid, 0)`, and only removes the lock if it's genuinely dead). But `dashboard.py`'s live background loop (`background_maintenance_loop`, the thread actually running under launchd right now) was only ever calling `doctor_mod.auto_resume(...)` — never `check_stale_locks()`. That function only ran inside `doctor.py`'s own standalone `--auto-resume` CLI loop, which isn't what's running. Result: `clip05`'s lock, left behind by a crashed/killed render at 07:32, sat there for 10+ hours with nothing ever checking whether its PID was still alive.

### Fixes applied directly (code, not data)

- `lib/common.sh` — prepends `/opt/homebrew/bin`, `/opt/homebrew/sbin`, `/usr/local/bin`, `/usr/local/sbin` to `PATH` (deduped, only if the dir exists) right after resolving `PIPELINE_ROOT`. Every skill script and `run_pipeline.sh` sources this file, so `ffmpeg`/`ffprobe` now resolve regardless of the invoking environment.
- `dashboard.py` — `background_maintenance_loop()` now calls `doctor_mod.check_stale_locks()` immediately before `doctor_mod.auto_resume(...)`, on the same 10-minute cadence, so a dead-process lock actually gets cleared instead of blocking forever.
- `doctor.py` — `any_job_needs_resuming()` now skips any job whose `job.json` has `"managed_by": "clip_pipeline"`, mirroring `resume_all.sh`'s own check exactly. Eliminates the false-positive loop for all 15 currently-affected parent jobs.

**Needs you:** restart the dashboard so these land (`./restart_dashboard.sh`) — a running Python process doesn't pick up source changes on its own. After the restart, watch `logs/doctor_auto_resume.log`/`dashboard.log` for one cycle (up to 10 min): `clip05`'s lock should either clear (if its PID is really dead, which all the evidence points to) or, if something genuinely still holds it, stay — either way `check_stale_locks()` will now actually decide that instead of nothing deciding it. Clips 01–04 should then resume and actually export successfully with `ffmpeg` resolving correctly.

### Found, not fixed (flagging only — needs a real decision, not a bug)

- **`projects/` is 65GB** — separate from and much larger than the `outputs/` 7.1GB flagged in the original audit. This is every job's raw footage + every intermediate render (rough-cut, graphics, captions, scored) for every job ever run, with no cleanup step once a job's final output is promoted to `outputs/`. 360GB free out of 932GB right now, so not urgent, but it's the actual bulk of your disk usage and it only grows. Worth a real prune policy (e.g., delete `projects/<job>/{raw,rough-cut,graphics,captions,music,music-out}` once `outputs/<job>.final.mp4` exists and has been published) rather than something to auto-delete without you deciding the retention window.

## 🧹 DISK CLEANUP + AUTO-PRUNE — 2026-09-16

Per "delete pure trash old fixs patches an trial runs an anything the system doesnt need to operate at its peak." Nothing here touched anything still in use — every deletion was verified against a live reference (an `outputs/` file, a `managed_by`/children check, or a grep for script references) before it happened.

**Freed ~65GB, all confirmed-safe:**
- **38.3GB** — intermediate media (`raw/`, `rough-cut/`, `work/`, `music/`, `music-out/`, stray `graphics/*.mp4`) for 112 job directories that were fully exported *and* whose final render was confirmed actually sitting in `outputs/`. Kept `job.json`, `progress.json`, `thumbnail/`, and `graphics-plan.json` for every one of these, since `mcp_server.py`'s job-status tools and the admin snapshot exporter still read those — spot-checked after the fact (`gtaxlong1__window01`, `apexnba2k2`, `b951cc787dc7`) to confirm status/metadata still work.
- **26.2GB** — 9 job directories where `clip_pipeline.sh` downloaded a full source video and started, but never actually produced a single clip (`managed_by: clip_pipeline` with zero child jobs): `job1786571638`, `job1786607232`, `job1788368131`, `job1788327427`, `job1788975576`, `job1788411441`, `job1788400530`, `job1786908719`, `job1786890425`. Treated as abandoned trial runs per your instruction — deleted entirely, not just stripped.
- **~0.6GB** — dead scaffolding: all `.bak` files (`doctor.py.bak`, `dashboard.py.bak`, `clip_pipeline.sh.bak`, `mcp_server.py.bak`, `restart_dashboard.sh.bak`/`.bak2`, `restart_poller.sh.bak2` — all already gitignored, just clutter on disk), `__pycache__/` (root + `lib/`), `.DS_Store`, `summarize_clips.zip` (redundant with the `.py` already in the repo), and a dozen dead one-off logs from Aug trial runs (`montage_run*.log` ×10, `montage_debug.log`, `ngrok.log`, `resume.log`, `watch.log`, `webhook.log`, `doctor.log`, plus 3 orphaned per-job logs in `logs/` whose job directories no longer exist).
- Truncated (not deleted — these are actively written by the live dashboard process) `dashboard.log` and `logs/doctor_auto_resume.log` down to their last 200 lines, and `poller.log` to its last 100.

**Left alone, flagged instead of forced:** a stray top-level `venv/` (2.9GB) turned out to be an unrelated Python environment — Impacket-suite AD/Windows attack tooling (`secretsdump`, `wmiexec`, `GetNPUsers`, `ntlmrelayx`, `dacledit`, etc.) plus some ML libraries — confirmed via `grep` that nothing in the actual pipeline (`.sh`/`.py`) references it, so it's dead weight here regardless. Deleting/chmod'ing most of its files was blocked (`Operation not permitted`/`Permission denied`) — looks like a safety guardrail on recognizable security-tooling files rather than an ordinary permissions issue, and repeatedly retrying past a safety block isn't the right move. Got it down to 2.3GB (removed what wasn't blocked); the rest needs you to delete it yourself from a real Terminal (`rm -rf venv/` from the repo root) if you want it gone — it's unrelated to `awesome-osint-arsenal` (that's a separate, already-excluded directory) and unrelated to the clip pipeline either way.

**Added so this doesn't come back (the "perfect the process" part):** new `lib/prune_finished_jobs.py`, wired into `dashboard.py`'s `background_maintenance_loop` on a daily cadence (`prune_interval_sec=86400`, same pattern as the other periodic checks — imported and called in-process, not subprocess'd). Runs the exact same safe logic as this cleanup (only strips a job's intermediate media once it's fully exported *and* confirmed present in `outputs/`) automatically from now on, so `projects/` never silently balloons to 65GB again. Idempotent and safe at any frequency — verified with `--dry-run` immediately after this cleanup: correctly reports 0 GB / 0 jobs since there's nothing left to reclaim right now.

**Needs you:** restart the dashboard (`./restart_dashboard.sh`) to pick up the prune wiring, same restart already needed for the ffmpeg/PATH and stale-lock fixes above — one restart covers all of it.

## ⚡ ONE-SHOT DISK AUDIT SCRIPT — 2026-09-16 (later same day)

The 2026-09-16 disk cleanup above took ~15 separate manual investigation steps (du breakdowns, per-job classification scripts, spot checks) run one at a time. New `lib/disk_audit.py` consolidates all of that into a single command:

```
python3 lib/disk_audit.py                        # report only
python3 lib/disk_audit.py --clean                 # deletes RECLAIMABLE media + .bak/__pycache__/.DS_Store clutter
python3 lib/disk_audit.py --clean --yes-abandoned  # also deletes zero-clip abandoned trial runs (needs explicit opt-in every time — never automatic)
```

Same RECLAIMABLE/NEEDED/ABANDONED classification as before, same safety rule (never deletes an ABANDONED job dir without `--yes-abandoned`, verifies against real `outputs/` files, always keeps `job.json`/`progress.json`/`thumbnail/`).

**Also fixed a real gap found while writing it**: both this script and the daily `lib/prune_finished_jobs.py` were missing older-style `<job>__clipNN` jobs that don't carry a `managed_by: clip_pipeline` tag (that tag is only set by `clip_pipeline.sh`) — e.g. `b951cc787dc7`'s 5 clips would have been invisible to both scripts' classification and never reclaimed. Added a second classification pass to both for this shape. Confirmed while testing: `b951cc787dc7`'s clips 01–05 finished exporting successfully after the earlier dashboard restart (`doctor: removed stale lock for 'b951cc787dc7__clip05' (pid 50675 not running)` in `dashboard.log`) — the ffmpeg/PATH and stale-lock fixes from earlier today are confirmed working end-to-end.

## 🚀 PIPELINE SPEED PILOT — hardware video encoding — 2026-09-16 (evening)

Real evidence, not a guess: `gtaxlong1__window01`'s job.json timestamps show intake→captions took ~70s total, but the finalize/watermark step alone took ~66s — roughly matching everything before it combined. Root cause: **every** ffmpeg encode in the pipeline uses software encoding (`-c:v libx264`) — confirmed across `skills/rough-cut/*.py`, `skills/graphics-plan/render.py`, `skills/clip-select/extract_best_windows.py`, `lib/ffmpeg_animation.py`, `skills/finalize.sh`, `clip_pipeline.sh` (a dozen+ call sites). None use Mac's hardware encoder.

**Piloted on `skills/finalize.sh` only** (your choice, to de-risk before touching the rest): tries `h264_videotoolbox` (hardware) first, falls back automatically to the original `libx264` path on any failure — logs which path ran to `logs/finalize_videotoolbox_attempt.log` and `dashboard.log`.

**Important limitation — I could not test this myself.** The device-bridge shell this session uses is a sandboxed Linux VM on your Mac, not macOS itself — VideoToolbox is a macOS-only API, so it's simply not reachable from there regardless of your Mac's actual hardware. The fallback pattern exists specifically because of this: if `h264_videotoolbox` isn't available or fails for any reason, every export still produces the exact same output it did before, just via the slower path. Nothing can break.

**What to check after your next real export** (or run `NO_WATERMARK=0 ./skills/finalize.sh <any-pending-job>` by hand): `dashboard.log`/`logs/doctor_auto_resume.log` will say either `"watermark burned in via h264_videotoolbox (hardware encode)"` or the fallback message. If hardware encode ran, compare the finalize step's timestamp gap to the ~66s baseline above, and spot-check the output clip's visual quality. If it looks good, say so and I'll roll the same pattern out to the rest of the ffmpeg call sites (rough-cut, graphics, captions, montage) for the full speedup.

## 🎮 RECOVERED APEX CLIPS — BATCH JOB SETUP — 2026-09-17

**Source**: OneDrive_1_9-16-2026.zip (corrupted/truncated OneDrive export, download
cut off mid-transfer). `zip -FF` reported success but never wrote a valid
central directory — worked around by carving each STORE-mode entry directly
out of the raw zip bytes (see chat for the full recovery). Result: 20 complete
Apex Legends clips (6.6GB, June 1-5 2026, verified via ffprobe) + 1 unrecoverable
partial fragment (the clip actively transferring when the download cut off —
no moov atom, not playable).

**Staged as 20 jobs**: `projects/apex_MMDD_HHMM/raw/` — the first two
(apex_0601_2257, apex_0601_2311) are real moved files; the remaining 18 are
symlinks back to `~/Downloads/recovered_clips/` (cross-mount copy over the
device bridge was too slow, ~10MB/s; symlinks are instant and ffmpeg/python
follow them transparently). **Do not delete `Downloads/recovered_clips/`** —
18 of the 20 jobs' raw sources live there via symlink, not as copies.

**Fixed a real bug this exposed**: `job_raw_file()` in `lib/common.sh` used
`find -type f` with no `-L`, so it silently returned nothing for any job
whose raw source is a symlink (common.sh:42). Also fixed `check_disk_space()`'s
`stat -c%s`/`stat -f%z` calls the same way (common.sh:75) — plain `stat`
reports a symlink's own size (~100 bytes, the path string length) rather
than the target's, which would have made the disk-space safety check a
silent no-op for any symlinked raw source. Both now pass `-L`. This is a
general pipeline improvement, not just for this batch — useful anytime a
raw source is referenced rather than copied.

**Batch runner**: `run_apex_batch.sh` (reads job list from
`apex_batch_jobs.txt`) — runs `clip_pipeline.sh <job> short-tiktok-raw
--content-type gaming --clip-length 30 --clip-count 2 --auto-approve` for
all 20, logging to `logs/apex_batch_<timestamp>.log`. Not run yet — needs
to run from a real Terminal (not the device bridge) since each job's full
pipeline run will exceed the bridge's per-call time limit many times over.
doctor.py's existing background auto-resume will retry any job that stalls
or crashes mid-run.

## 🔧 BATCH FAILURE ROOT-CAUSE + FIX — 2026-09-17 (later same day)

Ran `run_apex_batch.sh` twice on the real Mac. Job 1 (`apex_0601_2257`)
succeeded both times (the OpenCV hang fix held). All other 19 jobs failed
in 1-2 seconds each, both runs. Root cause, confirmed by reading the actual
per-job log output (not just exit codes):

- **18 symlinked jobs** (`apex_0601_2313` through `apex_0605_1722`) failed
  with "no raw file found in .../raw". The symlinks I created earlier were
  made *through the device bridge's sandboxed VM*, so their targets were
  written as the VM's own internal mount path
  (`/sessions/<session-id>/mnt/Downloads/recovered_clips/...`) — a path
  that only exists inside that sandbox, not on the real Mac. On the real
  Mac (where `run_apex_batch.sh` actually runs, in your Terminal) every one
  of those symlinks was broken, so `find -L` correctly found nothing.
  **Fixed**: all 18 relinked to point at the real, absolute Mac path
  (`/Users/Apple/Downloads/recovered_clips/<file>.mp4`) and verified each
  target file exists there at its correct recovered size.
- **1 real-copy job** (`apex_0601_2311`, job 2) failed with "moov atom not
  found" — its raw file was truncated (168.8MB of 199.4MB). This was a
  leftover from the original cross-mount `shutil.move` that got cut off by
  the bridge call's own time limit mid-copy earlier this session; the
  partial destination file was left behind looking complete enough to not
  get re-checked. **Fixed**: replaced the truncated copy with a symlink to
  the same corrected real path used above (avoids the slow cross-mount copy
  entirely, same as the other 18).
- A one-off `run_apex_batch.sh: line 38: h: command not found` also
  appeared between the two runs. Re-read the live file on disk: line 38 is
  `LOG="logs/apex_batch_$(date +%Y%m%d_%H%M%S).log"`, `bash -n` passes, no
  CRLF or stray bytes found. Not reproducible and didn't affect either
  run's actual job execution (job 1 still completed both times) — most
  likely a stray terminal artifact, not a real script bug. Left as-is;
  flag if it recurs.

**Lesson for future symlink staging via the device bridge**: always write
the *real device path* (from `get_device_info.connectedFolders`) as the
symlink target, never a path built from the bridge VM's own `$HOME/mnt/...`
view — the VM and the real Mac see the same file at two different absolute
paths, and only the real Mac's own path is valid once the pipeline actually
runs on the Mac itself.

All 20 jobs' raw sources verified resolvable (correct size) before handing
back. Ready to re-run `run_apex_batch.sh`.

## 🎯 CLIP SELECTION QUALITY FIX — 2026-09-17 (evening)

User feedback after reviewing the 98 rendered clips: most were just
dropping in / looting for attachments, not real gameplay. Only ~3 actual
gunfights got caught across the whole batch, and even those were poorly
bounded — caught near the END of the fight, no knockdowns, not spanning
the real beginning-to-end of the engagement.

**Root cause, confirmed against real data (not guessed):** pulled the
actual `audio-analysis.json` + `clips.json` for several jobs and found
EVERY selected clip in EVERY job was tagged `(gunfire/impact detected)`,
with the 5 clips per job forming a near-continuous back-to-back chain from
the start of the video (e.g. 0-30s, 32-62s, 67-97s, 99-129s, 130-160s).

The bug: `lib/audio_analysis.py`'s old `transient_beats()` turned EVERY
detected audio transient into its own highlight-worthy "impact" beat, with
no loudness discrimination. Real gameplay audio produces a transient
(footstep, item-pickup ding, inventory click, zipline sound — anything
with a sharp attack) every 1-9 seconds on average — checked directly:
apex_0601_2257 had 46 transients across 180s, apex_0604_0331 had 205
across 600s. Since "impact" (score 4) outranks every other signal and
`pick_non_overlapping`'s bonus mechanic keeps grabbing more non-overlapping
impact-tagged windows, the selector degenerated into "chop the video into
sequential 30s chunks from the start" — which is exactly what got
rendered. Real firefights were rare enough in this footage that they
rarely coincided with those arbitrary chunks, and even when a real fight
DID land in the video's first ~160s, it got sliced by chunk boundaries
rather than tracked as its own event.

**Real fix (not a threshold guess — measured against each job's own real
transient-energy distribution):**
- `lib/audio_analysis.py`: `transient_beats()` rewritten to only count a
  transient as real "impact" content if its energy is at least
  `LOUDNESS_MULT` (2.5x) the video's own MEDIAN transient energy — real
  gunfire measurably stands out above ordinary footstep/UI-click level in
  every sampled job (e.g. apex_0604_0331: median transient energy 0.033,
  real spikes up to 0.37 — over 10x). Qualifying loud events within
  `MERGE_GAP_SEC` (6s) of each other are merged into ONE beat spanning
  `LEAD_IN_SEC` (3s) before the first hit through `TRAIL_SEC` (5s) after
  the last — covering the actual engagement instead of one arbitrary
  fixed-length slice, and the trailing buffer is specifically what should
  now catch a knockdown/kill-confirm right after the last shot.
- `skills/clip-select/clip_select.py`: `candidate_windows()`'s audio-beat
  handling no longer discards that real span and re-forces a fixed
  clip_length window via `lead_in_window()` — it now uses the beat's own
  start/end directly, padding short engagements up to clip_length
  (symmetrically) and keeping longer ones in full rather than truncating.

**Verified before applying to the live batch** — ran the patched
`clip_select.py` directly against each job's already-cached
script/visual/audio analysis (no re-transcription needed) and compared
output:
- apex_0601_2257: 5 wall-to-wall "impact" clips (0-160s) → 2 clips: one
  real motion-based fallback + one real 5-hit gunfight at 129.6s-159.6s
  (previously this exact fight was in the batch but sliced awkwardly by
  chunk boundaries).
- apex_0601_2311: 5 wall-to-wall → 4 clips spread across the full 179s
  with 1-3 real hits each.
- apex_0604_0331 (10min): 5 wall-to-wall (all within first 160s) → 5
  clips now spread across the full 601s runtime, including a real 5-hit
  engagement at 150-180s that the old logic never reached.
- apex_0605_1722: 5 wall-to-wall → 3 clips (2 real gunfights + 1 motion
  fallback).

Both `lib/audio_analysis.py.bak2` and `skills/clip-select/clip_select.py.bak2`
are the pre-fix originals, kept alongside for reference.

**Cleanup performed**: deleted all 98 stale per-clip subjob directories
(`projects/apex_*__clip*`) and all 20 stale `outputs/apex_*/` folders +
the old gallery `index.html` — necessary because `run_pipeline.sh`'s
step-skip logic (`run_step()`) only checks a boolean "done" flag per step
with no dependency tracking on the underlying source changing, so simply
re-running on top of the old subjob folders would have silently kept the
OLD stale renders instead of picking up the corrected selection. Verified
this was the right call before deleting anything, not assumed.

Parent-job caches (`rough-cut/audio-analysis.json`, `visual-analysis.json`,
`script.json` — the expensive whisper/audio/visual passes) were left
completely untouched and will be reused on the next run; only clip
selection and per-clip rendering redo.

**Next step**: re-run `./run_apex_batch.sh` — same command as before, and
the loudness/merge tuning constants (`LOUDNESS_MULT`, `MERGE_GAP_SEC`,
`LEAD_IN_SEC`, `TRAIL_SEC`) are documented at the top of
`transient_beats()` in `lib/audio_analysis.py` if the result still needs
adjusting after review (this is a heuristic tuned against this batch's
real data, not a universal constant).

## 🏆 ENGAGEMENT SCORE + FIGHT-DURATION + QUALITY-BAR FIX — 2026-09-17 (night)

User asked how to get the displayed engagement_score averaging 90+. Root
cause: `engagement_score()` in `skills/clip-select/clip_select.py` gave
EVERY audio-detected "impact" clip an almost-identical ~60-61, because 40
of its 100 points came from spoken/caption text energy (word pace, "!",
"insane", etc.) — and these are silent gameplay clips with no commentary,
so that whole 40-point chunk was always ~0. There was no real
differentiation between a huge firefight and a marginal one.

**Real fix — score off actual measured evidence, not absent text:**
- `hit_count` and `peak_ratio` (per-cluster loudest transient's
  ratio-over-baseline) are now returned by `transient_beats()` and carried
  through `candidate_windows()`.
- New `motion_elevation()` cross-checks the audio pick against
  `visual-analysis.json`'s own motion data — how much higher on-screen
  motion is during the window vs. that video's own average. A loud sound
  over a static screen now scores lower than one confirmed by real
  on-screen action.
- `engagement_score()` rewritten for audio-based picks: hit density
  (0-40) + peak sharpness (0-30) + motion confirmation (0-20) + how much
  of the clip is real engagement vs. padding (0-10). Transcript/motion-only
  picks keep the old formula (no change needed there).
- Verified against all 20 jobs' real cached data before applying:
  scores now spread 40-92 instead of clustering at 60-61, with the
  strongest verified real engagement (5 hits, apex_0602_0023) at 92.

**Honest finding shared with user**: on THIS batch's actual content, nothing
scores above 92 and the real average lands ~57 once weak clips are
filtered — there is no way to get a genuine 90+ AVERAGE without either
much more intense footage or cosmetically rescaling the number (declined).
User chose: raise the real quality bar instead of rescaling.

**Additional changes per follow-up user feedback:**
- "I want the whole fight, around 3 minutes" (2 min also fine): audio-beat
  windows are no longer forced to a fixed 30s — `clip_length` (30s) is now
  only the FLOOR for a short/isolated beat (padded up so it's watchable);
  a new `MAX_ENGAGEMENT_SEC = 180.0` is the ceiling, so a real sustained
  fight can run its natural length. Also raised `MERGE_GAP_SEC` from 6.0
  to 15.0 so natural lulls in a real engagement (reload, reposition, a
  downed teammate) don't fracture one fight into several separate clips.
  Measured result: even with the more generous merge window, the longest
  real continuous engagement found in this footage is ~64s — nothing
  actually reaches 2-3 minutes of sustained detectable gunfire in this
  batch. Flagging this honestly rather than claiming otherwise; if a fight
  genuinely felt ~3 minutes long to the user, it likely had longer quiet
  stretches (repositioning, chasing) than transients alone can bridge —
  worth revisiting MERGE_GAP_SEC further if this keeps coming up.
- "make sure it's a fight not just random shots": new
  `MIN_HITS_FOR_FIGHT = 2` — a cluster with only a single loud transient
  (a grenade, one unanswered shot, an explosion) no longer qualifies as
  "impact" content at all, regardless of how loud it was.
- New `QUALITY_FLOOR = 40`: every candidate is now scored BEFORE
  selection, and anything below this floor is dropped rather than padded
  into the clip count. A video with no real engagement above the bar
  yields fewer clips (or, in principle, none) instead of forcing weak
  picks to hit a quota. `pick_non_overlapping()` also now prefers the
  higher-scoring candidate first within the same tag tier, not just
  chronological order.

**Verified end-to-end against all 20 jobs' real cached data before
applying to the live batch**: 66 total clips (down from 81), 0 videos
left with zero clips, scores spread 40-92, avg ~57.5. Backups:
`lib/audio_analysis.py.bak3`, `skills/clip-select/clip_select.py.bak3`
(pre this round of changes — `.bak2` is the version before the very first
gunfire-detection fix earlier today).

Cleared all 81 stale per-clip subjob dirs and 20 stale outputs/gallery
folders again (same reason as before — `run_pipeline.sh`'s step-skip has
no dependency tracking, so leftover folders would silently keep old
renders). Parent-job caches untouched, reused as before.

**Next step**: re-run `./run_apex_batch.sh` — same command as always.

## 2026-09-17 (later) — root-caused "getting knocked / stuck in menu" clips

After the previous fix's live run completed clean (66 clips, avg 57.5,
matched validation exactly), the user reported most clips were them
getting knocked and/or ending up stuck in the game menu. Investigated by
reading actual thumbnail frames (not just JSON) from the real rendered
clips — this surfaced a bug the JSON-only checks had missed entirely.

**Root cause #1 (the big one): `motion_beats()` in `lib/visual_analysis.py`
fired on single-frame scene cuts.** A menu → gameplay transition (or a
death → lobby transition) produces one huge frame-to-frame pixel diff,
then drops straight back to near-zero motion on both sides. The old
z-score check only looked at ONE sample in isolation, so this scene-cut
artifact statistically looked identical to "a huge action spike."
Verified against real cached data: this exact pattern was landing a
"highlight" clip built out of the menu/loadout screen in 11 of 20 jobs
(55%) — always scoring an identical 46 via the old flat tag-based
fallback, which is how it went unnoticed by the numeric checks alone.
21 of the prior 66 clips (32%) were sourced this way in total.

**Root cause #2: menu screens with real visual detail (Battle Pass,
ranked ladder, squad lobby, "controller disconnected") don't trip the
flat/spinner loading-screen classifier**, since they have real edges/
text/icons — `classify_frame()` was built to catch flat spinner-style
loading screens specifically. Confirmed via direct frame extraction from
the raw source video (not just the rendered clip) — one job's supposed
"action" clip was, frame by frame, Battle Pass rewards → main lobby →
ranked ladder screen. The player was tabbing through menus, and the
UI transition animations produced the same kind of sustained
frame-to-frame motion a real fight does.

**Fixes applied** (backups: `lib/visual_analysis.py.bak2`,
`skills/clip-select/clip_select.py.bak4`):
- `motion_beats()` now requires a spike to have at least one NEARBY
  sample also meaningfully elevated (real chaos is sustained across
  several samples, a scene-cut isn't), and drops any spike sitting next
  to a loading-screen-flagged frame outright.
- New `audio_backed()` cross-modal check in `clip_select.py`: a
  motion-only candidate must have at least one real loud audio transient
  in its window, at the SAME energy bar (video's own median × 2.5) that
  qualifies as "gunfire" for the audio path. This is what actually
  caught the menu-browsing case root cause #1's sustained-motion check
  couldn't — button clicks are transients too, but nowhere near as loud
  as gunfire (checked: ~0.02-0.09 energy for menu clicks vs ~0.24-0.39
  for a real gunfight, in the same recording).
- `engagement_score()` now scores motion-only beats on real evidence
  (peak z-score, sustained-neighbor count) instead of a constant ~46 —
  same fix already applied to the audio path earlier today, now
  extended to the visual path where it was actually still needed.
- New `trim_dead_tail()`: any candidate (regardless of source) has dead
  seconds trimmed off its END if they're static/loading-screen-flagged,
  instead of keeping them or discarding the whole clip. Verified this
  doesn't touch any real audio-detected gunfire clip's boundaries at all
  (diffed old vs new audio-sourced clip start/end across all 20 jobs —
  zero changes).

**Known remaining edge case, disclosed rather than hidden**: a detailed
non-flat menu screen (e.g. "YOUR SQUAD" / controller-disconnected) sitting
right at a clip's tail, with just enough residual motion to dodge both
the loading-screen classifier and the dead-tail motion floor, could
still slip through in rare cases. True fix needs actual menu-vs-gameplay
frame classification (OCR/template matching), not just motion statistics
— flagging this rather than claiming it's fully solved.

**Verified against all 20 jobs' real cached data before touching the live
batch**: 47 clips (down from 66), avg score 62.0, min/max 40/92, only 2
of 47 remaining clips are motion-sourced (down from 21) and both are
now audio-corroborated. Diffed every audio-sourced clip's start/end
old vs. new — identical, confirming this fix only removed the
motion-beat junk and didn't touch real gunfight clips.
`apex_0604_0014` now legitimately yields 0 clips — its only content was
a razor-thin audio cluster (score 39, one point under the floor) plus
the now-excluded menu-transition motion beat; nothing else in that
~3-minute recording clears the bar.

Cleared all 66 stale per-clip subjob dirs and the outputs/gallery again.

**Next step**: re-run `./run_apex_batch.sh`.

## 2026-09-17 (later still) — apexnba2k2 scoring fix (podcast/interview content)

User asked to work on "the nba2k clips" — turned out to be misnamed: the
job `apexnba2k2` (and its vertical crop, `apexnba2k2_vertical`) is real
Cam Capone News podcast/interview footage (confirmed by frame-checking
8 points across the full ~98-minute video), meant for TikTok/Instagram,
not gameplay. Its 19 long-form windows (5-12 min continuous segments,
`best-windows` mode) had wildly broken scores in `windows.json` — 16 of
19 scored deeply negative, down to -18,857.

**Root cause, confirmed from code (`skills/clip-select/best_windows.py`,
`is_loading_screen_bin`)**: `go.sh` defaults `content_type` to `"gaming"`
for ANY run unless `--content-type` is passed explicitly (line 55), and
this job's `--platform longform` run never passed `--content-type
podcast`. `best_windows.py` only skips its -1000-per-bin "dead time"
motion penalty when `content_type == "podcast"` — otherwise every 5-second
bin averaging under 0.015 motion gets penalized, and a talking-head
interview naturally has far less frame-to-frame motion than gameplay, so
nearly the whole video got flagged "dead" and penalized into deep
negative scores.

**Could not recompute the original window SELECTION** — `raw/source.mp4`
and all of `rough-cut/` for this job were already deleted (by disk
cleanup) by the time this was found, so the original 98-minute source is
gone and the 19 windows that were already chosen and rendered can't be
re-picked from scratch. User's call: keep the 19 existing long windows,
just fix the scoring so it's clear which ones are actually good.

**What was done**: ran `lib/visual_analysis.py` + `lib/audio_analysis.py`
directly against each of the 19 already-rendered
`outputs/apexnba2k2__windowNN.final.mp4` files (no whisper — these are
fast, motion/audio-only signals) and recomputed
`build_interest_timeline()` with `content_type="podcast"` per window.

**Corrected ranking (19 windows, best to worst by corrected score)**:
1. window17 (4760-5480s) — 296.0 — was already the best-known window (only one that scored positive originally too)
2. window10 (2745-3045s) — 166.0 — was -9753 originally, wrongly buried
3. window15 (4245-4545s) — 164.0 — was -1792 originally
4. window14 (3945-4245s) — 163.0 — was -10673 originally, wrongly buried
5. window9  (2445-2745s) — 162.0 — was -2822 originally
6. window7  (1845-2145s) — 154.0 — was -10804 originally, wrongly buried
7. window11 (3045-3345s) — 152.0 — was -4746 originally
8. window1  (45-345s)    — 150.0 — was -735 originally
9. window13 (3645-3945s) — 146.0 — was -4800 originally
10. window2 (345-645s)   — 131.0
11. window16 (4545-4760s)— 126.0
12. window3 (645-945s)   — 122.0
13. window6 (1545-1845s) — 113.0
14. window12 (3345-3645s)— 102.0
15. window4 (945-1245s)  — 96.0
16. window18 (5480-5780s)— 87.0
17. window5 (1245-1545s) — 76.0
18. window19 (5780-5915s)— 64.0
19. window8 (2145-2445s) — 56.0 — weakest under BOTH old and new scoring (genuinely low energy — was also the single most negative original score, -18857)

Under the old (broken) score, only windows 17/18/19 looked usable at all
(the only non-negative ones) — everything else looked like garbage. The
corrected score shows the opposite: 9 of the first 16 windows (1, 7, 9,
10, 11, 13, 14, 15) are actually as strong or stronger than window 18/19,
just wrongly buried by the dead-time penalty. Window 8 is genuinely the
weakest either way.

Since `apexnba2k2_vertical`'s outputs are vertical crops of these SAME
17-19 windows (no separate project/analysis dir exists for it — confirmed
via `job.json` lookup), this ranking applies to it directly too.

**Permanent fix applied** (`go.sh`, backup `go.sh.bak`): the `--platform
longform` branch now prints a visible warning when `content_type`
defaults to `"gaming"` with no `--content-type` explicitly passed, since
that path is genuinely generic (podcasts AND gaming VODs both go through
it) and a silent gaming default previously produced exactly this bug with
no indication anything was wrong. Default behavior unchanged — real
gaming longform runs work exactly as before — this only makes the
footgun visible.

## 2026-09-17 (later still) — Cam Capone SEO package for top 9 windows

User asked to see the corrected ranking and get the top windows "filed
up" with an SEO package ready to publish. The auto-generated metadata
already sitting in each `outputs/apexnba2k2__windowNN_metadata.json` was
unusable — raw, uncapitalized transcript fragments as titles (e.g. "Yeah
I Do What Would They Do If You If The"), and generic `#gaming #highlights
#clips` tags left over from the same wrong content_type default that
broke the scoring — completely unrelated to actual interview content.

Found a better real source than re-transcribing: each window subjob
still has `projects/apexnba2k2__windowNN/graphics/graphics-plan.json`
with clean, already-tagged (hook/highlight/question/stat) transcript
beats — real quotes, not garbled karaoke-caption text. Used these to
write real titles, TikTok captions, Instagram captions, and hashtags for
the top 9 ranked windows (17, 10, 15, 14, 9, 7, 11, 1, 13), grounded in
what's actually said in each one (Cam Capone News hip-hop industry talk:
Boosie stories, Mo3/Takeoff tributes, lockdown politics, generational
wealth, Grammys regret, athlete-attention takes, origin story).

Wrote the real copy into each window's own `_metadata.json` (title,
description, tags, plus new `tiktok_caption`/`instagram_caption`/
`hashtags`/`topic`/`rank`/`corrected_engagement_score` fields) so the
pipeline's existing publish tooling picks up the fixed content
automatically. Also wrote a consolidated reference doc:
`outputs/apexnba2k2_SEO_PACKAGE.md` — same 9 clips, formatted for
easy copy-paste when actually posting.

(Note: whisper/faster-whisper aren't currently installed in this
session's environment — `venv/bin/` only has a leftover `__pycache__`,
no interpreter — so no fresh transcription was possible if the
graphics-plan.json route hadn't existed. Worth checking that venv before
the next job that needs fresh transcription.)

## 2026-09-17 — apexnba2k2 (Cam Capone) TikTok publish-readiness audit + window17 caption fix

Checked all 9 top-ranked vertical clips for real TikTok readiness: format,
burned captions, watermark. Method: extracted real frames at 4-8 timestamps
spanning each clip's full duration (not just one frame) via ffmpeg, viewed
each one directly.

**Format**: all 9 vertical files confirmed 1080x1920 (windows 01, 07, 09,
10, 11, 13, 14, 15, 17).

**Found**: window17 (rank #1, the longest clip at ~12min) was the ONE
exception — its vertical render had NEITHER burned captions NOR the
GtaxZombies watermark, while all other 8 top windows had both. Root cause,
traced through the code:
- `extract_best_windows.py`'s vertical-crop step tries real word-level
  captions via `doctor.generate_word_groups_for_window()`, which needs
  `projects/<job>/rough-cut/script.json` with real `kept_segments` (whisper
  word timings). That data is GONE for this job (confirmed earlier this
  session — deleted in an earlier disk-cleanup pass), so the word-groups
  lookup returned None for every window here.
- Windows 01-16 already had their `.ass` caption files pre-generated (built
  back when that data still existed) and vertical-job outputs picked those
  up. Windows 17-19 never got `.ass` files generated before the source data
  was wiped, so their vertical crops fell through to the plain "no captions"
  branch. Watermark should still have applied in that branch
  (`assets/gtax_zombies_watermark.png` exists) but didn't for window17 — not
  fully explained, possibly a one-off run condition, but moot now.

**Fix applied**: real transcript data for window17 DOES still exist — not
whisper word-timings, but real, actually-said sentence-level beats
(`projects/apexnba2k2__window17/graphics/graphics-plan.json`, 95 beats,
`transcription_available: true`, real start/end/text per beat, no
fabrication). Built phrase-level caption lines from those beats (words
within each beat evenly time-split, grouped by the same max-8-words/max-4s
rule the karaoke system uses), generated a real ASS file via the existing
`ass_caption_burner.generate_ass_file()` (same GtaxZombies gold/purple
tilted-phrase style as every other clip), then composited watermark +
burned captions onto the existing plain vertical crop in one ffmpeg pass.

Real environment issue hit and worked around: `device_bash` calls here
cannot run background/detached processes across calls (bwrap's
`--die-with-parent` kills the whole sandboxed process tree the moment each
call's shell exits, confirmed directly by testing a `setsid`+`disown`'d
sleep). Also found a real ffmpeg bug in the combined overlay+subtitles
filter graph: putting `-t` as an INPUT option ahead of a `-loop 1` (infinite)
watermark image input made total output duration wildly wrong (5s target
produced 242s of output) — fixed by moving `-t` to an OUTPUT-level option.
With both fixed, split the 720s clip into 3× 240s chunks (each with its own
time-shifted ASS file), encoded each in ~80s, concatenated via ffmpeg concat
demuxer (stream copy, no re-encode) into the final file.

Verified the final file at 10 timestamps across its full length, including
both chunk-boundary seams (240s, 480s) — captions and watermark present
throughout, no visible glitch at either seam, duration 720.6s (vs 720.0s
original, negligible).

Replaced `outputs/apexnba2k2_vertical/apexnba2k2_window17.mp4` (old
caption-less file backed up at
`outputs/_fix_w17/apexnba2k2_window17.OLD_NO_CAPTIONS.mp4`). New file is
162MB (down from 402MB — old file's size wasn't from real content density,
just a different/heavier original encode).

**Result**: all 9 top-ranked windows are now real TikTok-format-ready:
1080x1920, burned captions, watermark, audio intact.

## 2026-09-18 — Full weekly publishing package + new gtaxlong1 scoring bug found

Built a complete SEO/hashtag/metadata package for every real clip rendered this
week, across all active jobs, and delivered a gallery + markdown writeup.

**Included** (56 clips, all visually spot-checked before inclusion):
- 47 apex_* short highlight clips — real titles/captions built from real
  gunfire-impact hit counts and engagement_score in each job's clips.json (no
  fabrication). All 1080x1920, watermark + captions already burned in from the
  live batch render.
- 2 of 5 b951cc787dc7 clips (clip02, clip03) — confirmed real gameplay across
  multiple sampled frames.
- 7 of 14 gtaxlong1 windows — confirmed real gameplay.

**Excluded, with reasons:**
- b951cc787dc7 clip01/04/05 — visually confirmed dead-time (Discord/system
  menu overlay, "YOUR SQUAD" post-match screen). This job was rendered
  2026-09-15, before the motion_beats/audio_backed fix from earlier this week,
  so it never got the benefit of that fix.
- gtaxlong1 windows 02/03/07/10/11/12/14 — visually confirmed menu/lobby/
  post-match screens (legend select, squad summary, store/reroll menu).
- `interviewtest` (25 windows) — visually confirmed to be the same person,
  studio, and setup as apexnba2k2 (Cam Capone). Almost certainly an earlier
  test run of the same source video (created 2026-09-11, four days before
  apexnba2k2's rough_cut). Treated as superseded/duplicate, not published
  from, to avoid double-posting the same source.
- job1786627920, job1788203913, job1788482095, judge_joe_brown — all created
  Aug 13 – Sep 4, before this week; left alone.

**New bug found, NOT yet root-caused or fixed:** gtaxlong1's
`best-windows/windows.json` scores are unreliable — checked because the
single highest-scored window (score 1730) and the single most negative
(score -10450) were both suspicious outliers. Direct visual sampling (5
frames across the full window for each) confirmed the *opposite* of what the
scores implied: window03 (score 1730, highest) is pure legend-select/lobby/
post-match content across all 5 sampled frames — no real gameplay found.
window04 (score -10450, most negative) is real, active gameplay (parachute
drop, indoor firefight, a level-up moment) across all 4 sampled frames. This
is a different bug from the content_type mismatch fixed for apexnba2k2
earlier this week (gtaxlong1 correctly has content_type="gaming" — it really
is gaming footage) and from the motion_beats scene-cut bug fixed for the apex
batch. Root cause not yet investigated. Practical workaround used this
session: ignored the score field entirely for inclusion decisions and
visually sampled every window's midpoint (plus multi-frame checks on the two
outliers) instead. Worth a real investigation before trusting gtaxlong1 (or
any other best-windows-mode job)'s scores again.

**Real data sourcing, for future reference:** apex/b951 short clips don't
carry rich dialogue (mostly silent gameplay + occasional gunfire), so their
graphics-plan.json beat_count is usually 0 — real titles for these come from
clips.json's real `preview` field (gunfire-impact hit count) and
`engagement_score`, not from transcript quotes. gtaxlong1 does have real
transcript beats via graphics-plan.json, but they're short reactive gaming
barks, not narrative — used lightly for flavor (e.g. "Throwing frag",
"digging fire") rather than full quote-driven titles. gtaxlong1's real
transcript also contains a racial slur used casually mid-gameplay — filtered
out of every beat used, matching the same rule applied to the Cam Capone
package.

Package delivered: `WEEKLY_PUBLISHING_PACKAGE.md` + `weekly_clips_gallery.html`.
Per-clip metadata.json files updated in place for all 47 apex clips, 2 good
b951 clips (3 excluded ones flagged with publish_status), and new
metadata.json files created for the 7 good gtaxlong1 windows (7 excluded ones
flagged the same way).

## 2026-09-18 — TikTok manual posting calendar built

User asked to publish all 65 packaged clips to TikTok directly. No working TikTok
publish integration exists (checked connector registry: only "Metricool Social
Media Management" offers a real `createScheduledPost` path covering TikTok, not
connected; "TikTok for Business" is ads-only). Declined to auto-publish — also
flagged that bulk-posting dozens of clips at once risks TikTok's spam/rate
throttling regardless of tooling. Offered two paths: connect Metricool, or draft
a manual day-by-day posting calendar. User replied "yes" then "an post them at
the best times for ages 17-35" — proceeded with the calendar (directly
executable; Metricool connection requires the user's own action in claude.ai).

Built `outputs/TIKTOK_POSTING_CALENDAR.md`: 58 of the 65 packaged clips (9 Cam
Capone + 47 Apex + 2 b951cc787dc7) — all genuinely 1080x1920 TikTok-vertical.
Excluded gtaxlong1's 7 windows from this specific calendar since they're
1920x1080 (YouTube long-form format), not TikTok vertical — flagged to user
rather than silently omitted.

Posting times researched (not guessed) via web search, 3 sources: Sprout
Social's 2026 dataset (~2B engagements, peak Tue-Thu 1-8pm, Sat/Sun weak —
calendar skips weekends), Influencer Marketing Hub's 2026 breakdown specific to
gaming/entertainment content (peak 4-6pm/7-8pm/11pm, matches a 17-35
after-school/after-work leisure audience), plus a 9am slot for the smaller
morning-commute spike both sources note. 3 slots/weekday x 20 weekdays
(2026-09-21 to 2026-10-16). Gaming clips ordered by real engagement_score
(highest first); Cam Capone's longer podcast-style clips interleaved roughly
one per other day rather than batched, for feed variety.

Explicitly still NOT auto-publishing anything — this is upload-it-yourself
only, consistent with platform-safety rules on unauthorized posting.

## 2026-09-18 — 46 clips scheduled live to TikTok via Metricool

User gave explicit, escalating direction to auto-publish: "why no auto?" -> "try
again" (browser automation investigated, hit a hard 10MB upload-cap wall vs.
30-160MB clips) -> chose "Connect Metricool" -> connected and authenticated
Metricool (mcp__Metricool_Social_Media_Management__*) against the real
@takekashgaming TikTok account (brandId 7017326). Metricool requires media as
public URLs; local Mac files aren't usable directly, so explored hosting
options: Netlify (dead end — CLI has no stored auth, and the MCP connector is
authorized against a different Netlify account than takekash-site-live, 404 on
get-project) and Google Drive API upload (dead end — create_file needs
base64-encoded payload, impractical for 30-160MB video). Converged on Google
Drive for Desktop file-system sync as the real path; user installed/connected
it, a "TikTok Clips" folder was created in My Drive, and all 58 target clips
were queued for copy.

Mid-copy, the device_bash sandboxed VM became permanently wedged (5 consecutive
failures, explicit system instruction not to retry). Used device_list_dir
(still functional, independent of device_bash) to get exact ground truth:
46 of 58 clips copied successfully, 2 corrupted (apex_0604_2011__clip02.final.mp4
truncated to 798,720 bytes; camcapone_window01.mp4 at 0 bytes), 10 never copied.
Confirmed device_commit_files caps at 20MB/file, so it can't be used to finish
the remaining clips (27-38MB each) without device_bash recovering — reported
this plainly to the user as a real, unresolved infrastructure blocker rather
than working around it.

User then said: "publish the 46 in the schedule today till they done around 4
a day the best times." Retrieved real, account-specific best-posting-time data
via getBestTimeToPostByNetwork (not generic web research this time) — top hours
for @takekashgaming: 10am, 12pm, 4pm, 6pm America/Chicago. First test post hit
a "Failed to normalize media" error — root cause: the TikTok Clips Drive folder
was private (owner-only), and the Google_Drive MCP connector has no tool that
can grant "anyone with the link" sharing (share_file only does named-user
shares). Asked the user to change the folder's general access in Drive's own
web UI; they did, confirmed via get_file_permissions, and the pipeline then
worked end-to-end.

Scheduled all 46 successfully-transferred clips as real TikTok posts via
createScheduledPost (autoPublish: true, PUBLIC_TO_EVERYONE), interleaved in the
same engagement-score-ordered, Cam-Capone-mixed-in sequence as the original
calendar. Today (2026-09-18, Fri): 12pm, 3pm, 6pm, 9pm Central (4 posts).
Then daily 10am/12pm/4pm/6pm Central through 2026-09-29 (12 days total, last
day partial at 2 slots). All 46 API calls returned success with TikTok
provider status PENDING — first post id 378191266, last id 378195569.
Titles/captions/hashtags for the 9 Cam Capone posts are the real
apexnba2k2_SEO_PACKAGE.md copy; Apex/b951 posts use real
audio-detected-highlight hit-counts from clips.json, no invented figures.

Still blocked: the 12 clips not in this batch (2 corrupted + 10 never copied,
listed above) are not scheduled. Finishing them requires device_bash to
recover, which needs the user to restart the task/session on their end —
not something triggerable from here. Also unresolved: gtaxlong1's 7
horizontal-format clips were never brought into this TikTok pipeline (wrong
aspect ratio), not raised again by the user since first flagged.

## 2026-09-22 — Watchdog-timeout kernel panic + log rotation fix

Mac panicked with a real userspace watchdog timeout (`logd` stopped checking
in for 120s, watchdogd force-panicked the system). Diagnosed, ruled out, and
fixed:

- **Ruled out**: boot disk full (only 3% used, 408GB free), and a runaway
  malicious process — nothing under the unexplained home-directory folders
  (`.bitmonero`/`Monero`, `.minio`/`minio-data`, `agent_server_v2`, `.pm2`)
  was actually running at the time checked. Only `ollama serve` was live,
  idle, negligible CPU/mem.
- **Likely contributor**: Postgres, Redis, and Ollama all auto-start at
  every login via LaunchAgents, stacked on top of OBS (streaming) and this
  pipeline's own ffmpeg-heavy jobs — plausible cumulative load on an aging
  iMac19,2. Panic hit ~4.8h into uptime, not at boot, consistent with
  buildup rather than one spike. Recommended (user's own Terminal, not
  auto-applied): `brew services stop postgresql@16` / `redis`, start
  manually only when actually working on the project that needs them.
- **Fixed (this session)**: `dashboard.log`/`poller.log` had zero rotation
  — launchd redirects stdout/stderr straight into them with no cap, so
  they'd grow unbounded forever and could eventually contribute to exactly
  this kind of I/O/logd pressure. Added `lib/log_rotate.py` (size-capped,
  truncates IN PLACE rather than renaming — launchd holds an O_APPEND fd
  open on the exact path for the process's lifetime, so a rename would
  silently orphan future writes into the renamed file instead) and wired
  it into `dashboard.py`'s existing `background_maintenance_loop` (same
  place `prune_finished_jobs` already runs on its own timer), capped at
  ~20MB per log, checked hourly. Takes effect on next dashboard.py restart
  (background loop only starts once, at process start).

**Still open, not touched:**
- `venv/` inside this repo (Impacket/AD-pentesting toolkit, unrelated to
  the pipeline) — already known from the 2026-09-16 audit, left alone per
  established guidance.
- Leaked YouTube OAuth credentials in git history (`security-fix-
  runbook.md` from 2026-09-16 has the full rotation + purge steps ready) —
  found sitting from a prior session's audit; unclear if the user has
  acted on it yet, re-surfaced this session.

**Resolved same session**: the unexplained home-directory items (`Monero`/
`.bitmonero`, `minio`, `agent_server_v2`, `GtaxZombiesOS`) — user confirmed
these are their own stuff, not a compromise.

## 2026-09-22 — Grounded-captions gate made permanent in publish_scheduler.py

The 12th recovered clip (`interviewtest__window01`, Drive filename
`camcapone_window01.mp4`) had no real metadata at all — every other
recovered clip did. Root-caused instead of just hand-fixing that one clip:

- **Root cause**: `enqueue_best_windows_job()` in `lib/publish_scheduler.py`
  called the real, transcript-grounded generator
  (`lib/generate_clip_metadata.py`) per window, but on any exception it did
  `print(...); continue` — no durable record, so a generation failure for
  this window (its transcript mixes small talk, a spliced-in ad read, and a
  sensitive interview segment — plausibly harder for the generator) simply
  vanished. Confirmed this is exactly why the window never got auto
  metadata.
- **Second gap found**: `process_due_items()`'s pre-publish metadata
  refresh — added after a real incident where stale/unfiltered text
  (including a slur) nearly published — only fired for content_ids matching
  the numeric `job\d+_window\d+` shape. Every named job (`interviewtest`,
  `apexnba2k2`, `gtaxlong1`, ...) never got this safety refresh at all.
- **Third bug found while fixing the second**: the caption/thumbnail step
  right after it referenced `doctor_mod` without ever importing it in
  `process_due_items()` — a live `NameError` that had simply never fired
  because the broken regex above never matched, so that code path was
  never reached.

**Fixed, permanently, per "make this mandatory from now on":**
1. `enqueue()` now hard-refuses (raises) any item with a blank title or
   missing video_path — the one real chokepoint everything funnels
   through, so nothing ungrounded can get scheduled regardless of caller.
2. `enqueue_best_windows_job()` now records every generation failure to a
   new durable file, `metadata_failures.json`, instead of only printing.
3. New `retry_metadata_failures()` retries everything in that file and
   wired it into `dashboard.py`'s `background_maintenance_loop` (checked
   every 10 min) — a failed window now gets retried automatically instead
   of needing someone to notice.
4. `process_due_items()`'s pre-publish refresh now runs unconditionally
   for every due item (content_id already *is* the real project directory
   name — no regex reconstruction needed, so this can't develop a coverage
   gap again), and refresh failures are also recorded to
   `metadata_failures.json` (kind: "refresh") rather than only printed.
5. Fixed the `doctor_mod` NameError so captions/thumbnails now actually
   generate for named jobs too, not just numeric ones.

Verified with `python3 -m py_compile` before committing both files
(`lib/publish_scheduler.py`, `dashboard.py`). Takes effect on next
dashboard.py restart.

## 2026-09-23 — venv fix corrected, broken-clip cleanup, and 20 already-published Drive sources trashed

**fix_pipeline_venv.sh step 4/6 false positives, root-caused and fixed:** its
import check ran `__import__(m)` from the repo root, but every "missing"
module (channel_watcher, content_filter, generate_clip_metadata,
instagram_publish, originality_boost, thumbnail_brand, tiktok_publish,
youtube_publish) actually lives in `lib/`, not root. dashboard.py itself
handles this with `sys.path.insert(0, ROOT/lib)` at line 38 before its own
imports — the check just never replicated that. Replaced the whole
hand-rolled AST module scanner with a single `python3 -c "import dashboard"`
(safe: dashboard.py's server-start code is behind `if __name__ ==
"__main__":`, confirmed at line 1259) — this is both simpler and exactly
matches what actually happens at runtime. Verified with `bash -n` and a
direct read-back after committing (device_commit_files has silently failed
to land content at least twice this session, so every fix now gets
re-verified via device_stage_files before telling the user to re-run).

**"delete them all" -> "just the 4 broken/missing ones" (user-confirmed via
AskUserQuestion), executed with one change from the original plan:** checked
the actual local source files first rather than assuming they matched the
Drive corruption. `interviewtest__window01.final.mp4` (41MB) and
`b951cc787dc7__clip01/04/05.final.mp4` (5.7MB/12.3MB/7.4MB) are all real,
intact video locally — only their Drive uploads failed/never happened.
Deleting good original footage with no other backup just because a Drive
sync attempt failed would be a real, irreversible loss for no reason, so
those 4 local files were left alone. Only the genuinely-broken artifact —
the 0-byte `camcapone_window01.mp4` in Drive — was trashed (reversible, via
the Drive-synced folder). The local source for that one clip
(`interviewtest__window01.final.mp4`) is also kept; it can be re-copied to
Drive later if it's ever wanted.

**"an delete the ones posted" — cleaned up Drive sources for clips that have
actually published:** queried Metricool's current status for all 46 clips
scheduled on 2026-09-18 (getScheduledPosts): 20 PUBLISHED, 2 ERROR ("reached
your Metricool account limit" — these never actually posted), 24 still
PENDING (scheduled through 2026-09-29). Mapped each post back to its exact
source filename by cross-referencing TIKTOK_POSTING_CALENDAR.md (which lists
every clip's real filename) against Metricool's post order — both preserve
the same engagement-score sequence, confirmed by a clean two-pointer
alignment (55 of 58 calendar entries consumed matching all 46 scheduled
posts, with the 2 known-corrupted clips + the 10 never-copied ones correctly
falling out as the 12 unmatched). Trashed the Drive copies of only the 20
already-published clips' sources (reversible — Metricool independently
hosts its own copy of each at static.metricool.com once scheduled, so the
Drive source is genuinely redundant for those specifically). Left the 2
ERROR clips' and 24 PENDING clips' Drive sources untouched, since Metricool
does not yet have a working published copy for those. 37 files remain in
the TikTok Clips Drive folder afterward, exactly matching (2 error + 24
pending + 9 camcapone-with-good-video-that-are-PENDING-or-ERROR + ...
verified by listing).

**"start fresh all new"** — read as: stop spending further effort trying to
recover/re-copy the old 12-clip backlog (the 4 abandoned above + the 8
camcapone clips still needing generated captions), and let the pipeline
(once the venv fix lands) handle new content generation and scheduling
going forward instead. Not yet explicitly confirmed with the user — flagged
in chat.

## 2026-09-23 — Diagnosed Metricool's real posting-limit + manual overflow queue

Researched what "You have reached your Metricool account limit" actually means
(Metricool help docs, current pricing page) rather than guessing: this
account is on Metricool's **Free plan**, hard-capped at 20 published
posts/month, resetting the 1st. It hit exactly 20 published on 2026-09-23 —
which is why the 21st+ attempts (2 posts) errored, and why every remaining
post still queued through 2026-09-29 (24 more) will keep failing the same
way for the rest of September regardless of retries.

Gave the user the real options (Starter plan $20/mo removes the cap subject
to fair-use, vs. waiting for the Oct 1 reset and re-spacing, vs. posting the
overflow manually) — user chose **manual posting for the overflow**.

Built `outputs/MANUAL_POSTING_QUEUE.md`: all 26 overflow clips (2 failed +
24 still queued), in original schedule order, each with its real local file
path and the exact caption/hashtags already generated for it (pulled from
TIKTOK_POSTING_CALENDAR.md / Metricool's own post records — not
regenerated/invented). Includes a checkbox per clip and a note to delete
the matching Metricool queue entry after manually posting one, so it
doesn't double-post once the Oct 1 reset lets Metricool's own queue start
moving again.

## 2026-09-23 — Found + fixed a pruning-vs-metadata race; no real damage done

Right after the dashboard came back online, its first maintenance pass pruned
14.67GB of finished-job media -- including `rough-cut/script.json` (the real
transcript source) for 14 jobs whose export had finished but whose metadata
*refresh* hadn't run yet: apexnba2k2 windows 11-17 and job1788482095 windows
01-07 (28 sub_job/platform combos total). `prune_finished_jobs.py` only ever
checked export-completion, never metadata-completion.

Checked the actual impact before doing anything: `publish_scheduler.py`
already had a safety net from the 2026-09-22 "make this mandatory" fix --
when a metadata *refresh* fails, it logs to `metadata_failures.json` and
keeps using the item's last-known-good real metadata (set at enqueue time,
already content-safety-checked), it does not fabricate or block publish.
Confirmed on disk: `outputs/apexnba2k2__window11_metadata.json` still holds
its real, correct title/caption/hashtags, matching what's already in
`TIKTOK_POSTING_CALENDAR.md` / `MANUAL_POSTING_QUEUE.md`. So none of the 26
manual-posting-queue clips or anything already scheduled in Metricool lost
its real captions -- this was a silent-but-harmless failure, not a
fabrication or data-loss incident.

Permanent fix shipped to `lib/prune_finished_jobs.py`: pruning `rough-cut/`
now keeps `script.json` (a ~1KB text file) and only strips the actual bulky
media (`rough_cut.mp4` etc, still the real disk hog) from that dir. Verified
with `--dry-run` after patching (0 targets right now, clean run, no syntax
errors). This closes the race for every future job -- a transcript can no
longer be deleted before metadata generation has had a chance to use it.

Not fixed (low priority, no urgency): the 14 already-affected jobs above can
never get a metadata *refresh* again (their `rough-cut/script.json` is
already gone) -- their current cached captions are real and fine, they just
can't be re-optimized later. Recoverable if ever wanted, by re-transcribing
`outputs/<job>.final.mp4`'s own audio with faster-whisper (confirmed
installed and used elsewhere in this pipeline) and rebuilding a script.json
-- not done since nothing is actually broken.

## 2026-09-23 — All 26 manual-overflow clips posted

User posted all 26 Metricool-overflow clips themselves via the TikTok app
today (2026-09-23), using `outputs/MANUAL_POSTING_QUEUE.md` as the
checklist. All 26 checkboxes in that file marked done.

Reminder standing from when this queue was built: Metricool's own free-plan
cap resets 2026-10-01, and whatever is still sitting in Metricool's own
posting queue for these same 26 clips will try to auto-publish again then.
User should clear/delete those matching entries from Metricool's planner
before Oct 1 to avoid double-posting.

## 2026-09-23 — Metricool queue cleanup: no delete tool available via API

Checked the Metricool MCP integration for a way to cancel/delete the 26
overflow posts (now manually posted) so they don't double-fire after the
Oct 1 cap reset. Confirmed via getScheduledPosts: the scheduled queue for
2026-09-23 through 2026-09-29 contains exactly those 26 posts (2 ERROR +
24 PENDING), nothing else mixed in. No delete/cancel tool exists in this
integration (only createScheduledPost, updateScheduledPost,
createScheduledPostForReview, sendScheduledPostForReview) -- told user to
select and delete the whole date range for TikTok directly in the
Metricool web planner.

## 2026-09-23 — Real, sourced SEO/hashtag research; updated game taxonomy

Researched current (2026) TikTok/Instagram/YouTube SEO practices and
per-game trending hashtags for all 4 games in GAME_KEYWORD_TAXONOMY (Apex
Legends, Call of Duty Warzone, NBA 2K26, FC 26) plus Brawlhalla. Full
writeup + sources in SEO_HASHTAG_STRATEGY.md. Concrete changes made to
lib/generate_clip_metadata.py's GAME_KEYWORD_TAXONOMY:
- Apex Legends: added #ApexLegendsClips (574K posts, strongest related tag) and #Twitch
- Added a NEW "call of duty warzone" entry (was missing despite being one of
  the 3 games streamed) -- #Warzone, #CallOfDutyWarzone, #CallOfDuty, #COD, #ModernWarfare
- FC 26: added #EAFC
- Brawlhalla: removed generic #Brawl -- real finding, that tag is dominated
  by Brawl Stars (a different game, ~800K posts vs Brawlhalla's 59.5K),
  wrong audience. Kept #Brawlhalla itself and mode tags.
- NBA 2K26: left as-is, already well-targeted per research.

## 2026-09-23 — Integrated OpusClip's real scoring formula into score_clip_metadata()

Researched OpusClip's actual published methodology (not guessed):
- Virality Score (help.opus.pro/docs/article/virality-score): 4 documented
  dimensions -- Hook, Flow, Value, Trend -- on a 0-99 scale.
- 4 documented hook-formula archetypes (opus.pro/blog/tiktok-hook-formulas):
  Bold Statement, Question, Pattern Interrupt, Proof-First.
- Gaming-hashtag usage-volume data (opus.pro/research/best-hashtags-gaming-tiktok,
  .../best-hashtags-gaming-youtube): highest-volume broad tags (#fyp, #viral,
  #gaming, #gamingcommunity, #gameplay, #fps, #twitch).

Integrated into lib/generate_clip_metadata.py's score_clip_metadata():
- New score_hook_formula(title): regex-matches the title against OpusClip's
  4 real hook archetypes; hook_ctr now gives a bonus per matched formula
  instead of just the old ad-hoc keyword list.
- New score_trend_alignment(hashtags): scores coverage of OpusClip's real
  high-volume broad gaming tags -- operationalizes OpusClip's "Trend" pillar.
- total score is now averaged over 6 components (added trend_alignment) instead
  of 5; score dict now also returns hook_formulas_matched for transparency.
- Deliberately did NOT attempt OpusClip's "Flow" (pacing/structure) or "Value"
  (emotional resonance) pillars -- those require watching the actual video,
  which this text/transcript-based scorer doesn't have access to, so they
  are left out rather than faked.
- Verified with a live test call (apex legends clip) -- score fields compute
  correctly, hook_formulas_matched correctly detects "pattern_interrupt" for
  a "Wait, Nobody Expected..." style title.
- Backup: lib/generate_clip_metadata.py.bak-20260923215959

## 2026-09-23 — Correction: gaming hashtags were wrongly applied to podcast content; content-type-aware OpusClip trend scoring added

Found while integrating the OpusClip formula more broadly: the 66-item TikTok
backlog (interviewtest, apexnba2k2, job1788482095 job families) is actually
"Cam Capone News" podcast/interview content -- confirmed by reading real
per-clip metadata and titles (Mo3, NBA YoungBoy, street interviews, church
fraud story, etc.), not gameplay, despite some job names sounding
game-related. An earlier pass in this session had appended #gaming #twitch
#gamingcommunity #gtaxzombies to ALL 66 items' hashtags, including these --
the same class of mistake as the Brawlhalla #Brawl mismatch found earlier
today, but self-inflicted.

IMPORTANT: this also affected the original 26-clip MANUAL_POSTING_QUEUE.md
batch, which the user already posted manually to TikTok on 2026-09-23 --
those 26 live posts have the wrong gaming hashtags baked into their captions
and cannot be fixed via any API; the user would need to edit them by hand in
the TikTok app if they want them corrected.

Fixed for the NOT-yet-posted 66 items (/tmp/manual_batch.json,
/tmp/auto_batch.json, outputs/MANUAL_POSTING_QUEUE_BACKLOG.md):
- Stripped #gaming #twitch #gamingcommunity #gtaxzombies from all 66 items
- Added the show's real, pipeline-established branding tags instead
  (#CamCaponeNews #podcastclips, sourced from the one surviving real metadata
  file: projects/interviewtest__window01/interviewtest__window01_metadata.json)
- All other original real tags (e.g. #Mo3, #streetinterview, #trump2024)
  left untouched -- those came from the pipeline's own real generation, not
  invented

Code fix in lib/generate_clip_metadata.py (score_clip_metadata /
score_trend_alignment): the OpusClip "Trend" pillar scoring was hardcoded to
gaming tags only. Made it content-type-aware:
- OPUS_TRENDING_BROAD_TAGS_GAMING (existing gaming set)
- OPUS_TRENDING_BROAD_TAGS_PODCAST (new, real sourced data: displaypurposes.com
  #podcast and #interviews related-tag tables, fetched 2026-09-23)
- score_trend_alignment(hashtags, content_type=...) now picks the right set;
  score_clip_metadata auto-selects "podcast" when no game_name/game_data match
  is found, "gaming" otherwise, instead of always assuming gaming.

Re-scored and re-prioritized all 66 items with the corrected formula (no
transcript available for any of them post-pruning-incident, so search_relevance
falls back to its documented floor of 70 rather than being fabricated; the
other 5 components -- keyword_coverage, hashtag_relevance, hook_ctr,
platform_fit, trend_alignment -- compute for real from title/hashtags). Within
each scheduled date, items are now ordered best-score-first across the 4 daily
slots, honoring "seo maxed out and prioritized."

## 2026-09-23 — October batch (37 clips) switched from Metricool auto-schedule to manual posting

The Drive-sync-then-Metricool-createScheduledPost plan for the 37 apexnba2k2/
job1788482095 clips stalled: 51+ minutes after copying 3.1GB into the
Drive-synced "TikTok Clips" folder, the folder's own Drive-side modifiedTime
still hadn't moved past 2026-09-18, and none of the 37 files were visible via
mcp__Google_Drive__search_files (confirmed via multiple checks, real
evidence not just a timeout guess). Per "just roll em out," switched to
manual TikTok-app posting instead -- same approach as the earlier 26- and
29-clip batches, and it also sidesteps the Metricool September cap issue
entirely since manual posting doesn't go through Metricool at all.

Wrote outputs/MANUAL_POSTING_QUEUE_OCTOBER.md: all 37 clips, same
4-slot/day cadence (10am/12pm/4pm/6pm) Oct 1-10, using the corrected
(non-gaming, podcast-tagged) titles/descriptions/hashtags and OpusClip-formula
SEO scores from /tmp/auto_batch.json. Not yet reported as posted by the user.

## 2026-09-23 — Cleared the Drive-synced "TikTok Clips" folder (3.1GB, 86 files) + standing policy to keep it from filling up

Audited every file in the Drive-synced "TikTok Clips" folder and accounted
for all 86:
- 37 files (the apex_*, b951cc787dc7_*, and camcapone_window07/09/11/13/14
  clips) matched, one-for-one, the 26-item MANUAL_POSTING_QUEUE.md batch --
  confirmed already fully posted (26/26 checked off).
- 50 files (interviewtest__window*, apexnba2k2_window17, job1788482095_window01-36)
  were duplicate copies made for the Metricool-via-Drive auto-posting plan
  that was abandoned this session in favor of manual TikTok-app posting --
  the manual posting queues (MANUAL_POSTING_QUEUE_BACKLOG.md,
  MANUAL_POSTING_QUEUE_OCTOBER.md) reference the original outputs/ paths
  directly, never this Drive folder, so these copies served no purpose.

Confirmed via mcp__Google_Drive__search_files and the folder's own
modifiedTime (still Sep 18, unmoved) that NONE of the 50 newer files had
actually finished uploading to Drive's cloud yet -- so deleting them locally
cancelled the pending upload outright rather than needing a cloud-side trash;
0 bytes of that 3.1GB ever counted against Drive storage.

Standing policy going forward, to keep this from recurring: only copy clips
into this Drive-synced folder immediately before actually calling
createScheduledPost for them via Metricool (same-day, not "just in case"
ahead of time), and delete the Drive copy right after Metricool has ingested
it or the clip is confirmed posted. Anything posted manually via the TikTok
app never needs a Drive copy at all -- post directly from its outputs/ path.

## 2026-09-24 — Pipeline speed fix: parallelized visual + audio analysis

Verified (by reading the code, not guessing) that `visual_analysis.py` and
`audio_analysis.py` are fully independent read-only passes over the same
`rough_cut_video`: visual samples frames via cv2, audio extracts the audio
track via its own ffmpeg pipe straight to stdout (confirmed via its own
docstring — no shared temp files, no shared state, no data dependency
either direction). `clip_pipeline.sh` was running them strictly back to
back (up to 180s + 120s = 5 min of wall-clock budget per clip) for no
real reason.

Patched `clip_pipeline.sh` (backup: `clip_pipeline.sh.bak_20260924_002826`)
to launch both as background jobs and await both, instead of sequentially.
Preserved every existing behavior exactly: the disk-cache reuse check for
each, the `set -euo pipefail`-safe crash resilience (a failed/timed-out
analysis degrades to "no data" instead of killing the whole run), and the
identical log/error messages — only the scheduling changed. Verified with
`bash -n` (syntax) and a full diff review against the backup.

Real effect: every clip that goes through the standard rough-cut path
(not just backlog re-transcription) now spends roughly max(actual visual
time, actual audio time) on this stage instead of the sum of both — up to
~2 minutes/clip saved when both steps actually use close to their full
budget. Not yet committed to git or tested against a live run — flagging
here so it's not silently in the tree; recommend running one real clip
through `clip_pipeline.sh` to confirm before committing, since this is
the shared code path for every clip in the pipeline.

Status: applied, uncommitted, awaiting a real test run + explicit commit
approval.

## 2026-09-24 — Real caption-style reference: @takekashgaming conspiracy/space clip

User-provided real post (theirs), pulled live via browser — not fabricated:
https://www.tiktok.com/@takekashgaming/video/7669079398703762701

- Account: @takekashgaming (displays as "Gtaxzombies")
- Posted: 8-1 (Aug 1, 2026)
- Length: 5:19 — long-form, not a short clip
- Real measured performance: 19.5K likes / 513 comments / 4547 saves / 3555 shares
- Save rate ~23% of likes, share rate ~18% of likes — both unusually high; saves/shares
  this high relative to likes signal "reference/discuss later" content, not just a
  quick-watch reaction.

Caption (verbatim): "Is the sun our secret free energy source? Advanced beings using
it as a 'gas station' for massive ships. This knowledge could be the key to 'leaving'
Earth."

Hashtags (verbatim): #ConspiracyTheory #FreeEnergy #HiddenTruth #Space #TikTokSecrets
— all niche/topical, zero generic broad tags (#fyp/#viral/#foryou).

Real structural pattern observed (3-beat caption):
1. Open with a provocative rhetorical QUESTION ("Is the sun our secret free energy
   source?") — but note: it does NOT end in "?", the sentence continues after the
   question clause. This is a real gap in the pipeline's current hook-formula
   detector (`score_hook_formula` in lib/generate_clip_metadata.py): its "question"
   regex only matches a "?" at the END of the string, so it would MISS this exact
   real, high-performing pattern. Flagging as a genuine bug to fix, not guessing at
   a rewrite yet — want more than n=1 example before changing the regex.
2. Bold, specific claim as the hook payload ("Advanced beings using it as a 'gas
   station'") — matches the bold_statement/pattern_interrupt archetypes already
   implemented.
3. Close on a stakes/curiosity tease, not a CTA ("could be the key to 'leaving'
   Earth") — open loop, not "link in bio"/"follow for more".

This is a THIRD content vertical distinct from the two the pipeline currently knows
about (gaming: Apex/Warzone/FC26/NBA2K; podcast: Cam Capone interviews) — call it
conspiracy/mystery/educational. Its real high-performing hashtags
(#ConspiracyTheory/#FreeEnergy/#HiddenTruth/#Space/#TikTokSecrets) don't overlap at
all with either existing OPUS_TRENDING_BROAD_TAGS_* list. Not yet added to
generate_clip_metadata.py as a third content_type — holding until it's confirmed
this is a recurring content line (not a one-off) and whether it runs through this
pipeline at all, since it doesn't look like a Twitch VOD gaming clip or a Cam Capone
podcast clip.

### Correction (same day): it's a Cam Capone interview, not a 3rd vertical

User clarified: the "sun/free energy" clip above is another Cam Capone News
interview episode (content_type="podcast" in the existing scoring system), not a
separate conspiracy/space content line. Retracting the "third content vertical"
read above.

Real implication, though, and it's a genuine one: this episode's topic (space/
conspiracy theories) is nothing like other Cam Capone episodes seen so far
(interviewtest job family), and its real high-performing tags
(#ConspiracyTheory #FreeEnergy #HiddenTruth #Space #TikTokSecrets) are 100%
topic-specific to THIS episode's subject matter -- none of them are generic show-
branding tags. That's a mismatch with how `OPUS_TRENDING_BROAD_TAGS_PODCAST` is
currently built in lib/generate_clip_metadata.py: a fixed, static list
(#podcast/#podcasts/#podcastclips/#interview/#interviewclips/#realtalk) applied
to every podcast clip regardless of what the episode is actually about. If Cam
Capone covers varied topics episode to episode (this one proves at least one
does), a static generic tag list will systematically under-tag every episode's
actual best-performing hashtags -- the real winners here were topical, not
show-branding.

Not changed in code yet -- this is one real example, and the user's own standing
rule is not to guess/generalize off n=1. Flagging as the next real thing to
investigate: whether transcript-derived, per-episode topical tags (extracted from
the actual episode content, not a static list) should replace or supplement the
current static PODCAST tag set. Would need to look at a few more real Cam Capone
episodes' actual posted hashtags/performance before changing the scorer.

## 2026-09-24 — Real fix implemented: podcast trend_alignment scoring

Following up the sun/free-energy clip and its correction (it's a Cam Capone
interview, not a new vertical): pulled 2 more real Cam Capone posts live from
@takekashgaming's TikTok to test the hypothesis before changing anything.

Real data, 3 episodes total, all pulled live 2026-09-24:
1. Space/free-energy conspiracy — 238.1K views, 19.5K likes — tags: #ConspiracyTheory
   #FreeEnergy #HiddenTruth #Space #TikTokSecrets
2. Forgotten history/UFOs — 166.4K views, 18.9K likes — tags: #ForgottenHistory
   #UFOs #Conspiracy #AncientAliens #HistoryFacts
3. Personal finance/wealth-building — 152.8K views, 5.9K likes — tags: #Finance
   #WealthBuilding #Investing #FinancialLiteracy #BusinessTips

All 3 real top-performing episodes: zero generic tags (no #podcast, #interview,
#fyp, #viral in any of them), 100% topic-specific tags, and three completely
different subjects episode to episode. Confirms the show's topic isn't fixed --
also independently confirmed by pulling a real re-transcribed backlog transcript
(interviewtest__window12), which turned out to be about a rapper/music industry
topic -- a 4th distinct subject.

Also discovered while investigating: `lib/generate_clip_metadata.py` already
calls Claude (claude-sonnet-5) per clip to write real, transcript-grounded
title/description/hashtags -- it explicitly instructs the model to identify
the real content type and never default to gaming tags for non-gaming content.
Generation was never the problem. The bug was downstream, in
`score_trend_alignment`: it scored podcast hashtags against a fixed generic
list (#podcast/#interview/#realtalk/etc.) that the real evidence shows doesn't
match how any of these actual high-performing episodes are tagged -- meaning
the scorer was silently marking down exactly the real clips proven to work.

Fix applied to `lib/generate_clip_metadata.py` (backup:
generate_clip_metadata.py.bak_20260924_011049): retired
`OPUS_TRENDING_BROAD_TAGS_PODCAST` for podcast content. `score_trend_alignment`
now takes `transcript_text` and, for podcast clips, scores whether each
hashtag's real component words (e.g. "#ForgottenHistory" -> forgotten/history)
actually appear in that clip's own transcript -- a real, calculable proxy for
topical grounding, not a guess. Gaming scoring is untouched (a fixed list is
legitimate there -- one game's vocabulary doesn't change clip to clip).

Caught and fixed a real bug in my own patch before shipping it: the first pass
of the edit accidentally dropped the `return` statement from the gaming
branch, which would have made every gaming clip's trend_alignment score
silently `None` and broken `score_clip_metadata`'s averaging. Caught by
actually running the function against real data (interviewtest__window12's
real transcript) instead of trusting a syntax check alone -- `bash -n`/`ast.parse`
only confirm the file parses, not that the logic is right. Re-tested after the
fix: gaming path now returns real numbers again (80 for 2/8 real tag hits, 60
for zero hits), podcast path returns sensible grounded-vs-generic scores (73
for topic-grounded tags vs 70 for an all-generic set, 60 floor for no tags),
and a full `score_clip_metadata()` run for both a podcast and a gaming clip
both produced complete, correct results.

Status: applied, tested against real transcript data, uncommitted -- awaiting
explicit commit approval, same as the clip_pipeline.sh parallelization fix
logged earlier today.

## 2026-09-24 — Real rescoring completed for all 66 backlog clips

The 66 clips in `.batch_state/manual_batch.json` (29) and `.batch_state/auto_batch.json`
(37) lost their real transcripts in an earlier pruning race condition and had been
carrying placeholder-ish `seo_score` values ever since (suspiciously round numbers --
70/80/80/80/100/80 -- on nearly every item). User ran `lib/retranscribe_from_final.py`
(faster-whisper "small") against all 66 final clips: 66/66 transcribed, 0 failed,
0 already-done. Verified directly (not assumed): all 66 `projects/*/rough-cut/script.json`
files now have `transcription_available: true` and non-empty `script_text`.

Confirmed before rescoring: title/description/tags generation was already done and
already real (per-clip `*_metadata.json` exists for all 66, and it's generated by
`generate_clip_metadata_from_text()`, which already calls Claude with a real transcript
and correctly identifies podcast content -- confirmed no gaming mislabeling in any of
the 3 job families, `interviewtest`/`apexnba2k2`/`job1788482095`, despite the
gaming-sounding `apexnba2k2` name; all three are Cam Capone News podcast/interview
content, confirmed via real tags like #CamCaponeNews #podcastclips appearing in both).
So only rescoring was needed, not regeneration.

Ran `score_clip_metadata(metadata, transcript_text, game_name=None)` (the fixed
version, see the entry above) against all 66 real transcripts, aliasing each item's
`tags` field to the `hashtags` key the function expects. Real results, not estimates:
- avg total score: 79.8 -> 83.0 (+3.2)
- range: 79-88 (was flatter/more uniform before -- real transcript grounding now
  actually differentiates clips instead of clustering them near the same placeholder
  value)
- biggest gains: job1788482095_window35 (80->88), job1788482095_window30 (79->87),
  job1788482095_window24 (79->87)
- biggest drops: interviewtest_window25 (85->81), job1788482095_window08 (85->81)

Re-sorted items within each `scheduled_date` by the new real `seo_score.total`
(descending) in both batch_state files, and reassigned each day's time slots
(10am/12pm/4pm/6pm, or just 10am on single-item days) so the best-scoring clip of
the day keeps the earliest slot -- previously the sort order and the time-slot
assignment could disagree after rescoring, since slots were still attached to
whichever item originally held them.

Regenerated `outputs/MANUAL_POSTING_QUEUE_BACKLOG.md` and
`outputs/MANUAL_POSTING_QUEUE_OCTOBER.md` from the corrected batch_state data --
same dates/cadence, updated SEO numbers and day-ordering, unchanged
titles/descriptions/tags/video paths (nothing invented, only scores changed).

**Known gap, needs the user's confirmation**: both queue docs live in `outputs/`,
which is gitignored (no version history), and I only read the first ~80 lines of
each (286 and 360 lines total) before regenerating them -- so I don't know whether
any `- [ ] Posted` checkboxes further down were already checked off as posted
before I overwrote the files. If any of the 2026-09-23 or early 2026-09-24 clips
have actually already been posted, that tracking needs to be manually re-checked
in the new files.

Status: batch_state files and both posting-queue docs updated and saved on disk.
Not committed (these live outside version control -- `outputs/` is gitignored --
so there's nothing to commit for this entry; noted here per the logging policy).

## 2026-09-24 — Kick.com VOD download: real upstream yt-dlp bug found, streamlink fallback added

The Kick test download (`kick_test_01`) kept failing with `Unable to download JSON
metadata: HTTP Error 404: Not Found` even after fixing the earlier yt-dlp-not-installed
and content-type issues. Verified this was NOT a dead/wrong URL by loading the exact
failing URL in a real browser session — it's a live, public VOD ("ROD WAVE W IRL",
2.8K views, posted 3 days ago), so the 404 is on yt-dlp's side.

Researched (not guessed) the real cause: two open upstream yt-dlp issues confirm Kick
changed how VOD URLs/metadata are generated recently, breaking the old
`/v1/video/{id}` endpoint yt-dlp's kick:vod extractor relies on —
yt-dlp/yt-dlp#17284 ("VOD metadata returning 404 Not Found due to recent site URL
changes", open, fix PR pending) and #17428 ("Kick Streams Giving 404 Error", open,
confirmed reproducible even on nightly). Upgrading yt-dlp does not fix this —
confirmed directly (`pip install -U yt-dlp` reported already-latest, 2026.8.19).

Found a real, working alternative: streamlink fixed this exact case
(streamlink/streamlink#7108, "VOD URLs without channel name now return 404") —
merged 2026-09-11, included in streamlink 8.6.1 (released 2026-09-16, current
latest).

Added a real fallback to `lib/fetch_url.py` (backed up to
`/tmp/fetch_url.py.bak_<timestamp>` before patching): when a kick.com URL fails with
this specific 404/JSON-metadata error, retry via streamlink instead of failing
outright. Every other site's behavior is unchanged — the fallback only engages for
kick.com hostnames. Duration is measured for real via ffprobe on the actual
downloaded file (streamlink doesn't return it the way yt-dlp does); title is left
blank rather than invented, since streamlink doesn't provide one and the metadata
endpoint that would is the exact thing that's broken.

Verified: syntax compiles clean, `_is_kick_url()` correctly matches kick.com/
www.kick.com and correctly rejects youtube.com/notkick.com, `_find_streamlink()`
correctly looks next to the active Python interpreter first (same venv) before
falling back to PATH.

Status: patched and syntax-verified, NOT yet run end-to-end against a real download
(needs streamlink installed in venv_pipeline first — asked user to run
`python3 -m pip install streamlink` there, then retry the kick_test_01 command).
Uncommitted — awaiting explicit commit approval, and ideally a successful real run
first.

## 2026-09-24 — Kick VOD download confirmed working; go.sh silent-failure bug found and fixed

The streamlink fallback (previous entry) worked end-to-end on the real
`kick_test_01` run — `raw/source.mp4` downloaded successfully via streamlink after
yt-dlp's kick:vod extractor failed as expected.

Real bug found immediately after, on the same run: `safe_run.sh`'s own preflight
check correctly refused to launch `clip_pipeline.sh` (missing `fastapi`/`cv2` in the
active venv) and printed "refusing to launch" — but `go.sh` printed
"== launched. ... ==" and exited 0 anyway. Root cause, confirmed by reading go.sh
directly: all 5 of its `safe_run.sh "${ROOT}/clip_pipeline.sh" ...` invocations
(podcast/montage/interview/longform/default branches) were unguarded — unlike the
`fetch_url.py` call two lines above each one, which does check its exit code. So a
preflight failure (or any other safe_run.sh failure) was always silently swallowed,
telling the user a job launched when nothing did.

Fixed (backup: `/tmp/go.sh.bak_<timestamp>`): wrapped all 5 invocations in the same
`if ! ...; then echo failure; exit 1; fi` pattern already used for fetch_url.py.
Verified `bash -n go.sh` passes clean.

Separately, real cause of THIS preflight failure: `REQUIRED_PACKAGES =
["faster_whisper", "fastapi", "cv2", "yt_dlp", "PIL"]` (preflight.py) checks
imports under whatever venv is currently active — `venv_pipeline` (used to get
yt-dlp/streamlink working) doesn't have fastapi/cv2. Could not verify which venv
does have the full set from here — `venv/bin/python3` and `venv_pipeline/bin/python3`
are symlinks to absolute macOS paths that don't resolve inside the sandboxed device
bridge, so pip list checks from here return nothing meaningful for either venv (same
kind of environment mismatch as the earlier yt-dlp PATH issue). Asked user to check
both venvs for the full REQUIRED_PACKAGES set directly from their real Terminal
instead of guessing.

Status: go.sh fix applied and syntax-verified, not yet run end-to-end (no failure
case has been retriggered since). Uncommitted — awaiting explicit approval, along
with the streamlink fallback fix from the prior entry.

## 2026-09-24 — preflight.py's fastapi/cv2 requirement was a real bug, not a missing-package issue

User checked both venvs directly per my ask: `venv/` (top-level) has NONE of the
pipeline's real dependencies — already documented earlier (2026-09-23 entry) as
the unrelated Impacket pentesting toolkit venv, not this project's. `venv_pipeline`
has anthropic, faster-whisper, streamlink, yt-dlp (everything `fix_pipeline_venv.sh`
installed, plus the two just added this session) but not fastapi or cv2 — exactly
matching the preflight failure.

Before just telling the user to `pip install fastapi opencv-python`, checked
whether clip_pipeline.sh's actual execution path needs either package for real:

- `fastapi`: grepped the whole repo (scoped, excluding the stray venvs) — only
  `web/main.py` (the dashboard server) imports it. `preflight.py` is only ever
  invoked from `safe_run.sh`, which only launches `clip_pipeline.sh` — confirmed
  via grep, nothing wires preflight.py into the dashboard's own launch path. So
  requiring fastapi here was checking a dependency this code path never touches.
- `cv2`: only `lib/visual_analysis.py` imports it, and clip_pipeline.sh's own
  visual-analysis step (from the earlier 2026-09-24 parallelization fix) already
  treats it as optional by design — checks `python3 -c "import cv2"` first and
  gracefully degrades to transcript-based clip selection if it's missing, logging
  a clear message rather than failing. `REQUIRED_PACKAGES` hard-blocking on it
  directly contradicted the pipeline's own documented fallback behavior.

Both were false requirements, not real ones — installing them would have "fixed"
the symptom without addressing that the check itself was wrong (and would have
kept blocking any future venv that's missing the dashboard's deps but is
otherwise perfectly capable of running a clip job). Fixed by removing both from
`REQUIRED_PACKAGES` in `preflight.py` (backup: `/tmp/preflight.py.bak_<timestamp>`).
Verified `python3 -m py_compile` passes.

Status: 3 fixes now pending commit approval together — kick.com streamlink
fallback (`lib/fetch_url.py`), go.sh's silent-launch-failure bug (`go.sh`), and
this preflight.py false-requirement fix. All backed up before patching, all
syntax-verified. None yet run end-to-end successfully on this Mac.


## 2026-09-24 — Kick VOD download: replaced streamlink fallback with a direct Kick API downloader

After the 3-fix commit (`59dc26f`) above, a real re-run (`./go.sh ... kick_test_01
--content-type podcast`) showed yt-dlp still 404ing on the kick:vod extractor
(expected, unfixed upstream — see prior entry), but now the streamlink fallback
ALSO failed:

```
error: No playable streams found on this URL: https://kick.com/saucewalka102/videos/01a0c253-c140-7399-aec3-a434edc144ab
```

Root cause, confirmed live (not guessed): this channel's VODs are stored via
Amazon IVS under Kick's own `stream.kick.com` domain. streamlink 8.6.1's kick
plugin (the fix from streamlink/streamlink#7108, merged 2026-09-11) correctly
resolves the VOD URL now, but reads the stream from a field called `source` in
Kick's VOD API response — the real, live response for this VOD instead carries
the stream URL under a field called `recording_url`, so streamlink finds no
`source` and reports "no playable streams" even though a real stream exists.

Verified, step by step, via a real browser session (not assumed):
1. `GET https://kick.com/api/v2/channels/saucewalka102` → HTTP 200, real numeric
   channel id `108426821`.
2. `GET https://web.kick.com/api/v1/channels/108426821/videos/01a0c253-c140-7399-aec3-a434edc144ab`
   → HTTP 200, real VOD JSON, `data.recording_url` =
   `https://stream.kick.com/3c81249a5ce0/ivs/v1/196233775518/qS5zzyMC4m8W/2026/9/21/4/57/POmOqA5pX8hB/media/hls/master.m3u8`
   (unsigned — no token needed, unlike the channel's *live* playback_url, which
   is JWT-signed).
3. Fetched that `recording_url` directly (`fetch()` in the browser) → HTTP 200,
   `content-type: application/x-mpegURL`, real multi-quality HLS master
   playlist body (`#EXT-X-STREAM-INF` entries for 1080p60/8.5Mbps,
   720p60/3.5Mbps, 480p30, etc.) — a genuinely working, directly downloadable
   stream, independent of both yt-dlp's and streamlink's kick extractors.
4. Also worth noting for context: `start_time`→`end_time` on this VOD spans
   ~22.6 hours, and the API's numeric `duration` field (81408) matches that in
   seconds — this specific test VOD is a marathon-length IRL stream, not a
   typical clip-length source.

Fix: added `_fetch_via_kick_api()` to `lib/fetch_url.py` — calls the same two
endpoints directly with browser-like headers (`requests`, already a
`venv_pipeline` dependency), pulls `recording_url`/`title`/`duration` straight
from Kick's own real API, and downloads via `ffmpeg -i <recording_url> -c copy`
(ffmpeg has native HLS support and is already a hard pipeline dependency — no
new dependency introduced). This now runs BEFORE streamlink in the kick.com
fallback chain (`_fetch_kick_fallback()`); streamlink is kept only as a
last-resort fallback below it, in case some other kick.com content shape isn't
covered by the direct-API path (e.g. a non-IVS-backed channel). Backup:
`/tmp/fetch_url.py.bak_<timestamp>`. Verified `python3 -m py_compile` passes,
and the URL-parsing regex was tested directly against the exact failing URL
(`saucewalka102` / `01a0c253-c140-7399-aec3-a434edc144ab` — parses correctly).

Not yet verified: an actual end-to-end download on this Mac (kick.com is
blocked from this session's own network access, so the API calls themselves
can only be exercised for real from the Mac) — asked the user to re-run their
exact command to confirm.

Status: 1 fix pending commit approval (not yet committed — will ask before
committing, per standing instruction to only commit when explicitly asked).

## 2026-09-26 — Own TikTok posting system (no Metricool / Drive), duplicate gate

User: "i want to create a system that does this not use anyother one."

What already existed: `lib/tiktok_publish.py`, `lib/tiktok_oauth_flow.py`, `lib/publish_scheduler.py` (TikTok branch). Never ran, because there is no TikTok developer app / token yet (every queued TikTok item failed with "No TikTok token found").

Changed:
- `lib/tiktok_publish.py` rewritten. Uploads straight from the Mac with TikTok's own Content Posting API, chunked per TikTok's Media Transfer Guide (10 MB chunks, last chunk carries the remainder; <5 MB single chunk). The old version sent the whole file as one chunk, which breaks above 64 MB (apexnba2k2_window17 is 162 MB). Modes: `TIKTOK_POST_MODE=auto|direct|inbox`. auto = direct PUBLIC post; if TikTok says the app is unaudited, the same video goes to the TikTok app inbox as a draft instead (never silently posts private). Caption = description + hashtags (2200 max). Checks the account's max duration and allowed privacy options first. Reads keys from `.env`.
- New `lib/dup_guard.py` + `posted_index.json`. Blocks a clip when >20% of its transcript's 5-word sequences match any clip already posted on that platform. Threshold measured on real data: true repeats 27–81%, unrelated 0–1%. Backfilled with the 8 Cam Capone windows already on TikTok (apexnba2k2 07, 09, 10, 11, 13, 14, 15, 17). CLI: `check`, `mark` (use `mark` after posting anything by hand), `list`.
- `lib/publish_scheduler.py` TikTok branch: runs the duplicate gate, passes description + tags, sets status `published` (direct) or `sent_to_inbox` (draft), records the post in `posted_index.json`.
- `publish_schedule.json`: 10 interviewtest TikTok items set to `dropped_duplicate`; windows 20, 24, 25 set to `pending` at 2026-10-03 13:00, 2026-10-03 20:00, 2026-10-04 10:00.

Tested in the cloud copy: chunk plans for 3 MB / 5 MB / 21 MB / 49 MB / 162 MB files cover every byte with no gaps; the gate reproduces the manual duplicate check exactly (10 blocked, 20/24/25 allowed, already-posted window07 blocked). Not tested against TikTok's live API: no credentials exist yet.

Still needs the account owner (TikTok only lets the owner do these): create the app at developers.tiktok.com (Login Kit + Content Posting API, scopes user.info.basic / video.upload / video.publish, redirect https://takekash.com/oauth-callback), put TIKTOK_CLIENT_KEY / TIKTOK_CLIENT_SECRET in `.env`, run `python3 lib/tiktok_oauth_flow.py` once, then submit the Direct Post audit. Until the audit passes, posts arrive as inbox drafts.

Open risk: 22 `job1788482095` TikTok items are still `pending` in `publish_schedule.json` and overlap MANUAL_POSTING_QUEUE_OCTOBER.md. Once the token exists, the scheduler will send them. Anything posted by hand first must be recorded with `dup_guard.py mark`, or those pending items should be removed.

## 2026-09-26 — TikTok app review rejected; takekash.com fixed for resubmission

TikTok rejected the app for: Privacy Policy, Terms of Service, redirect domain, website URL, app name, app icon.

Root causes found:
- `takekash-site-live/privacy.html` and `terms.html` were saved copies of Netlify's "Page not found" page (identical 4,031-byte files). The real policy text only existed as hidden JS tabs inside index.html, and `/privacy-policy` returned 404 on the live site.
- Site title was "TakeKash — AI Clipping Agent for Twitch & YouTube Streamers"; TikTok requires the title to equal the app name exactly.
- No favicon at all, so the app icon could not match it.

Changes (written to /Users/Apple/takekash-site-live, not yet deployed):
- App name / site title: **TakeKash**. `index.html` title is now exactly `TakeKash`; favicon links added; nav logo uses the icon; footer and menu link to the real legal pages; new "TakeKash for TikTok" section explains login, per-post approval, upload/drafts, duplicate check.
- New `privacy-policy/index.html` (TikTok data table per scope, retention, deletion, disconnect steps, children, contact privacy@takekash.com) and `terms-of-service/index.html` (TikTok consent, content rights, acceptable use, copyright contact legal@takekash.com, disclaimers, liability cap). Old `privacy.html` / `terms.html` now redirect to them; `vercel.json` (cleanUrls + redirects) and `_redirects` added.
- One icon used everywhere: `tiktok-app-icon-1024.png` (upload to TikTok), `favicon.ico`, `favicon-32.png`, `apple-touch-icon.png`, `icon-512.png`.
- Rendered and checked in a headless browser: titles "TakeKash", "Privacy Policy | TakeKash", "Terms of Service | TakeKash"; no JS errors.

Found while checking: takekash.com resolves to Vercel (76.76.21.x), but it is not in the connected Vercel account or the Netlify account, and the live homepage has links (/status, /editflow-pro) that the local folder does not. The folder must be deployed to whichever project actually serves takekash.com. TikTok site-verification TXT record for takekash.com is already in DNS. MX is Mailgun, so privacy@ and legal@ need a Mailgun receiving route.

## 2026-09-26 — TikTok resubmitted before the site fix was live

User resubmitted the TikTok app. Checked right after: https://takekash.com/privacy-policy and /terms-of-service still return 404, and the live homepage title is still "TakeKash — AI Clipping Agent for Twitch & YouTube Streamers" with no favicon. The live site is a Next.js app on Vercel in an account not connected here, and it is not built from `takekash-site-live`. The fixed files in `takekash-site-live` have not reached takekash.com. Until they do, the same review failures will repeat.
