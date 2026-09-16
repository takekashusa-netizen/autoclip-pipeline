#!/usr/bin/env python3
"""
lib/system_health.py
Real System Observability (Layer 45).
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))


def check_ffmpeg():
    try:
        result = subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=5, stdin=subprocess.DEVNULL)
        return "ONLINE" if result.returncode == 0 else "OFFLINE"
    except Exception:
        return "OFFLINE"


def check_database():
    db_path = os.path.join(ROOT, "takekash.db")
    return "ONLINE" if os.path.exists(db_path) else "NOT INITIALIZED"


def check_ai():
    return "ONLINE" if os.environ.get("ANTHROPIC_API_KEY") else "NO API KEY SET"


def check_tiktok():
    from platform_plugins import get_plugin
    health = get_plugin("tiktok").get_health()
    return "CONNECTED" if health.get("oauth") == "PASS" else "DISCONNECTED"


def check_instagram():
    return "DISCONNECTED"


def check_workers():
    try:
        result = subprocess.run(["pgrep", "-f", "dashboard.py"], capture_output=True, text=True, timeout=5)
        return "ONLINE" if result.stdout.strip() else "OFFLINE"
    except Exception:
        return "UNKNOWN"


def get_system_health():
    return {
        "workers": check_workers(),
        "database": check_database(),
        "ffmpeg": check_ffmpeg(),
        "tiktok": check_tiktok(),
        "instagram": check_instagram(),
        "ai": check_ai(),
    }


if __name__ == "__main__":
    import json
    print(json.dumps(get_system_health(), indent=2))
