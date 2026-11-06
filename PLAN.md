# once-campfire-egg

ONCE Campfire in Egg, measured with basecamp/once-campfire-verification
against the Rails, Go, Rust and C ports. The reference is
basecamp/once-campfire-rust (checked out beside this repo); Go is the
second reference.

## Phase 1: the benchmark routes

What `bin/benchmark` in once-campfire-verification needs, passing its
contracts (bench/contracts.rb) on its Rails-built seed:

| route | contract |
| --- | --- |
| `POST /session` | loadgen logs in with email and password: bcrypt check, signed `session_token` cookie |
| `GET /rooms/:id` | full HTML page; the newest 40 message ids in order, each message's DOM id and words |
| `GET /rooms/:id/messages?before=` | the 40 before the anchor, same checks |
| `GET /users/me/sidebar` | full page with `shared_rooms` and every visible open room's name |
| `GET /searches?q=coffee` | full page; FTS5 matches in the user's rooms, newest 100 |
| `GET /users/:token/avatar` | the stored image, exact bytes |
| `GET <css>` | the stylesheet, exact bytes |
| `GET /up` | `background-color: green` |
| `POST /rooms/:id/messages` | turbo-stream `append` to the room's messages target; the write audited in SQLite and FTS |

Pieces, each a module in this repo unless it belongs in Egg's std:

1. SQLite (from egg's examples/ffi/sqlite), prepared statements kept per worker
2. HTTP/1.1 server with keep-alive and a worker pool (from egg's examples/http_server)
3. Rails compatibility: signed cookies (PBKDF2-SHA256 key, HMAC), bcrypt, Base64, JSON
4. HTML rendering of the room page, messages, sidebar and search, after the Rust Askama templates
5. gzip (zlib) for responses that ask for it
6. A Linux Docker image, as the harness runs every app from one

C libraries come through `extern fn`: sqlite3, zlib, libcrypto, and a
bcrypt implementation (crypt_blowfish, public domain, as the bcrypt gem
vendors it).

Rails' signed `session_token` cookie, from once-campfire-rust's
rails_compat: the value is the JSON string of the token, in the legacy
envelope `{"_rails":{"message":<base64>,"exp":<iso8601 ms>,"pur":"cookie.session_token"}}`,
strict Base64, then `--` and the hex HMAC-SHA1 of that Base64 under
PBKDF2-HMAC-SHA256(SECRET_KEY_BASE, "signed cookie", 1000 rounds, 64 bytes),
and Rack-escaped on the wire.

## Status

- `GET /up` serves; the worker pool opens the seed's SQLite
- written, checked against Ruby (src/units_test.egg): codec (Base64, hex,
  form and cookie escaping), timefmt (DB, ISO 8601, HTTP dates)
- sign-in: `GET /session/new`, `POST /session` (bcrypt, a sessions row with a
  base58 token, a Rails-signed `session_token` cookie that Ruby's OpenSSL
  verifies, 302); `session.current_user` reads the cookie back
- `GET /rooms/:id` and `GET /rooms/:id/messages?before=`: byte for byte
  what once-campfire-rust serves on the seed (script/compare.sh), from
  templates/ compiled to src/views.egg by script/templates.rb
- `GET /users/me/sidebar`: the same, for David, Kevin, JZ and Lonely Lou
  (`CAMPFIRE_USER=kevin script/compare.sh ...`); rooms a user is not in
  redirect to / and their message pages are Rails' 404 page, as in Rust
- `GET /searches?q=`: the same, with blank, empty, punctuated and
  no-match queries; direct rooms' pages too (names, "Ping with")
- `GET /users/:signed_id/avatar` (a processed :square variant) and
  `GET /assets/*`: the same bytes; script/assets.sh adds Rust's four
  overridden JS files to the Rails assets
- `POST /rooms/:id/messages`: the same turbo-stream (but for times and
  ids), body, search entry and unread marks as Rust; forgery checked by
  Origin and Sec-Fetch-Site as Rust does (422 page)
- gzip (zlib, level 6, bodies of 1 KB or more but not compressed images),
  as the Rust app's Rack::Deflater rules; the Rust app splices fragments it
  compressed before, so its room page is 24 KB gzipped against Egg's 21 KB
- Dockerfile: egg at a pinned commit, the app on debian-slim, laid out
  as once-campfire-rust's image (/rails, storage mounted at
  /rails/storage/{db,files}); `docker build -t once-campfire-egg:app .`
  after script/assets.sh build/assets RUST_URL. Its pages match Rust's.
- the benchmark: .github/workflows/benchmark.yml (manual) runs
  femto/once-campfire-verification's egg branch (apps egg and egg-cache)
  against once-campfire-rust's published image on ubuntu-latest

The pages follow once-campfire-rust's HTML, not Rails': no CSRF tokens (Rust
checks Sec-Fetch-Site), and the copy-link button carries a path, which two of
Rust's JS files expect. So the assets to serve are Rust's, not the Rails
image's (script/assets.sh still copies Rails').

