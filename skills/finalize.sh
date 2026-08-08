#!/usr/bin/env bash
set -euo pipefail
# args: <job>
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../lib/common.sh"

job="$1"

# Walk the pipeline's artifact chain backwards to find the last real output —
# lets finalize work whether or not background-music/captions actually ran
# (e.g. long-form skips captions, --skip-music skips scoring).
for candidate in \
  "$(job_dir "$job")/music-out/scored_cut.mp4" \
  "$(job_dir "$job")/captions/captions_cut.mp4" \
  "$(job_dir "$job")/graphics/graphics_cut.mp4" \
  "$(job_dir "$job")/rough-cut/rough_cut.mp4"
do
  if [[ -f "$candidate" ]]; then
    src="$candidate"
    break
  fi
done

if [[ -z "${src:-}" ]]; then
  echo "finalize: no rendered output found for job '${job}' — did earlier steps run?" >&2
  exit 1
fi

dest="${PIPELINE_ROOT}/outputs/${job}.final.mp4"
mkdir -p "${PIPELINE_ROOT}/outputs"
cp "$src" "$dest"
state_set "$job" "artifacts.final_output" "\"outputs/${job}.final.mp4\""
log "finalize: promoted $(basename "$src") -> outputs/${job}.final.mp4"
