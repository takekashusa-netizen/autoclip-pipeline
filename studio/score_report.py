"""Score report: show the buyer WHY a clip shipped (or was held), as JSON + a branded HTML card.

Inputs come from what the pipeline already measured: clips.json
(engagement_score, signal bonus/reasons) and signals.json moments inside the
clip. Gate: 90 by default (owner channels + top tier), matching the quality
gate decision; other tiers can use a lower --gate.
"""
import html
import json
import os

GATE = 90


def build(clip_name, clip_entry, moments=None, gate=GATE, extras=None):
    e = clip_entry or {}
    score = int(e.get("engagement_score", 0))
    inside = [m for m in (moments or []) if e and e.get("start", 0) <= m.get("peak_t", m["start"]) <= e.get("end", 0)]
    reasons = []
    if e.get("signal_reasons"):
        reasons += [f"Chat/HUD proven: {r}" for r in e["signal_reasons"]]
    for m in inside:
        if m.get("source") == "game" or "game" in m.get("sources", []):
            reasons.append(f"Game event: {m['label']}")
        if m.get("source") == "chat" or "chat" in m.get("sources", []):
            reasons.append(f"Chat reaction: {m['label']}")
    if e.get("bonus"):
        reasons.append("Bonus highlight pick (strong kill/clutch/hype moment)")
    reasons = list(dict.fromkeys(reasons))
    rep = {"clip": clip_name, "score": score, "gate": gate, "decision": "PASS" if score >= gate else "HOLD",
           "window": [e.get("start"), e.get("end")], "signal_bonus": e.get("signal_bonus", 0),
           "reasons": reasons or ["Audio/visual action density (no chat or HUD signal for this window)"],
           "features": {"signal_bonus": e.get("signal_bonus", 0), "base_score": score - e.get("signal_bonus", 0),
                        "game_events": sum(len(m.get("events", [])) for m in inside),
                        "chat_confirmed": any("chat" in m.get("sources", [m.get("source")]) for m in inside),
                        "duration": (e.get("end", 0) or 0) - (e.get("start", 0) or 0)}}
    if extras:
        rep.update(extras)
    return rep


def to_html(rep):
    ok = rep["decision"] == "PASS"
    col = "#7CFF4F" if ok else "#E8452F"
    items = "".join(f"<li>{html.escape(r)}</li>" for r in rep["reasons"])
    pct = max(0, min(100, rep["score"]))
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>Clip score — {html.escape(rep['clip'])}</title>
<style>body{{margin:0;background:#0E1114;color:#F4F5F2;font:16px/1.5 Poppins,system-ui,sans-serif;display:grid;place-items:center;min-height:100vh}}
.c{{width:min(560px,92vw);background:#171C20;border:1px solid #2A3137;border-radius:14px;padding:28px}}
.k{{font:600 12px ui-monospace,monospace;letter-spacing:.2em;color:#9AA3A9}}h1{{margin:.2em 0 0;font-size:22px}}
.s{{display:flex;align-items:center;gap:20px;margin:22px 0}}.n{{font-size:64px;font-weight:800}}
.bar{{flex:1;height:10px;background:#2A3137;border-radius:5px;position:relative}}.bar i{{position:absolute;inset:0 auto 0 0;width:{pct}%;background:#E8452F;border-radius:5px}}
.bar b{{position:absolute;left:{rep['gate']}%;top:-6px;bottom:-6px;width:2px;background:#F4F5F2}}
.d{{display:inline-block;border:2px solid {col};color:{col};font-weight:800;letter-spacing:.15em;padding:4px 14px;border-radius:6px}}
ul{{padding-left:18px;color:#d6dadc}}</style></head><body><div class="c">
<div class="k">GTAXZOMBIES CLIP STUDIO · SCORE REPORT</div><h1>{html.escape(rep['clip'])}</h1>
<div class="s"><div class="n">{rep['score']}</div><div class="bar"><i></i><b title="gate"></b></div></div>
<div class="d">{rep['decision']}</div> <span class="k">&nbsp;GATE {rep['gate']}+</span>
<h3>Why</h3><ul>{items}</ul></div></body></html>"""


def write(rep, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    jp = os.path.join(out_dir, "report.json")
    hp = os.path.join(out_dir, "report.html")
    json.dump(rep, open(jp, "w"), indent=2)
    open(hp, "w").write(to_html(rep))
    return jp, hp
