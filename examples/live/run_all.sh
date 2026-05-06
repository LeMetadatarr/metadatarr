#!/usr/bin/env bash
# Run every metadatarr live check; report PASS/FAIL/SKIP per check.
# Live providers may flake on upstream rate-limits or HTML changes.

set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
cd "$ROOT"

CHECKS=(
    # Offline / pure-model smoke
    "license"
    "helpers"
    "programme_schedule"
    "release_relation"
    # Live providers (no auth)
    "anilist"
    "jikan"
    "google_books"
    "openlibrary"
    "librivox"
    "apple_podcasts"
    "tvmaze"
)

declare -a PASSED FAILED SKIPPED
EXIT=0

for name in "${CHECKS[@]}"; do
    script="$HERE/check_${name}.py"
    [[ -f "$script" ]] || continue
    echo
    echo "==> $name"
    set +e
    out=$(cd "$HERE" && python "check_${name}.py" 2>&1)
    code=$?
    set -e
    echo "$out"
    if [[ $code -ne 0 ]]; then
        FAILED+=("$name"); EXIT=1
    elif echo "$out" | grep -q "^SKIP"; then
        SKIPPED+=("$name")
    else
        PASSED+=("$name")
    fi
done

echo
echo "================================="
echo "PASSED:  ${PASSED[*]:-(none)}"
echo "SKIPPED: ${SKIPPED[*]:-(none)}"
echo "FAILED:  ${FAILED[*]:-(none)}"
echo "================================="
exit $EXIT
