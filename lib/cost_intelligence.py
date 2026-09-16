#!/usr/bin/env python3
"""
lib/cost_intelligence.py
Real Cost Intelligence (Layers 43-44). Pricing verified 2026-09-12.
"""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COST_LOG_PATH = os.path.join(ROOT, "cost_log.json")

PRICING = {
    "claude-sonnet-5": {"input": 2.00, "output": 10.00},
    "claude-opus-5": {"input": 5.00, "output": 25.00},
    "claude-haiku-4-5-20251001": {"input": 1.00, "output": 5.00},
}


def real_cost(model, input_tokens, output_tokens):
    rates = PRICING.get(model, PRICING["claude-sonnet-5"])
    return (input_tokens / 1_000_000 * rates["input"]) + (output_tokens / 1_000_000 * rates["output"])


def log_cost(clip_id, model, input_tokens, output_tokens, task_type=""):
    cost = real_cost(model, input_tokens, output_tokens)
    entry = {
        "clip_id": clip_id, "model": model, "task_type": task_type,
        "input_tokens": input_tokens, "output_tokens": output_tokens,
        "cost_usd": round(cost, 6),
    }
    log = []
    if os.path.exists(COST_LOG_PATH):
        with open(COST_LOG_PATH) as f:
            log = json.load(f)
    log.append(entry)
    with open(COST_LOG_PATH, "w") as f:
        json.dump(log, f, indent=2)
    return cost


def cost_summary():
    if not os.path.exists(COST_LOG_PATH):
        return {"total_cost_usd": 0, "clip_count": 0, "cost_per_clip": 0, "cost_per_1000_clips": 0}
    with open(COST_LOG_PATH) as f:
        log = json.load(f)
    total = sum(e["cost_usd"] for e in log)
    clip_ids = set(e["clip_id"] for e in log)
    clip_count = len(clip_ids) or 1
    per_clip = total / clip_count
    return {
        "total_cost_usd": round(total, 4),
        "clip_count": clip_count,
        "cost_per_clip": round(per_clip, 4),
        "cost_per_1000_clips": round(per_clip * 1000, 2),
    }
