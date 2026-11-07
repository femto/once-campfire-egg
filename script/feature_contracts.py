#!/usr/bin/env python3
"""Uploads, rendering, encrypted notices and independently decrypted Web Push."""
import base64
import hashlib
import html
import http.server
import http.client
import json
import os
from pathlib import Path
import queue
import re
import socket
import sqlite3
import struct
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from account_contracts import ROOT, client

received=queue.Queue()
retry_count=0
class Endpoint(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        received.put((self.path,dict(self.headers),b''))
        self.send_response(200);self.send_header('Content-Type','text/html');self.end_headers();self.wfile.write(b'<title>Private service</title>')
    def log_message(self,*args): pass
    def do_POST(self):
        data=self.rfile.read(int(self.headers['Content-Length']))
        received.put((self.path,dict(self.headers),data))
        global retry_count
        if self.path=='/retry': retry_count+=1
        self.send_response(410 if self.path=='/gone' else 503 if self.path=='/retry' and retry_count==1 else 201);self.send_header('Content-Length','0');self.end_headers()

def b64(data): return base64.urlsafe_b64encode(data).decode().rstrip('=')
def decode(data): return base64.urlsafe_b64decode(data+'='*(-len(data)%4))
def eventually(test,timeout=8):
    until=time.monotonic()+timeout
    while time.monotonic()<until:
        result=test()
        if result: return result
        time.sleep(.05)
    raise AssertionError('condition did not become true')

def decrypt(delivery,key,auth,origin,vapid):
    _,headers,body=delivery
    assert headers['Content-Encoding']=='aes128gcm' and headers['TTL']=='2419200'
    assert body[20]==65 and struct.unpack('>I',body[16:20])[0]==len(body)-86
    server=ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(),body[21:86])
    client_public=key.public_key().public_bytes(serialization.Encoding.X962,serialization.PublicFormat.UncompressedPoint)
    shared=key.exchange(ec.ECDH(),server)
    ikm=HKDF(algorithm=hashes.SHA256(),length=32,salt=auth,info=b'WebPush: info\0'+client_public+body[21:86]).derive(shared)
    cek=HKDF(algorithm=hashes.SHA256(),length=16,salt=body[:16],info=b'Content-Encoding: aes128gcm\0').derive(ikm)
    nonce=HKDF(algorithm=hashes.SHA256(),length=12,salt=body[:16],info=b'Content-Encoding: nonce\0').derive(ikm)
    plain=AESGCM(cek).decrypt(nonce,body[86:],None)
    assert plain.endswith(b'\x02\x00')
    jwt,public=headers['Authorization'][len('vapid t='):].split(',k=')
    assert public==vapid
    head,claims,signature=jwt.split('.')
    assert json.loads(decode(head))['alg']=='ES256'
    claim=json.loads(decode(claims))
    assert claim['aud']==origin and time.time()<claim['exp']<time.time()+43300
    r,s=struct.unpack('>32s32s',decode(signature))
    ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(),decode(public)).verify(utils.encode_dss_signature(int.from_bytes(r),int.from_bytes(s)),(head+'.'+claims).encode(),ec.ECDSA(hashes.SHA256()))
    return json.loads(plain[:-2])

