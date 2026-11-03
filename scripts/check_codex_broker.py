"""Real installed Codex against a local stub: tool inventory, denials and roles.

No external inference, subscription credentials or physical world are used.
"""
import argparse
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time

from PIL import Image
from robofrontier.codex.launch import launch_config
from robofrontier.codex.tool_backend import doctor, preflight_probe
from robofrontier.run_setup import write_json
from robofrontier.task_config import ROOT

NATIVE = {'native_shell':'shell_command','native_exec':'exec_command','native_stdin':'write_stdin',
          'native_patch':'apply_patch','native_image':'view_image','native_read':'read_file',
          'native_list':'list_dir','native_js':'js','native_agent':'spawn_agent',
          'native_collab':'collaboration.spawn_agent','native_freeform':'apply_patch'}


def check(output):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    home = output/'codex-home'; home.mkdir(mode=0o700)
    env = {'PATH': os.environ['PATH'], 'LANG':'C.UTF-8', 'CODEX_HOME':str(home),
           'ROBOFRONTIER_OFFLINE_STUB_TOKEN':'local-stub-no-credential'}
    kernel = doctor()
    Image.new('RGB',(32,32),'red').save(output/'colors.png')
    probe = preflight_probe(output)
    requests, outputs, counts = [], {}, Counter()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def do_POST(self):
            body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            requests.append(body)
            scenario=re.findall(r'scenario:([a-z_0-9]+)',json.dumps(body.get('input',[])))[-1]
            counts[scenario]+=1
            if counts[scenario]==1:
                name='policy_exec';args={'command':probe['command']}
                if scenario in ('image','image_escape'):
                    name='policy_image';args={'path':probe['image'] if scenario=='image' else str(Path(probe['run_dir'])/'private/secret.txt')}
                elif scenario in NATIVE:
                    name=NATIVE[scenario];args={'cmd':'touch '+str(output/'NATIVE_EXECUTED'),
                        'command':'touch '+str(output/'NATIVE_EXECUTED'),'path':probe['image'],'session_id':999999}
                item=dict(id='fc_'+scenario,type='function_call',call_id='call_'+scenario,name=name,
                          arguments=json.dumps(args),status='completed')
                if scenario=='native_freeform':
                    item=dict(id='fc_'+scenario,type='custom_tool_call',call_id='call_'+scenario,name=name,
                        input='*** Begin Patch\n*** Add File: '+str(output/'NATIVE_EXECUTED')+'\n+bad\n*** End Patch',status='completed')
            else:
                tool_outputs=[x for x in body.get('input',[]) if x.get('type')=='function_call_output']
                outputs[scenario]=tool_outputs[-1].get('output') if tool_outputs else None
                item=dict(id='msg_'+scenario,type='message',role='assistant',status='completed',
                          content=[dict(type='output_text',text='BROKER_PROTOCOL_OK',annotations=[])])
            response=dict(id='resp_'+str(len(requests)),object='response',created_at=int(time.time()),
                status='completed',model=body.get('model'),output=[item],usage=dict(input_tokens=10,output_tokens=10,
                    total_tokens=20,input_tokens_details={'cached_tokens':0},output_tokens_details={'reasoning_tokens':0}))
            self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
            for index,(kind,data) in enumerate([
                ('response.created',{'response':{**response,'status':'in_progress','output':[]}}),
                ('response.output_item.added',{'output_index':0,'item':{**item,'status':'in_progress'}}),
                ('response.output_item.done',{'output_index':0,'item':item}),
                ('response.completed',{'response':response})]):
                self.wfile.write(('event: '+kind+'\ndata: '+json.dumps({'type':kind,'sequence_number':index,**data})+'\n\n').encode())
            self.wfile.flush()
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    profile=dict(model='offline-broker',provider='offline_protocol',effort='high',vision=True,
        context_window=300000,auto_compact_token_limit=267000,tool_backend='landlock-v1',
        use_cached_model_metadata=False,base_url=f'http://127.0.0.1:{server.server_port}',
        env_key='ROBOFRONTIER_OFFLINE_STUB_TOKEN')
    launch=launch_config(profile,output,run_dir=Path(probe['run_dir']))
    launch.update(tool_probe=probe,python=sys.executable)
    write_json(output/'launch.json',launch)
    try:
        result=subprocess.run(['node',str(ROOT/'tests/codex_broker_probe.js'),str(output)],
            env=env,capture_output=True,text=True,timeout=120)
        (output/'client.log').write_text(result.stdout+result.stderr)
        write_json(output/'requests.json',requests)
        inventory=sorted({t.get('name',t.get('type')) for r in requests for t in r.get('tools',[])})
        client=json.loads((output/'client-report.json').read_text()) if (output/'client-report.json').exists() else {}
        refused={name:'unsupported' in json.dumps(outputs.get(name)).lower() for name in NATIVE}
        report=dict(passed=False,external_model_calls=0,local_stub_requests=len(requests),
            tool_inventory=inventory,native_rejected=refused,kernel=kernel,client=client,client_exit_code=result.returncode)
        report['passed']=(result.returncode==0 and inventory==['policy_exec','policy_image','robot']
            and all(refused.values()) and not (output/'NATIVE_EXECUTED').exists()
            and client.get('fork_verified') and client.get('resume_verified')
            and client.get('concurrent_roles')==8 and client.get('tools_succeeded')==12
            and client.get('private_image_rejected'))
        write_json(output/'report.json',report)
        if not report['passed']:print(result.stderr[-3000:],file=sys.stderr)
        return report
    finally: server.shutdown()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    report=check(parser.parse_args().output)
    print(json.dumps(report,indent=2))
    raise SystemExit(0 if report['passed'] else 1)
