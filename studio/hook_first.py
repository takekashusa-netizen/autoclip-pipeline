"""Hook-first edit: put the payoff in the first ~2 seconds, then play the build-up.

Output = [payoff teaser, punched-in, with optional on-screen tease text]
         + a 6-frame white flash ("rewind")
         + the full original clip.
The payoff point comes from (in order): an explicit --payoff time, a studio
signal/game event inside the clip, or the loudest sustained second of audio.
If the payoff is already inside the first 3 seconds the clip is left alone.
"""
import os

from .common import AUDIO_ENC, VIDEO_ENC, StudioError, ff_escape, ffmpeg, font, probe, read_audio_mono, rms_envelope

TEASE_LEN = 2.0


def find_payoff(clip, signal_times=None):
    info = probe(clip)
    dur = info["duration"]
    for t in sorted(signal_times or []):
        if 0 <= t <= dur:
            return float(t), "signal"
    if not info["has_audio"]:
        return dur * 0.7, "fallback-70pct"
    import numpy as np
    sr = 16000
    a = read_audio_mono(clip, sr)
    env = rms_envelope(a, sr, 0.1)
    if len(env) < 10:
        return dur * 0.7, "fallback-70pct"
    win = np.convolve(env, np.ones(10) / 10, mode="same")  # loudest sustained ~1 s, not a single click
    i = int(np.argmax(win))
    return i * 0.1, "audio-peak"


def make(clip, out, payoff=None, signal_times=None, tease_text=None, tease_len=TEASE_LEN):
    info = probe(clip)
    dur = info["duration"]
    how = "given"
    if payoff is None:
        payoff, how = find_payoff(clip, signal_times)
    if payoff < 3.0:
        return {"skipped": True, "reason": f"payoff already at {payoff:.1f}s — hook is already first", "payoff": payoff}
    if dur < tease_len + 4:
        return {"skipped": True, "reason": "clip too short for a cold open"}
    a = max(0.0, min(payoff - tease_len * 0.6, dur - tease_len))
    b = a + tease_len
    w, h, fps = info["width"], info["height"], round(info["fps"]) or 30
    flash = 6 / fps
    txt = ""
    if tease_text:
        fs = int(h * 0.055)
        txt = (f",drawtext=fontfile='{font('Black')}':text='{ff_escape(tease_text.upper())}':fontsize={fs}:"
               f"fontcolor=white:borderw={max(3, fs // 12)}:bordercolor=black:x=(w-tw)/2:y=h*0.16")
    vf = (f"[0:v]trim={a:.3f}:{b:.3f},setpts=PTS-STARTPTS,fps={fps},"
          f"scale=iw*1.08:ih*1.08,crop={w}:{h},setsar=1{txt}[tv];"
          f"color=c=white:s={w}x{h}:r={fps}:d={flash:.3f},format=yuv420p,setsar=1,fade=t=out:st=0:d={flash:.3f}[fl];"
          f"[0:v]fps={fps},setsar=1[mv];")
    if info["has_audio"]:
        af = (f"[0:a]atrim={a:.3f}:{b:.3f},asetpts=PTS-STARTPTS,aresample=48000,afade=t=out:st={tease_len - 0.15:.3f}:d=0.15[ta];"
              f"anullsrc=r=48000:cl=stereo,atrim=0:{flash:.3f}[fa];"
              f"[0:a]aresample=48000,aformat=channel_layouts=stereo[ma];[ta]aformat=channel_layouts=stereo[ta2];")
        fc = vf + af + "[tv][ta2][fl][fa][mv][ma]concat=n=3:v=1:a=1[v][a]"
        maps = ["-map", "[v]", "-map", "[a]"] + AUDIO_ENC
    else:
        fc = vf + "[tv][fl][mv]concat=n=3:v=1:a=0[v]"
        maps = ["-map", "[v]"]
    ffmpeg(["-i", clip, "-filter_complex", fc] + maps + VIDEO_ENC + ["-movflags", "+faststart"], out)
    return {"skipped": False, "out": out, "payoff": round(payoff, 2), "payoff_source": how,
            "teaser": [round(a, 2), round(b, 2)], "duration": round(dur + tease_len + flash, 2)}


if __name__ == "__main__":
    import json
    import sys
    if len(sys.argv) < 3:
        raise SystemExit("usage: hook_first.py <clip.mp4> <out.mp4> [payoff_sec]")
    print(json.dumps(make(sys.argv[1], sys.argv[2], float(sys.argv[3]) if len(sys.argv) > 3 else None), indent=2))
