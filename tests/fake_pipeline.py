"""Offline executor. No MuJoCo import, windows, model calls or real actions."""
import os
from pathlib import Path

# Tests never probe the real model API hosts (robofrontier/runtime/outage.py).
os.environ.setdefault('ROBOFRONTIER_OUTAGE_PROBE', 'off')

class FakeWorld:
    def __init__(self,directory,task):
        self.directory=Path(directory);self.task=task;self.time=0.;self.running={};self.finished=[];self.executed=[]
    def robot_facts(self,cfg):
        return {'adapter':'FakeWorld','robots':list(self.task['arms']),'scope':'Synthetic adapter facts, not a Panda model'}
    def validate_action(self,actor,op,data,cfg):
        if actor in self.running:raise ValueError('Fake arm busy')
        if op=='gripper':
            if data.get('mode')=='grasp':
                if not {'width_m','force_n'}<=set(data):raise ValueError('Invalid fake grasp')
            elif data.get('state') not in ('open','close'):raise ValueError('Invalid gripper')
        return {'op':op,'data':data}
    def start_action(self,actor,call_id,command):
        self.running[actor]=call_id;self.executed.append((actor,call_id,command))
    def complete(self,actor,status='completed'):
        call_id=self.running.pop(actor);self.finished.append({'call_id':call_id,'status':status})
    def poll_actions(self,timeout):
        values=self.finished;self.finished=[];return values
    def abort_actions(self,reason):
        values=[{'call_id':call_id,'status':'failed','reason':reason} for call_id in self.running.values()]
        self.running.clear();return values
    arms={}  # no physical arms: finish's settle before scoring only advances time
    def step(self):self.time+=.02
    def evaluate(self):return {'scope':'fake executor only; not a robot score'}

def fake_capture(cameras):
    return {'images':{},'camera_names':cameras,'robot':{},'scope':'fake, no pixels captured'}
