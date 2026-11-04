#!/bin/sh
# Compares the Egg app's pages with once-campfire-rust's, byte for byte.
# Both run on copies of the same seed and sign in as David; the Egg app's
# host is put back to Rust's before comparing. No User-Agent is sent, as
# the benchmark's load generator sends none.
#   script/compare.sh EGG_URL RUST_URL STORAGE
# STORAGE is the seed (labels.json, reference.env).
set -eu
egg=$1 rust=$2 storage=$3
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
password=$(grep ^VERIFICATION_PASSWORD= "$storage/reference.env" | cut -d= -f2-)
label() { ruby -rjson -e 'puts JSON.parse(File.read(ARGV[0])).fetch(ARGV[1])' "$storage/labels.json" "$1"; }
email=$(label emails.david)
for side in egg rust; do
  eval base=\$$side
  curl -s -H 'User-Agent:' -c "$tmp/$side.jar" -o /dev/null --data-urlencode "email_address=$email" --data-urlencode "password=$password" "$base/session"
done
room=$(label rooms.watercooler)
status=0
for path in "/rooms/$room" "/rooms/$room/messages?before=$(label messages.busy_060)" "/rooms/$room/messages" "/rooms/$(label rooms.hq)"; do
  curl -s -H 'User-Agent:' -b "$tmp/egg.jar" "$egg$path" | sed "s#$egg#$rust#g" > "$tmp/egg.html"
  curl -s -H 'User-Agent:' -b "$tmp/rust.jar" "$rust$path" > "$tmp/rust.html"
  if cmp -s "$tmp/egg.html" "$tmp/rust.html"; then
    echo "same  $path ($(wc -c < "$tmp/rust.html") bytes)"
  else
    echo "DIFF  $path"
    diff "$tmp/egg.html" "$tmp/rust.html" | head -20
    status=1
  fi
done
exit $status
