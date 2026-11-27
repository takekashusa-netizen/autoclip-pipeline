#!/usr/bin/env python3
"""TakeKash Motion Studio — character videos made in-house, no outside services at render time.

  python3 motion.py assets  SHEET.png  [--preset presets/kash.json]   # cut + 4x-upscale character assets
  python3 motion.py poster  ART.png    [--preset presets/kash.json]   # hero art 2x + background stage
  python3 motion.py voice   [--preset presets/kash.json]              # King narration (Kokoro, local)
  python3 motion.py score                                             # taiko/koto soundtrack mixed with the voice
  python3 motion.py preview                                           # 10 frames -> motion_work/out/preview.jpg
  python3 motion.py render  [--name kash_tour]                        # full 9:16 video with sound
  python3 motion.py make    SHEET.png ART.png [--preset ...]          # everything, in order

Models download once from GitHub (Kokoro voice: Apache-2.0, Real-ESRGAN anime: BSD-3) into motion_work/models.
Work files (art, voice, renders) stay in motion_work/ and are git-ignored.
"""
import argparse, json, os, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__))
MOT = os.path.join(HERE, 'studio', 'motion')
sys.path.insert(0, MOT)
import config  # noqa: E402

def sh(*a): subprocess.run([sys.executable, *a], cwd=MOT, check=True)

def main():
    p = argparse.ArgumentParser(description='TakeKash Motion Studio')
    p.add_argument('cmd', choices=['assets', 'poster', 'voice', 'score', 'preview', 'render', 'make'])
    p.add_argument('files', nargs='*')
    p.add_argument('--preset', default=os.path.join(HERE, 'presets', 'kash.json'))
    p.add_argument('--name', default='kash_tour')
    a = p.parse_args()
    P = json.load(open(a.preset))
    if a.cmd in ('assets', 'make'):
        import extract
        print(json.dumps(extract.run(a.files[0], config.ASSETS, a.preset)))
    if a.cmd in ('poster', 'make'):
        import prep
        prep.run(a.files[-1] if a.cmd == 'poster' else a.files[1], a.preset); print('poster + stage ready')
    if a.cmd in ('voice', 'make'):
        import voice
        print(json.dumps(voice.make(P['lines']), indent=1))
    if a.cmd in ('score', 'make'):
        sh('score.py')
    if a.cmd == 'preview':
        sh('render.py', 'preview')
        print(os.path.join(config.OUT, 'preview.jpg'))
    if a.cmd in ('render', 'make'):
        import tour
        mid = round(tour.DUR / 2, 2)
        procs = [subprocess.Popen([sys.executable, 'render.py', 'render', '0', str(mid), 'p1'], cwd=MOT),
                 subprocess.Popen([sys.executable, 'render.py', 'render', str(mid), str(tour.DUR + 0.1), 'p2'], cwd=MOT)]
        if any(pr.wait() for pr in procs): sys.exit('render failed')
        o = config.OUT
        open(f'{o}/list.txt', 'w').write(f"file '{o}/p1.mp4'\nfile '{o}/p2.mp4'\n")
        final = f'{o}/{a.name}.mp4'
        subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'concat', '-safe', '0', '-i', f'{o}/list.txt', '-i', f'{o}/tour.wav',
                        '-map', '0:v', '-map', '1:a', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '256k', '-shortest', '-movflags', '+faststart',
                        final + '.tmp.mp4'], check=True)
        os.replace(final + '.tmp.mp4', final); print(final)

if __name__ == '__main__':
    main()