Not yet like Rust (none of it is in the benchmark's rooms): the invitation in the first room while
it has under a page of messages, notification help for a User-Agent (the
page has the text for none), attachments and rich text rendering (bodies go
out as stored, which matches every message in the benchmark room), the
`last_room` cookie, the account's custom styles. The sidebar is always a
whole page (Rust sends only the frame to a Turbo-Frame request), and
initials upper-case ASCII only. Search's [[:word:]] is approximated with
ranges outside ASCII. Avatars without a processed variant (initials and bot SVGs) are 404s.
No ETag or 304s yet. Posting a message does not broadcast it over Action
Cable, send Web Push or call bots' webhooks (Rust does all three after the
response), and a body with HTML tags is stored as it came rather than
re-serialized as Nokogiri would. Sign-in has no rate limit yet (Rails and
Rust allow 10 tries in 3 minutes). `all_emoji` approximates the Unicode properties with
code point ranges.

Rust caches whole responses and message fragments (response_cache,
fragment_cache); the Egg app renders every request.

## Measurements

The benchmark's own results are in docs/benchmark.md. The tables below are
earlier rough local checks (Docker on macOS through port forwarding), kept
for the before and after of each change, not for comparing apps.

2026-11-04, rough: both images under Docker (OrbStack) on one macOS laptop,
no CPU pinning, the verification loadgen on the same machine, 16
connections for 4 s, gzip, signed in as David. Egg renders every request;
the Rust app answers most reads from its response cache.

| route | Rust req/s | Egg req/s | Rust p50 ms | Egg p50 ms |
| --- | ---: | ---: | ---: | ---: |
| room page | 10042 | 1030 | 1.19 | 11.49 |
| messages?before= | 10409 | 1826 | 1.18 | 7.01 |
| sidebar | 11294 | 2427 | 1.11 | 5.70 |
| search | 10901 | 2001 | 1.10 | 6.73 |
| avatar | 19015 | 5536 | 0.59 | 2.27 |
| CSS | 21917 | 25662 | 0.54 | 0.43 |
| /up | 15640 | 31960 | 0.76 | 0.31 |

Without gzip the room page is 3428 (Rust) against 1879 (Egg): gzip of the
whole 416 KB page is about half of Egg's time there. The sidebar is the
same either way (11995 against 2417), so its gap is per request: every
query is prepared afresh (no statement cache yet) and the Rust app's
answer comes from its cache.

