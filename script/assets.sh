#!/bin/sh
# The precompiled assets the pages link to: those of the pinned Rails app
# (Propshaft's output, digests in their names), copied out of the reference
# image that once-campfire-verification's bin/seed builds, plus the four
# once-campfire-rust overrides in vendor/rust-assets.
#   script/assets.sh DIR
set -eu
image=${REFERENCE_IMAGE:-once-campfire-verification:reference-90b3300}
out=$1
if [ -e "$out" ]; then
  echo "$out exists; remove it first" >&2
  exit 1
fi
mkdir -p "$(dirname "$out")"
out=$(cd "$(dirname "$out")" && pwd)/$(basename "$out")
id=$(docker create "$image")
docker cp "$id:/rails/public/assets" "$out"
docker rm "$id" >/dev/null
(cd "$(dirname "$0")/../vendor/rust-assets" && find . -name '*.js' | while read -r file; do
  mkdir -p "$out/$(dirname "$file")"
  cp "$file" "$out/$file"
done)
