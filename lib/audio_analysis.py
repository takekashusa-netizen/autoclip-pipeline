#!/usr/bin/env python3
"""
lib/audio_analysis.py <video_or_audio_path> <out_json_path>

Detects audio transients — gunfire, explosions, impacts — as a genuinely
different signal from "loud audio" in general. A music swell or someone
shouting is loud but RISES gradually; a gunshot has a near-instant attack
(energy jumps sharply within a few tens of milliseconds) and a fast decay.
That specific shape is what's actually detected here, not just volume.

Approach: extract mono PCM via ffmpeg, compute short-time RMS energy over
small windows, then flag points where energy jumps by a large ratio over
a very short time window relative to the recent local baseline — that
combination (big jump + fast attack) is the transient signature, and is
what separates "gunfire" from "the music got louder" or "someone yelled."
"""
import argparse
import json
import subprocess
import sys

import numpy as np


def _probe_duration(video_path, timeout_sec=30):
    """Fast metadata-only read — safe with a short, fixed timeout
    regardless of file size, since this never touches the actual video
    content, just the container's own header info."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", video_path],
            capture_output=True, text=True, timeout=timeout_sec,
        )
        return float(result.stdout.strip())
    except Exception:
        return None  # genuinely unknown — caller falls back to a safe default


def extract_pcm(video_path, sample_rate=16000, timeout_sec=None):
    """Returns a 1-D float32 numpy array of mono PCM samples, via ffmpeg
    piped raw output — no temp file needed.

    Real bug fixed, three times now: first no timeout at all; then a
    fixed 180s that was too short for a real multi-hour file; then a
    fixed 1800s that was still just a bigger guess, not a real fix — any
    single fixed constant is eventually wrong in one direction or the
    other for some source length. This now reads the source's own real
    duration first (a fast, safe, size-independent metadata read) and
    scales the actual timeout to it, so it stays correctly sized
    whether the source is 10 minutes or 10 hours, without ever needing
    another manual bump."""
    if timeout_sec is None:
        duration = _probe_duration(video_path)
        timeout_sec = max(300, int(duration * 0.5)) if duration else 1800
    cmd = [
        "ffmpeg", "-nostdin", "-v", "error", "-i", video_path,
        "-f", "f32le", "-ac", "1", "-ar", str(sample_rate), "-",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, check=True, timeout=timeout_sec)
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"audio extraction timed out after {timeout_sec}s — "
                            f"likely a corrupted/truncated region of the source") from e
    audio = np.frombuffer(result.stdout, dtype=np.float32)
    return audio, sample_rate


def short_time_energy(audio, sample_rate, window_ms=20):
    """RMS energy per short window — the envelope used for transient
    detection. 20ms windows are short enough to catch a gunshot's fast
    attack without smearing it into neighboring quiet time."""
    window_samples = max(1, int(sample_rate * window_ms / 1000))
    n_windows = len(audio) // window_samples
    energy = np.zeros(n_windows)
    for i in range(n_windows):
        chunk = audio[i * window_samples:(i + 1) * window_samples]
        energy[i] = np.sqrt(np.mean(chunk ** 2)) if len(chunk) else 0.0
    times = np.arange(n_windows) * window_ms / 1000.0
    return times, energy


def detect_transients(times, energy, baseline_windows=15, jump_ratio=4.0,
                       attack_windows=3, min_gap_sec=1.0, min_energy=0.02):
    """A transient = energy at window i is at least `jump_ratio` times the
    ROLLING MEDIAN of the preceding `baseline_windows` (the recent quiet/
    normal level), AND that jump happens within `attack_windows` (fast
    attack, not a multi-second swell). min_energy is an absolute floor so
    near-silent audio doesn't produce "transients" from tiny fluctuations
    (jump_ratio alone breaks down near zero — any tiny absolute change
    looks like a huge ratio)."""
    events = []
    last_event_time = -min_gap_sec
    for i in range(baseline_windows, len(energy)):
        baseline = np.median(energy[i - baseline_windows:i - attack_windows]) if i - attack_windows > 0 else 0
        current = energy[i]
        if current < min_energy:
            continue
        if baseline <= 0:
            continue
        if current >= baseline * jump_ratio:
            t = times[i]
            if t - last_event_time >= min_gap_sec:
                events.append({"time": round(float(t), 2),
                               "energy": round(float(current), 4),
                               "baseline": round(float(baseline), 4),
                               "ratio": round(float(current / baseline), 2)})
                last_event_time = t
    return events


def analyze(video_path, window_ms=20, **detect_kwargs):
    audio, sr = extract_pcm(video_path)
    times, energy = short_time_energy(audio, sr, window_ms)
    duration = len(audio) / sr
    events = detect_transients(times, energy, **detect_kwargs)
    return {"duration": duration, "transients": events}


def transient_beats(analysis, window_sec=3.0):
    """Turns detected transients into beat-like dicts tagged 'impact' —
    same downstream shape as motion_beats/highlight beats, so clip-select
    and build_montage can treat a gunfire moment identically to a
    transcript highlight or a visual action spike."""
    beats = []
    for e in analysis.get("transients", []):
        start = max(0.0, e["time"] - window_sec / 3)
        end = e["time"] + window_sec * 2 / 3
        beats.append({
            "start": round(start, 2), "end": round(end, 2),
            "text": "(gunfire/impact detected)", "tags": ["impact"],
        })
    return beats


def main():
    p = argparse.ArgumentParser()
    p.add_argument("video_path")
    p.add_argument("out_json_path")
    p.add_argument("--jump-ratio", type=float, default=4.0)
    args = p.parse_args()

    try:
        result = analyze(args.video_path, jump_ratio=args.jump_ratio)
    except subprocess.CalledProcessError as e:
        json.dump({"error": f"ffmpeg audio extraction failed: {e}"}, open(args.out_json_path, "w"))
        print(json.dumps({"available": False}))
        sys.exit(1)

    json.dump(result, open(args.out_json_path, "w"), indent=2)
    print(json.dumps({"available": True, "transient_count": len(result["transients"])}))


if __name__ == "__main__":
    main()
