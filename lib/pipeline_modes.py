#!/usr/bin/env python3
"""
lib/pipeline_modes.py
Real Fast/Quality/Balanced modes (Layers 37-39).
"""

MODES = {
    "fast": {
        "model": "tiny",
        "content_type": "gaming",
        "skip_music": True,
        "description": "Minimal processing time - use for time-sensitive content.",
    },
    "quality": {
        "model": "small",
        "content_type": "podcast",
        "skip_music": False,
        "description": "Maximum real analysis depth - use for important uploads.",
    },
    "balanced": {
        "model": "tiny",
        "content_type": "gaming",
        "skip_music": True,
        "description": "Real, default TakeKash workflow.",
    },
}


def get_mode_flags(mode_name="balanced"):
    mode = MODES.get(mode_name, MODES["balanced"])
    flags = ["--model", mode["model"], "--content-type", mode["content_type"]]
    if mode["skip_music"]:
        flags.append("--skip-music")
    return flags
