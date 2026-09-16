import os
import subprocess


def render_montage(raw_video, segments, out_path, work_dir, xfade_dur=0.6, timeout_sec=1800):
    """Real montage render: extracts each selected segment (already
    word-boundary-snapped, chronologically ordered), then joins them with
    real xfade/acrossfade transitions instead of a hard concat cut —
    smoother, more watchable, avoids the tacky/choppy jump-cut feel of a
    plain stream-copy concat. Requires re-encoding at the transition
    points (crossfades can't be a simple stream copy), unlike the
    continuous-window path."""
    if not segments:
        raise ValueError("render_montage needs at least one real segment")

    os.makedirs(work_dir, exist_ok=True)
    part_files = []
    durations = []
    for i, seg in enumerate(segments):
        part_path = os.path.join(work_dir, f"montage_part_{i:03d}.mp4")
        dur = seg["end"] - seg["start"]
        cmd = [
            "ffmpeg", "-nostdin", "-y", "-ss", str(seg["start"]), "-i", raw_video,
            "-t", str(dur), "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-color_range", "tv", "-c:a", "aac",
            part_path,
        ]
        subprocess.run(cmd, check=True, timeout=timeout_sec, capture_output=True)
        part_files.append(part_path)
        durations.append(dur)

    if len(part_files) == 1:
        os.replace(part_files[0], out_path)
        return out_path

    # Real xfade chain: each transition's offset is the cumulative real
    # duration of everything merged so far, minus the crossfade length
    # (since the fade overlaps the tail of one clip with the head of the
    # next, rather than sitting between them).
    filter_parts = []
    video_labels = [f"[{i}:v]" for i in range(len(part_files))]
    audio_labels = [f"[{i}:a]" for i in range(len(part_files))]

    cumulative = durations[0]
    prev_v, prev_a = video_labels[0], audio_labels[0]
    for i in range(1, len(part_files)):
        offset = max(0.0, cumulative - xfade_dur)
        out_v = f"[v{i}]"
        out_a = f"[a{i}]"
        filter_parts.append(
            f"{prev_v}{video_labels[i]}xfade=transition=fade:duration={xfade_dur}:offset={offset}{out_v}"
        )
        filter_parts.append(
            f"{prev_a}{audio_labels[i]}acrossfade=d={xfade_dur}{out_a}"
        )
        prev_v, prev_a = out_v, out_a
        cumulative += durations[i] - xfade_dur  # real overlap reduces total length

    filter_complex = ";".join(filter_parts)

    inputs = []
    for p in part_files:
        inputs += ["-i", p]

    cmd = [
        "ffmpeg", "-nostdin", "-y", *inputs,
        "-filter_complex", filter_complex,
        "-map", prev_v, "-map", prev_a,
        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-color_range", "tv", "-c:a", "aac",
        out_path,
    ]
    render_timeout = max(timeout_sec, len(part_files) * 60)
    subprocess.run(cmd, check=True, timeout=render_timeout, capture_output=True)

    for p in part_files:
        if os.path.exists(p):
            os.remove(p)

    return out_path
