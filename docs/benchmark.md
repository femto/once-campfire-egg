# Benchmark

once-campfire-verification's benchmark (`bin/benchmark`), run from
[femto's fork](https://github.com/femto/once-campfire-verification/tree/egg),
whose `egg` branch adds two apps:

- `egg`: this app's image as it is, rendering every page;
- `egg-cache`: the same image with `CAMPFIRE_CACHE=1`, which keeps whole
  responses per worker (src/respcache.egg), as once-campfire-rust's
  response cache does for the whole process.

Every app runs the same route contracts on the same Rails-built seed, in
alternating rounds, and a run fails on any invalid response or any
acknowledged write that is not in the database and the search index exactly
as posted. All requests are David's, with gzip, from 16 clients; 2 s of
warmup, then 8 s per sample.

`rust` is once-campfire-rust's published image
(`ghcr.io/basecamp/once-campfire-rust:main`, revision `6dae2fd`), with its
caches.

## GitHub Actions, ubuntu-latest, 2 + 2 cores

[Run 41987883777](https://github.com/femto/once-campfire-egg/actions/runs/41987883777),
2026-11-05, commit `f9ae6bf`, from `.github/workflows/benchmark.yml`. The
runner has 4 CPUs: the apps get 2 (`--cpus 0-1`) and the load generator 2
(`--client-cpus 2-3`), on a shared virtual machine whose hardware changes
from run to run. Compare apps within a run, not across runs or with the
published results.

Median requests/second over 2 rounds:

| route | Rust | Egg | Egg, cached |
| --- | ---: | ---: | ---: |
| room page | 12710 | 592 | 41833 |
| messages page | 12553 | 783 | 43399 |
| sidebar | 14287 | 3888 | 51243 |
| search | 14138 | 1755 | 50540 |
| avatar | 47899 | 51165 | 50559 |
| static CSS | 48060 | 108952 | 108761 |
| /up | 16177 | 112253 | 111849 |
| post a message | 1818 | 1963 | 1771 |

## Reading them

- Uncached, Egg renders and gzips every page: the room page is 416 KB of
  HTML, deflated whole each time (zlib-ng, level 6). Rust answers these
  reads from its response cache, and even on a miss splices message
  fragments it compressed before.
- Cached, both serve the four pages from memory after signing in and
  checking room access; Egg's cache is per worker and takes no lock.
- Avatar and CSS: each Egg worker keeps an asset's or an avatar's response
  as it sent it, gzipped or not (src/filecache.egg), since a digested asset
  name or an Active Storage blob key never changes content; a repeat
  request still signs in and looks up the avatar's blob, but reads no file
  and compresses nothing. Rust sends the avatar from disk (`send_file`) and
  the CSS from its binary, which embeds the assets, gzipping it on every
  request as Rack::Deflater does.
- Posting: the two are on par. The Rust app also broadcasts the message
  over Action Cable, queues Web Push and calls bots' webhooks after it
  answers; Egg does none of these yet (see PLAN.md).
- The benchmark measures one user's identical requests. It does not measure
  how many users or connections an app holds, nor WebSockets.
