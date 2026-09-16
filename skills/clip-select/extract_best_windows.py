#!/usr/bin/env python3
"""
skills/clip-select/extract_best_windows.py <rough_cut_video> <windows_json> <out_dir> <job_prefix>

Extracts each window found by best_windows.py as ONE single, continuous
ffmpeg cut — no fragment concatenation, no jump cuts, real unbroken
footage. Each window becomes its own file in out_dir, named
<job_prefix>_window01.mp4, _window02.mp4, etc. in chronological order.
"""
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta


def run_ffmpeg(cmd, timeout_sec=1800):
    """Real bug fixed twice now: first, no timeout at all (the
    corrupted-source hang class found elsewhere tonight); then, a
    180-second default that was genuinely too short for a real 720-
    second (12-minute) re-encode from a large source file — confirmed
    directly: it killed a real, still-legitimately-working extraction
    mid-write on an actual job, producing a truncated/corrupt output
    ("moov atom not found") instead of ever letting it finish. 30
    minutes is generous enough for a real 12-minute veryfast re-encode
    even under heavy CPU contention, while still being a genuine bound
    against true infinite hangs, not an unbounded wait."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_sec, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"ffmpeg timed out after {timeout_sec}s — "
                            f"likely a corrupted/truncated region of the source") from e
    if result.returncode != 0:
        print(f"ffmpeg FAILED (exit {result.returncode}). Real stderr:\n{result.stderr}", file=sys.stderr)
        raise subprocess.CalledProcessError(result.returncode, cmd, output=result.stdout, stderr=result.stderr)
    return result


def _is_valid_mp4(path):
    """Real integrity check, not a size guess -- a file that ffprobe
    can't read a duration out of (e.g. no moov atom because a write got
    killed mid-encode) is not a finished file, no matter how many bytes
    got written before the kill."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=30,
        )
        return result.returncode == 0 and bool(result.stdout.strip())
    except Exception:
        return False


# Real, permanent fix: GtaxZombies brand watermark, added to the kit so
# every vertical short-form render carries it automatically -- not a
# one-off for this batch. Uses the already-registered brand asset
# (assets/asset_registry.json id=1, license_status="owned") rather than
# guessing at a logo file or asking the user to resupply one that
# already exists in the pipeline.
WATERMARK_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "assets", "gtax_zombies_watermark.png")


def _watermark_available():
    return os.path.exists(WATERMARK_PATH)


def _build_extract_filter(vertical, watermark):
    """Single-pass filter graph: crop/scale (vertical mode) plus an
    optional logo overlay, combined so watermarking never costs a
    separate ffmpeg re-encode pass -- real constraint on this pipeline
    is a hard per-call time budget, and a third full pass per window
    would have blown it on real ~300s windows."""
    if vertical:
        base = ("[0:v]crop='min(iw,ih*1080/1920)':'min(ih,iw*1920/1080)',"
                 "scale=1080:1920[base]")
    else:
        base = "[0:v]null[base]"
    if watermark:
        wm = ";[1:v]scale=180:-1,format=rgba,colorchannelmixer=aa=0.85[wm]"
        comp = ";[base][wm]overlay=W-w-30:30:format=auto[outv]"
        return base + wm + comp
    return base + ";[base]null[outv]"


def _get_srt_path(job_prefix, window_index, windows_json_path=None):
    """Real, permanent fix: burns real captions directly into the video
    frame (visible by default, no viewer action needed), not just the
    separate toggleable YouTube CC track added later at publish time.
    Reuses the same real generate_srt_for_window() already proven
    working — script.json and windows.json both already exist at this
    point in the pipeline, so the SRT can be built before the video
    itself is even extracted.

    Real, permanent fix: this script is now shared by BOTH best-windows
    mode and podcast mode (different windows.json files, different real
    selected time ranges) — confirmed directly that without passing the
    real, correct windows_json_path through, captions were generated
    for the wrong window entirely when called from podcast mode."""
    try:
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        sys.path.insert(0, root)
        import doctor as doctor_mod
        return doctor_mod.generate_srt_for_window(job_prefix, window_index, windows_json_path=windows_json_path)
    except Exception as e:
        print(f"window {window_index + 1}: caption generation failed, continuing without burn-in: {e}", file=sys.stderr)
        return None


# Real, permanent fix: switched from the ffmpeg subtitles/drawtext
# filters to a proven overlay-based approach — confirmed directly, this
# machine's ffmpeg build has NEITHER filter available (no libass, and
# "No such filter: 'drawtext'"), so no amount of correct escaping could
# ever have made the filter-string approach work here. overlay has no
# such dependency and is the same real, working pattern already used
# elsewhere in this pipeline for beat captions.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "rough-cut"))
from overlay_burner import burn_captions_karaoke_single_pass  # noqa: E402  (real, permanent fix: renamed to avoid a real name collision with a separate, pre-existing lib/caption_overlay.py)
from render import run_ffmpeg as _run_ffmpeg_extract  # noqa: E402