def run(base,db,endpoint,restart):
    owner,jar=client()
    def post(path,fields,opener=owner):
        return opener.open(urllib.request.Request(base+path,urllib.parse.urlencode(fields).encode()),timeout=8)
    def json_post(path,data,opener=owner):
        return opener.open(urllib.request.Request(base+path,json.dumps(data).encode(),headers={'Content-Type':'application/json'}),timeout=8)
    def upload(path,name,filename,mime,data,fields=(),opener=owner):
        boundary='campfire-file-contract'
        body=b''
        for field,value in fields:
            body+=f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"\r\n\r\n{value}\r\n'.encode()
        body+=f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{filename}"\r\nContent-Type: {mime}\r\n\r\n'.encode()+data+f'\r\n--{boundary}--\r\n'.encode()
        return opener.open(urllib.request.Request(base+path,body,headers={'Content-Type':'multipart/form-data; boundary='+boundary}),timeout=20)
    with post('/first_run',{'user[name]':'Alice','user[email_address]':'alice@example.test','user[password]':'password123'}): pass
    connection=http.client.HTTPConnection(urllib.parse.urlsplit(base).netloc,timeout=5)
    connection.request('POST','/rooms/1/messages',headers={'Content-Length':str(33554433)})
    response=connection.getresponse();assert response.status==413;response.read();connection.close()
    png=subprocess.check_output(['convert','-size','800x400','xc:red','png:-'])
    with upload('/users/me/profile','user[avatar]','face.png','image/png',png,[('_method','patch')]): pass
    assert db.execute('SELECT name FROM users WHERE id=1').fetchone()[0]=='Alice'
    avatar=db.execute("SELECT b.key FROM active_storage_blobs b JOIN active_storage_attachments a ON a.blob_id=b.id WHERE a.record_type='User'").fetchone()[0]
    with owner.open(base+'/users/me/profile') as response: profile=response.read().decode()
    avatar_url=re.search(r'src="([^"]+/avatar[^"]*)"',profile).group(1).replace('&amp;','&')
    with owner.open(base+avatar_url) as response:
        picture=response.read();assert response.headers['Content-Type']=='image/webp' and picture[8:12]==b'WEBP'
    assert subprocess.check_output(['identify','-format','%wx%h','webp:-'],input=picture)==b'512x256'
    flash_cookie=next(c.value for c in jar if c.name=='campfire_flash')
    assert 'Image' not in flash_cookie
    with owner.open(base+'/flash') as response: assert json.load(response)=='Image updated'
    with owner.open(base+'/flash') as response: assert json.load(response)==''
    probe,_=client()
    with probe.open(urllib.request.Request(base+'/flash',headers={'Cookie':'campfire_flash='+flash_cookie[:-2]+'XX'})) as response: assert json.load(response)==''
    try:
        upload('/users/me/profile','user[avatar]','fake.png','image/png',b'not an image')
        raise AssertionError('invalid avatar accepted')
    except urllib.error.HTTPError as error: assert error.code==422
    assert db.execute("SELECT b.key FROM active_storage_blobs b JOIN active_storage_attachments a ON a.blob_id=b.id WHERE a.record_type='User'").fetchone()[0]==avatar
    with upload('/account','account[logo]','logo.png','image/png',png,[('_method','patch')]): pass
    with probe.open(base+'/account/logo') as response:
        logo=response.read();assert response.headers['Content-Type']=='image/png'
        assert subprocess.check_output(['identify','-format','%wx%h','png:-'],input=logo)==b'512x512'
    with probe.open(base+'/account/logo?size=small') as response:
        assert subprocess.check_output(['identify','-format','%wx%h','png:-'],input=response.read())==b'192x192'
    other,_=client();code=db.execute('SELECT join_code FROM accounts').fetchone()[0]
    with post('/join/'+code,{'user[name]':'Bob','user[email_address]':'bob@example.test','user[password]':'password123'},other): pass
    try:
        upload('/account','account[logo]','logo.png','image/png',png,opener=other)
        raise AssertionError('member changed account logo')
    except urllib.error.HTTPError as error: assert error.code==403
    with post('/rooms/directs',{'user_ids[]':'2'}) as response: room=int(response.url.rsplit('/',1)[1])
    with upload(f'/rooms/{room}/messages','message[attachment]','photo.png','image/png',png) as response:
        markup=response.read();assert b'?preview=1' in markup and b'<img loading=' in markup
    blob=db.execute("SELECT b.key FROM active_storage_blobs b JOIN active_storage_attachments a ON a.blob_id=b.id WHERE a.record_type='Message' ORDER BY a.id DESC LIMIT 1").fetchone()[0]
    with owner.open(base+'/attachments/'+blob) as response: assert response.read()==png
    with other.open(base+'/attachments/'+blob+'?preview=1') as response: assert response.read()[8:12]==b'WEBP'
    with owner.open(urllib.request.Request(base+'/attachments/'+blob,headers={'Range':'bytes=0-7'})) as response: assert response.status==206 and response.read()==png[:8]
    with owner.open(urllib.request.Request(base+'/attachments/'+blob,headers={'Range':'bytes=-8'})) as response: assert response.status==206 and response.read()==png[-8:]
    try:
        owner.open(urllib.request.Request(base+'/attachments/'+blob,headers={'Range':'bytes=99999999-'}))
        raise AssertionError('unsatisfiable range accepted')
    except urllib.error.HTTPError as error: assert error.code==416
    # Video posters and native audio controls use the same protected endpoints.
    with tempfile.TemporaryDirectory(prefix='campfire-video-') as temp:
        video_path=temp+'/clip.mp4'
        subprocess.run(['ffmpeg','-nostdin','-v','error','-f','lavfi','-i','color=c=blue:s=320x240:d=0.2','-c:v','libx264','-pix_fmt','yuv420p','-y',video_path],check=True)
        with upload(f'/rooms/{room}/messages','message[attachment]','clip.mp4','video/mp4',Path(video_path).read_bytes()) as response:
            rendered=response.read();assert b'<video controls' in rendered and b'poster=' in rendered
        video=db.execute("SELECT b.key FROM active_storage_blobs b JOIN active_storage_attachments a ON a.blob_id=b.id WHERE a.record_type='Message' ORDER BY a.id DESC LIMIT 1").fetchone()[0]
        with owner.open(base+'/attachments/'+video+'?preview=1') as response: assert response.read()[8:12]==b'WEBP'
        with owner.open(base+'/attachments/'+video+'?inline=1') as response: assert response.headers['Content-Disposition'].startswith('inline')
    with upload(f'/rooms/{room}/messages','message[attachment]','audio.mp3','audio/mpeg',b'audio fixture') as response: assert b'<audio controls' in response.read()
    with owner.open(base+'/autocompletable/users?query=Bob') as response: sgid=json.load(response)[0]['sgid']
    body=f'<p><strong>Rich text</strong></p><action-text-attachment sgid="{sgid}"></action-text-attachment>'
    with post('/rooms/1/messages',{'message[body]':body}) as response: assert b'class="mention"' in response.read()
    content='<div><a href="https://example.com">Preview title</a><img src="javascript:bad" onerror="alert(1)"></div>'
    embed='<action-text-attachment content-type="application/vnd.actiontext.opengraph-embed" content="'+html.escape(content,quote=True)+'"></action-text-attachment>'
    with post('/rooms/1/messages',{'message[body]':embed}) as response:
        rendered=response.read();assert b'Preview title' in rendered and b'onerror' not in rendered and b'javascript:' not in rendered
    with json_post('/unfurl_link',{'url':endpoint+'/private'}) as response: assert response.status==204
    assert received.empty(),'unfurl requested a private endpoint'
    key=ec.generate_private_key(ec.SECP256R1());auth=os.urandom(16)
    public=key.public_key().public_bytes(serialization.Encoding.X962,serialization.PublicFormat.UncompressedPoint)
    subscription={'push_subscription':{'endpoint':endpoint+'/push','p256dh_key':b64(public),'auth_key':b64(auth)}}
    try:
        json_post('/users/me/push_subscriptions',subscription,other)
        raise AssertionError('private push endpoint accepted by default')
    except urllib.error.HTTPError as error: assert error.code==422
    secure_private=dict(subscription['push_subscription'],endpoint=endpoint.replace('http:','https:')+'/push')
    try:
        json_post('/users/me/push_subscriptions',{'push_subscription':secure_private},other)
        raise AssertionError('private HTTPS push endpoint accepted')
    except urllib.error.HTTPError as error: assert error.code==422
    restart(True)
    with json_post('/users/me/push_subscriptions',subscription,other): pass
    with json_post('/users/me/push_subscriptions',subscription,other): pass
    assert db.execute('SELECT COUNT(*) FROM push_subscriptions').fetchone()[0]==1
    with owner.open(base+'/users/me/profile') as response: vapid=re.search(r'name="vapid-public-key" content="([^"]+)"',response.read().decode()).group(1)
    with post(f'/rooms/{room}/messages',{'message[body]':'Encrypted hello'}): pass
    payload=decrypt(received.get(timeout=8),key,auth,endpoint,vapid)
    assert payload['title']=='Alice' and payload['options']['body']=='Encrypted hello' and payload['options']['data']['path'].startswith(f'/rooms/{room}/@')
    eventually(lambda:db.execute('SELECT COUNT(*) FROM egg_push_jobs').fetchone()[0]==0)
    with post('/rooms/1/messages',{'message[body]':'No mention, no push'}): pass
    with post('/rooms/1/messages',{'message[body]':f'<action-text-attachment sgid="{sgid}">@Bob</action-text-attachment> Notification mention'}): pass
    assert decrypt(received.get(timeout=8),key,auth,endpoint,vapid)['options']['body'].endswith('Notification mention')
    eventually(lambda:db.execute('SELECT COUNT(*) FROM egg_push_jobs').fetchone()[0]==0)
    assert received.empty()
    sid=db.execute('SELECT id FROM push_subscriptions').fetchone()[0]
    with post(f'/users/me/push_subscriptions/{sid}/test_notifications',{},other): pass
    assert decrypt(received.get(timeout=8),key,auth,endpoint,vapid)['title']=='Campfire Test'
    eventually(lambda:db.execute('SELECT COUNT(*) FROM egg_push_jobs').fetchone()[0]==0)
    db.execute("UPDATE push_subscriptions SET endpoint=? WHERE id=?",(endpoint+'/retry',sid));db.commit()
    with post(f'/users/me/push_subscriptions/{sid}/test_notifications',{},other): pass
    assert decrypt(received.get(timeout=8),key,auth,endpoint,vapid)['title']=='Campfire Test'
    eventually(lambda:db.execute('SELECT attempts FROM egg_push_jobs').fetchone()==(1,))
    db.execute('UPDATE egg_push_jobs SET available_after=0');db.commit()
    assert decrypt(received.get(timeout=8),key,auth,endpoint,vapid)['title']=='Campfire Test'
    eventually(lambda:db.execute('SELECT COUNT(*) FROM egg_push_jobs').fetchone()[0]==0)
    db.execute("UPDATE push_subscriptions SET endpoint=? WHERE id=?",(endpoint+'/gone',sid));db.commit()
    with post(f'/users/me/push_subscriptions/{sid}/test_notifications',{},other): pass
    received.get(timeout=8)
    eventually(lambda:db.execute('SELECT COUNT(*) FROM push_subscriptions').fetchone()[0]==0)
    print('PASS: avatar/logo uploads, attachment previews and ranges, rich text, encrypted one-use Flash, private-address guards, Web Push decryption, VAPID signatures, targeting and expired subscriptions')

