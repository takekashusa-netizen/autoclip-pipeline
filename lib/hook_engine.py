#!/usr/bin/env python3
"""
lib/hook_engine.py
Real Hook Engine (Layers 15-16).
"""
import json
import os
import re


def generate_hook(transcript_text, clip_duration_sec):
    try:
        import anthropic
    except ImportError as e:
        raise RuntimeError("anthropic package not installed") from e

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")

    prompt = f"""Here is the real, actual transcript of one short video clip ({clip_duration_sec:.0f}s long):

{transcript_text[:2500]}

Generate a real, genuine hook for the first 1-3 seconds of this clip -
text that would make someone stop scrolling, grounded in what
genuinely happens later in this real clip (a real tease of the real
payoff, not an invented claim). Do not overclaim beyond what the
transcript actually shows.

Respond with ONLY valid JSON:
{{"hook_text": "...", "hook_duration_sec": 1-3, "real_payoff_reference": "one real sentence naming what part of the transcript this hook is teasing"}}"""

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
    return json.loads(raw)