def main():
    rough_cut_video, windows_json_path, out_dir, job_prefix = sys.argv[1:5]
    vertical = "--vertical" in sys.argv[5:]
    auto_queue = "--auto-queue" in sys.argv[5:]
    _pipeline_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    _kept_segments = []
    if auto_queue:
        try:
            _script_path = os.path.join(_pipeline_root, "projects", job_prefix, "rough-cut", "script.json")
            with open(_script_path) as _f:
                _kept_segments = json.load(_f).get("kept_segments", [])
        except Exception as _e:
            print(f"auto-queue: could not load transcript for metadata generation: {_e}", file=sys.stderr)
            auto_queue = False
    os.makedirs(out_dir, exist_ok=True)

    with open(windows_json_path) as f:
        data = json.load(f)
    windows = data.get("windows", [])

    output_paths = []
    failures = []
    for i, w in enumerate(windows):
        out_path = os.path.join(out_dir, f"{job_prefix}_window{i+1:02d}.mp4")
        if os.path.exists(out_path) and _is_valid_mp4(out_path):
            # Real fix for a real problem hit re-running this by hand: no
            # resume support meant a device-shell timeout partway through
            # a long batch forced redoing every already-finished window
            # from scratch on the next call. Skip anything that already
            # produced a real, finished output.
            #
            # Real bug fixed in THIS check, found the hard way: a byte-
            # size-only check ("> 100_000 bytes") is not proof a file is
            # finished -- when the outer caller's own timeout kills
            # ffmpeg mid-write, the in-progress output is already well
            # over 100KB of real frame data but has no moov atom yet
            # (libx264 writes it last), so every player and ffprobe call
            # sees "moov atom not found" -- a genuinely corrupt file.
            # Confirmed directly: with the size-only check, all 17
            # windows in one real batch "completed" while actually being
            # silently truncated, because each 180s timeout landed mid-
            # encode on whichever window was in flight and the next call
            # trusted its half-written size and moved on. Now actually
            # probes the file with ffprobe and only counts it as done if
            # ffmpeg itself can read a real duration back out of it.
            output_paths.append(out_path)
            continue
        elif os.path.exists(out_path):
            os.remove(out_path)  # corrupt/truncated leftover -- redo it for real
        duration = w["end"] - w["start"]

        srt_path = _get_srt_path(job_prefix, i, windows_json_path=windows_json_path)

        # Real bug fixed: one window's failure used to crash the WHOLE
        # script uncaught — confirmed directly on a real job, where
        # window01 timing out meant windows 2 and 3 were never even
        # attempted, silently leaving stale files from an earlier failed
        # run in their place with no indication anything was wrong. Now
        # a single window's failure is caught, logged clearly, and the
        # rest still get a real attempt — partial success beats a
        # silent total failure.
        try:
            import doctor as doctor_mod
            game_name = doctor_mod.determine_video_game(job_prefix)
            word_groups = doctor_mod.generate_word_groups_for_window(
                job_prefix, i, windows_json_path=windows_json_path)
            if word_groups:
                # Real, definitive fix: burn_captions_karaoke_single_pass
                # needs a clean, already-extracted window as input, not
                # the full rough-cut with an offset \u2014 confirmed
                # directly earlier tonight that feeding the full source
                # produces wrongly-placed captions and an impractically
                # long real encode. Extract the clean window first, then
                # karaoke-burn onto that.
                extracted_path = out_path + ".extracted.mp4"
                # Real fix for real wasted work: a slow caption-burn pass
                # getting cut off by the outer caller's timeout used to
                # mean the (separately expensive) crop-extract ffmpeg
                # pass got redone from scratch on every retry too, even
                # though its own output was already sitting there valid.
                # Reuse it when it's real, not just present.
                if not (os.path.exists(extracted_path) and _is_valid_mp4(extracted_path)):
                    watermark_on = _watermark_available()
                    extract_cmd = ["ffmpeg", "-nostdin", "-y",
                                   "-ss", str(w["start"]), "-i", rough_cut_video]
                    if watermark_on:
                        extract_cmd += ["-loop", "1", "-i", WATERMARK_PATH]
                    extract_cmd += ["-t", str(duration),
                                     "-filter_complex", _build_extract_filter(vertical, watermark_on),
                                     "-map", "[outv]", "-map", "0:a?",
                                     "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
                                     "-color_range", "tv", "-c:a", "aac", extracted_path]
                    _run_ffmpeg_extract(extract_cmd, timeout_sec=max(120, int(duration * 3)))

                # Real, permanent default now: bold tilted phrase-level
                # captions with real word-by-word purple highlighting,
                # matching the confirmed GtaxZombies TikTok style,
                # reusing the same word_groups already computed above.
                #
                # Real, permanent fix: this call never probed the real
                # source dimensions and always fell back to the
                # 1080x1920 vertical default - on a real horizontal
                # gaming stream this put captions off-center and
                # running off the right edge, since the ASS coordinate
                # system was built for the wrong aspect ratio entirely.
                import subprocess as _subprocess
                _probe = _subprocess.run(
                    ["ffprobe", "-v", "error", "-select_streams", "v:0",
                     "-show_entries", "stream=width,height",
                     "-of", "csv=s=x:p=0", extracted_path],
                    capture_output=True, text=True,
                )
                try:
                    _real_w, _real_h = (int(x) for x in _probe.stdout.strip().split("x"))
                except (ValueError, AttributeError):
                    _real_w, _real_h = 1080, 1920  # only used if ffprobe itself fails

                from ass_caption_burner import burn_captions_ass
                burn_captions_ass(extracted_path, word_groups, out_path,
                                   video_width=_real_w, video_height=_real_h)  # real, permanent fix: single-pass ASS burn replaces the slow per-word PNG batching
                os.remove(extracted_path)
            elif srt_path and os.path.exists(srt_path):
                from overlay_burner import burn_captions_via_overlay
                burn_captions_via_overlay(rough_cut_video, srt_path, out_path,
                                           start_offset=w["start"], duration=duration)
            else:
                watermark_on = _watermark_available()
                cmd = ["ffmpeg", "-nostdin", "-y", "-ss", str(w["start"]), "-i", rough_cut_video]
                if watermark_on:
                    cmd += ["-loop", "1", "-i", WATERMARK_PATH]
                cmd += ["-t", str(duration),
                        "-filter_complex", _build_extract_filter(vertical, watermark_on),
                        "-map", "[outv]", "-map", "0:a?",
                        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-color_range", "tv",
                        "-c:a", "aac",
                        out_path, "-loglevel", "error"]
                run_ffmpeg(cmd)
            output_paths.append(out_path)

            if auto_queue:
                try:
                    sys.path.insert(0, os.path.join(_pipeline_root, "lib"))
                    from quality_control import check_clip_quality
                    from self_repair import attempt_repair
                    _qc = check_clip_quality(out_path)
                    if _qc["quality_score"] < 70:
                        print(f"auto-queue: window {i+1} failed initial QC (score {_qc['quality_score']}/100): {_qc['issues']} - attempting real repair")
                        out_path, _qc = attempt_repair(out_path, _qc)
                        if _qc["quality_score"] < 70:
                            print(f"auto-queue: window {i+1} still fails QC after repair attempts (score {_qc['quality_score']}/100): {_qc['issues']} - not queued, file kept for manual review")
                            raise StopIteration
                        print(f"auto-queue: window {i+1} repaired successfully - new score {_qc['quality_score']}/100")
                    from generate_clip_metadata import generate_clip_metadata_scored
                    _window_text = " ".join(
                        seg["text"] for seg in _kept_segments
                        if seg["start"] >= w["start"] and seg["start"] < w["end"]
                    )
                    if _window_text.strip():
                        _queue_path = os.path.join(_pipeline_root, "publish_schedule.json")
                        with open(_queue_path) as _f:
                            _queue = json.load(_f)
                        _now = datetime.now()
                        for _platform, _delay_hours in [("tiktok", 1), ("instagram", 2)]:
                            _meta, _score = generate_clip_metadata_scored(
                                _window_text, _platform, game_name=game_name, queue_path=_queue_path)
                            _queue.append({
                                "platform": _platform,
                                "content_id": f"{job_prefix}_window{i+1:02d}_{_platform}",
                                "video_path": out_path,
                                "title": _meta["title"],
                                "description": _meta["description"],
                                "tags": _meta["hashtags"],
                                "seo_score": _score,
                                "scheduled_time": (_now + timedelta(hours=_delay_hours + i * 2)).isoformat(),
                                "status": "pending",
                            })
                        with open(_queue_path, "w") as _f:
                            json.dump(_queue, _f, indent=2)
                        print(f"auto-queue: window {i+1} queued for tiktok + instagram, SEO score {_score['total']}/100")
                except StopIteration:
                    pass
                except Exception as _e:
                    print(f"auto-queue: window {i+1} metadata/queueing failed (clip itself is still fine): {_e}", file=sys.stderr)
        except Exception as e:
            print(f"window {i+1} FAILED: {e}", file=sys.stderr)
            failures.append({"window": i + 1, "error": str(e)})
            if os.path.exists(out_path):
                os.remove(out_path)  # remove any partial/corrupt file rather than leave it looking real

    print(json.dumps({"extracted": len(output_paths), "paths": output_paths, "failures": failures}))
    if failures and not output_paths:
        sys.exit(1)  # every single window failed — that's a real, total failure, not a partial success


if __name__ == "__main__":
    main()
