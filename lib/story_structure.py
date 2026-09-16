#!/usr/bin/env python3
"""
lib/story_structure.py
Real Story Structure analysis (Layer 5).
"""
import json
import os
import re


def analyze_story_structure(transcript_text):
    try:
        import anthropic
    except ImportError as e:
        raise RuntimeError("anthropic package not installed") from e

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")

    prompt = f"""Here is the real, actual transcript of one clip:

{transcript_text[:2500]}

Identify the real story structure genuinely present in this transcript
(hook, context, buildup, payoff, reaction) - not every clip has all
five real parts, and some may be genuinely absent. Also identify any
real "dead time" segments that could be genuinely cut (long silence,
repeated/filler content) without losing real context or payoff.

Respond with ONLY valid JSON:
{{"hook_present": true/false, "context_present": true/false,
  "buildup_present": true/false, "payoff_present": true/false,
  "reaction_present": true/false,
  "real_dead_time_note": "one real sentence, or null if none genuinely found"}}"""

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
