#!/usr/bin/env python3
"""
skills/rough-cut/cut_engine.py

Transcribes the raw clip, strips filler words/dead air, and emits:
  - script.json  : the kept-segment transcript (the "script" other steps read)
  - edl.json     : edit decision list (start/end pairs to keep, in source time)

Transcription backend, in preference order:
  1. whisperx   (best word-level timestamps — what the diagram calls for)
  2. faster-whisper (good fallback, same rough interface)
  3. none available -> pass-through mode: no cuts are made, a single segment
     spanning the whole file is kept, and script.json is flagged
     "transcription_unavailable" so downstream steps and the human reviewer
     know rough-cut didn't actually do filler removal.

Filler-word pass is a simple heuristic on the transcript text, not audio
analysis — good enough for a rough cut, the second-pass (manual) step is
where a human catches what this misses.
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "lib"))
import progress as progress_mod  # noqa: E402

FILLER_WORDS = {
    "um", "umm", "uh", "uhh", "erm", "hm", "hmm",
    "like", "you know", "i mean", "kind of", "sort of", "basically",
    "actually", "literally", "so yeah", "right?",
}

MIN_SEGMENT_SEC = 0.15  # drop segments shorter than this after filler-stripping


def ffprobe_duration(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


WHISPER_MODEL = os.environ.get("PIPELINE_WHISPER_MODEL", "small")
# defaults balance speed/accuracy; override with PIPELINE_WHISPER_MODEL=tiny
# or =base for a big speed jump on CPU-only machines (much faster, some
# accuracy loss). "small" is the previous default, kept unless overridden.

MODEL_LOAD_TIMEOUT_SEC = int(os.environ.get("PIPELINE_MODEL_LOAD_TIMEOUT", 180))
# hard timeout on model load/download — direct fix for a real failure: a
# stalled network connection during a first-time model download left the
# process hanging with zero progress or error for over an hour. Python
# threads can't be force-killed, so this can't reclaim the stuck network
# call itself, but it DOES let the process detect the stall and exit with
# a clear diagnosis instead of hanging silently forever.


def _load_with_timeout(loader_fn, timeout_sec=MODEL_LOAD_TIMEOUT_SEC):
    import threading
    result = {}

    def _run():
        try:
            result["value"] = loader_fn()
        except Exception as e:
            result["error"] = e

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout_sec)
    if t.is_alive():
        raise TimeoutError(
            f"model load/download stalled past {timeout_sec}s with no progress "
            f"(likely a network hang, not a code bug) — check "
            f"~/.cache/huggingface/hub for a partial/broken download and "
            f"consider deleting it, or retry on a better connection"
        )
    if "error" in result:
        raise result["error"]
    return result["value"]


def _first_item_with_timeout(iterator, timeout_sec):
    """Same timeout-detection pattern as _load_with_timeout, applied to
    pulling the FIRST item out of a lazy generator — this is where the
    real gap was tonight. faster-whisper's transcribe() returns instantly
    (it's lazy), so a stall during VAD's full-file scan or other setup
    work happens the moment we try to iterate, which is BEFORE the
    per-segment checkpoint loop ever starts. Confirmed via real evidence
    tonight: a 129-minute stuck run had genuinely zero checkpoints,
    because it never got past fetching item #1."""
    import threading
    result = {}
    sentinel = object()

    def _run():
        try:
            result["value"] = next(iterator, sentinel)
        except Exception as e:
            result["error"] = e

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout_sec)
    if t.is_alive():
        raise TimeoutError(
            f"first segment stalled past {timeout_sec}s with no progress — "
            f"this happens during VAD/setup, BEFORE any transcript data "
            f"exists, so nothing is recoverable from this attempt; likely "
            f"the same network hang pattern seen repeatedly tonight "
            f"(confirmed via CLOSE_WAIT TCP connections + OpenMP worker "
            f"threads parked at a barrier, real evidence, not a guess)"
        )
    if "error" in result:
        raise result["error"]
    return result["value"], sentinel


