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

So far, what [once-campfire-verification](https://github.com/basecamp/once-campfire-verification)'s
benchmark asks for, passing its contracts and write audits:

- signing in (`POST /session`, bcrypt, the `session_token` cookie)
- a room page and older pages of its messages
- the sidebar and search
- avatars and precompiled assets
- posting a message (the row, the search index and unread marks in one
  transaction, answered with a turbo-stream)
- `/up`

Not yet: Action Cable, Web Push, bot webhooks, invitations, initials and bot
avatars, and the rest of the app. PLAN.md has the status and the gaps.

## Performance

Uncached, Egg renders and gzips every page; with `CAMPFIRE_CACHE=1` each
worker keeps whole responses until the next commit, as the Rust app does.
On GitHub's ubuntu-latest, requests a second:

| route | Rust | Egg | Egg, cached |
| --- | ---: | ---: | ---: |
| room page | 12710 | 592 | 41833 |
| sidebar | 14287 | 3888 | 51243 |
| avatar | 47899 | 51165 | 50559 |
| static CSS | 48060 | 108952 | 108761 |
| post a message | 1818 | 1963 | 1771 |

docs/benchmark.md has every route, the local runs, the setup and how to read
the numbers; `.github/workflows/benchmark.yml` runs it.

## Building and running

Needs an Egg checkout, Ruby (for the template compiler and asset script), a
C compiler, and SQLite, zlib and OpenSSL's libcrypto.

```sh
make EGG_DIR=~/path/to/egg          # build/campfire
script/assets.sh build/assets       # the Rails app's precompiled assets
SECRET_KEY_BASE=... CAMPFIRE_STORAGE_PATH=storage build/campfire
```

`docker build -t once-campfire-egg:app .` builds the image the benchmark
runs (Debian, zlib-ng).

| variable | default |
| --- | --- |
| `HTTP_PORT` | 3000 |
| `CAMPFIRE_WORKERS` | 32 (one connection each) |
| `CAMPFIRE_STORAGE_PATH` | `storage` |
| `CAMPFIRE_DATABASE_PATH` | `<storage>/db/production.sqlite3` |
| `CAMPFIRE_FILES_PATH` | `<storage>/files` (Active Storage) |
| `CAMPFIRE_ASSETS_PATH` | `build/assets` |
| `CAMPFIRE_CACHE` | `0`; `1` keeps whole responses |
| `SECRET_KEY_BASE` | required |
| `VAPID_PUBLIC_KEY` | empty |

## Layout

- `src/`: the app (`main.egg`, `app.egg` routes, `model.egg` queries) and
  what Rails gives it (cookies, signed ids, Turbo, rich text, gzip, SQLite)
- `templates/`: the pages, compiled to `src/views.egg` by
  `script/templates.rb`
- `script/`: `compare.sh` (byte comparison with Rust), `bench.sh` (a quick
  local load test), `assets.sh`, generators
- `vendor/`: crypt_blowfish (bcrypt) and the Rust app's overridden scripts
