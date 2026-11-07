# Benchmark

once-campfire-verification's benchmark (`bin/benchmark`), run from
[femto's fork](https://github.com/femto/once-campfire-verification/tree/egg),
whose `egg` branch adds these apps. The runs below predate 2026-11-07, when
the image started caching by default; `egg` here is the image with
`CAMPFIRE_CACHE=0`.

- `egg`: rendering every page;
- `egg-cache`: the same image with `CAMPFIRE_CACHE=1`, which keeps whole
  responses per worker (src/respcache.egg), as once-campfire-rust's
  response cache does for the whole process, and messages' HTML
  (src/fragcache.egg) and gzipped pages in pieces (src/splice.egg), as
  Rust's fragment cache and splicing deflater do (the runs below predate
  these two);
- `egg-fragments` and `rust-fragments`: the two without whole responses
  (`CAMPFIRE_RESPONSE_CACHE=0`, `CAMPFIRE_RESPONSE_CACHE_MB=0`), to compare
  what a page costs after a commit.

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

## Local: OrbStack Linux VM, 4 + 4 cores

2026-11-04, commit `b7c7d16` (before src/filecache.egg, so Egg still read
and gzipped the CSS and read the avatar on every request), `~/bench/run.sh`
in an OrbStack Ubuntu machine on an Intel i7-9700K (8 cores, 2018) Mac: the
apps on CPUs 0-3, the load generator on 4-7, as the published comparison
splits its cores, with host networking inside the VM. macOS cannot reserve
the cores, so other work on the Mac shares them: rounds differ by up to
about 20%.

Median requests/second over 3 rounds:

| route | Rust | Egg | Egg, cached |
| --- | ---: | ---: | ---: |
| room page | 13121 | 1410 | 59800 |
| messages page | 12075 | 1864 | 59695 |
| sidebar | 14627 | 7704 | 64253 |
| search | 13758 | 3518 | 56033 |
| avatar | 44806 | 60067 | 63582 |
| static CSS | 56112 | 63956 | 63633 |
| /up | 23429 | 113103 | 127918 |
| post a message | 1677 | 1703 | 1519 |

To run it again (in the VM, with this repo, the fork's `egg` branch and
once-campfire-rust under `~/bench`):

```sh
cd ~/bench/once-campfire-egg && git pull
~/bench/run.sh > ~/bench/run.log 2>&1   # APPS, ROUNDS, DURATION to change them
tail -16 ~/bench/run.log
```

## Action Cable fan-out: 1000 WebSockets

`loadgen cable` (once-campfire-verification's load generator), 2026-11-06,
commit `aa35d59` (Egg `8f14ee6`), in the same OrbStack VM, apps on CPUs
0-3, the load generator on 4-7, host networking, a fresh seed each; Rust
and Egg in turn within the hour. 1000 clients, each subscribed as a room
page is (the busy room's messages, presence, unread rooms, heartbeat); 30
posts at a steady pace, then 4 posters as fast as they can for 15 s. Every
message is checked to reach every client.

| | Rust | Egg |
| --- | ---: | ---: |
| clients ready / failed | 1000 / 0 | 1000 / 0 |
| paced: to every client, p50 / p99 | 12.4 / 33.8 ms | 13.0-13.4 / 20.4-40.4 ms |
| saturated: messages delivered to all a second | 178 | 195-222 |
| saturated: to every client, p50 / p99 | 37 / 185 ms | 51-56 / 166-196 ms |
| messages not reaching every client | 0 | 0 |
| memory, peak | 134 MiB | 35-39 MiB |
| threads, peak | 18 | 39 |

Egg's ranges are two runs; runs on this VM differ by 10-20%, so the two
are level rather than one ahead. Egg serves its sockets from
`CAMPFIRE_CABLE_LOOPS` event loops (4 here), each a thread with a
`net.poller()`. The script is `~/bench/cable.sh APP IMAGE PORT` in the VM.

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