def try_whisperx(audio_path, job=None, duration=None):
    try:
        import whisperx  # noqa: F401
    except ImportError:
        return None
    import whisperx
    if job:
        progress_mod.report(job, "transcribing", 0, "loading model")
    model = _load_with_timeout(lambda: whisperx.load_model(WHISPER_MODEL, device="cpu", compute_type="int8"))
    result = model.transcribe(audio_path, batch_size=16)
    # whisperx doesn't stream segments — no incremental progress possible here,
    # but we can still mark the phase so the tracker shows *something* moving
    if job:
        progress_mod.report(job, "transcribing", 50, "whisperx transcribing (no incremental progress available)")
    segments = [
        {"start": s["start"], "end": s["end"], "text": s["text"].strip()}
        for s in result["segments"]
    ]
    return segments


def try_faster_whisper(audio_path, job=None, duration=None, work_dir=None):
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        return None

    # Real fix, direct response to a genuine 2-hour loss tonight: a
    # network-related mid-transcription hang (same CLOSE_WAIT signature
    # as the earlier model-load hang, but this time deep into a long
    # file — likely VAD's own lazy-loaded component) meant killing a
    # stuck process threw away the ENTIRE transcript, since nothing was
    # ever saved until the very end. Now: partial progress checkpoints
    # to disk periodically, and a killed/restarted run picks up from the
    # last checkpoint instead of starting over. Resume is done by
    # physically trimming the audio with ffmpeg (proven, tested
    # extensively tonight) rather than relying on faster-whisper's
    # clip_timestamps parameter, whose exact accepted format I can't
    # verify without the library installed here — this is high-stakes
    # enough not to ship an unverified guess.
    checkpoint_path = os.path.join(work_dir, "transcript_checkpoint.json") if work_dir else None
    resume_from = 0.0
    existing_segments = []
    if checkpoint_path and os.path.exists(checkpoint_path):
        try:
            with open(checkpoint_path) as f:
                cp = json.load(f)
            existing_segments = cp.get("segments", [])
            if existing_segments:
                resume_from = max(s["end"] for s in existing_segments)
                if job:
                    progress_mod.report(job, "transcribing", 0,
                                         f"resuming from checkpoint at {resume_from/60:.0f} min (found {len(existing_segments)} already-transcribed segments)")
        except Exception:
            existing_segments = []
            resume_from = 0.0

    transcribe_audio_path = audio_path
    if resume_from > 0 and work_dir:
        trimmed_path = os.path.join(work_dir, "audio_resume.wav")
        try:
            subprocess.run(
                ["ffmpeg", "-nostdin", "-y", "-i", audio_path, "-ss", str(resume_from),
                 "-c", "copy", trimmed_path, "-loglevel", "error"],
                check=True, capture_output=True, text=True,
            )
            transcribe_audio_path = trimmed_path
        except subprocess.CalledProcessError:
            resume_from = 0.0  # trim failed for any reason — fall back to processing the whole file rather than silently losing audio

    if job:
        progress_mod.report(job, "transcribing", 0, "loading model")
    cpu_count = os.cpu_count() or 4
    model = _load_with_timeout(lambda: WhisperModel(
        WHISPER_MODEL, device="cpu", compute_type="int8",
        cpu_threads=cpu_count,  # was using library default (often just 4)
    ))
    seg_iter, info = model.transcribe(
        transcribe_audio_path,
        vad_filter=True,   # skips silence/dead-air — speed win with no
                            # quality cost, doesn't touch actual speech
        word_timestamps=True,  # per-word timing, for karaoke-style
                                # animated captions instead of whole-
                                # segment burn-in
    )
    total = duration or getattr(info, "duration", None) or 0

    segments = list(existing_segments)  # start from whatever survived a previous attempt
    last_report = [0]
    last_checkpoint = [0]

    def process_segment(s):
        # timestamps from a trimmed resume file are relative to the trim
        # point, not the original audio — offset them back
        words = []
        if getattr(s, "words", None):
            words = [{"start": w.start + resume_from, "end": w.end + resume_from,
                      "word": w.word} for w in s.words]
        segments.append({"start": s.start + resume_from, "end": s.end + resume_from,
                          "text": s.text.strip(), "words": words})
        now = __import__("time").time()
        if job and total:
            if now - last_report[0] > 2:  # throttle progress writes to every ~2s, not every segment
                pct = min(99.0, ((s.end + resume_from) / total) * 100)
                mins_done = (s.end + resume_from) / 60
                mins_total = total / 60
                progress_mod.report(
                    job, "transcribing", round(pct, 1),
                    f"{mins_done:.0f} of {mins_total:.0f} min transcribed",
                )
                last_report[0] = now
        if checkpoint_path and (now - last_checkpoint[0] > 30):  # checkpoint every ~30s of wall time
            try:
                with open(checkpoint_path + ".tmp", "w") as f:
                    json.dump({"segments": segments}, f)
                os.replace(checkpoint_path + ".tmp", checkpoint_path)
            except Exception as e:
                # Real bug fixed: this used to swallow ALL checkpoint
                # write failures completely silently — a 150-minute real
                # run hit a stall with ZERO checkpoint data saved, and
                # there was no error anywhere to explain why. Still
                # best-effort (a checkpoint failure must never break real
                # transcription), but now it's visible via progress.json
                # instead of vanishing without a trace.
                if job:
                    progress_mod.report(job, "transcribing", None,
                                         f"WARNING: checkpoint write failed ({type(e).__name__}: {e}) — progress since last successful checkpoint is NOT protected")
            last_checkpoint[0] = now

    # Real, critical gap closed: a hang during VAD's full-file scan (or
    # any other setup work) happens the moment we try to pull the FIRST
    # item from this lazy generator — BEFORE the per-segment checkpoint
    # loop below ever runs even once. Confirmed with real evidence
    # tonight: a 129-minute stuck run had genuinely zero checkpoints,
    # because it never got past this exact point. This wraps ONLY the
    # first fetch in a timeout (subsequent segments are typically much
    # faster once the initial setup succeeds, and are already protected
    # by the per-segment checkpointing below).
    first_segment_timeout = int(os.environ.get("PIPELINE_FIRST_SEGMENT_TIMEOUT_SEC", 600))
    first_item, sentinel = _first_item_with_timeout(seg_iter, first_segment_timeout)
    if first_item is not sentinel:
        process_segment(first_item)
    for s in seg_iter:
        process_segment(s)
    if job:
        progress_mod.report(job, "transcribing", 100, "transcription complete")
    if checkpoint_path and os.path.exists(checkpoint_path):
        os.remove(checkpoint_path)  # only needed while a run is genuinely mid-flight
    return segments


