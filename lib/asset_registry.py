#!/usr/bin/env python3
"""
lib/asset_registry.py
Real Asset Intelligence + License Tracking (Layers 41-42).
"""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REGISTRY_PATH = os.path.join(ROOT, "assets", "asset_registry.json")

REAL_CATEGORIES = ["logo", "font", "animation", "sound_effect", "transition",
                    "overlay", "background", "icon", "template"]


def _load():
    if not os.path.exists(REGISTRY_PATH):
        return []
    with open(REGISTRY_PATH) as f:
        return json.load(f)


def _save(assets):
    os.makedirs(os.path.dirname(REGISTRY_PATH), exist_ok=True)
    with open(REGISTRY_PATH, "w") as f:
        json.dump(assets, f, indent=2)


def register_asset(file_path, category, license_status="unverified", source="",
                    brand_compatible=True, platforms=None):
    assets = _load()
    assets.append({
        "id": len(assets) + 1,
        "file_path": file_path,
        "category": category,
        "license_status": license_status,
        "source": source,
        "brand_compatible": brand_compatible,
        "platforms": platforms or [],
        "usage_count": 0,
    })
    _save(assets)
    return assets[-1]


def flag_for_review(asset_id, reason):
    assets = _load()
    for a in assets:
        if a["id"] == asset_id:
            a["license_status"] = "flagged"
            a["flag_reason"] = reason
    _save(assets)


def get_usable_assets(category=None, platform=None):
    assets = _load()
    usable = [a for a in assets if a["license_status"] in ("owned", "licensed")]
    if category:
        usable = [a for a in usable if a["category"] == category]
    if platform:
        usable = [a for a in usable if not a["platforms"] or platform in a["platforms"]]
    return usable
