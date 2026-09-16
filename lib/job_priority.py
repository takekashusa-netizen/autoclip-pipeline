#!/usr/bin/env python3
"""
lib/job_priority.py
Real Job Priority Engine (Layer 2).
"""
import time


def score_job_priority(seo_score=None, scheduled_time_epoch=None, deadline_epoch=None,
                        now=None):
    now = now or time.time()
    score = 50

    if seo_score is not None:
        score += (seo_score - 50) * 0.4

    if scheduled_time_epoch is not None:
        minutes_until_due = (scheduled_time_epoch - now) / 60
        if minutes_until_due < 30:
            score += 30
        elif minutes_until_due < 120:
            score += 15

    if deadline_epoch is not None and now > deadline_epoch:
        score += 40

    return max(0, min(100, int(score)))


def priority_label(score):
    if score >= 80:
        return "HIGH"
    if score >= 50:
        return "NORMAL"
    return "LOW"