def is_filler(text):
    stripped = text.strip().lower().strip(".,!?")
    if not stripped:
        return True
    if stripped in FILLER_WORDS:
        return True
    # a segment that's ONLY filler words (e.g. "um, like")
    words = [w.strip(".,!?") for w in stripped.split()]
    return len(words) > 0 and all(w in FILLER_WORDS for w in words)


def build_edl(segments):
    """Keep non-filler segments, dropping ones too short to matter."""
    kept, cut = [], []
    for seg in segments:
        dur = seg["end"] - seg["start"]
        if is_filler(seg["text"]) or dur < MIN_SEGMENT_SEC:
            cut.append(seg)
        else:
            kept.append(seg)
    return kept, cut


MIN_RENDER_BATCH = 3    # kept for the self-heal fallback path below


def _select_expr(segments):
    return "+".join(f"between(t\\,{s['start']}\\,{s['end']})" for s in segments)


def _render_batch_select(raw_video, segments, out_path):
    """Old approach — kept ONLY as a fallback for the rare case where
    per-segment seeking (below) somehow fails on a given segment. NOT used
    as the primary path anymore: measured ~30x slower on a real 1080p
    H.264 file for a segment near the end of a 120s clip, because select
    forces ffmpeg to decode the ENTIRE source to reach that point rather
    than seeking to it. For a multi-hour source with many batches, that
    meant decoding the full video dozens of times over — the real cause
    of "rendering_cut" taking far longer than it should have."""
    expr = _select_expr(segments)
    vf = f"select='{expr}',setpts=N/FRAME_RATE/TB"
    af = f"aselect='{expr}',asetpts=N/SR/TB"
    cmd = ["ffmpeg", "-nostdin", "-y", "-i", raw_video,
           "-vf", vf, "-af", af,
           "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac",
           out_path]

    if len(segments) <= MIN_RENDER_BATCH:
        subprocess.run(cmd, check=True)
        return

    result = subprocess.run(cmd, capture_output=True)
    if result.returncode == 0:
        return

    mid = len(segments) // 2
    left, right = segments[:mid], segments[mid:]
    left_path = out_path + ".left.mp4"
    right_path = out_path + ".right.mp4"
    _render_batch_select(raw_video, left, left_path)
    _render_batch_select(raw_video, right, right_path)

    concat_list = out_path + ".concat.txt"
    with open(concat_list, "w") as f:
        f.write(f"file '{left_path}'\nfile '{right_path}'\n")
    subprocess.run(
        ["ffmpeg", "-nostdin", "-y", "-f", "concat", "-safe", "0", "-i", concat_list,
         "-c", "copy", out_path],
        check=True,
    )
    for p in (left_path, right_path, concat_list):
        if os.path.exists(p):
            os.remove(p)


