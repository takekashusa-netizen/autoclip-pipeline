"""Learning loop: learn which clip traits actually get views for each creator.

Training rows = studio report.json features + the real views that clip got
(views.json mapping {clip_stem: views}, or publish_schedule.json titles joined
to yt_video_stats.json). Fits a small ridge regression of log(views) on the
features. With fewer than MIN_ROWS real results it refuses to adjust anything.
The profile is used by `adjust(features)` -> a bounded +/-10 score nudge.
"""
import json
import math
import os

from .common import ROOT

MIN_ROWS = 15
FEATS = ["base_score", "signal_bonus", "game_events", "chat_confirmed", "duration", "hook_first", "split_layout"]
PROFILE_DIR = os.path.join(ROOT, "presets", "creator-weights")


def _vec(f):
    return [float(f.get(k, 0) or 0) for k in FEATS]


def dataset(report_paths, views_map):
    X, y = [], []
    for p in report_paths:
        rep = json.load(open(p))
        stem = rep.get("clip")
        if stem in views_map:
            X.append(_vec(rep.get("features", {})))
            y.append(math.log1p(views_map[stem]))
    return X, y


def views_from_youtube(schedule_path=None, stats_path=None):
    """Join publish_schedule.json (content_id/video_path -> title) to yt_video_stats.json (title -> views)."""
    schedule_path = schedule_path or os.path.join(ROOT, "publish_schedule.json")
    stats_path = stats_path or os.path.join(ROOT, "yt_video_stats.json")
    if not (os.path.exists(schedule_path) and os.path.exists(stats_path)):
        return {}
    by_title = {v.get("title", "").strip().lower(): v.get("views", 0) for v in json.load(open(stats_path))}
    out = {}
    for it in json.load(open(schedule_path)):
        t = (it.get("title") or "").strip().lower()
        if t in by_title and it.get("video_path"):
            stem = os.path.basename(it["video_path"]).replace(".final.mp4", "").replace(".mp4", "")
            out[stem] = by_title[t]
    return out


def fit(X, y, lam=1.0):
    import numpy as np
    X, y = np.array(X, float), np.array(y, float)
    mu, sd = X.mean(0), X.std(0) + 1e-9
    Z = (X - mu) / sd
    A = Z.T @ Z + lam * np.eye(Z.shape[1])
    w = np.linalg.solve(A, Z.T @ (y - y.mean()))
    pred = Z @ w + y.mean()
    ss = ((y - y.mean()) ** 2).sum()
    r2 = 1 - ((y - pred) ** 2).sum() / ss if ss > 0 else 0.0
    return {"features": FEATS, "mean": mu.tolist(), "std": sd.tolist(), "weights": w.tolist(),
            "intercept": float(y.mean()), "y_std": float(y.std() + 1e-9), "rows": len(y), "r2": round(float(r2), 3)}


def train(creator, report_paths, views_map=None):
    views_map = views_map if views_map is not None else views_from_youtube()
    X, y = dataset(report_paths, views_map)
    if len(y) < MIN_ROWS:
        return {"trained": False, "rows": len(y), "note": f"need {MIN_ROWS}+ published clips with real view counts; have {len(y)}"}
    prof = fit(X, y)
    prof["creator"] = creator
    os.makedirs(PROFILE_DIR, exist_ok=True)
    path = os.path.join(PROFILE_DIR, f"{creator}.json")
    json.dump(prof, open(path, "w"), indent=2)
    top = sorted(zip(FEATS, prof["weights"]), key=lambda kv: -abs(kv[1]))[:3]
    return {"trained": True, "path": path, "rows": prof["rows"], "r2": prof["r2"],
            "strongest": [{"feature": k, "effect": "more views" if v > 0 else "fewer views"} for k, v in top]}


def load(creator):
    p = os.path.join(PROFILE_DIR, f"{creator}.json")
    return json.load(open(p)) if os.path.exists(p) else None


def adjust(features, profile):
    """Bounded score nudge (-10..+10) from the creator's learned profile."""
    if not profile:
        return 0
    z = sum(((v - m) / s) * w for v, m, s, w in zip(_vec(features), profile["mean"], profile["std"], profile["weights"]))
    return int(max(-10, min(10, round(z / profile["y_std"] * 5))))
