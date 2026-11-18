#!/usr/bin/env bash
# Prints the release notes for one version from CHANGELOG.md: everything under
# the version's "## [X.Y.Z]" heading, up to the next "## " heading. The release
# workflow (.github/workflows/release.yml) uses this text for the GitHub Release.
# Preview it before you tag a release:
#   scripts/release-notes.sh 0.2.0
set -euo pipefail

version="${1:?Usage: scripts/release-notes.sh VERSION, for example 0.2.0}"

# Work from the repository root, wherever the script was started from.
cd "$(dirname "$0")/.."

notes="$(awk -v heading="## [$version]" '
  index($0, heading) == 1 { found = 1; next } # this version: start after its heading
  !found { next }                             # before it: skip
  /^## / { exit }                             # the next version: stop
  /^\[[^]]+\]: / { exit }                     # the list of links at the end: stop
  !started && /^[[:space:]]*$/ { next }       # skip blank lines before the first text
  { started = 1; print }
' CHANGELOG.md)"

# No section, or a section without any text, is an error.
if [ -z "$notes" ]; then
  echo "CHANGELOG.md has no notes under a '## [$version]' heading." >&2
  exit 1
fi
printf '%s\n' "$notes"
