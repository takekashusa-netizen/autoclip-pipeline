#!/usr/bin/env python3
"""
lib/pacing_engine.py
Real Pacing Engine (Layer 6).
"""
import json


def analyze_pacing(visual_analysis_path, window_start=None, window_end=None):
    with open(visual_analysis_path) as f:
        data = json.load(f)

    samples = data["samples"]
    if window_start is not None and window_end is not None:
        samples = [s for s in samples if window_start <= s["time"] <= window_end]

    if not samples:
        return {"pacing": "unknown", "avg_motion": 0, "note": "no real samples in this range"}

    avg_motion = sum(s["motion_score"] for s in samples) / len(samples)

    if avg_motion < 0.05:
        pacing = "slow"
    elif avg_motion < 0.15:
        pacing = "normal"
    elif avg_motion < 0.30:
        pacing = "fast"
    else:
        pacing = "extreme"

    return {
        "pacing": pacing,
        "avg_motion": round(avg_motion, 4),
        "real_sample_count": len(samples),
    }


def pacing_recommendations(pacing):
    return {
        "slow": {"zoom_frequency": "low", "caption_timing": "relaxed", "cuts": "minimal", "transitions": "smooth"},
        "normal": {"zoom_frequency": "medium", "caption_timing": "standard", "cuts": "standard", "transitions": "standard"},
        "fast": {"zoom_frequency": "high", "caption_timing": "tight", "cuts": "frequent", "transitions": "quick"},
        "extreme": {"zoom_frequency": "very_high", "caption_timing": "very_tight", "cuts": "rapid", "transitions": "hard_cuts"},
    }.get(pacing, {})
