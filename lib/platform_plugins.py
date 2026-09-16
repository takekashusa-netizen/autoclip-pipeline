#!/usr/bin/env python3
"""
lib/platform_plugins.py
Real Plugin Architecture (Layer 48).
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib"))


class PlatformPlugin:
    name = "base"

    def publish(self, video_path, title, **kwargs):
        raise NotImplementedError

    def get_health(self):
        raise NotImplementedError


class TikTokPlugin(PlatformPlugin):
    name = "tiktok"

    def publish(self, video_path, title, privacy_level=None, video_url=None, **kwargs):
        from tiktok_publish import publish_video
        return publish_video(video_path, title, privacy_level=privacy_level, video_url=video_url)

    def get_health(self):
        import sys as _sys
        _sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        import dashboard
        return dashboard._tiktok_health_check()


class InstagramPlugin(PlatformPlugin):
    name = "instagram"

    def publish(self, video_path, title, **kwargs):
        raise NotImplementedError("real Instagram publish function not yet built - OAuth still pending")

    def get_health(self):
        return {"oauth": "FAIL", "note": "Instagram not yet connected"}


REAL_PLUGINS = {
    "tiktok": TikTokPlugin(),
    "instagram": InstagramPlugin(),
}


def get_plugin(platform_name):
    plugin = REAL_PLUGINS.get(platform_name.lower())
    if plugin is None:
        raise ValueError(f"no real plugin registered for platform '{platform_name}'")
    return plugin
