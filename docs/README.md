# autoclip-pipeline

Scaffold for the 7-step editing pipeline (raw clip -> shipped output), part of
the `autoclip-app` project. Same seven steps run for every job; only steps 3
(Graphics) and 5 (Captions) branch by format.

## Pipeline

| # | Step             | Kind           | Notes                                              |
|---|------------------|----------------|-----------------------------------------------------|
| 1 | Intake           | copy           | copy raw clip into `projects/<job>/raw/`             |
| 2 | Rough cut        | skill          | WhisperX cut, kill filler, polish audio, makes script; off-ramp to Premiere Pro via `to-premiere` |
| 3 | Graphics         | format-specific| graphics-plan -> HyperFrames engine; plan beats, then build graphics |
| 4 | Second pass      | manual         | human review, incremental re-composite               |
| 5 | Captions         | format-specific| short-form only, burn-in on-beat                      |
| 6 | Background music | optional       | sidechain duck, re-normalize                          |
| 7 | Export           | finish line    | finalize/prune -> promotes to `outputs/<job>.final.mp4` |

## Format variants (steps 3 & 5 only)

- `short-explainer` — 9:16 1080x1920, top-half card graphics, centered locked captions, thumbnail usually skipped
- `short-tiktok-raw` — 9:16 1080x1920, hook card -> raw, low captions under face, thumbnail skipped
- `long-form-youtube` — 16:9 1920x1080, glass+zoom graphics, no burned captions (YT CC instead), thumbnail always generated

Configs for each live in `formats/`.

## Skills

Each folder under `skills/` is a self-contained step: `rough-cut`,
`graphics-plan`, `embedded-captions`, `background-music`,
`thumbnail-generator`, `to-premiere`. `finalize.sh` and `prune.sh` live at the
top of `skills/` since they're plain scripts, not multi-file skills.

## Engine

`engine/hyperframes/` is the vendored HyperFrames toolkit (reframe, graphics,
b-roll, motion, captions — an HTML-based video engine). It is updated only
via the `skills-lock.json` registry pinned version; never hand-edited.

## Presets

`presets/` holds the locked style presets (`signature-style`,
`captions-style`, `tiktok-raw-style`, `liquid-glass-style`) plus
`caption-corrections.json` for upstream brand/spelling fixes.

## Clip pipeline (long-form -> multiple short clips)

For podcast episodes or livestream VODs — paste in a long source, get N
short clips back, automatically picked around highlight/hook moments:

```
./clip_pipeline.sh <job> <format> --clip-length 60 --clip-count 5 \
  [--content-type podcast|gaming|irl] [--skip-music]
```

Transcribes the full source once, then runs the normal 7-step pipeline on
each selected window as its own sub-job (`<job>__clip01`, `<job>__clip02`,
...) — each pauses at the same second-pass review gate as any other job.
No re-transcription per clip.

`--content-type gaming` forces letterbox reframing (no crop) so
killfeed/minimap/HUD elements at the screen edges don't get cut off —
`podcast`/`irl` still center-crop by default.

## URL input (no manual download needed)

Upload accepts a link instead of a file — in the web UI, switch Source to
"YouTube / URL". Works with anything yt-dlp supports (1000+ sites:
YouTube, Twitch, TikTok, X, Instagram, Kick, direct .mp4 URLs, etc.),
not just YouTube. Downloads server-side into `projects/<job>/raw/` before
the pipeline runs. Requires `yt-dlp` (`pip install yt-dlp`, already in
`web/requirements.txt`). Private/subscriber-only/login-gated content isn't
supported without cookies — you'll get a clear error, not a hang.

## Channel auto-watch (livestream automation)

`worker/channel_watch.py` polls a channel for new videos/VODs and
auto-submits new ones to `clip_pipeline.sh` — sends new uploads straight to
clipping without you touching anything. Runs on Celery beat alongside the
GC task. Configure via env vars on the worker:

```
PIPELINE_WATCH_CHANNEL_URL=https://youtube.com/@yourchannel
PIPELINE_WATCH_FORMAT=short-tiktok-raw
PIPELINE_WATCH_CONTENT_TYPE=gaming
PIPELINE_WATCH_CLIP_LENGTH=60
PIPELINE_WATCH_CLIP_COUNT=3
PIPELINE_WATCH_INTERVAL_SECONDS=900
PIPELINE_WATCH_MAX_NEW=3
```

Tracks already-processed video IDs in `worker/.channel_watch_seen.json` so
it never reprocesses the same upload.

## Publishing (auto-upload) and download-all

Once a job is done:
- **Download all** — for clip-mode jobs (multiple clips), zips every clip
  into one download instead of grabbing them one at a time.
- **Publish to YouTube** — uploads directly from the web UI or via
  `POST /api/jobs/<job>/publish` (form fields: `platform=youtube`,
  `title`, `description`, `privacy=private|unlisted|public`, `tags`).
  Defaults to `private` so nothing goes public by accident.

One-time setup (per machine):
```
pip install google-auth-oauthlib google-api-python-client
```
1. In [Google Cloud Console](https://console.cloud.google.com): create a
   project, enable "YouTube Data API v3", create an OAuth 2.0 Client ID
   (type "Desktop app"), download the JSON.
2. Save it as `skills/publish/client_secret.json`.
3. Run once: `python3 skills/publish/youtube_auth_setup.py` — opens a
   browser to sign into the channel you want to publish to, saves a
   reusable token. No further browser interaction needed after that.

TikTok/Instagram auto-publish aren't wired up — both require going through
each platform's developer app-review process yourself before their APIs
allow posting, which only the account owner can complete.

## Web UI

```
pip install -r web/requirements.txt
uvicorn web.main:app --reload --port 8000
```

Upload a clip, pick a format, watch it run, approve the second-pass gate from
the browser, download the final output. Thin layer over `run_pipeline.sh`
and `lib/jobstate.py` — no separate state to keep in sync.

## Running a job

```
./run_pipeline.sh <job> <format>
# e.g. ./run_pipeline.sh ep42 short-tiktok-raw
```

Each step is a stub right now — wire in the real WhisperX / HyperFrames /
ffmpeg calls inside the corresponding `skills/*/run.sh`.
