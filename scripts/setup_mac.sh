#!/usr/bin/env bash
# One-command setup for a fresh Mac (or to re-sync an existing one).
#   curl -fsSL https://raw.githubusercontent.com/takekashusa-netizen/autoclip-pipeline/main/scripts/setup_mac.sh | bash
# Safe to re-run: it only installs what's missing and fast-forwards the repos.
# A full log lands in ~/mac_setup.log.
#
# What it puts on this machine (every project):
#   ~/autoclip-pipeline     clip engine / GtaxZombies Clip Studio / dashboard (branch main)
#   ~/takekash-site-live    takekash.com site + EditFlow + SEO engine (branch main)
#   ~/q                     private repo (cloned once GitHub sign-in is done)
#   CLI tools               ffmpeg(+libass) ffprobe tesseract yt-dlp imagemagick redis jq git gh
#                           python 3.12, node + npm, watchman, cocoapods
#   Deploy / build CLIs     eas-cli (TakeKash app), railway (api.takekash.com), netlify, vercel,
#                           stripe, shopify, claude (Claude Code)
#   Apps                    Docker Desktop, OBS, Chrome, VS Code, Claude desktop
#   Python                  ~/autoclip-pipeline/venv_pipeline with pipeline + web/worker deps
set -uo pipefail
exec > >(tee -a "$HOME/mac_setup.log") 2>&1
GH=https://github.com/takekashusa-netizen
FAILED=()
step(){ printf '\n== %s ==\n' "$*"; }
try(){ "$@" || { echo "  !! failed: $*"; FAILED+=("$*"); }; }

# keep the Mac awake for the whole run (sleep would kill a long install)
command -v caffeinate >/dev/null && { caffeinate -dis -w $$ & disown; }
# when piped through curl, stdin is the script itself; interactive prompts read the keyboard
TTY=/dev/tty; [[ -r $TTY ]] || TTY=/dev/null
# ask for the Mac password once, then keep sudo alive (Homebrew + Docker need it)
echo "Enter your Mac login password once (typing is hidden):"
sudo -v <"$TTY" && { while kill -0 $$ 2>/dev/null; do sudo -n true; sleep 50; done & disown; }

step "1/9 Apple command line tools"
if ! xcode-select -p >/dev/null 2>&1; then
  xcode-select --install || true
  echo "  A macOS window opened: click Install, wait for it to finish..."
  until xcode-select -p >/dev/null 2>&1; do sleep 10; done
fi
echo "  OK: $(xcode-select -p)"

step "2/9 Homebrew"
if ! command -v brew >/dev/null; then
  NONINTERACTIVE=1 /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" <"$TTY"
fi
BREW=$( [[ -x /opt/homebrew/bin/brew ]] && echo /opt/homebrew/bin/brew || echo /usr/local/bin/brew )
eval "$("$BREW" shellenv)"
# persist brew on PATH for every new Terminal (fresh Macs don't have this)
grep -q 'brew shellenv' "$HOME/.zprofile" 2>/dev/null || echo "eval \"\$($BREW shellenv)\"" >> "$HOME/.zprofile"
brew update --quiet || true

step "3/9 Command line tools"
FORMULAS=(git gh python@3.12 node ffmpeg tesseract yt-dlp imagemagick jq redis watchman cocoapods wget railway)
for p in "${FORMULAS[@]}"; do
  brew list --formula "$p" >/dev/null 2>&1 && echo "  have $p" || try brew install --quiet "$p"
done
brew tap stripe/stripe-cli >/dev/null 2>&1; brew list stripe >/dev/null 2>&1 || try brew install --quiet stripe/stripe-cli/stripe
ffmpeg -hide_banner -filters 2>/dev/null | grep -q ' subtitles ' && echo "  ffmpeg has libass (burned-in captions OK)" \
  || { echo "  ffmpeg missing libass, reinstalling"; try brew reinstall ffmpeg; }

step "4/9 Apps"
CASKS=(docker obs google-chrome visual-studio-code claude)
for c in "${CASKS[@]}"; do
  brew list --cask "$c" >/dev/null 2>&1 && echo "  have $c" || try brew install --cask --quiet "$c"
done

step "5/9 Deploy / build CLIs (npm)"
NPMS=(eas-cli netlify-cli vercel @shopify/cli @anthropic-ai/claude-code)
for n in "${NPMS[@]}"; do
  npm ls -g --depth=0 "$n" >/dev/null 2>&1 && echo "  have $n" || try npm install -g --silent "$n"
done