def _output_is_valid(path, expected_duration, tolerance=0.5):
    """Verifies an extracted segment actually has content — ffmpeg can
    exit 0 while still producing an empty file (observed: 'Output file is
    empty' when a fixed pre-roll seek margin undershoots/overshoots the
    source's actual keyframe interval, which varies by encode and isn't
    knowable in advance)."""
    if not os.path.exists(path) or os.path.getsize(path) < 100:
        return False
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True,
    )
    try:
        actual = float(result.stdout.strip())
    except ValueError:
        return False
    return abs(actual - expected_duration) <= tolerance


def _extract_segment(raw_video, start, end, out_path):
    """Seeks directly to the segment instead of scanning from the start —
    the actual fix. -ss before -i is a fast keyframe seek; a pre-roll plus
    a second -ss after -i (frame-accurate within that pre-roll window)
    keeps cut points accurate without paying the full-scan cost.

    The pre-roll margin isn't a fixed value — a source's keyframe interval
    varies by encode and can't be known in advance, and a margin smaller
    than that interval can cause the coarse seek to overshoot the target
    entirely, silently producing an empty file even though ffmpeg exits 0
    (a real failure mode hit and fixed here, not theoretical). So: verify
    the output, and retry with a larger margin if it's not right, before
    falling back to the slower whole-file select method as a last resort."""
    duration = end - start
    for margin in (2.0, 8.0, 20.0, 60.0):
        coarse = max(0.0, start - margin)
        fine_offset = start - coarse
        cmd = ["ffmpeg", "-nostdin", "-y",
               "-ss", f"{coarse:.3f}", "-i", raw_video,
               "-ss", f"{fine_offset:.3f}", "-t", f"{duration:.3f}",
               "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac",
               out_path]
        subprocess.run(cmd, capture_output=True)
        if _output_is_valid(out_path, duration):
            return

    # every margin failed — fall back to the old whole-file select approach
    # for just this one segment (slow, but correct; self-healing beats a
    # hard failure on what's hopefully a rare edge case)
    _render_batch_select(raw_video, [{"start": start, "end": end}], out_path)


