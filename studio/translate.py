"""Multi-language captions: translate a clip's SRT, keep the timing, optionally burn in.

Uses the Anthropic API (ANTHROPIC_API_KEY). Cues go out as one numbered JSON
batch per ~80 cues so the model keeps context; the response must return the
same count or the batch is retried once, then fails loudly (never silently
mis-timed). Output: <stem>.<lang>.srt next to the original, and with
--burn a <stem>.<lang>.mp4 with brand-styled subtitles.
"""
import json
import os
import re

from .common import AUDIO_ENC, VIDEO_ENC, StudioError, ffmpeg, find_srt, parse_srt, write_srt, FONTS

MODEL = os.environ.get("STUDIO_TRANSLATE_MODEL", "claude-sonnet-5-5")
LANG_NAMES = {"es": "Spanish", "pt": "Brazilian Portuguese", "fr": "French", "de": "German", "it": "Italian",
              "ja": "Japanese", "ko": "Korean", "zh": "Simplified Chinese", "hi": "Hindi", "ar": "Arabic",
              "tl": "Filipino", "id": "Indonesian", "ru": "Russian", "tr": "Turkish", "pl": "Polish", "vi": "Vietnamese"}


def claude_translator(texts, lang):
    try:
        import anthropic
    except ImportError as e:
        raise StudioError("pip install anthropic") from e
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise StudioError("ANTHROPIC_API_KEY not set")
    name = LANG_NAMES.get(lang, lang)
    prompt = (f"Translate these gaming/stream caption lines into natural, casual {name} the way a native "
              f"streamer's audience talks. Keep slang energy, keep gamer terms (GG, clutch, squad wipe, etc.) "
              f"if that's what native speakers use, keep names unchanged, keep each line short.\n"
              f"Return ONLY a JSON array of exactly {len(texts)} strings, same order.\n\n"
              + json.dumps(texts, ensure_ascii=False))
    client = anthropic.Anthropic()
    r = client.messages.create(model=MODEL, max_tokens=4000, messages=[{"role": "user", "content": prompt}])
    raw = next(b.text for b in r.content if getattr(b, "type", "") == "text").strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw)
    return json.loads(raw)


def translate_cues(cues, lang, translator=claude_translator, batch=80):
    out = []
    for i in range(0, len(cues), batch):
        chunk = cues[i:i + batch]
        texts = [c["text"].replace("\n", " ") for c in chunk]
        for attempt in range(2):
            res = translator(texts, lang)
            if isinstance(res, list) and len(res) == len(texts):
                break
        else:
            raise StudioError(f"translation for {lang} returned the wrong number of lines twice — not writing a mistimed file")
        out += [{"start": c["start"], "end": c["end"], "text": str(t).strip()} for c, t in zip(chunk, res)]
    return out


def make(clip, langs, srt=None, burn=False, translator=claude_translator, out_dir=None):
    srt = srt or find_srt(clip)
    if not srt:
        raise StudioError(f"no captions found for {clip} (looked for captions/<name>.srt)")
    cues = parse_srt(srt)
    stem = os.path.splitext(os.path.basename(srt))[0]
    out_dir = out_dir or os.path.dirname(srt)
    results = {}
    for lang in langs:
        tc = translate_cues(cues, lang, translator)
        p = write_srt(tc, os.path.join(out_dir, f"{stem}.{lang}.srt"))
        entry = {"srt": p, "cues": len(tc)}
        if burn:
            mp4 = os.path.join(out_dir, f"{stem}.{lang}.mp4")
            style = ("FontName=Poppins Black,Fontsize=16,PrimaryColour=&H00F2F5F4,OutlineColour=&H00000000,"
                     "BorderStyle=1,Outline=2,Shadow=0,Alignment=2,MarginV=60")
            esc = p.replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
            ffmpeg(["-i", clip, "-vf", f"subtitles='{esc}':fontsdir='{FONTS}':force_style='{style}'", "-map", "0:v",
                    "-map", "0:a?"] + VIDEO_ENC + AUDIO_ENC + ["-movflags", "+faststart"], mp4)
            entry["video"] = mp4
        results[lang] = entry
    return results
