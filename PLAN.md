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

Remaining differences from Rust: Flash uses a dedicated encrypted Campfire
cookie instead of Rails' encrypted session envelope. PDF thumbnails and remote
link-card images are not provided. Search's [[:word:]] is approximated with
ranges outside ASCII, as are `all_emoji` Unicode properties. ETag/304 validators
cover ordinary responses, cached pages and files. Messages broadcast over
Action Cable and queue bot webhooks and Web Push. Sign-in allows 10 tries per
IP in 3 minutes, shared across workers. Rust and Egg both cache responses and
message fragments when caching is enabled.

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

At 1000 WebSockets Egg is level with Rust, on a quarter of the memory:
docs/benchmark.md, "Action Cable fan-out". Cable runs on event loops with
Egg's `net.poller()` (egg #82); a socket more than 4 MB behind is let go.

## Phase 2: bin/browser

once-campfire-verification's functional gate (`bin/browser`, browser/smoke.mjs)
walks a fresh install in Chromium and fails on any console error. Each step
is compared with once-campfire-rust's output (a fresh `rust-fresh` container)
byte for byte where it can be.

Done:

- [x] Fresh install: schema on an empty database (src/setup.egg, generated
  src/schema.egg), GET/POST /first_run, / to the last room, /session/new to
  /first_run while there are no users, bcrypt passwords.
- [x] The original room's welcome with the join link (rooms/show/_invitation).
- [x] Initials avatars (and the stock bot avatar), /account/logo (stock icon),
  /webmanifest.json, /service-worker.js.
- [x] Message bodies sanitized when presented (src/sanitize.egg); tagged
  bodies stored normalized.
- [x] Message edit, show, update (replace broadcast, search reindex) and
  delete.

Completed in the order bin/browser needs them:

- [x] Profile: /users/me/profile and PATCH (name, email, password, bio);
  memberships with involvement buttons; GET and PUT /rooms/:id/involvement.
- [x] Session transfer: the link on the profile (signed id, purpose
  "transfer", 4 h), GET /session/transfers/:id (auto-submit form), POST.
- [x] QR codes: /qr_code/:base64url (SVG of the URL).
- [x] Account: /account/edit and update (name); custom styles
  (/account/custom_styles/edit, the style tag in every layout); join code
  regenerate; /join/:code signup; members see no admin controls.
- [x] Rooms: /rooms/opens/new and create, room settings and rename,
  #shared_rooms broadcasts to other sidebars.
- [x] Bots: /account/bots new/create/edit/update, the curl command, and the
  bot message API (POST /rooms/:id/:bot_key/messages).
- [x] Direct pings: New Ping in the sidebar, /autocompletable/users, create
  a direct room, the "Ping with ..." nav; all selected recipients are included,
  duplicate selections removed, and an exact existing member set reused.
- [x] Run bin/browser (`node browser/smoke.mjs --base URL` in the
  verification repo; Playwright 1.63 installed there): passed on a fresh database.
- [x] Session metadata and authentication: IP/User-Agent saved on session
  creation, sign-out revokes the current session, and sign-in limits all workers
  together to 10 attempts per IP in 3 minutes. `make test-accounts` checks these
  contracts, password preservation and group Ping membership.

- [x] Notification help names common browsers and operating systems from the
  User-Agent; page cache keys include that header. Instructions remain generic.
- [x] ETag/304 for GET responses, including page and file cache hits, weak
  validators, lists and wildcard matching. Regression checks run with caching
  enabled and disabled, and verify invalidation after a message write.

- [x] Bot webhook configuration and asynchronous delivery: transactional SQLite
  outbox, active direct-room bots and signed mentions, JSON payloads, text replies
  and downloadable binary attachments, live reply/unread broadcasts.
  `make test-webhooks` checks restart recovery, timeout/transport failures,
  targeting and attachment access. Binary thumbnails are still missing.

- [x] Avatar and account Logo multipart uploads: raster decoding, bounded
  conversion, WebP avatars, 192/512 PNG PWA icons and cache-version updates.
- [x] User message attachments, protected downloads, image thumbnails, video
  posters, audio/video controls and single byte-range requests.
- [x] Rich-text signed mentions and sanitized Action Text link-card contents;
  public HTTP(S) link unfurling with private-address rejection and bounded fetches.
- [x] One-use encrypted Flash notices for profile/account updates and notification
  management; authenticated ciphertext and expiry checks.
- [x] Web Push subscriptions, test notifications, VAPID ES256 and RFC 8291
  encryption, durable delivery/retries, recipient involvement and presence rules,
  expired-subscription cleanup. A stable default key pair is derived from the
  app secret; deployments may supply matching VAPID keys.
- [x] `make test-features`: real uploads/media requests, independent Web Push
  decryption and VAPID verification, notice tampering and endpoint guards.

## Later

PDF thumbnails, remote link-card images and Rails encrypted-session cookie
interoperability. The custom Flash cookie provides notices in the Egg UI.

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

- no way to learn a connection's peer address, for sessions' IP and the
  sign-in rate limit: egg #83 (`TcpConn.peer_ip(a)`)

The numbered issues are merged.