if __name__=='__main__':
    endpoint=http.server.ThreadingHTTPServer(('127.0.0.1',0),Endpoint);threading.Thread(target=endpoint.serve_forever,daemon=True).start()
    with tempfile.TemporaryDirectory(prefix='campfire-features-') as directory:
        with socket.socket() as sock: sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        base=f'http://127.0.0.1:{port}';database=directory+'/app.sqlite3'
        env=dict(os.environ,HTTP_PORT=str(port),CAMPFIRE_DATABASE_PATH=database,CAMPFIRE_FILES_PATH=directory+'/files',CAMPFIRE_ASSETS_PATH=str(ROOT/'build/assets'),SECRET_KEY_BASE='feature-contracts-secret',CAMPFIRE_PUSH_ALLOW_LOCAL='0')
        with open(directory+'/server.log','w+') as log:
            server=None
            def restart(local=False):
                global server
                if server: server.terminate();server.wait(timeout=5)
                env['CAMPFIRE_PUSH_ALLOW_LOCAL']='1' if local else '0'
                server=subprocess.Popen([str(ROOT/'build/campfire')],env=env,cwd=ROOT,stdout=log,stderr=log)
                def ready():
                    try:
                        opener,_=client()
                        with opener.open(base+'/up',timeout=1): return True
                    except OSError: return False
                eventually(ready)
            try:
                restart()
                with sqlite3.connect(database) as db: run(base,db,f'http://127.0.0.1:{endpoint.server_port}',restart)
            except Exception:
                log.seek(0);print(log.read());raise
            finally:
                if server: server.terminate();server.wait(timeout=5)
                endpoint.shutdown();endpoint.server_close()
