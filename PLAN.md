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
- next: the benchmark

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

## Later

Action Cable (WebSocket), the rest of the app, attachments and media, Web Push.

## Egg pain points found

Recorded as they come up; each becomes an egg issue or PR.

- `[]u8` and `Buf(u8)` could not reach C; `a.cstr` never frees: egg #74
  (`@strPtr` of any text, `@bufPtr`, `@sliceFromPtr`)
- no environment variables (`getenv` cannot be declared): egg #75 (`args.env`)
- no top-level value constants: egg #76 (`const MAX = 8192`)
- no wall clock, no random bytes: egg #77 (`uses time` Clock, `uses rand` Random)

All four are merged; `make` builds with egg main.
