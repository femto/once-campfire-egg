#!/bin/sh
# Rough local throughput of the benchmark's read routes, Rust against Egg,
# with once-campfire-verification's load generator: CONC connections for
# SECS seconds per route, gzip unless GZIP=0, signed in as David.
#   script/bench.sh EGG_URL RUST_URL STORAGE
set -eu
egg=$1 rust=$2 storage=$3
lg=${LOADGEN:-$HOME/git/once-campfire-verification/loadgen/target/release/loadgen}
conc=${CONC:-16} secs=${SECS:-4} gzip=${GZIP:-1}
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
label() { ruby -rjson -e 'puts JSON.parse(File.read(ARGV[0])).fetch(ARGV[1])' "$storage/labels.json" "$1"; }
password=$(grep ^VERIFICATION_PASSWORD= "$storage/reference.env" | cut -d= -f2-)
"$lg" login --base "$rust" --email "$(label emails.david)" --password "$password" > "$tmp/rust.login"
"$lg" login --base "$egg" --email "$(label emails.david)" --password "$password" > "$tmp/egg.login"
room=$(label rooms.watercooler)
printf "%-18s %9s %9s %8s %8s\n" route rust_rps egg_rps rust_p50 egg_p50
for route in "/rooms/$room" "/rooms/$room/messages?before=$(label messages.busy_060)" /users/me/sidebar "/searches?q=coffee" "/users/$(label avatar_tokens.jason)/avatar" /assets/_reset-9c3efd7b.css /up; do
  for side in rust egg; do
    eval base=\$$side
    cookie=$(ruby -rjson -e 'puts JSON.parse(File.read(ARGV[0])).fetch("cookie")' "$tmp/$side.login")
    "$lg" http --base "$base" --cookie "$cookie" --path "$route" --conc "$conc" --duration "$secs" --gzip "$gzip" > "$tmp/$side.json"
  done
  ruby -rjson -e '
    r, e = ARGV[1, 2].map { |f| JSON.parse(File.read(f)) }
    bad = [r, e].any? { |d| d["errors"] != 0 || d["invalid_responses"] != 0 } ? " ERRORS" : ""
    printf("%-18s %9.0f %9.0f %8.2f %8.2f%s\n", ARGV[0][0, 18], r["rps"], e["rps"], r["latency"]["p50_ms"], e["latency"]["p50_ms"], bad)' "$route" "$tmp/rust.json" "$tmp/egg.json"
done
