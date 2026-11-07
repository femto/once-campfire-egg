#!/usr/bin/env python3
"""Real local HTTP callbacks against a disposable Campfire installation."""
import base64
import hashlib
import hmac
import http.server
import json
import os
from pathlib import Path
import queue
import socket
import sqlite3
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from account_contracts import ROOT, client

received = queue.Queue()
blocked = threading.Event()
release = threading.Event()
PDF = b"%PDF-1.4\nwebhook bytes\x00\xff"

class Hook(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass
    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        received.put((self.path, payload, self.headers['Content-Type']))
        if self.path == '/timeout':
            time.sleep(10)
        if self.path == '/slow':
            blocked.set()
            release.wait(15)
        if self.path == '/binary':
            content_type, body = 'application/pdf', PDF
        else:
            content_type, body = 'text/html', b'<strong>Webhook reply</strong><script>alert(1)</script>'
        self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass


def eventually(test, timeout=10):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        result = test()
        if result:
            return result
        time.sleep(.05)
    raise AssertionError('condition did not become true')


def run(base, db, hook_base, restart):
    owner, _ = client()
    def post(path, fields, opener=owner):
        return opener.open(urllib.request.Request(base + path, urllib.parse.urlencode(fields).encode()), timeout=5)
    with post('/first_run', {'user[name]':'Alice','user[email_address]':'alice@example.test','user[password]':'password123'}):
        pass
    bots = []
    for name, path in [('Helper','/text'), ('Second','/text'), ('File','/binary'), ('Slow','/slow')]:
        with post('/account/bots', {'user[name]':name,'user[webhook_url]':hook_base+path}):
            pass
        bots.append(db.execute('SELECT id FROM users WHERE name=?',(name,)).fetchone()[0])
    with owner.open(base+'/autocompletable/users?query=Helper') as response:
        sgid = json.load(response)[0]['sgid']
    encoded, signature = sgid.split('--')
    key = hashlib.pbkdf2_hmac('sha256',b'webhook-contracts-secret',b'signed_global_ids',1000,64)
    assert hmac.new(key,encoded.encode(),hashlib.sha1).hexdigest()==signature
    assert json.loads(base64.urlsafe_b64decode(encoded)) == {'_rails':{'data':f'gid://campfire/User/{bots[0]}?expires_in','pur':'attachable'}}
    with post('/rooms/directs', [('user_ids[]',str(bot)) for bot in bots[:2]]) as response:
        room = int(response.url.rsplit('/',1)[1])
    with post(f'/rooms/{room}/messages', {'message[body]':'Hello bots'}):
        pass
    first, second = received.get(timeout=5), received.get(timeout=5)
    assert first[2] == second[2] == 'application/json'
    for _, payload, _ in (first, second):
        assert payload['user']=={'id':1,'name':'Alice'}
        assert payload['room']['id']==room and payload['room']['name'] is None
        assert payload['message']['body']['plain']=='Hello bots'
        assert payload['room']['path'].endswith('/messages')
        assert payload['message']['path'].startswith(f'/rooms/{room}/@')
    eventually(lambda: db.execute('SELECT COUNT(*) FROM messages WHERE room_id=? AND creator_id!=1',(room,)).fetchone()[0]==2)
    with owner.open(base+f'/rooms/{room}') as response:
        page=response.read()
    assert b'<strong>Webhook reply</strong>' in page and b'<script>alert(1)' not in page
    assert received.empty(), 'bot replies must not start a loop'

    # Inbound bot API messages target other bots, never their sender.
    api_path = first[1]['room']['path']
    sender_id = int(api_path.split('/')[3].split('-')[0])
    with owner.open(urllib.request.Request(base+api_path,b'Bot API message'),timeout=5) as response:
        assert response.status==201
    _, api_payload, _ = received.get(timeout=5)
    assert api_payload['user']['id']==sender_id and api_payload['message']['body']['plain']=='Bot API message'
    eventually(lambda: db.execute('SELECT COUNT(*) FROM egg_webhook_jobs').fetchone()[0]==0)
    assert received.empty()

    # Forged SGIDs and ordinary room messages do not trigger a webhook.
    with post('/rooms/1/messages', {'message[body]':'No mention'}):
        pass
    forged = sgid[:-1] + ('0' if sgid[-1]!='0' else '1')
    with post('/rooms/1/messages', {'message[body]':f'<action-text-attachment sgid="{forged}">@Helper</action-text-attachment> forged'}):
        pass
    with post('/rooms/1/messages', {'message[body]':f'<action-text-attachment sgid="{sgid}">@Helper</action-text-attachment> hello'}):
        pass
    _, payload, _ = received.get(timeout=5)
    assert payload['room']['id']==1 and payload['message']['body']['plain']=='hello'
    eventually(lambda: db.execute('SELECT COUNT(*) FROM egg_webhook_jobs').fetchone()[0]==0)
    assert received.empty(), 'only the mentioned bot should receive the open-room message'

    with post('/rooms/directs', [('user_ids[]',str(bots[2]))]) as response:
        file_room=int(response.url.rsplit('/',1)[1])
    with post(f'/rooms/{file_room}/messages', {'message[body]':'Send file'}):
        pass
    received.get(timeout=5)
    blob = eventually(lambda: db.execute("SELECT b.key FROM active_storage_blobs b JOIN active_storage_attachments a ON a.blob_id=b.id WHERE a.record_type='Message'").fetchone())
    assert db.execute('SELECT checksum FROM active_storage_blobs WHERE key=?',(blob[0],)).fetchone()[0] == base64.b64encode(hashlib.md5(PDF).digest()).decode()
    with owner.open(base+'/attachments/'+blob[0]) as response:
        assert response.read()==PDF and response.headers['Content-Disposition'].startswith('attachment')
        assert response.headers['Content-Type']=='application/pdf'
    other, _ = client()
    code=db.execute('SELECT join_code FROM accounts').fetchone()[0]
    with post('/join/'+code, {'user[name]':'Outsider','user[email_address]':'outsider@example.test','user[password]':'password123'}, other):
        pass
    try:
        other.open(base+'/attachments/'+blob[0])
        raise AssertionError('nonmember could download attachment')
    except urllib.error.HTTPError as error:
        assert error.code==404

    with post('/rooms/directs', [('user_ids[]',str(bots[3]))]) as response:
        slow_room=int(response.url.rsplit('/',1)[1])
    with post(f'/rooms/{slow_room}/messages', {'message[body]':'Persist this job'}):
        pass
    assert blocked.wait(5)
    received.get(timeout=5)
    with owner.open(base+'/up',timeout=1) as response:
        assert response.status==200
    assert db.execute('SELECT COUNT(*) FROM egg_webhook_jobs').fetchone()[0]==1
    # A deleted source message must not be delivered later from its outbox row.
    with post(f'/rooms/{file_room}/messages', {'message[body]':'Delete before delivery'}):
        pass
    removed=db.execute('SELECT MAX(id) FROM messages WHERE room_id=?',(file_room,)).fetchone()[0]
    with post(f'/rooms/{file_room}/messages/{removed}', {'_method':'delete'}):
        pass
    # Restart while delivery is in flight: committed jobs are recovered.
    restart()
    received.get(timeout=5)
    release.set()
    eventually(lambda: db.execute('SELECT COUNT(*) FROM egg_webhook_jobs').fetchone()[0]==0)
    assert db.execute('SELECT COUNT(*) FROM messages WHERE room_id=? AND creator_id=?',(slow_room,bots[3])).fetchone()[0]==1
    assert received.empty(), 'deleted source message was delivered'
    # Transport failures are discarded; the worker can deliver the next job.
    with post('/account/bots', {'user[name]':'Timeout','user[webhook_url]':hook_base+'/timeout'}):
        pass
    timeout_bot=db.execute("SELECT id FROM users WHERE name='Timeout'").fetchone()[0]
    with post('/rooms/directs', [('user_ids[]',str(timeout_bot))]) as response:
        timeout_room=int(response.url.rsplit('/',1)[1])
    with post(f'/rooms/{timeout_room}/messages', {'message[body]':'Timeout please'}):
        pass
    received.get(timeout=5)
    eventually(lambda: db.execute('SELECT COUNT(*) FROM messages WHERE room_id=? AND creator_id=?',(timeout_room,timeout_bot)).fetchone()[0]==1, timeout=15)
    timeout_reply=db.execute("SELECT t.body FROM action_text_rich_texts t JOIN messages m ON m.id=t.record_id WHERE t.record_type='Message' AND m.room_id=? AND m.creator_id=?",(timeout_room,timeout_bot)).fetchone()[0]
    assert 'Failed to respond within' in timeout_reply
    with post(f'/account/bots/{timeout_bot}', {'_method':'patch','user[name]':'Timeout','user[webhook_url]':'http://127.0.0.1:1/unreachable'}):
        pass
    with post(f'/rooms/{timeout_room}/messages', {'message[body]':'Connection failure'}):
        pass
    eventually(lambda: db.execute('SELECT COUNT(*) FROM egg_webhook_jobs').fetchone()[0]==0)
    assert db.execute('SELECT COUNT(*) FROM messages WHERE room_id=? AND creator_id=?',(timeout_room,timeout_bot)).fetchone()[0]==1
    with post(f'/account/bots/{timeout_bot}', {'_method':'patch','user[name]':'Timeout','user[webhook_url]':hook_base+'/text'}):
        pass
    with post(f'/rooms/{timeout_room}/messages', {'message[body]':'Recovered'}):
        pass
    received.get(timeout=5)
    eventually(lambda: db.execute('SELECT COUNT(*) FROM messages WHERE room_id=? AND creator_id=?',(timeout_room,timeout_bot)).fetchone()[0]==2)
    print('PASS: webhook targeting, signed mentions, payloads, sanitized replies, binary attachment permissions, isolated delivery, durable restart, API sender exclusion, timeout and transport recovery')


if __name__=='__main__':
    hook=http.server.ThreadingHTTPServer(('127.0.0.1',0),Hook)
    thread=threading.Thread(target=hook.serve_forever,daemon=True);thread.start()
    with tempfile.TemporaryDirectory(prefix='campfire-webhooks-') as directory:
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        database=str(Path(directory)/'app.sqlite3')
        env=dict(os.environ, HTTP_PORT=str(port), CAMPFIRE_WORKERS='4', CAMPFIRE_DATABASE_PATH=database,
                 CAMPFIRE_FILES_PATH=directory+'/files', CAMPFIRE_ASSETS_PATH=str(ROOT/'build/assets'),
                 SECRET_KEY_BASE='webhook-contracts-secret')
        base=f'http://127.0.0.1:{port}'
        with open(Path(directory)/'server.log','w+') as log:
            server=None
            def restart():
                global server
                if server:
                    server.terminate();server.wait(timeout=5)
                server=subprocess.Popen([str(ROOT/'build/campfire')],env=env,cwd=ROOT,stdout=log,stderr=log)
                def ready():
                    try:
                        opener,_=client()
                        with opener.open(base+'/up',timeout=1): return True
                    except (OSError,urllib.error.URLError): return False
                eventually(ready)
            try:
                restart()
                with sqlite3.connect(database) as db:
                    run(base,db,f'http://127.0.0.1:{hook.server_port}',restart)
            except Exception:
                log.seek(0);print(log.read());raise
            finally:
                release.set()
                if server:
                    server.terminate();server.wait(timeout=5)
                hook.shutdown();hook.server_close()
