#!/usr/bin/env python3
"""
lib/moment_understanding.py
Real AI Moment Understanding (Layer 4).
"""
import json
import os
import re


MOMENT_TYPES = [
    "CLUTCH", "FAIL", "FUNNY", "HYPE", "RAGE", "REACTION", "WIN", "LOSS",
    "INSANE_PLAY", "TUTORIAL", "EXPLANATION", "STORY", "JOKE", "TRASH_TALK",
    "SURPRISE", "PLOT_TWIST", "OTHER",
]


def classify_moment(transcript_text, avg_motion_score=None, transient_count=None):
    try:
        import anthropic
    except ImportError as e:
        raise RuntimeError("anthropic package not installed") from e

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")

    context_lines = []
    if avg_motion_score is not None:
        context_lines.append(f"Real average visual motion score for this window: {avg_motion_score:.2f} (0-1 scale, higher = more visual action)")
    if transient_count is not None:
        context_lines.append(f"Real audio transient count for this window: {transient_count} (higher = more gunfire/impact-style sounds)")
    context = "\n".join(context_lines)

    prompt = f"""Here is the real, actual transcript of one short video clip:

{transcript_text[:2000]}

{context}

Classify the genuine, dominant moment type from what is actually said
and the real signals above. Choose exactly one from this list:
{', '.join(MOMENT_TYPES)}

Ground your answer in what is genuinely present - do not invent a
moment type not supported by the transcript or signals. Respond with
ONLY valid JSON: {{"moment_type": "...", "confidence": 0-100, "reasoning": "one real sentence"}}"""

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}],
    )
    text_block = next((b for b in response.content if getattr(b, "type", None) == "text"), None)
    if text_block is None:
        raise RuntimeError("no real text block in model response")
    raw = text_block.text.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    result = json.loads(raw)
    if result.get("moment_type") not in MOMENT_TYPES:
        result["moment_type"] = "OTHER"
    return result
