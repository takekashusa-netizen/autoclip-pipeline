#!/usr/bin/env python3
"""
lib/one_click_production.py
Real "CREATE CONTENT" one-click production (Layer 36).
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from batch_approval import approve_above_score
from content_plan import generate_content_plan


def one_click_create(min_seo_score=85, plan_days=7):
    approved_count = approve_above_score(min_seo_score)
    plan = generate_content_plan(days=plan_days)
    return {
        "real_approved_count": approved_count,
        "real_plan": plan,
    }


if __name__ == "__main__":
    result = one_click_create()
    print(f"TakeKash approved {result['real_approved_count']} real clips (SEO 85+)")
    print(f"Real content plan covers {result['real_plan']['real_days_covered']}/{result['real_plan']['real_days_requested']} days")
