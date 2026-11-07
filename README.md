# once-campfire-egg

[ONCE Campfire](https://github.com/basecamp/once-campfire), the Rails group
chat, ported to [Egg](https://github.com/femto/egg), a language with
ownership instead of a garbage collector that compiles to C.

It runs on the database the Rails app makes and answers as the Rails app
does: the same signed cookies, signed ids and Turbo stream names, the same
HTML. The reference is
[once-campfire-rust](https://github.com/basecamp/once-campfire-rust), and
pages are compared with it byte for byte (`script/compare.sh`).

## What it serves

What [once-campfire-verification](https://github.com/basecamp/once-campfire-verification)'s
benchmark asks for, passing its contracts and write audits, and what keeps
an open room live:

- signing in (`POST /session`, bcrypt, the `session_token` cookie)
- a room page and older pages of its messages, and what changed in a room
  since a page loaded (`/rooms/:id/refresh`)
- the sidebar and search
- avatars and precompiled assets
- posting a message (the row, the search index and unread marks in one
  transaction, answered with a turbo-stream), from a plain or a multipart
  form
- Action Cable over WebSocket (`/cable`, src/cable.egg): the Turbo streams
  a page subscribes to, with a new message appended live in its room, and
  the app's channels: unread and read rooms, presence (who is in a room,
  which decides unread marks) and typing. Messages and database writes
  match once-campfire-rust's step for step.
- `/up`
- first-run setup, profile and account settings, invitation signup and
  session transfer links
- message editing and deletion, open-room creation and renaming, chat bots,
  and direct pings

Bot webhooks run in a background worker with a durable SQLite outbox. Direct
rooms notify their active bots; open rooms notify signed mentions. Text replies
are broadcast as bot messages, and binary replies become downloadable message
attachments. Jobs survive restarts and may redeliver an in-flight request; remote
endpoints can deduplicate by message id and bot path.

Avatar and account logo uploads, message attachments, image/video thumbnails,
audio/video playback, signed mentions and sanitized rich-text link cards are
supported. Flash notices use an encrypted, one-use Campfire cookie. Web Push
uses VAPID and RFC 8291 encryption, a durable outbox, recipient settings,
bounded retries and expired-subscription cleanup.

Not yet: PDF thumbnails, boost creation and full Rails encrypted-session
interoperability. PLAN.md has the
status and the gaps. The verification project's Chromium smoke test passes
on a fresh database.

## Performance

By default each
worker keeps, as the Rust app does for the process, whole responses until
the next commit, messages' HTML, and each page's gzip in pieces it splices
together (src/respcache.egg, src/fragcache.egg, src/splice.egg). With
`CAMPFIRE_CACHE=0` it renders and gzips every page.
On GitHub's ubuntu-latest, requests a second:

| route | Rust | Egg | Egg, cached |
| --- | ---: | ---: | ---: |
| room page | 12710 | 592 | 41833 |
| sidebar | 14287 | 3888 | 51243 |
| avatar | 47899 | 51165 | 50559 |
| static CSS | 48060 | 108952 | 108761 |
| post a message | 1818 | 1963 | 1771 |

With 1000 WebSockets on one busy room (`loadgen cable`), every message
reaches every client, as fast as the Rust app's (195-222 against 178
messages a second to all, at full load), in 35-39 MiB against its 134.

docs/benchmark.md has every route, the local runs, the WebSocket run, the
setup and how to read the numbers; `.github/workflows/benchmark.yml` runs
the HTTP routes.

## Building and running

Needs an Egg checkout, Ruby (for the template compiler and asset script), a
C compiler, SQLite, zlib, OpenSSL's libcrypto and libcurl (7.85 or newer).
ImageMagick (`convert`) handles raster images; ffmpeg handles video posters.

```sh
make EGG_DIR=~/path/to/egg          # build/campfire
script/assets.sh build/assets       # the Rails app's precompiled assets
SECRET_KEY_BASE=... CAMPFIRE_STORAGE_PATH=storage build/campfire
```

`docker build -t once-campfire-egg:app .` builds the image the benchmark
runs (Debian, zlib-ng).

`make test-accounts` checks group Ping membership, profile password
preservation, session metadata, login limits and sign-out using a disposable
database. Docker applies the local `TcpConn.peer_ip` compiler patch to its
pinned Egg checkout; native builds need that API in `EGG_DIR` too.

`make test-webhooks` exercises real local callbacks, signed mentions, payloads,
text and binary replies, attachment permissions, timeout handling, sender
exclusion and recovery after a restart. HTTP(S) delivery uses a 7-second
inactivity/connect limit, a 60-second total limit and a 100 MB reply limit.
Transport failures are logged and discarded. User uploads support PNG/JPEG/GIF/
WebP previews, video posters and native media controls; arbitrary files remain
protected downloads. The multipart request limit is 32 MB. Link unfurling
fetches public pages with size/time limits and rejects private addresses;
remote link-card images are currently omitted.

| variable | default |
| --- | --- |
| `HTTP_PORT` | 3000 |
| `CAMPFIRE_WORKERS` | 32 (one connection each) |
| `CAMPFIRE_STORAGE_PATH` | `storage` |
| `CAMPFIRE_DATABASE_PATH` | `<storage>/db/production.sqlite3` |
| `CAMPFIRE_FILES_PATH` | `<storage>/files` (Active Storage) |
| `CAMPFIRE_ASSETS_PATH` | `build/assets` |
| `CAMPFIRE_CACHE` | `1`: keeps messages' HTML, their gzip, and whole responses; `0` keeps none |
| `CAMPFIRE_RESPONSE_CACHE` | `1`; `0` keeps all but whole responses |
| `SECRET_KEY_BASE` | required; also derives stable VAPID keys when no pair is supplied |
| `VAPID_PRIVATE_KEY`, `VAPID_PUBLIC_KEY` | optional matching P-256 keys, URL-safe Base64 |
| `VAPID_SUBJECT` | `mailto:admin@example.com`; configure your contact URI |
| `VAPID_PUBLIC_KEY` | empty |

## Layout

- `src/`: the app (`main.egg`, `app.egg` routes, `model.egg` queries) and
  what Rails gives it (cookies, signed ids, Turbo, rich text, gzip, SQLite)
- `templates/`: the pages, compiled to `src/views.egg` by
  `script/templates.rb`
- `script/`: `compare.sh` (byte comparison with Rust), `bench.sh` (a quick
  local load test), `assets.sh`, generators
- `vendor/`: crypt_blowfish (bcrypt) and the Rust app's overridden scripts

`make test-features` additionally needs Python's `cryptography` package. It
checks uploads, media ranges, rich-text scrubbing, Flash authentication,
private-address rejection and Web Push decryption/signatures using an
independent recipient implementation. Use `PYTHON=/path/to/venv/bin/python`
to select a virtual environment. Its local push endpoint is enabled only
inside the test process with `CAMPFIRE_PUSH_ALLOW_LOCAL=1`; production defaults
to public HTTPS endpoints.

`node script/browser_features.mjs --base URL` exercises upload forms, visible
Flash and the composer preview against a disposable fresh database, using the
adjacent verification checkout's Playwright installation.
