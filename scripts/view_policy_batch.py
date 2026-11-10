"""Loopback, read-only batch viewer using existing JSON and images only.

Supports unified Codex/Claude jobs and legacy case lists. Never opens SQLite,
creates runtime files, calls a model, renders a view or sends robot requests.
"""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit
from robofrontier.runtime import layout as run_layout

HTML='''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>RoboFrontier run status</title>
<style>body{margin:28px;background:#f4f6f8;color:#20313d;font:16px system-ui}.sub,footer{color:#60707b}.grid{display:grid;grid-template-columns:repeat(3,minmax(240px,1fr));gap:18px}.card{background:white;border:1px solid #dce4ea;border-radius:13px;padding:18px}.head{display:flex;justify-content:space-between;gap:10px}.badge{color:#00766c}img{width:100%;aspect-ratio:1.6;object-fit:contain;margin:12px 0;background:#edf1f4;border-radius:7px}.dim{color:#687883;font-size:13px}.actions{display:flex;gap:16px}a{color:#12659b}footer{margin-top:24px}@media(max-width:950px){.grid{grid-template-columns:repeat(2,minmax(230px,1fr))}}@media(max-width:600px){.grid{grid-template-columns:1fr}body{margin:16px}}</style>
<h1>RoboFrontier run status</h1><p id="summary" class="sub">Reading existing batch metadata...</p><div id="content" class="grid"></div>
<footer>Read-only JSON/image snapshots. Missing task state is not reported as a started or successful task. Images and saved runtime snapshots can lag execution; this page does not poll a live database, render images or control a run. Completion and process records remain separate. Real-time video is shown only when an existing recording is available.</footer>
<script>
const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function update(){try{const response=await fetch('/api');if(!response.ok)throw Error('Metadata unavailable');const d=await response.json();document.getElementById('summary').textContent=`${d.cases.length} tasks | Saved batch: ${d.status} | ${d.engine||'engine not reported'}`;document.getElementById('content').innerHTML=d.cases.map(r=>`<article class="card"><div class="head"><b>${esc(r.case_id)}</b><span class="badge">${esc(r.lifecycle)}</span></div><p class="dim">${esc(r.profile||'profile not reported')} | ${esc(r.family||'family not reported')} | Level ${esc(r.level??'?')} | ${esc(r.arms??'?')} arms</p>${r.image_mtime?`<img alt="Latest saved task view" src="/frame/${r.key}?v=${r.image_mtime}">`:'<p>No saved image</p>'}<p>${r.evaluation?(r.evaluation.task_success?'Recorded completion: successful':'Recorded completion: not successful'):'No terminal evaluation reported'}</p><p class="dim">${r.snapshot_mtime?`Saved task snapshot: ${Math.max(0,Math.floor(Date.now()/1000-r.snapshot_mtime))} s old`:'No task runtime snapshot; status is from batch metadata'} | Actions: ${esc(r.actions??'not reported')} | Delegates: ${esc(r.delegates??'not reported')}</p><div class="actions">${r.viewer?`<a target="_blank" rel="noopener" href="${esc(r.viewer)}">Existing observation panel</a>`:''}${r.video?`<a target="_blank" href="/video/${r.key}">Existing real-time video</a>`:''}</div></article>`).join('');}catch(e){document.getElementById('summary').textContent='Batch metadata is unavailable; no task state inferred.';}}update();setInterval(update,3000);
</script></html>'''


