#!/usr/bin/env python3
"""
lib/render_cache.py
Real Render Cache (Layer 24).
"""
import hashlib
import json
import os

CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".render_cache")


def _cache_key(source_path, start, end, caption_version="v1", extra=""):
    try:
        mtime = os.path.getmtime(source_path)
    except OSError:
        mtime = 0
    raw = f"{source_path}|{mtime}|{start}|{end}|{caption_version}|{extra}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def get_cached_render(source_path, start, end, caption_version="v1", extra=""):
    key = _cache_key(source_path, start, end, caption_version, extra)
    index_path = os.path.join(CACHE_DIR, "index.json")
    if not os.path.exists(index_path):
        return None
    with open(index_path) as f:
        index = json.load(f)
    cached_path = index.get(key)
    if cached_path and os.path.exists(cached_path):
        return cached_path
    return None


def register_render(source_path, start, end, output_path, caption_version="v1", extra=""):
    os.makedirs(CACHE_DIR, exist_ok=True)
    key = _cache_key(source_path, start, end, caption_version, extra)
    index_path = os.path.join(CACHE_DIR, "index.json")
    index = {}
    if os.path.exists(index_path):
        with open(index_path) as f:
            index = json.load(f)
    index[key] = output_path
    with open(index_path, "w") as f:
        json.dump(index, f, indent=2)
