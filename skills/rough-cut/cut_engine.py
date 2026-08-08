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


def try_whisperx(audio_path):
    try:
        import whisperx  # noqa: F401
    except ImportError:
        return None
    import whisperx
    model = whisperx.load_model(WHISPER_MODEL, device="cpu", compute_type="int8")
    result = model.transcribe(audio_path, batch_size=16)
    segments = [
        {"start": s["start"], "end": s["end"], "text": s["text"].strip()}
        for s in result["segments"]
    ]
    return segments


def try_faster_whisper(audio_path):
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        return None
    cpu_count = os.cpu_count() or 4
    model = WhisperModel(
        WHISPER_MODEL, device="cpu", compute_type="int8",
        cpu_threads=cpu_count,  # was using library default (often just 4)
    )
    segs, _ = model.transcribe(
        audio_path,
        vad_filter=True,   # skips silence/dead-air — speed win with no
                            # quality cost, doesn't touch actual speech
    )
    return [{"start": s.start, "end": s.end, "text": s.text.strip()} for s in segs]


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


SELECT_BATCH_SIZE = 40  # bounds filter-string length / memory on long transcripts.
                         # Lowered from 300 after a real failure: ffmpeg on some
                         # platforms/builds hard-errors on very long select
                         # boolean expressions well before hitting memory
                         # limits (observed failure around ~50 terms on one
                         # macOS ffmpeg build). Combined with the retry-by-
                         # splitting fallback below, this doesn't need to be
                         # exactly right for every platform — just small
                         # enough to rarely trigger the fallback path.
MIN_RENDER_BATCH = 3    # stop splitting once a batch is this small; if it
                         # still fails at this size, something else is wrong
                         # and we should surface the real error


def _select_expr(segments):
    return "+".join(f"between(t\\,{s['start']}\\,{s['end']})" for s in segments)


def _render_batch(raw_video, segments, out_path):
    """O(1) filter-graph nodes regardless of segment count — select/aselect
    evaluate one boolean expression per frame instead of building a trim
    node per segment (which doesn't scale on long-form video). Self-heals
    on failure: some ffmpeg builds hard-error on very long select
    expressions for reasons that don't show up as a clean, parseable error
    (platform/build-specific internal limits) — rather than guessing the
    exact threshold, split the batch in half and retry on any failure."""
    expr = _select_expr(segments)
    vf = f"select='{expr}',setpts=N/FRAME_RATE/TB"
    af = f"aselect='{expr}',asetpts=N/SR/TB"
    cmd = ["ffmpeg", "-nostdin", "-y", "-i", raw_video,
           "-vf", vf, "-af", af,
           "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac",
           out_path]

    if len(segments) <= MIN_RENDER_BATCH:
        subprocess.run(cmd, check=True)  # base case — let real errors surface
        return

    result = subprocess.run(cmd, capture_output=True)
    if result.returncode == 0:
        return

    # failed — split this batch in half and retry each half, then concat
    mid = len(segments) // 2
    left, right = segments[:mid], segments[mid:]
    left_path = out_path + ".left.mp4"
    right_path = out_path + ".right.mp4"
    _render_batch(raw_video, left, left_path)
    _render_batch(raw_video, right, right_path)

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


def render_cut(raw_video, kept_segments, out_path, work_dir):
    """Trim + concat kept segments. Batches into groups of
    SELECT_BATCH_SIZE, then stream-copy-concats the batches (no re-encode
    on the concat step, no leftover batch files once done)."""
    if not kept_segments:
        subprocess.run(["ffmpeg", "-nostdin", "-y", "-i", raw_video, "-c", "copy", out_path], check=True)
        return

    batches = [kept_segments[i:i + SELECT_BATCH_SIZE]
               for i in range(0, len(kept_segments), SELECT_BATCH_SIZE)]

    if len(batches) == 1:
        _render_batch(raw_video, batches[0], out_path)
        return

    os.makedirs(work_dir, exist_ok=True)
    batch_files = []
    for i, batch in enumerate(batches):
        bf = os.path.join(work_dir, f"batch_{i:04d}.mp4")
        _render_batch(raw_video, batch, bf)
        batch_files.append(bf)

    concat_list = os.path.join(work_dir, "batches.txt")
    with open(concat_list, "w") as f:
        for bf in batch_files:
            f.write(f"file '{bf}'\n")
    subprocess.run(
        ["ffmpeg", "-nostdin", "-y", "-f", "concat", "-safe", "0", "-i", concat_list,
         "-c", "copy", out_path],
        check=True,
    )
    for bf in batch_files:
        os.remove(bf)


def main():
    job, raw_video, audio_path, out_dir, work_dir = sys.argv[1:6]
    os.makedirs(out_dir, exist_ok=True)

    duration = ffprobe_duration(raw_video)

    segments = try_whisperx(audio_path) or try_faster_whisper(audio_path)
    transcription_available = segments is not None
    if segments is None:
        segments = [{"start": 0.0, "end": duration, "text": ""}]

    kept, cut = build_edl(segments)

    render_cut(raw_video, kept if transcription_available else [], os.path.join(out_dir, "rough_cut.mp4"), work_dir)

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