step "6/9 GitHub sign-in"
if ! gh auth status >/dev/null 2>&1; then
  echo "  A browser window will open: approve GitHub access (account takekashusa-netizen)."
  gh auth login --hostname github.com --git-protocol https --web <"$TTY" || echo "  skipped; private repos will be cloned on the next run"
fi
gh auth setup-git >/dev/null 2>&1 || true
git config --global pull.ff only
git config --global init.defaultBranch main

step "7/9 Project repos on branch main"
sync_repo(){ # url dir
  if [[ -d "$2/.git" ]]; then
    git -C "$2" fetch --quiet origin main && git -C "$2" checkout --quiet main && git -C "$2" merge --ff-only --quiet origin/main \
      && echo "  $2: up to date ($(git -C "$2" log -1 --format=%h))" \
      || echo "  $2: has local changes that block a fast-forward; left as is (commit or stash them, then re-run)"
  else
    git clone --quiet "$1" "$2" && echo "  cloned $1 -> $2" || { echo "  !! could not clone $1"; FAILED+=("clone $1"); }
  fi
}
sync_repo "$GH/autoclip-pipeline" "$HOME/autoclip-pipeline"
sync_repo "$GH/takekash-site" "$HOME/takekash-site-live"
gh auth status >/dev/null 2>&1 && sync_repo "$GH/q" "$HOME/q"
mkdir -p "$HOME/autoclip-pipeline/projects" "$HOME/autoclip-pipeline/outputs" "$HOME/autoclip-pipeline/logs"
chmod +x "$HOME"/autoclip-pipeline/*.sh "$HOME"/autoclip-pipeline/skills/*/run.sh 2>/dev/null || true

step "8/9 Python env, website deps, dashboard service, SEO engine"
cd "$HOME/autoclip-pipeline" || exit 1
try bash fix_pipeline_venv.sh
# extras the SaaS server, worker, studio and tests import that fix_pipeline_venv.sh doesn't cover
try ./venv_pipeline/bin/pip install --prefer-binary --quiet -r web/requirements.txt -r worker/requirements.txt cryptography pytest
[[ -f "$HOME/takekash-site-live/package.json" ]] && (cd "$HOME/takekash-site-live" && try npm install --silent)
try bash "$HOME/autoclip-pipeline/scripts/sync_seo_engine.sh" "$HOME/takekash-site-live"
# .env template (gitignored) so keys have one home
if [[ ! -f .env ]]; then
  cat > .env <<'EOF'
# Fill these in, then: source ~/.zshrc  (setup adds an auto-loader)
ANTHROPIC_API_KEY=
QUEUE_SECRET=
REDIS_URL=redis://localhost:6379/0
EOF
fi
grep -q 'autoclip-pipeline/.env' "$HOME/.zshrc" 2>/dev/null || \
  echo '[ -f "$HOME/autoclip-pipeline/.env" ] && set -a && . "$HOME/autoclip-pipeline/.env" && set +a' >> "$HOME/.zshrc"
set -a; . ./.env; set +a
brew services start redis >/dev/null 2>&1 || true

step "9/9 Checks"
cd "$HOME/autoclip-pipeline" || exit 1
./venv_pipeline/bin/python3 tests/test_seo_finalize.py 2>&1 | tail -1
./venv_pipeline/bin/python3 -c "import cv2, faster_whisper, anthropic, fastapi, celery, yt_dlp; print('python deps OK')"
./venv_pipeline/bin/python3 check_setup.py 2>&1 | tail -15
for t in ffmpeg ffprobe tesseract yt-dlp magick redis-server node npm gh eas railway netlify vercel stripe shopify claude docker; do
  command -v "$t" >/dev/null && printf '  OK    %s\n' "$t" || printf '  MISS  %s\n' "$t"
done
[[ -n "${ANTHROPIC_API_KEY:-}" ]] && echo "  OK    ANTHROPIC_API_KEY" || echo "  TODO  put ANTHROPIC_API_KEY in ~/autoclip-pipeline/.env"
[[ -d "$HOME/autoclip-pipeline/takekash-app" ]] || echo "  NOTE  takekash-app (Expo) was never pushed to GitHub; copy it from the old Mac into ~/autoclip-pipeline/takekash-app"

echo
if [[ ${#FAILED[@]} -eq 0 ]]; then echo "ALL DONE. Log: ~/mac_setup.log"
else echo "Done with ${#FAILED[@]} failure(s) (re-run the same command to retry just those):"; printf '  - %s\n' "${FAILED[@]}"; fi
echo "Sign-ins to finish once: eas login (account takekash) | railway login | netlify login | vercel login | stripe login | shopify auth"
