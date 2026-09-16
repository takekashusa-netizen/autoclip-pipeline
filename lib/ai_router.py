#!/usr/bin/env python3
"""
lib/ai_router.py
Real AI Model Router (Layer 49).
"""

TASK_MODEL_MAP = {
    "hashtag_generation": "claude-haiku-4-5-20251001",
    "seo_metadata": "claude-sonnet-5",
    "moment_scoring": "claude-sonnet-5",
    "deep_video_reasoning": "claude-opus-5",
    "final_quality_review": "claude-opus-5",
}

DEFAULT_MODEL = "claude-sonnet-5"


def model_for_task(task_type):
    return TASK_MODEL_MAP.get(task_type, DEFAULT_MODEL)
