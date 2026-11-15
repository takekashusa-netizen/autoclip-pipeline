#!/usr/bin/env bash
# Keep lib/seo_engine/engine.cjs identical to the website's copy (takekash-site/lib/seo/engine.cjs).
# Usage: scripts/sync_seo_engine.sh [path-to-takekash-site]   (default ~/takekash-site-live, then ~/takekash-site)
set -euo pipefail
here="$(cd "$(dirname "$0")/.." && pwd)"
site="${1:-}"
for c in "$site" "$HOME/takekash-site-live" "$HOME/takekash-site"; do
  [[ -n "$c" && -f "$c/lib/seo/engine.cjs" ]] && { site="$c"; break; }
done
[[ -f "$site/lib/seo/engine.cjs" ]] || { echo "takekash-site not found; pass its path"; exit 1; }
if cmp -s "$site/lib/seo/engine.cjs" "$here/lib/seo_engine/engine.cjs"; then echo "seo engine already in sync"; else
  cp "$site/lib/seo/engine.cjs" "$here/lib/seo_engine/engine.cjs"; echo "seo engine updated from $site"; fi
