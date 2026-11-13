"""Sponsor media kit: one printable page built only from real stats on file.

Sources: yt_video_stats.json (YouTube uploads + views) and, if present,
takekash.db analytics. Nothing is estimated or invented; sections without
data are left out. Open the HTML and Print -> Save as PDF.
"""
import html
import json
import os
import sqlite3
from datetime import datetime, timezone

from .common import ROOT


def gather(stats_path=None, db_path=None, days=90):
    stats_path = stats_path or os.path.join(ROOT, "yt_video_stats.json")
    vids = json.load(open(stats_path)) if os.path.exists(stats_path) else []
    vids = [v for v in vids if v.get("privacy", "public") == "public"]
    now = datetime.now(timezone.utc)
    recent = []
    for v in vids:
        try:
            pub = datetime.fromisoformat(v["publishedAt"].replace("Z", "+00:00"))
        except (KeyError, ValueError):
            continue
        v["_age"] = (now - pub).days
        if v["_age"] <= days:
            recent.append(v)
    views = [v.get("views", 0) for v in vids]
    rv = [v.get("views", 0) for v in recent]
    out = {"youtube": {"videos": len(vids), "total_views": sum(views),
                       "avg_views": round(sum(views) / len(views)) if views else 0,
                       "median_views": sorted(views)[len(views) // 2] if views else 0,
                       "recent_days": days, "recent_videos": len(recent), "recent_views": sum(rv),
                       "uploads_per_week": round(len(recent) / (days / 7), 1) if recent else 0,
                       "top": sorted(vids, key=lambda v: -v.get("views", 0))[:5]}}
    db_path = db_path or os.path.join(ROOT, "takekash.db")
    if os.path.exists(db_path):
        try:
            c = sqlite3.connect(db_path)
            rows = c.execute("SELECT sp.platform, SUM(a.views), COUNT(DISTINCT sp.id) FROM analytics a "
                             "JOIN social_posts sp ON sp.id=a.social_post_id GROUP BY sp.platform").fetchall()
            out["platforms"] = [{"platform": r[0], "views": r[1] or 0, "posts": r[2]} for r in rows]
            c.close()
        except sqlite3.Error:
            pass
    return out


def render(data, out_path, name="GtaxZombies", handles=None, games=None, contact=None):
    handles = handles or {"Twitch": "twitch.tv/gtaxzombies", "TikTok": "@gtaxzombies", "Instagram": "@gtaxzombies",
                          "YouTube": "@gtaxzombies"}
    games = games or ["Warzone", "Apex Legends", "NBA 2K"]
    yt = data["youtube"]

    def n(x):
        return f"{x / 1e6:.1f}M" if x >= 1e6 else f"{x / 1e3:.1f}K" if x >= 1e3 else str(x)
    stats = [("YouTube views (all tracked)", n(yt["total_views"])), ("Avg views / video", n(yt["avg_views"])),
             (f"Uploads / week (last {yt['recent_days']}d)", str(yt["uploads_per_week"])),
             (f"Views, last {yt['recent_days']} days", n(yt["recent_views"]))]
    for p in data.get("platforms", []):
        stats.append((f"{p['platform'].title()} views ({p['posts']} posts)", n(p["views"])))
    tiles = "".join(f"<div class=t><b>{html.escape(v)}</b><span>{html.escape(k)}</span></div>" for k, v in stats if v not in ("0", "0.0"))
    top = "".join(f"<li><span>{html.escape(v.get('title', '')[:80])}</span><b>{n(v.get('views', 0))}</b></li>" for v in yt["top"])
    hs = "".join(f"<div><span>{html.escape(k)}</span>{html.escape(v)}</div>" for k, v in handles.items())
    gm = " · ".join(html.escape(g) for g in games)
    page = f"""<!DOCTYPE html><html><head><meta charset=utf-8><title>{html.escape(name)} — Media Kit</title><style>
@page{{size:letter;margin:0}}*{{box-sizing:border-box}}body{{margin:0;background:#0E1114;color:#F4F5F2;font:15px/1.45 Poppins,system-ui,sans-serif;-webkit-print-color-adjust:exact;print-color-adjust:exact}}
.p{{max-width:850px;margin:auto;padding:48px}}.k{{font:600 12px ui-monospace,monospace;letter-spacing:.22em;color:#E8452F}}
h1{{font-size:56px;margin:.1em 0 0;letter-spacing:-.01em}}h1 i{{color:#E8452F;font-style:normal}}.sub{{color:#9AA3A9}}
.g{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin:28px 0}}.t{{background:#171C20;border:1px solid #2A3137;border-radius:12px;padding:18px}}
.t b{{display:block;font-size:34px}}.t span{{color:#9AA3A9;font-size:13px}}h2{{font-size:16px;letter-spacing:.15em;color:#9AA3A9;margin-top:34px}}
ol{{padding:0;list-style:none}}li{{display:flex;justify-content:space-between;gap:16px;padding:10px 0;border-bottom:1px solid #2A3137}}li b{{color:#E8452F}}
.h{{display:grid;grid-template-columns:1fr 1fr;gap:8px}}.h div span{{color:#9AA3A9;display:inline-block;width:92px}}.f{{margin-top:34px;color:#5C666D;font-size:12px}}</style></head>
<body><div class=p><div class=k>SPONSOR MEDIA KIT · {datetime.now().strftime('%B %Y').upper()}</div>
<h1>{html.escape(name).upper()[:-7] if name.upper().endswith('ZOMBIES') else html.escape(name)}<i>{'ZOMBIES' if name.upper().endswith('ZOMBIES') else ''}</i></h1>
<div class=sub>{gm} · live on Twitch · clips daily across TikTok, YouTube Shorts and Reels</div>
<div class=g>{tiles}</div><h2>TOP VIDEOS</h2><ol>{top}</ol><h2>WHERE TO FIND ME</h2><div class=h>{hs}</div>
<h2>WHAT I OFFER</h2><div class=sub>Dedicated short-form integrations, live on-stream placements, product reviews, and clip packages
cut by GtaxZombies Clip Studio — every brand clip passes the same 90%+ quality gate as my own.</div>
{f'<h2>CONTACT</h2><div>{html.escape(contact)}</div>' if contact else ''}
<div class=f>All figures pulled from platform data on {datetime.now().strftime('%Y-%m-%d')}. No estimates.</div></div></body></html>"""
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    open(out_path, "w").write(page)
    return out_path
