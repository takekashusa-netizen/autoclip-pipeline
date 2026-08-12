#!/usr/bin/env python3
"""
compare_whisper_models.py <audio_path> <model1> <model2> ...

Runs each given whisper model size against the SAME real audio sample,
times each one, and prints the resulting transcript text side by side —
a real, direct speed-vs-quality comparison instead of guessing.
"""
import sys
import time

from faster_whisper import WhisperModel

audio_path = sys.argv[1]
model_names = sys.argv[2:]

for model_name in model_names:
    print(f"\n=== {model_name} ===")
    start = time.time()
    model = WhisperModel(model_name, device="cpu", compute_type="int8")
    segments, info = model.transcribe(audio_path, vad_filter=True)
    text_parts = []
    for s in segments:
        text_parts.append(s.text.strip())
    elapsed = time.time() - start
    full_text = " ".join(text_parts)
    print(f"time: {elapsed:.1f}s")
    print(f"transcript ({len(full_text)} chars):")
    print(full_text[:800])
