#!/bin/sh
# The precompiled assets of the pinned Rails app (Propshaft's output, with
# digests in their names), copied out of the reference image that
# once-campfire-verification's bin/seed builds. Usage: script/assets.sh DIR
set -eu
image=${REFERENCE_IMAGE:-once-campfire-verification:reference-90b3300}
out=$1
rm -rf "$out"
mkdir -p "$(dirname "$out")"
id=$(docker create "$image")
docker cp "$id:/rails/public/assets" "$out"
docker rm "$id" >/dev/null
