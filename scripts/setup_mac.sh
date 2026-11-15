#!/usr/bin/env bash
# One-command setup for a fresh Mac (or to re-sync an existing one).
#   curl -fsSL https://raw.githubusercontent.com/takekashusa-netizen/autoclip-pipeline/main/scripts/setup_mac.sh | bash
# Safe to re-run: it only installs what's missing and fast-forwards the repos.
#
# What the system needs on this machine:
#   ~/autoclip-pipeline     clip engine (this repo, branch main)
#   ~/takekash-site-live    website repo (takekash-site, branch main); the pipeline writes
#                           Instagram hosting files and the admin snapshot into it
#   ffmpeg, tesseract, node, python 3.12 + venv_pipeline (via fix_pipeline_venv.sh)
set -euo pipefail
GH=https://github.com/takekashusa-netizen
step(){ printf '\n== %s ==\n' "$*"; }

step "1/5 Homebrew packages"
if ! command -v brew >/dev/null; then
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  eval "$(/opt/homebrew/bin/brew shellenv 2>/dev/null || /usr/local/bin/brew shellenv)"
fi
for p in git ffmpeg tesseract node python@3.12; do
  brew list --formula "$p" >/dev/null 2>&1 || brew install "$p"
done

step "2/5 Repos on branch main"
sync_repo(){ # url dir
  if [[ -d "$2/.git" ]]; then
    git -C "$2" fetch --quiet origin main && git -C "$2" checkout --quiet main && git -C "$2" merge --ff-only --quiet origin/main \
      && echo "  $2: up to date ($(git -C "$2" log -1 --format=%h))" \
      || echo "  $2: has local changes that block a fast-forward; left as is (commit or stash them, then re-run)"
  else
    git clone --quiet "$1" "$2" && echo "  cloned $1 -> $2"
  fi
}
sync_repo "$GH/autoclip-pipeline" "$HOME/autoclip-pipeline"
sync_repo "$GH/takekash-site" "$HOME/takekash-site-live"

step "3/5 Python environment + dashboard service"
cd "$HOME/autoclip-pipeline" && bash fix_pipeline_venv.sh

step "4/5 SEO engine in sync with the website"
bash "$HOME/autoclip-pipeline/scripts/sync_seo_engine.sh" "$HOME/takekash-site-live"

step "5/5 Checks"
cd "$HOME/autoclip-pipeline"
./venv_pipeline/bin/python3 tests/test_seo_finalize.py | tail -1
./venv_pipeline/bin/python3 -c "import cv2, faster_whisper, anthropic; print('python deps OK')"
missing=()
for v in ANTHROPIC_API_KEY; do [[ -n "${!v:-}" ]] || missing+=("$v"); done
[[ ${#missing[@]} -eq 0 ]] && echo "env OK" || echo "Set in ~/.zshrc (or .env): ${missing[*]}  (clip vision, titles and captions need it)"
echo; echo "Done. Pipeline: ~/autoclip-pipeline   Website repo: ~/takekash-site-live"
