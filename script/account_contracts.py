#!/usr/bin/env python3
"""Exercise group membership and session contracts against a disposable app DB."""
import concurrent.futures
import http.cookiejar
import http.client
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def client():
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(jar)
    )
    return opener, jar


def run(base, db):
    owner, owner_jar = client()

    def post(opener, path, fields):
        request = urllib.request.Request(
            base + path,
            urllib.parse.urlencode(fields).encode(),
            headers={"User-Agent": "Campfire account contracts"},
        )
        return opener.open(request, timeout=5)

    with post(owner, "/first_run", {
        "user[name]": "Alice", "user[email_address]": "alice@example.test",
        "user[password]": "password123",
    }):
        pass
    assert db.execute("SELECT ip_address, user_agent FROM sessions").fetchone() == (
        "127.0.0.1", "Campfire account contracts"
    )
    code = db.execute("SELECT join_code FROM accounts").fetchone()[0]
    for name in ("Bob", "Carol"):
        opener, _ = client()
        with post(opener, "/join/" + code, {
            "user[name]": name, "user[email_address]": name + "@example.test",
            "user[password]": "password123",
        }):
            pass
    with post(owner, "/rooms/directs", [
        ("user_ids[]", "2"), ("user_ids[]", "3"), ("user_ids[]", "2"),
    ]) as response:
        group = response.url
    group_id = int(group.rsplit("/", 1)[1])
    assert db.execute("SELECT user_id FROM memberships WHERE room_id=? ORDER BY user_id", (group_id,)).fetchall() == [(1,), (2,), (3,)]
    with post(owner, "/rooms/directs", [("user_ids[]", "3"), ("user_ids[]", "2")]) as response:
        assert response.url == group
    with post(owner, "/rooms/directs", [("user_ids[]", "2")]) as response:
        assert response.url != group
    boundary = "account-contracts"
    body = "".join(
        f'--{boundary}\r\nContent-Disposition: form-data; name="user_ids[]"\r\n\r\n{value}\r\n'
        for value in ("3", "2")
    ) + f"--{boundary}--\r\n"
    with owner.open(urllib.request.Request(base + "/rooms/directs", body.encode(), headers={
        "Content-Type": "multipart/form-data; boundary=" + boundary,
    }), timeout=5) as response:
        assert response.url == group
    assert db.execute("SELECT COUNT(*) FROM rooms WHERE type='Rooms::Direct'").fetchone()[0] == 2

    # Reuse a connection after 304; exercise both file and page cache paths.
    auth = "; ".join(cookie.name + "=" + cookie.value for cookie in owner_jar)
    connection = http.client.HTTPConnection(urllib.parse.urlsplit(base).netloc, timeout=5)
    def get(path, headers=None):
        connection.request("GET", path, headers=dict({"Cookie": auth}, **(headers or {})))
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    ua = "Mozilla/5.0 (Windows NT 10.0) Chrome/140.0 Safari/537.36 Edg/140.0"
    status, headers, body = get("/rooms/1", {"User-Agent": ua})
    assert status == 200 and b"Check your Edge settings" in body and b"Check your Windows settings" in body
    tag = headers["ETag"]
    for validator in (tag, "W/" + tag, '"wrong", W/' + tag, "*"):
        status, conditional_headers, body = get("/rooms/1", {"User-Agent": ua, "If-None-Match": validator})
        assert status == 304 and body == b"" and "Content-Length" not in conditional_headers
        assert conditional_headers["ETag"] == tag
    status, _, body = get("/rooms/1", {"User-Agent": "Mozilla/5.0 (iPhone) Version/18.0 Safari/604.1"})
    assert status == 200 and b"Check your Safari settings" in body and b"Check your iOS settings" in body
    status, compressed_headers, _ = get("/rooms/1", {"User-Agent": ua, "Accept-Encoding": "gzip"})
    assert status == 200 and compressed_headers["ETag"] != tag
    status, _, body = get("/rooms/1", {"User-Agent": ua, "If-None-Match": '"wrong"'})
    assert status == 200 and body
    with post(owner, "/rooms/1/messages", {"message[body]": "validator invalidation", "message[client_message_id]": "validator-contract"}):
        pass
    status, updated_headers, body = get("/rooms/1", {"User-Agent": ua, "If-None-Match": tag})
    assert status == 200 and updated_headers["ETag"] != tag and b"validator invalidation" in body
    asset = next((ROOT / "build/assets").rglob("*.css"))
    asset_path = "/assets/" + str(asset.relative_to(ROOT / "build/assets"))
    status, headers, body = get(asset_path)
    assert status == 200 and body
    status, _, body = get(asset_path, {"If-None-Match": headers["ETag"]})
    assert status == 304 and not body
    connection.close()

    # A bot created without a webhook can acquire one later and disable it.
    with post(owner, "/account/bots", {"user[name]": "Helper", "user[webhook_url]": ""}):
        pass
    bot = db.execute("SELECT id FROM users WHERE role=2").fetchone()[0]
    for url in ("http://example.test/hook", "http://example.test/changed", "", "http://example.test/restored"):
        with post(owner, f"/account/bots/{bot}", {"_method": "patch", "user[name]": "Helper", "user[webhook_url]": url}):
            pass
        rows = db.execute("SELECT url FROM webhooks WHERE user_id=?", (bot,)).fetchall()
        assert rows == ([(url,)] if url else []), rows

    # Updating a profile with a blank password must preserve its login digest.
    digest = db.execute("SELECT password_digest FROM users WHERE id=1").fetchone()[0]
    with post(owner, "/users/me/profile", {
        "user[name]": "Alice", "user[email_address]": "alice@example.test",
        "user[bio]": "updated", "user[password]": "", "_method": "patch",
    }):
        pass
    assert db.execute("SELECT password_digest FROM users WHERE id=1").fetchone()[0] == digest

    def attempt(_):
        opener, _ = client()
        try:
            with post(opener, "/session", {"email_address": "alice@example.test", "password": "wrong"}) as response:
                return response.status
        except urllib.error.HTTPError as error:
            return error.code
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        statuses = list(pool.map(attempt, range(15)))
    assert statuses.count(401) == 10 and statuses.count(429) == 5, statuses
    db.execute("UPDATE egg_login_limits SET expires_at=0")
    db.commit()
    signed_in, jar = client()
    with post(signed_in, "/session", {"email_address": "alice@example.test", "password": "password123"}):
        pass
    assert db.execute("SELECT attempts FROM egg_login_limits").fetchone()[0] == 1
    old_cookie = "; ".join(cookie.name + "=" + cookie.value for cookie in jar)
    before = db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    with post(signed_in, "/session", {"_method": "delete"}) as response:
        assert response.url.endswith("/session/new")
    assert db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == before - 1
    probe, _ = client()
    with probe.open(urllib.request.Request(base + "/users/me/profile", headers={"Cookie": old_cookie}), timeout=5) as response:
        assert response.url.endswith("/session/new")
    print("PASS: group Pings, profile password preservation, session metadata, shared login limits, expiry, sign-out, notification platform, ETag/304 and webhook configuration")


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="campfire-accounts-") as directory:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        database = str(Path(directory) / "app.sqlite3")
        environment = dict(os.environ, HTTP_PORT=str(port), CAMPFIRE_WORKERS="4",
                           CAMPFIRE_DATABASE_PATH=database, CAMPFIRE_CACHE=os.environ.get("CAMPFIRE_CACHE", "0"),
                           SECRET_KEY_BASE="account-contracts-secret",
                           CAMPFIRE_ASSETS_PATH=str(ROOT / "build/assets"))
        with open(Path(directory) / "server.log", "w+") as log:
            server = subprocess.Popen([str(ROOT / "build/campfire")], env=environment, cwd=ROOT, stdout=log, stderr=log)
            try:
                base = f"http://127.0.0.1:{port}"
                probe, _ = client()
                for _ in range(100):
                    try:
                        with probe.open(base + "/up", timeout=1):
                            break
                    except (OSError, urllib.error.URLError):
                        if server.poll() is not None:
                            log.seek(0)
                            raise RuntimeError(log.read())
                        time.sleep(0.05)
                else:
                    raise RuntimeError("app did not start")
                with sqlite3.connect(database) as db:
                    run(base, db)
            finally:
                server.terminate()
                server.wait(timeout=5)