def render_cut(raw_video, kept_segments, out_path, work_dir, job=None):
    """Extracts each kept segment via direct seek (fast — only decodes
    that segment's own duration, not the whole source), then concatenates
    via stream copy (no re-encode on the concat step)."""
    if not kept_segments:
        subprocess.run(["ffmpeg", "-nostdin", "-y", "-i", raw_video, "-c", "copy", out_path], check=True)
        return

    os.makedirs(work_dir, exist_ok=True)
    total_kept = sum(s["end"] - s["start"] for s in kept_segments)
    cumulative = 0.0
    part_files = []

    for i, seg in enumerate(kept_segments):
        part_path = os.path.join(work_dir, f"part_{i:05d}.mp4")
        _extract_segment(raw_video, seg["start"], seg["end"], part_path)
        part_files.append(part_path)
        cumulative += seg["end"] - seg["start"]
        if job and total_kept:
            pct = min(99.5, (cumulative / total_kept) * 100)
            progress_mod.report(
                job, "rendering_cut", round(pct, 1),
                f"segment {i+1} of {len(kept_segments)}",
            )

    concat_list = os.path.join(work_dir, "parts.txt")
    with open(concat_list, "w") as f:
        for p in part_files:
            f.write(f"file '{p}'\n")
    subprocess.run(
        ["ffmpeg", "-nostdin", "-y", "-f", "concat", "-safe", "0", "-i", concat_list,
         "-c", "copy", out_path],
        check=True,
    )
    for p in part_files:
        os.remove(p)
    os.remove(concat_list)
    if job:
        progress_mod.report(job, "rendering_cut", 100, "render complete")


def main():
    job, raw_video, audio_path, out_dir, work_dir = sys.argv[1:6]
    os.makedirs(out_dir, exist_ok=True)
    # Real, critical bug fixed: work_dir was never created before
    # transcription started — only render_cut() created it, AFTER
    # transcription finished. This meant every checkpoint write attempt
    # during a multi-hour transcription failed silently (caught by the
    # deliberately-permissive except-and-continue around checkpointing),
    # so the whole point of checkpointing — surviving a mid-transcription
    # stall — never actually worked. Confirmed directly: a real 150-minute
    # run hit the exact same network stall as before and had ZERO
    # checkpoint data to show for it.
    os.makedirs(work_dir, exist_ok=True)

    duration = ffprobe_duration(raw_video)

    segments = try_whisperx(audio_path, job=job, duration=duration) \
        or try_faster_whisper(audio_path, job=job, duration=duration, work_dir=work_dir)
    transcription_available = segments is not None
    if segments is None:
        segments = [{"start": 0.0, "end": duration, "text": ""}]

    kept, cut = build_edl(segments)

    progress_mod.report(job, "rendering_cut", None, f"rendering {len(kept)} kept segments")
    render_cut(raw_video, kept if transcription_available else [], os.path.join(out_dir, "rough_cut.mp4"), work_dir, job=job)

    script_text = " ".join(s["text"] for s in kept if s["text"]).strip()
    script = {
        "job": job,
        "transcription_available": transcription_available,
        "source_duration_sec": duration,
        "kept_segments": kept,
        "cut_segments": cut,
        "script_text": script_text,
    }
    if not transcription_available:
        script["note"] = (
            "no transcription backend (whisperx/faster-whisper) installed — "
            "rough_cut.mp4 is a pass-through copy, no filler removal was performed"
        )

    with open(os.path.join(out_dir, "script.json"), "w") as f:
        json.dump(script, f, indent=2)

    edl = {
        "job": job,
        "keep": [[s["start"], s["end"]] for s in kept],
        "cut": [[s["start"], s["end"]] for s in cut],
    }
    with open(os.path.join(out_dir, "edl.json"), "w") as f:
        json.dump(edl, f, indent=2)

    print(json.dumps({
        "transcription_available": transcription_available,
        "kept_segments": len(kept),
        "cut_segments": len(cut),
        "script_chars": len(script_text),
    }))


if __name__ == "__main__":
    main()
