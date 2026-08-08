#!/usr/bin/env python3
"""
lib/diagnose.py

Turns a raw error string into a plain-language diagnosis: what actually
happened, why, and what to do differently next time — instead of leaving
a stack trace or ffmpeg dump as the only signal. Patterns here are drawn
directly from real failures hit while building/running this pipeline, not
speculative — each one maps to something that actually happened.
"""
import re

# (pattern, category, reason, avoid_next_time)
PATTERNS = [
    (
        r"CLOSE_WAIT|Connection.*timed out|Read timed out",
        "network_stall",
        "A network connection (likely a model download) stalled — the "
        "remote server stopped responding but the connection never closed, "
        "so the process waited forever with no progress and no error.",
        "Model loading now has a hard timeout (see load_model_with_timeout) "
        "so this fails fast with a clear message instead of hanging silently.",
    ),
    (
        r"ModuleNotFoundError.*faster_whisper|No module named 'faster_whisper'",
        "missing_dependency",
        "faster-whisper isn't installed in the Python environment actually "
        "running the job — often because a different venv/interpreter is "
        "active than the one it was installed into.",
        "Check `which python3` matches the venv you installed into before "
        "running a job. Run `python3 -c \"import faster_whisper\"` to verify.",
    ),
    (
        r"No such file or directory: '.*'\n?$|can't open file",
        "path_word_splitting",
        "A path containing a space got split into multiple arguments by "
        "the shell — usually from an unquoted variable expansion.",
        "Fixed in lib/common.sh (jobstate_cmd) — if this recurs, look for "
        "other unquoted $VAR usages in shell scripts.",
    ),
    (
        r"Enter command:.*target.*all.*time.*command",
        "ffmpeg_stole_stdin",
        "ffmpeg was running in the foreground and read stray keystrokes "
        "from the terminal as interactive commands instead of letting them "
        "reach the shell.",
        "All ffmpeg invocations now use -nostdin. If this recurs, some "
        "ffmpeg call is missing that flag.",
    ),
    (
        r"returned non-zero exit status 244",
        "ffmpeg_batch_crash",
        "ffmpeg hard-errored on an unusually long select-filter boolean "
        "expression — some ffmpeg builds have an internal limit that "
        "doesn't produce a clean, parseable error.",
        "Fixed with a smaller SELECT_BATCH_SIZE plus automatic "
        "split-and-retry in cut_engine.py. If this recurs, the batch size "
        "may need to be lowered further for this specific ffmpeg build.",
    ),
    (
        r"insufficient disk space",
        "disk_space",
        "Not enough free space for the estimated intermediate render "
        "files for this job.",
        "Free up space, or lower the safety margin via check_disk_space's "
        "margin parameter if you're confident the estimate is too "
        "conservative for this job.",
    ),
    (
        r"Sign in to confirm you.re not a bot|needs login/cookies",
        "youtube_bot_check",
        "YouTube served a bot-detection challenge instead of the real "
        "video/audio streams.",
        "fetch_url.py already passes --cookies-from-browser and "
        "--remote-components ejs:github for this. If it recurs, the "
        "browser's cookies may be stale — re-log into YouTube in that "
        "browser.",
    ),
    (
        r"mean_volume.*-9[0-9]\.0 dB|effectively silent",
        "silent_audio",
        "The source's audio track has no real signal — not a "
        "transcription failure, the audio itself is silent.",
        "Nothing to avoid — this is correct behavior for genuinely silent "
        "source audio. Confirm the source actually has audio if this is "
        "unexpected.",
    ),
]


def diagnose(error_text):
    """Returns a dict with category/reason/avoid, or a generic fallback if
    nothing matches — never returns None, so callers can always show
    something useful."""
    if not error_text:
        return None
    text = str(error_text)
    for pattern, category, reason, avoid in PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return {"category": category, "reason": reason, "avoid_next_time": avoid}
    return {
        "category": "unknown",
        "reason": "This error doesn't match a known pattern yet.",
        "avoid_next_time": "No automatic mitigation available — check the "
                            "raw error text below for specifics.",
    }


def main():
    import sys
    text = sys.stdin.read() if not sys.argv[1:] else " ".join(sys.argv[1:])
    result = diagnose(text)
    import json
    print(json.dumps(result))


if __name__ == "__main__":
    main()
