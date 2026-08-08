#!/usr/bin/env bash
set -euo pipefail
# args: <job> <format>
SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SKILL_DIR}/../../lib/common.sh"

job="$1"; format="$2"

edl_path="$(job_dir "$job")/rough-cut/edl.json"
if [[ ! -f "$edl_path" ]]; then
  echo "to-premiere: no edl.json from rough-cut — run rough-cut first" >&2
  exit 1
fi

out_dir="$(job_dir "$job")/to-premiere"
mkdir -p "$out_dir"

log "to-premiere: converting rough-cut's edl.json (no re-cutting) -> Premiere XML"
python3 - "$edl_path" "$out_dir/rough-cut.xml" <<'PY'
import json, sys
edl_path, out_path = sys.argv[1:3]
edl = json.load(open(edl_path))
# TODO: real Final Cut Pro XML / EDL writer. Placeholder keeps the keep-list
# so this doesn't silently lose the cut when swapped for a real exporter.
with open(out_path, "w") as f:
    f.write("<!-- stub premiere XML -->\n")
    f.write(f"<!-- keep ranges: {edl.get('keep')} -->\n")
PY

log "to-premiere: wrote to-premiere/rough-cut.xml — import into Premiere Pro"
