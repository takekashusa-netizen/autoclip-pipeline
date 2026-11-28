# TakeKash Motion Studio

In-house character video engine. It takes a character sheet and a hero image and produces a narrated 9:16 brand video. Nothing at render time depends on an outside company.

## One command
```
python3 motion.py make kash_sheet.png kash_poster.png --preset presets/kash.json
# -> motion_work/out/kash_tour.mp4
```

## Steps (run separately to tweak)
| Step | Command | What it does |
|---|---|---|
| Assets | `motion.py assets SHEET.png` | Cuts each pose/head out of the sheet (transparent or white background) and upscales it 4x with our own torch-free Real-ESRGAN (anime) runner |
| Poster | `motion.py poster ART.png` | 2x-upscales the hero art for the opening/closing shots and builds a dark "stage" plate with the character removed |
| Voice | `motion.py voice` | The King narration from the preset's `lines` (Kokoro, deep blended voice, -2.5 semitones). Brand names are respelled for pronunciation only |
| Score | `motion.py score` | Taiko and koto score, rain, thunder and sword hits, with the voice mixed in and the music ducked under it |
| Preview | `motion.py preview` | 10 frames in one image to check framing before a full render |
| Render | `motion.py render` | Two parallel halves, joined with -c copy, sound added |

## New character or new script
- New character: copy `presets/kash.json`, then change `boxes` (pixel crops on the sheet) and `erase` (fractional rects to clean neighbour slivers). Without a preset, `assets` auto-splits by connected parts (`part01`, `part02`...).
- New script: edit `lines`. The timeline rebuilds itself from the real voice durations, and the slash lands near the end of the `clips` line.

## Why it's built this way (own-the-stack rule)
- PyTorch and Hugging Face downloads were blocked, so the upscaler loads the `.pth` weights with a tiny unpickler and rebuilds the network as ONNX. It runs on onnxruntime only.
- Models come from GitHub releases once, are size-checked, and are cached in `motion_work/models`.
- Character art, voice and renders stay in `motion_work/` (git-ignored), because this repo is public.

## Licences
Kokoro voice model: Apache-2.0. Real-ESRGAN weights: BSD-3. Poppins and JetBrains Mono: OFL (included in `studio/motion/fonts`).

## Brand ads (internal use: our own promos)
`python3 studio/motion/brandad.py brief.json OUT_DIR` turns a brand's reply (link, logo, goal) into a finished
9:16 ad with voice-over, captions and a beat in ~30 seconds. Brief fields: brand, headline, 3 benefits,
goal (buy/follow/book/download), url, colors {primary, accent, bg}, optional logo/product PNGs (relative to the
brief), voice (female/male/king), watermark (default on: "Made by TakeKash" for the free tier).
No logo or product? It builds a clean brand card in their colours.

## KASH episode 2 — "Your first ad is on us"
`studio/motion/freead.py <vo_dir> <out_dir> [lo hi]` + `freead_score.py` (katana split-reveal, hanko stamps,
phone that builds an ad, NO CARD slam + 48H counter, enso CTA).
