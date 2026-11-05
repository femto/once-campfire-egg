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

Both runs below are of commit `b7c7d16`, after two fixes the first runs
found: posts from 16 clients at once sometimes failed (SQLite's lock
waiting is not fair; writers now take turns through a channel), and each
commit was synced to disk (connections now get Rails' settings, among them
`synchronous=NORMAL`).

## Local: OrbStack Linux VM, 4 + 4 cores

2026-11-04, `~/bench/run.sh` in an OrbStack Ubuntu machine on an Intel
i7-9700K (8 cores, 2018) Mac: the apps on CPUs 0-3, the load generator on
4-7, as the published comparison splits its cores, with host networking
inside the VM. macOS cannot reserve the cores, so other work on the Mac
shares them: rounds differ by up to about 20%.

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

## GitHub Actions, ubuntu-latest, 2 + 2 cores

[Run 41828621264](https://github.com/femto/once-campfire-egg/actions/runs/41828621264),
2026-11-04, from `.github/workflows/benchmark.yml`. The runner has 4 CPUs:
the apps get 2 (`--cpus 0-1`) and the load generator 2 (`--client-cpus 2-3`),
on a shared virtual machine whose hardware changes from run to run (Rust's
room page was 21863 req/s in an earlier run, 12784 in this one). Compare
apps within a run, not across runs or with the published results.

Median requests/second over 2 rounds (reads within 3% of each other;
posting varies more):

| route | Rust | Egg | Egg, cached |
| --- | ---: | ---: | ---: |
| room page | 12784 | 593 | 42236 |
| messages page | 12654 | 785 | 43465 |
| sidebar | 14269 | 3987 | 51442 |
| search | 14216 | 1775 | 50851 |
| avatar | 45166 | 32561 | 32682 |
| static CSS | 48356 | 29835 | 29966 |
| /up | 16832 | 110646 | 110718 |
| post a message | 1801 | 2187 | 1898 |

## After `f9ae6bf`: assets and avatars kept as sent

Each worker keeps an asset's or an avatar's response as it sent it, gzipped
or not (src/filecache.egg): a digested asset name and an Active Storage
blob key never change content, so nothing invalidates them. A repeat
request reads no file and compresses nothing; it still signs in and looks
up the avatar's blob.

[Run 41987883777](https://github.com/femto/once-campfire-egg/actions/runs/41987883777),
2026-11-05, ubuntu-latest, 2 + 2 cores, all routes, median of 2 rounds:

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

The local VM (4 + 4 cores), Rust and Egg on these three routes only,
median of 3 rounds:

| route | Rust | Egg |
| --- | ---: | ---: |
| avatar | 38661 | 57860 |
| static CSS | 47960 | 122742 |
| /up | 22028 | 121123 |

## Reading them

- Uncached, Egg renders and gzips every page: the room page is 416 KB of
  HTML, deflated whole each time (zlib-ng, level 6). Rust answers these
  reads from its response cache, and even on a miss splices message
  fragments it compressed before.
- Cached, both serve the four pages from memory after signing in and
  checking room access; Egg's cache is per worker and takes no lock.
- Avatar and CSS, at `b7c7d16`: Egg read the file and gzipped the CSS on
  every request. Rust sends the avatar from disk (`send_file`) and the CSS
  from its binary, which embeds the assets, gzipping it each time as
  Rack::Deflater does. Which was faster depended on the machine (Egg on the
  local VM, Rust on the runner). Since `f9ae6bf` each Egg worker keeps an
  asset's or an avatar's response as sent (src/filecache.egg); see below.
- Posting: the two are on par. The Rust app also broadcasts the message
  over Action Cable, queues Web Push and calls bots' webhooks after it
  answers; Egg does none of these yet (see PLAN.md).
- The benchmark measures one user's identical requests. It does not measure
  how many users or connections an app holds, nor WebSockets.