def document(path):
    """Optional snapshots may be missing or temporarily unavailable."""
    try:
        value=json.loads(path.read_text())
        return value if isinstance(value,dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def batch_rows(base):
    batch=document(base/'batch.json')
    if 'jobs' not in batch and 'cases' not in batch:
        raise ValueError('No supported batch metadata')
    state=document(run_layout.batch_path(base,'engineering_status')) or batch
    rows=[]
    for index,job in enumerate(batch.get('jobs',batch.get('cases',[]))):
        raw=Path(job.get('run_directory',job.get('run_dir','')))
        run=(raw if raw.is_absolute() else base/raw).resolve()
        if run==base or not run.is_relative_to(base):
            raise ValueError('Run directory must stay inside the selected batch')
        live=next((j for j in state.get('jobs',[]) if
            (j.get('profile'),j.get('case_id'))==(job.get('profile'),job.get('case_id'))),job)
        rows.append({**job,'key':str(index),'run_dir':run,'status':live.get('status')})
    return batch,state,rows


def frame(row):
    run=row['run_dir']
    finals=[run/'private/outputs'/('final-global'+ext) for ext in ('.png','.jpg','.jpeg')]
    finals=[p for p in finals if p.is_file()]
    if finals:return max(finals,key=lambda x:x.stat().st_mtime),'final'
    files=[p for ext in ('png','jpg','jpeg') for p in (run/'public/observations').glob('*-global.'+ext)]
    if files:return max(files,key=lambda x:x.stat().st_mtime),'observation'
    previews=[run/'public/inputs'/('preview-global'+ext) for ext in ('.jpg','.jpeg','.png')]
    return next((p for p in previews if p.is_file()),previews[0]),'preview'


def batch_snapshot(base):
    batch,state,rows=batch_rows(base)
    config=document(base/'effective-config.json')
    values=[]
    for row in rows:
        run=row['run_dir'];task=document(run/'public/inputs/task.json')
        snapshot_path=run/'private/outputs/runtime.json';snapshot=document(snapshot_path)
        agents=snapshot.get('agents');jobs=snapshot.get('jobs')
        lifecycle=snapshot.get('lifecycle') or row.get('status') or 'not_reported'
        if not snapshot and state.get('status')=='running' and lifecycle in ('prepared','draft','prepared_not_started'):
            lifecycle='task_state_not_reported'
        image,kind=frame(row)
        evaluation=document(run/'private/outputs/evaluation.json')
        # Do not return work notes, mail, connection tokens or evaluator truth.
        values.append(dict(key=row['key'],case_id=row['case_id'],profile=row.get('profile'),
            family=row.get('family',task.get('family')),level=row.get('level',task.get('level')),
            arms=row.get('arms',len(task['arms']) if isinstance(task.get('arms'),(dict,list)) else None),
            lifecycle=lifecycle,snapshot_mtime=snapshot_path.stat().st_mtime if snapshot else None,
            actions=len(jobs) if isinstance(jobs,(dict,list)) else None,
            delegates=sum(v.get('kind')=='delegate' for v in agents.values()) if isinstance(agents,dict) else None,
            image_kind=kind,image_mtime=image.stat().st_mtime if image.is_file() else None,
            video=(run/'private/outputs/global-realtime.mp4').is_file(),
            viewer=document(run/'private/state/observer.json').get('url'),
            evaluation={'task_success':evaluation['task_success']} if 'task_success' in evaluation else None))
    return dict(cases=values,status=state.get('status','not_reported'),
        engine=config.get('policy',{}).get('engine',batch.get('engine')),read_only=True,
        source='Existing atomic batch JSON and saved task snapshots; SQLite is never opened')


def create_server(batch,port=0):
    base=Path(batch).resolve()
    batch_rows(base)  # Validate without creating files before opening a port.
    def row(key):
        rows=batch_rows(base)[2]
        matches=[r for r in rows if r['key']==key]
        if not matches:matches=[r for r in rows if r['case_id']==key]
        if len(matches)!=1:raise ValueError('Unknown or ambiguous task')
        return matches[0]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def reply(self,data,kind):
            self.send_response(200);self.send_header('Content-Type',kind);self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
        def do_GET(self):
            path=urlsplit(self.path).path
            try:
                if path=='/':return self.reply(HTML.encode(),'text/html;charset=utf-8')
                if path=='/api':return self.reply(json.dumps(batch_snapshot(base)).encode(),'application/json')
                if path.startswith('/frame/'):
                    f,_=frame(row(unquote(path.removeprefix('/frame/'))));return self.reply(f.read_bytes(),'image/jpeg' if f.suffix.lower() in ('.jpg','.jpeg') else 'image/png')
                if path.startswith('/video/'):
                    f=row(unquote(path.removeprefix('/video/')))['run_dir']/'private/outputs/global-realtime.mp4';size=f.stat().st_size;start=0;end=size-1;part=self.headers.get('Range')
                    if part:
                        m=re.fullmatch(r'bytes=(\d+)-(\d*)',part)
                        if not m:raise ValueError('Unsupported range')
                        start=int(m[1]);end=min(end,int(m[2]) if m[2] else end)
                        if not 0<=start<=end:raise ValueError('Invalid range')
                    self.send_response(206 if part else 200);self.send_header('Content-Type','video/mp4');self.send_header('Accept-Ranges','bytes');self.send_header('Content-Length',str(end-start+1))
                    if part:self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
                    self.end_headers()
                    with f.open('rb') as stream:
                        stream.seek(start);left=end-start+1
                        while left:
                            data=stream.read(min(left,1024*1024))
                            if not data:break
                            self.wfile.write(data);left-=len(data)
                    return
                self.send_error(404)
            except (FileNotFoundError,KeyError,StopIteration,ValueError):self.send_error(404)
            except (BrokenPipeError,ConnectionResetError):pass
    server=ThreadingHTTPServer(('127.0.0.1',port),Handler);server.daemon_threads=True
    return server


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('batch',type=Path);p.add_argument('--port',type=int,default=0);a=p.parse_args()
    server=create_server(a.batch,a.port)
    print(json.dumps(dict(url=f'http://127.0.0.1:{server.server_port}/',read_only=True)),flush=True)
    try:server.serve_forever()
    finally:server.server_close()


if __name__=='__main__':main()
