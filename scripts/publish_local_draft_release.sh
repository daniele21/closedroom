#!/usr/bin/env bash
# Prepare and upload a qualified local macOS artifact as a draft GitHub Release.
# Never run inside GitHub Actions; no build occurs in this script.
set -euo pipefail
if [[ "${GITHUB_ACTIONS:-}" == "true" ]]; then
  echo "Draft release staging must run on the release Mac, not GitHub Actions" >&2
  exit 1
fi
if [[ "$#" -ne 4 ]]; then
  echo "Usage: $0 <vX.Y.Z> <exact-tag-sha> <production-artifact-dir> <stable|prerelease>" >&2
  exit 2
fi
tag="$1"
revision="$2"
artifact_dir="$3"
release_state="$4"
repo="daniele21/closedroom"
[[ "$tag" =~ ^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$ ]] || { echo "Invalid release tag" >&2; exit 1; }
[[ "$revision" =~ ^[0-9a-f]{40}$ ]] || { echo "Exact source SHA required" >&2; exit 1; }
[[ "$release_state" == "stable" || "$release_state" == "prerelease" ]] || { echo "Invalid release state" >&2; exit 1; }
[[ -d "$artifact_dir" ]] || { echo "Missing local qualified artifact directory" >&2; exit 1; }
command -v gh >/dev/null || { echo "Install and authenticate gh locally" >&2; exit 1; }
command -v jq >/dev/null || { echo "Install jq locally" >&2; exit 1; }
[[ "$(git rev-parse HEAD)" == "$revision" ]] || { echo "Checkout must match release SHA" >&2; exit 1; }
[[ -z "$(git status --porcelain)" ]] || { echo "Release source checkout must be clean" >&2; exit 1; }
git fetch origin main --tags
[[ "$(git rev-parse "refs/tags/${tag}^{commit}")" == "$revision" ]] || { echo "Tag/SHA mismatch" >&2; exit 1; }
git merge-base --is-ancestor "$revision" origin/main || { echo "Source is not in main history" >&2; exit 1; }
python3 scripts/product_version.py --root . --expect-tag "$tag"
notes="docs/releases/${tag}.md"
[[ -f "$notes" ]] || { echo "Missing curated release notes" >&2; exit 1; }
if gh release view "$tag" --repo "$repo" >/dev/null 2>&1; then
  echo "Release already exists; refusing to overwrite assets" >&2
  exit 1
fi
output_dir="dist/github-release/${tag}"
python3 scripts/prepare_github_release.py \
  --root . --artifact-dir "$artifact_dir" --tag "$tag" \
  --source-revision "$revision" --notes-source "$notes" \
  --release-state "$release_state" --output-dir "$output_dir"
plan="$output_dir/release-plan.json"
jq -e --arg tag "$tag" --arg source "$revision" \
  '.draft == true and .tag == $tag and .source_revision == $source and (.assets | length) == 4' \
  "$plan" >/dev/null
files=()
while IFS= read -r name; do files+=("$name"); done < <(jq -r '.assets[].name' "$plan")
for name in "${files[@]}"; do
  [[ -f "$output_dir/assets/$name" ]] || { echo "Missing staged asset: $name" >&2; exit 1; }
done
args=(release create "$tag" --repo "$repo" --draft --verify-tag
      --title "ClosedRoom $tag" --notes-file "$output_dir/RELEASE_NOTES.md")
if [[ "$release_state" == "prerelease" ]]; then args+=(--prerelease); fi
for name in "${files[@]}"; do args+=("$output_dir/assets/$name"); done
gh "${args[@]}"
# Re-read GitHub's release record: uploaded bytes must match qualified staging.
release_json="$(gh api -H 'X-GitHub-Api-Version: 2026-03-10' "repos/${repo}/releases/tags/${tag}")"
expected_prerelease=false
if [[ "$release_state" == "prerelease" ]]; then expected_prerelease=true; fi
jq -e --arg tag "$tag" --arg title "ClosedRoom $tag" \
  --argjson prerelease "$expected_prerelease" \
  '.draft == true and .tag_name == $tag and .name == $title and .prerelease == $prerelease' \
  <<<"$release_json" >/dev/null || { echo "Draft release identity mismatch" >&2; exit 1; }
expected_assets="$(jq -r '.assets[] | [.name, (.bytes | tostring), ("sha256:" + .sha256)] | @tsv' "$plan" | sort)"
actual_assets="$(jq -r '.assets[] | [.name, (.size | tostring), (.digest // "")] | @tsv' <<<"$release_json" | sort)"
[[ "$expected_assets" == "$actual_assets" ]] || {
  echo "GitHub Release asset name, byte count or SHA-256 digest mismatch" >&2
  exit 1
}
echo "Created verified DRAFT GitHub Release $tag from local qualified artifact; publication remains manual."
