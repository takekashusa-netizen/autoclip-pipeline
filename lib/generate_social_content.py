#!/usr/bin/env python3
"""
lib/generate_social_content.py <job_name>

Real, automated content generation: takes a finished job's actual
transcript, calls the Anthropic API with a real, voice-calibrated prompt,
and produces a LinkedIn post, 3 Twitter threads, and one email
newsletter — all grounded in what actually happened in that specific
stream, not generic gaming-content filler.

Requires ANTHROPIC_API_KEY set in the environment.
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECTS = os.path.join(ROOT, "projects")
OUTPUTS = os.path.join(ROOT, "outputs")

# Real voice calibration, grounded in an actual approved draft (confirmed
# as matching the creator's real voice) — hyped, competitive, genuine
# trash-talk energy, real specific callouts from what actually happened.
# Deliberately excludes slurs and excessive profanity, especially for
# LinkedIn: posting that there risks the account being flagged or banned
# by the platform itself, which defeats the entire point.
VOICE_SYSTEM_PROMPT = """You are writing social content in the voice of a gaming streamer/creator, based on real transcript excerpts from their actual stream. Your job is to capture their genuine energy — hyped, competitive, direct, real trash-talk with their squad, specific real callouts from what actually happened — NOT generic gaming-influencer copy.

Real, hard rules:
- NEVER include slurs, even if they appear in the source transcript. The real transcript will contain profanity and slurs since it's raw stream audio — your job is to capture the ENERGY, not transcribe it.
- Minimize profanity overall. Light, natural swearing is fine for Twitter/email; LinkedIn should have none — that platform will flag/restrict accounts for it, which defeats the purpose.
- Ground everything in specific, real details from the actual transcript excerpts you're given (real callouts, real moments, real chaos) — not generic "epic gaming moment" filler.
- Write like a real person texted this, not like a marketing team wrote it. Short sentences. Real energy. No corporate voice, even on LinkedIn — capture authenticity there, don't sanitize into blandness.

Output ONLY valid JSON matching this exact structure, nothing else:
{
  "linkedin_post": "...",
  "twitter_thread_1": ["tweet 1 text", "tweet 2 text", ...],
  "twitter_thread_2": ["tweet 1 text", "tweet 2 text", ...],
  "twitter_thread_3": ["tweet 1 text", "tweet 2 text", ...],
  "email_subject": "...",
  "email_body": "..."
}"""


def clean_transcript_excerpt(text):
    """Real, basic slur/profanity stripping on the INPUT side too — belt
    and suspenders. The model is instructed not to reproduce this, but
    not sending it in the first place is a real, additional layer, not
    just relying on the instruction alone."""
    sys.path.insert(0, os.path.join(ROOT, "lib"))
    from content_filter import clean_text
    return clean_text(text)


def get_transcript_excerpts(job_name, max_segments=60):
    """Real, representative sample of the actual stream — spread across
    the whole video, not just the start, so the generated content
    reflects the real range of what happened."""
    script_path = os.path.join(PROJECTS, job_name, "rough-cut", "script.json")
    if not os.path.exists(script_path):
        raise FileNotFoundError(f"no real transcript found for job '{job_name}' at {script_path}")

    with open(script_path) as f:
        script = json.load(f)
    segments = script.get("kept_segments", [])
    if not segments:
        raise ValueError(f"job '{job_name}' has no real kept_segments to generate content from")

    step = max(1, len(segments) // max_segments)
    sampled = segments[::step][:max_segments]
    return [{"time": round(s["start"], 1), "text": clean_transcript_excerpt(s["text"])} for s in sampled]


def generate_social_content(job_name, youtube_url=None):
    try:
        import anthropic
    except ImportError as e:
        raise RuntimeError("anthropic package not installed. Run: pip install anthropic --break-system-packages") from e

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set in environment")

    excerpts = get_transcript_excerpts(job_name)
    excerpt_text = "\n".join(f"[{e['time']}s] {e['text']}" for e in excerpts)

    user_prompt = f"""Here are real, actual transcript excerpts from a gaming stream, spread across the full session:

{excerpt_text}

{f"The finished clip from this stream is now live at: {youtube_url}" if youtube_url else ""}

Write the LinkedIn post, 3 Twitter threads, and email newsletter now, grounded in the real, specific moments above."""

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=4000,
        system=VOICE_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )

    raw_text = response.content[0].text.strip()
    # real, defensive parsing — strip markdown code fences if the model
    # added them despite the "ONLY valid JSON" instruction
    raw_text = re.sub(r"^```(?:json)?\s*", "", raw_text)
    raw_text = re.sub(r"\s*```$", "", raw_text)

    try:
        content = json.loads(raw_text)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"model did not return valid JSON: {e}\nRaw response: {raw_text[:500]}") from e

    required_keys = {"linkedin_post", "twitter_thread_1", "twitter_thread_2", "twitter_thread_3",
                      "email_subject", "email_body"}
    missing = required_keys - content.keys()
    if missing:
        raise RuntimeError(f"model response missing required keys: {missing}")

    return content


def main():
    if len(sys.argv) < 2:
        print("usage: generate_social_content.py <job_name> [youtube_url]", file=sys.stderr)
        sys.exit(1)
    job_name = sys.argv[1]
    youtube_url = sys.argv[2] if len(sys.argv) > 2 else None

    content = generate_social_content(job_name, youtube_url)

    out_dir = os.path.join(OUTPUTS, f"{job_name}_social_content")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "content.json")
    with open(out_path, "w") as f:
        json.dump(content, f, indent=2)

    print(json.dumps({"output": out_path, "keys": list(content.keys())}))


if __name__ == "__main__":
    main()
