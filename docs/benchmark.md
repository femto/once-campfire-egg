# Benchmark

once-campfire-verification's benchmark (`bin/benchmark`), run from
[femto's fork](https://github.com/femto/once-campfire-verification/tree/egg),
whose `egg` branch adds two apps:

- `egg`: this app's image as it is, rendering every response;
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

## GitHub Actions, ubuntu-latest

[Run 41799108184](https://github.com/femto/once-campfire-egg/actions/runs/41799108184),
2026-11-04, from `.github/workflows/benchmark.yml`. The runner has 4 CPUs:
the apps get 2 (`--cpus 0-1`) and the load generator 2 (`--client-cpus 2-3`),
on a shared virtual machine. The numbers compare these apps with each other;
they are not comparable with the published results (4 dedicated cores each
for the app and the generator, on a faster machine).

Median requests/second over 2 rounds (each round's figure within 10% of the
other's):

| route | Rust | Egg | Egg, cached |
| --- | ---: | ---: | ---: |
| room page | 21863 | 815 | 58959 |
| messages page | 21259 | 1091 | 59483 |
| sidebar | 24438 | 6983 | 70334 |
| search | 24393 | 2574 | 70388 |
| avatar | 63676 | 51182 | 52716 |
| static CSS | 66803 | 43844 | 44925 |
| /up | 30873 | 156138 | 157771 |
| post a message | 2642 | 1766 | 1800 |

## Reading them

- Uncached, Egg renders and gzips every page: the room page is 416 KB of
  HTML, deflated whole each time (zlib-ng, level 6). Rust answers these
  reads from its response cache, and even on a miss splices message
  fragments it compressed before.
- Cached, both serve the four pages from memory after signing in and
  checking room access; Egg's cache is per worker and takes no lock.
- Avatar and CSS: Egg reads the file on every request; Rust serves them
  from memory.
- Posting: the Rust app also broadcasts the message over Action Cable,
  queues Web Push and calls bots' webhooks after it answers; Egg does none
  of these yet (see PLAN.md), and still posts fewer per second.
- The benchmark measures one user's identical requests. It does not measure
  how many users or connections an app holds, nor WebSockets.
