"""Read-only configured-camera panel for an already-running shared world.

Runs independently of the research conversation; never submits robot actions.
Open the printed URL: it carries a per-launch key that sets a same-site cookie,
and every other request needs that cookie and a 127.0.0.1 Host, so other web
pages cannot trigger observations or read frames.
"""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
import os
from pathlib import Path
import secrets
import threading
import time
import urllib.parse
import urllib.request
import uuid

CAMERAS=['global','global_side']+[a+'_'+s for a in 'ABC' for s in ('front','side')]
COOKIE='robofrontier_panel'


def make_capture(connection,cameras,lock,cache):
    def capture():
        with lock:
            body={'actor':connection['actor'],'op':'observe','call_id':uuid.uuid4().hex,'data':{'cameras':cameras}}
            if connection.get('schema_version') in (2,3):body.update(schema_version=connection['schema_version'],run_id=connection['run_id'])
            req=urllib.request.Request(connection['url']+'/op',json.dumps(body).encode(),headers={'Content-Type':'application/json','X-Token':connection['token']})
            with urllib.request.urlopen(req,timeout=45) as r:result=json.load(r)
            if result.get('error'):raise RuntimeError(result['error'])
            if 'observation' not in result:raise RuntimeError('Capture pending; try refresh later')
            obs=result['observation'];cache['images']={c:(Path(f).read_bytes(), 'image/jpeg' if Path(f).suffix.lower() in ('.jpg','.jpeg') else 'image/png') for c,f in obs['images'].items()}
            cache.update(captured_at=time.time(),sim_time_s=obs['sim_time_s'],error=None)
            return {'cameras':cameras,'sim_time_s':cache['sim_time_s'],'captured_at':cache['captured_at']}
    return capture


def make_handler(key,capture,cameras,lock,cache):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*a):pass
        def reply(self,body,kind='application/json',status=200,headers=()):
            raw=body if isinstance(body,bytes) else json.dumps(body,ensure_ascii=False).encode()
            self.send_response(status);self.send_header('Content-Type',kind);self.send_header('Cache-Control','no-store')
            for name,value in headers:self.send_header(name,value)
            self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
        def allowed_host(self):
            # Pins the loopback origin, so a rebound DNS name cannot reach the panel.
            port=self.server.server_address[1]
            return self.headers.get('Host') in (f'127.0.0.1:{port}',f'localhost:{port}')
        def allowed(self):
            # The cookie proves the request comes from the page opened with this launch's key.
            port=self.server.server_address[1]
            if not self.allowed_host():return False
            origin=self.headers.get('Origin')
            if origin is not None and origin not in (f'http://127.0.0.1:{port}',f'http://localhost:{port}'):return False
            cookies=dict(part.strip().split('=',1) for part in (self.headers.get('Cookie') or '').split(';') if '=' in part)
            return hmac.compare_digest(cookies.get(COOKIE,''),key)
        def do_GET(self):
            path,_,query=self.path.partition('?')
            if path=='/' and hmac.compare_digest(urllib.parse.parse_qs(query).get('k',[''])[0],key) and self.allowed_host():
                return self.reply((Path(__file__).resolve().parents[1]/'assets/pipeline_cameras.html').read_bytes(),'text/html; charset=utf-8',
                                  headers=[('Set-Cookie',f'{COOKIE}={key}; HttpOnly; SameSite=Strict; Path=/')])
            if not self.allowed():return self.reply({'error':'forbidden'},status=403)
            if path=='/':return self.reply((Path(__file__).resolve().parents[1]/'assets/pipeline_cameras.html').read_bytes(),'text/html; charset=utf-8')
            if path.startswith('/frames/'):
                name=path.removeprefix('/frames/').removesuffix('.png')
                with lock:item=cache['images'].get(name)
                return self.reply(item[0],item[1]) if item else self.reply({'error':'refresh first'},status=404)
            if path=='/api/status':
                with lock:return self.reply({'cameras':cameras,**{k:v for k,v in cache.items() if k!='images'}})
            return self.reply({'error':'not found'},status=404)
        def do_POST(self):
            if not self.allowed():return self.reply({'error':'forbidden'},status=403)
            if self.path!='/api/refresh':return self.reply({'error':'not found'},status=404)
            try:return self.reply(capture())
            except Exception as e:return self.reply({'error':str(e)},status=503)
    return Handler


def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument('--run-dir',type=Path,required=True);p.add_argument('--port',type=int,default=0);args=p.parse_args(argv)
    run=args.run_dir.resolve();cameras=CAMERAS
    connection_path=next((run/p for p in ('private/state/connections/Meta.json','private/connections/Meta.json','public/connection-research.json') if (run/p).exists()),None)
    if connection_path is None:raise SystemExit('No existing role connection; camera panel never starts a world')
    connection=json.loads(connection_path.read_text())
    task_path=next((run/p for p in ('public/inputs/task.json','public/task.json') if (run/p).exists()),run/'public/inputs/task.json')
    if task_path.exists():cameras=json.loads(task_path.read_text()).get('cameras',cameras)
    if not connection.get('url'):raise SystemExit('Execution owner not started; camera panel never starts one')
    lock=threading.Lock();cache={'images':{},'captured_at':None,'sim_time_s':None,'error':None}
    key=secrets.token_urlsafe(24)
    server=ThreadingHTTPServer(('127.0.0.1',args.port),make_handler(key,make_capture(connection,cameras,lock,cache),cameras,lock,cache))
    server.daemon_threads=True
    url=f'http://127.0.0.1:{server.server_port}/'
    panel_file=run/('private/state/camera-panel.json' if connection.get('schema_version')==3 else 'camera-panel.json')
    # The key is printed for the operator only, never written into the run.
    panel_file.write_text(json.dumps({'url':url,'pid':os.getpid(),'read_only':True,'key_required':True},indent=2)+'\n')
    print(json.dumps({'url':url+'?k='+key,'read_only':True}),flush=True)
    server.serve_forever()


if __name__=='__main__':main()
