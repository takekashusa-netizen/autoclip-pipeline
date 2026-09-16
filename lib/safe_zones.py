#!/usr/bin/env python3
"""
lib/safe_zones.py
Real Safe-Zone Engine (Layer 13).
"""

SAFE_ZONE_PROFILES = {
    "tiktok": {
        "top_margin_px": 120,
        "bottom_margin_px": 320,
        "right_margin_px": 100,
        "left_margin_px": 20,
    },
    "instagram": {
        "top_margin_px": 100,
        "bottom_margin_px": 280,
        "right_margin_px": 90,
        "left_margin_px": 20,
    },
    "youtube_shorts": {
        "top_margin_px": 90,
        "bottom_margin_px": 250,
        "right_margin_px": 80,
        "left_margin_px": 20,
    },
}


def safe_zone_profile(platform, canvas_width=1080, canvas_height=1920):
    profile = SAFE_ZONE_PROFILES.get(platform.lower(), SAFE_ZONE_PROFILES["tiktok"])
    return {
        "safe_left": profile["left_margin_px"],
        "safe_top": profile["top_margin_px"],
        "safe_right": canvas_width - profile["right_margin_px"],
        "safe_bottom": canvas_height - profile["bottom_margin_px"],
        "safe_width": canvas_width - profile["left_margin_px"] - profile["right_margin_px"],
        "safe_height": canvas_height - profile["top_margin_px"] - profile["bottom_margin_px"],
    }
