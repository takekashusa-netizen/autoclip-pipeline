#!/usr/bin/env python3
"""
lib/retranscribe_from_final.py

Real re-transcription for clips whose rough-cut/script.json was lost (e.g.
the 2026-09-23 pruning-race-condition incident, before that bug was fixed).
Unlike the normal rough-cut step, these are already-cut, short final clips
-- so this transcribes the final .mp4 directly with faster-whisper (same
model/settings as skills/rough-cut/cut_engine.py) and writes a script.json
in the same real schema, rather than re-running the full rough-cut pipeline.

MUST be run from a real macOS Terminal (not the sandboxed device-bridge
shell) with the pipeline's real venv_pipeline interpreter, because it needs
to download the whisper model from Hugging Face on first run -- both the
device-bridge sandbox and the cloud container block huggingface.co at the
network level, confirmed 2026-09-23 (403, "blocked-by-allowlist"). This is
not something Claude can do from either sandbox; it has to run here.

Usage:
    cd ~/autoclip-pipeline
    venv_pipeline/bin/python3 lib/retranscribe_from_final.py

Reads .batch_state/manual_batch.json and .batch_state/auto_batch.json (copied
into the repo, not /tmp, so this real Terminal run and Claude's sandboxed
device-bridge session both see the same files) for the list of
content_id -> video_path pairs, transcribes each video directly, and writes
projects/<job>/rough-cut/script.json (creating the rough-cut/ dir if it
doesn't exist -- it was stripped along with the rest of raw/rough-cut/work/
when these jobs were marked RECLAIMABLE and cleaned up).

Safe to re-run: skips any job that already has a real script.json with
transcription_available == true, so an interrupted run just picks up where
it left off.
"""
import datetime
import json
import os
import sys
import time

PIPELINE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WHISPER_MODEL = os.environ.get("PIPELINE_WHISPER_MODEL", "small")  # matches cut_engine.py's default

BATCH_FILES = [
    os.path.join(PIPELINE_ROOT, ".batch_state", "manual_batch.json"),
    os.path.join(PIPELINE_ROOT, ".batch_state", "auto_batch.json"),
]


def content_id_to_job(content_id):
    # e.g. "job1788482095_window01_tiktok" -> "job1788482095__window01"
    #      "apexnba2k2_window17_tiktok"    -> "apexnba2k2__window17"
    #      "interviewtest_window12_tiktok" -> "interviewtest__window12"
    base = content_id.replace("_tiktok", "")
    for prefix in ("interviewtest", "apexnba2k2", "job1788482095"):
        if base.startswith(prefix + "_window"):
            window = base[len(prefix + "_window"):]
            return f"{prefix}__window{window}"
    raise ValueError(f"unrecognized content_id shape: {content_id}")


def load_items():
    items = []
    for path in BATCH_FILES:
        if not os.path.exists(path):
            print(f"  (skipping {path}, not found)")
            continue
        with open(path) as f:
            items.extend(json.load(f))
    return items


def main():
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print("faster-whisper not importable -- run with venv_pipeline/bin/python3, "
              "not the system python3 (fix_pipeline_venv.sh already installed it there).")
        sys.exit(1)

    items = load_items()
    if not items:
        print("No items found in .batch_state/manual_batch.json or .batch_state/auto_batch.json.")
        sys.exit(1)

    print(f"Loading whisper model '{WHISPER_MODEL}' (first run downloads it from "
          f"Hugging Face -- this is the step that needs real internet access)...")
    cpu_count = os.cpu_count() or 4
    model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8", cpu_threads=cpu_count)
    print("Model loaded.\n")

    done, skipped, failed = 0, 0, 0
    for it in items:
        content_id = it["content_id"]
        try:
            job = content_id_to_job(content_id)
        except ValueError as e:
            print(f"  SKIP {content_id}: {e}")
            skipped += 1
            continue

        out_dir = os.path.join(PIPELINE_ROOT, "projects", job, "rough-cut")
        script_path = os.path.join(out_dir, "script.json")

        if os.path.exists(script_path):
            try:
                existing = json.load(open(script_path))
                if existing.get("transcription_available") and existing.get("script_text"):
                    print(f"  already done: {job}")
                    skipped += 1
                    continue
            except Exception:
                pass  # corrupt/partial -- re-transcribe

        video_path = it["video_path"]
        if not os.path.exists(video_path):
            print(f"  MISSING video for {job}: {video_path}")
            failed += 1
            continue

        print(f"  transcribing {job} ({os.path.basename(video_path)}) ...", end=" ", flush=True)
        t0 = time.time()
        try:
            segments, info = model.transcribe(video_path, vad_filter=True, word_timestamps=True)
            kept = []
            for s in segments:
                words = [{"start": w.start, "end": w.end, "word": w.word} for w in (s.words or [])]
                kept.append({"start": s.start, "end": s.end, "text": s.text.strip(), "words": words})
            script_text = " ".join(s["text"] for s in kept if s["text"]).strip()

            os.makedirs(out_dir, exist_ok=True)
            script = {
                "job": job,
                "transcription_available": True,
                "source_duration_sec": getattr(info, "duration", None),
                "kept_segments": kept,
                "cut_segments": [],
                "script_text": script_text,
                "note": (f"re-transcribed directly from the final clip {datetime.date.today().isoformat()} "
                         "after the original rough-cut/script.json was lost in the 2026-09-23 "
                         "pruning incident -- this is real whisper output, not reconstructed/guessed."),
            }
            with open(script_path, "w") as f:
                json.dump(script, f, indent=2)

            elapsed = time.time() - t0
            print(f"done ({elapsed:.1f}s, {len(script_text)} chars)")
            done += 1
        except Exception as e:
            print(f"FAILED: {e}")
            failed += 1

    print(f"\n{done} transcribed, {skipped} already done/skipped, {failed} failed.")
    print("Next: re-run the rescoring step (Claude will do this once you tell it this finished).")


if __name__ == "__main__":
    main()
