# GtaxZombies Clip Studio — feature pack

One command: `studio.py`. Tiers live in `presets/studio-tiers.json` (prices match the Fiverr gig).

| Feature | Command | Tier |
|---|---|---|
| Chat-proven moments (Poisson spike test + hype words) | `studio.py signals --job J --chat LOG\|--chat-url URL` | all |
| HUD game events (kills, multi-kills, squad wipes, wins, 2K threes/and-ones) | `studio.py signals --job J --game apex\|warzone\|nba2k --player GtaxZombies` | all |
| 90%+ score report (JSON + branded HTML "why it shipped") | automatic in `run` | all |
| Hook-first cold open (payoff in first 2 s) | `studio.py hook-first CLIP OUT` | standard+ |
| Best-frame thumbnail (16:9 + 9:16 cover) + 3 titles | `studio.py thumbs CLIP DIR` | standard+ |
| Brand-safe: bleep profanity, flag likely music | `studio.py brand-safe CLIP OUT` | standard+ |
| Split-screen facecam/gameplay 9:16 | `studio.py split CLIP OUT --cam x,y,w,h` | standard+ |
| Scheduled auto-post (TikTok/YouTube/IG via publish_scheduler) | automatic in `run` | premium |
| Multi-language captions (+ burned versions) | `studio.py translate CLIP --langs es,pt --burn` | premium |
| Weekly long-form compilation + YouTube chapters | `studio.py compile OUT --from-reports DIR` | premium |
| Sponsor media kit (real stats only) | `studio.py media-kit OUT.html` | premium |
| Learning loop (per-creator view model, ±10 nudge) | `studio.py learn --reports DIR` | premium |
| Podcast active-speaker crop | `studio.py podcast CLIP OUT` | premium |

## Normal use

```
./safe_run.sh ./clip_pipeline.sh JOB short-tiktok-raw --game apex --chat https://youtube.com/live/...   # signals feed selection
python3 studio.py run outputs/<folder> --tier premium --job JOB --cam 1500,60,380,280 --compile --media-kit
```
`--game`/`--chat` on clip_pipeline.sh write `projects/JOB/rough-cut/signals.json`; clip_select.py adds up to
+30 to windows holding a proven moment and adds windows for strong moments it missed. No signals file = old behaviour.

## Limits (honest)
- HUD regions are defaults for 1080p captures; calibrate with `studio.py game-events VIDEO --game apex --dump-crops /tmp/c`.
- Twitch VOD chat replay depends on yt-dlp; if Twitch returns nothing, log chat live and pass the file.
- Music check is a heuristic for review, not Content ID.
- Titles/translation need `ANTHROPIC_API_KEY`; without it titles use transcript fallbacks (marked).
- Learning loop refuses to adjust scores until 15+ published clips have real view counts.

Tests: `python3 -m pytest tests/test_studio.py -q` (19 tests, synthetic media).
