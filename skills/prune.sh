#!/usr/bin/env bash
set -euo pipefail
# args: <job>
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../lib/common.sh"

job="$1"

# Removes bulky intermediate render work once outputs/<job>.final.mp4 exists —
# keeps job.json + the small plan/script JSON artifacts (useful for
# debugging/re-render) but drops the per-step video files and scratch audio.
final="${PIPELINE_ROOT}/outputs/${job}.final.mp4"
if [[ ! -f "$final" ]]; then
  echo "prune: refusing to prune — outputs/${job}.final.mp4 doesn't exist yet" >&2
  exit 1
fi

work_dir="$(job_work_dir "$job")"
removed=0
for f in \
  "$(job_dir "$job")/rough-cut/rough_cut.mp4" \
  "$(job_dir "$job")/graphics/graphics_cut.mp4" \
  "$(job_dir "$job")/captions/captions_cut.mp4" \
  "$(job_dir "$job")/music-out/scored_cut.mp4"
do
  if [[ -f "$f" ]]; then
    rm -f "$f"
    removed=$((removed + 1))
  fi
done
if [[ -d "$work_dir" ]]; then
  rm -rf "$work_dir"
fi

log "prune: removed ${removed} intermediate render(s) + scratch work dir for job '${job}'"
