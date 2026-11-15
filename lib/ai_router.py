#!/usr/bin/env python3
"""
lib/ai_router.py
Real AI Model Router (Layer 49).
"""

import os

# Current Claude models (Nov 2026). Every entry can be overridden with an env var
# AI_MODEL_<TASK> (e.g. AI_MODEL_SEO_METADATA=claude-opus-5-5) without a code change.
TASK_MODEL_MAP = {
    "hashtag_generation": "claude-haiku-5-5",
    "seo_metadata": "claude-sonnet-5-5",
    "moment_scoring": "claude-sonnet-5-5",
    "frame_labeling": "claude-haiku-5-5",      # cheap per-frame game/scene labels across a whole VOD
    "clip_vision": "claude-sonnet-5-5",        # what actually happens in one candidate clip
    "deep_video_reasoning": "claude-opus-5-5",
    "final_quality_review": "claude-opus-5-5",
}
DEFAULT_MODEL = os.environ.get("AI_MODEL_DEFAULT", "claude-sonnet-5-5")


def model_for_task(task_type):
    return os.environ.get(f"AI_MODEL_{task_type.upper()}") or TASK_MODEL_MAP.get(task_type, DEFAULT_MODEL)
