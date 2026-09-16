"""Clip scoring through the Message Batches API, with the cache set up properly.

Batch usage is charged at 50% of standard API prices; cached input reads run
about a tenth of standard input. The two stack.

The trap: the default cache TTL is 5 minutes, and batches routinely take longer
than that, so a 5-minute TTL gives you cache writes with no reads. Batched
shared context needs the 1-hour TTL.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import anthropic

MODEL = os.environ.get("CLIP_SCORER_MODEL", "claude-sonnet-4-6")

RUBRIC = """You score candidate short-form clips cut from a live gaming stream.

Score each on four axes, 0-10 integers:

hook       Does something land in the first 2 seconds? A clip that opens with
           setup, walking, or menu time scores low no matter how good the
           payoff is. This is the axis that decides feed performance.
payoff     Is there a clear resolution - the kill, the goal, the fail, the
           punchline? Buildup with no landing scores low.
standalone Would this make sense to someone who has never watched this
           streamer? Inside jokes and mid-conversation references cut this down.
clean_cut  Does it start and end on a natural boundary, or does it clip a word
           or an action in half?

Also return:
  title     A title that tells a stranger what they are about to watch, before
            they finish watching it. Specific beats hype.
  verdict   "keep" or "kill"
  reason    One sentence, max 20 words.

Respond with a single JSON object and nothing else. No markdown fences."""


def _system_blocks() -> list[dict[str, Any]]:
    return [{
        "type": "text",
        "text": RUBRIC,
        "cache_control": {"type": "ephemeral", "ttl": "1h"},
    }]


def _user_turn(clip: dict) -> str:
    chat = "\n".join(f"  - {m}" for m in clip.get("chat_sample", []))
    return (
        f"clip_id: {clip['clip_id']}\n"
        f"duration: {clip['duration']}s\n"
        f"chat reaction at the peak:\n{chat or '  (none captured)'}\n\n"
        f"transcript:\n{clip.get('transcript', '(no speech)')}"
    )


def submit(clips: list[dict], client: anthropic.Anthropic | None = None) -> str:
    client = client or anthropic.Anthropic()
    batch = client.messages.batches.create(requests=[
        {
            "custom_id": c["clip_id"],
            "params": {
                "model": MODEL,
                "max_tokens": 400,
                "system": _system_blocks(),
                "messages": [{"role": "user", "content": _user_turn(c)}],
            },
        }
        for c in clips
    ])
    return batch.id


def collect(batch_id: str, client: anthropic.Anthropic | None = None,
            poll: int = 60, timeout: int = 86_400) -> dict[str, dict]:
    client = client or anthropic.Anthropic()
    waited = 0
    while waited < timeout:
        batch = client.messages.batches.retrieve(batch_id)
        if batch.processing_status == "ended":
            break
        time.sleep(poll)
        waited += poll
    else:
        raise TimeoutError(f"batch {batch_id} still running after {timeout}s")

    out: dict[str, dict] = {}
    for row in client.messages.batches.results(batch_id):
        if row.result.type != "succeeded":
            out[row.custom_id] = {"error": row.result.type}
            continue
        text = "".join(b.text for b in row.result.message.content if b.type == "text")
        out[row.custom_id] = _parse(text)
    return out


def score_one(clip: dict, client: anthropic.Anthropic | None = None) -> dict:
    client = client or anthropic.Anthropic()
    msg = client.messages.create(
        model=MODEL, max_tokens=400,
        system=_system_blocks(),
        messages=[{"role": "user", "content": _user_turn(clip)}],
    )
    text = "".join(b.text for b in msg.content if b.type == "text")
    result = _parse(text)
    result["_usage"] = {
        "cache_write": getattr(msg.usage, "cache_creation_input_tokens", None),
        "cache_read": getattr(msg.usage, "cache_read_input_tokens", None),
        "input": msg.usage.input_tokens,
        "output": msg.usage.output_tokens,
    }
    return result


def _parse(text: str) -> dict:
    raw = text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        raw = raw[4:] if raw.startswith("json") else raw
    try:
        d = json.loads(raw.strip())
    except json.JSONDecodeError:
        return {"error": "unparseable", "raw": text[:300]}
    for k in ("hook", "payoff", "standalone", "clean_cut"):
        d[k] = int(d.get(k, 0))
    d["total"] = d["hook"] * 2 + d["payoff"] + d["standalone"] + d["clean_cut"]
    return d


def rank(scored: dict[str, dict]) -> list[tuple[str, dict]]:
    rows = [(k, v) for k, v in scored.items() if "total" in v]
    rows.sort(key=lambda kv: kv[1]["total"], reverse=True)
    return rows


def write(scored: dict, out: str | Path) -> Path:
    p = Path(out)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(scored, indent=2), encoding="utf-8")
    return p
