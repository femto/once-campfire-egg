#!/bin/sh
# The precompiled assets the pages link to: those of the pinned Rails app
# (Propshaft's output, digests in their names), copied out of the reference
# image that once-campfire-verification's bin/seed builds, plus the files
# once-campfire-rust overrides (crates/assets/overrides), which only its
# binary holds: any /assets/ path a page from RUST_URL links to that the
# Rails app lacks is downloaded from it.
#   script/assets.sh DIR [RUST_URL]
set -eu
image=${REFERENCE_IMAGE:-once-campfire-verification:reference-90b3300}
out=$1
rust=${2:-}
if [ -e "$out" ]; then
  echo "$out exists; remove it first" >&2
  exit 1
fi
mkdir -p "$(dirname "$out")"
id=$(docker create "$image")
docker cp "$id:/rails/public/assets" "$out"
docker rm "$id" >/dev/null
if [ -n "$rust" ]; then
  # The sign-in page needs no session and links every stylesheet and script.
  curl -sf "$rust/session/new" | grep -o '/assets/[^"]*' | sort -u | while read -r path; do
    file="$out/${path#/assets/}"
    if [ ! -f "$file" ]; then
      mkdir -p "$(dirname "$file")"
      curl -sf -o "$file" "$rust$path"
      echo "from Rust: $path"
    fi
  done
fi