After keeping prepared statements and linking zlib-ng (as fast as the
Rust app's zlib-rs), same setup:

| route | Rust req/s | Egg req/s | Egg, no gzip | Rust, no gzip |
| --- | ---: | ---: | ---: | ---: |
| room page | 10400 | 1387 | 2575 | 3231 |
| messages?before= | 5926 | 1953 | 2434 | 3383 |
| sidebar | 11206 | 7654 | 11679 | 8979 |
| search | 9707 | 4234 | | |
| avatar | 20177 | 9738 | | |

The laptop is noisy (runs differ by up to 40%). With gzip the Rust app
sends fragments it compressed earlier, which is caching; Egg deflates the
whole page each time, and that is now most of its cost on the big pages.

With CAMPFIRE_CACHE=1 (src/respcache.egg: whole responses per worker,
invalidated on any commit through PRAGMA data_version on a read-only
connection, taken before signing in, 15 s TTL, as the Rust app's
response_cache but not shared between workers):

| route | Rust req/s | Egg cached req/s | Rust p50 ms | Egg p50 ms |
| --- | ---: | ---: | ---: | ---: |
| room page | 11154 | 24026 | 1.12 | 0.44 |
| messages?before= | 9460 | 25677 | 1.22 | 0.42 |
| sidebar | 11274 | 26406 | 1.10 | 0.40 |
| search | 10183 | 26275 | 1.16 | 0.41 |

Message fragments and their precompressed pieces (the Rust app's
fragment_cache and splice deflater) are cached too since `392eda3`
(src/fragcache.egg, src/splice.egg); they matter once writes empty the
response cache (the mixed profile).

## Action Cable fan-out

`loadgen cable` (once-campfire-verification), 2026-11-06, in the OrbStack
Ubuntu VM: the app on CPUs 0-3, the load generator on 4-7, host networking,
a fresh seed each; 1000 clients on the busy room's messages, presence,
unread rooms and heartbeat; 30 paced posts, then 4 posters for 15 s. Egg at
`4dbf4a5`, Rust's published image `6dae2fd`.

| | Rust | Egg |
| --- | ---: | ---: |
| clients ready / failed | 1000 / 0 | 1000 / 0 |
| paced: reached every client | 30 / 30 | 30 / 30 |
| paced: to every client, p50 / p99 | 11.7 / 19.6 ms | 13.1 / 102.9 ms |
| saturated: posts a second | 181 | 69 |
| saturated: messages delivered whole a second | 181 | 50 |
| saturated: to every client, p50 / p99 | 41 / 157 ms | 4.9 / 5.8 s |
| saturated: messages not reaching every client | 0 | 0 |
| memory, peak | 142 MiB | 90 MiB |
| threads (tasks), peak | 18 | 2035 |

Both deliver every message to every client. Under load Egg delivers a
quarter of what Rust does, and posts queue up behind the fan-out (5 s).
Why: each socket is two threads (2000 on 4 cores), and the hub, one
thread, builds each listener's JSON and frame anew (about 10 KB each, over
10 MB copied per message), where Rust encodes a frame once and shares it.

Done since (`aa35d59`, Egg `8f14ee6`): egg #82 added `net.poller()`, a
readiness poller (epoll, kqueue, WSAPoll or poll), and cable now runs on
`CAMPFIRE_CABLE_LOOPS` event loops (4), each a thread with a Poller serving
its sockets: frames are taken from what has come in, what a socket cannot
take waits in its outbox, a socket 4 MB behind is let go (so no one can
hold the others up), and a broadcast's frame is made once per
subscription identifier. The same profile, Egg and Rust in turn the same
hour (two runs of Egg, one of Rust; runs on this VM differ by 10-20%):

| | Rust | Egg, event loops |
| --- | ---: | ---: |
| clients ready / failed | 1000 / 0 | 1000 / 0 |
| paced: to every client, p50 / p99 | 12.4 / 33.8 ms | 13.0-13.4 / 20.4-40.4 ms |
| saturated: posts a second | 178 | 195-222 |
| saturated: messages delivered whole a second | 178 | 195-222 |
| saturated: to every client, p50 / p99 | 37 / 185 ms | 51-56 / 166-196 ms |
| saturated: messages not reaching every client | 0 | 0 |
| memory, peak | 134 MiB | 35-39 MiB |
| threads (tasks), peak | 18 | 39 |

Level with Rust: every message reaches every client, about as fast, on a
quarter of the memory.

The script: ~/bench/cable.sh in the VM (`cable.sh APP IMAGE PORT`).

## Later

The rest of the app (see README: editing, boosts, rooms, accounts, bots,
invitations...), what bin/browser walks through first; attachments and
media; Web Push.

## Egg pain points found

Recorded as they come up; each becomes an egg issue or PR.

- `[]u8` and `Buf(u8)` could not reach C; `a.cstr` never frees: egg #74
  (`@strPtr` of any text, `@bufPtr`, `@sliceFromPtr`)
- no environment variables (`getenv` cannot be declared): egg #75 (`args.env`)
- no top-level value constants: egg #76 (`const MAX = 8192`)
- no wall clock, no random bytes: egg #77 (`uses time` Clock, `uses rand` Random)

- no way for two threads to use one socket (a WebSocket's reader and
  writer): egg #79 (`TcpConn.clone()`), with sockets and (egg #80) files
  close-on-exec
- `threads.spawn(m.f, ...)` with another module's function crashed code
  generation: egg #81
- no poll/epoll, no event loop: every blocking socket needed a thread of
  its own (see Action Cable fan-out): egg #82 (`net.poller()`)

All are merged; `make` builds with egg main.
