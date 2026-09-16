#!/usr/bin/env python3
"""
lib/orchestration_states.py
Real Orchestration state formalization (Layer 1).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jobstate

SPEC_STATES = [
    "UPLOADED", "ANALYZING", "CLIPS_FOUND", "PROCESSING", "READY_FOR_REVIEW",
    "APPROVED", "SCHEDULED", "PUBLISHING", "PUBLISHED", "FAILED", "ARCHIVED",
]

STEP_TO_STATE = {
    "intake": "ANALYZING",
    "rough_cut": "ANALYZING",
    "graphics": "PROCESSING",
    "second_pass": "PROCESSING",
    "captions": "PROCESSING",
    "background_music": "PROCESSING",
    "export": "READY_FOR_REVIEW",
}


def get_spec_state(job):
    try:
        data = jobstate.load(job)
    except SystemExit:
        return "UPLOADED"

    steps = data.get("steps", {})

    current_state = "UPLOADED"
    for step in jobstate.STEPS:
        step_data = steps.get(step, {})
        if step_data.get("status") == "done":
            current_state = STEP_TO_STATE.get(step, current_state)
        elif step_data.get("status") == "failed":
            return "FAILED"

    if _has_published_entry(job):
        return "PUBLISHED"
    if _has_scheduled_entry(job):
        return "SCHEDULED"

    return current_state


def _has_published_entry(job):
    import json
    queue_path = os.path.join(jobstate.ROOT, "publish_schedule.json")
    if not os.path.exists(queue_path):
        return False
    with open(queue_path) as f:
        queue = json.load(f)
    return any(i.get("content_id", "").startswith(job) and i.get("status") == "published" for i in queue)


def _has_scheduled_entry(job):
    import json
    queue_path = os.path.join(jobstate.ROOT, "publish_schedule.json")
    if not os.path.exists(queue_path):
        return False
    with open(queue_path) as f:
        queue = json.load(f)
    return any(i.get("content_id", "").startswith(job) and i.get("status") in ("pending", "approved") for i in queue)
