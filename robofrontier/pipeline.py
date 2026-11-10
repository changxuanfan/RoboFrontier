"""One MuJoCo world, independently controlled Panda arms, file-backed mailbox.

The server owns physics/GL. Policy clients never mutate model/data directly.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
import os
import queue
import secrets
import threading
import time
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import glfw
import mujoco
import numpy as np
from PIL import Image

from .scene import ROOT
from .sim import RobotIK
from .recording import Video

from .task_config import load_task, action_limits, panda_control_profile
from .robot_control import PandaArm
from .scene_task import camera_names
from .observation_image import observation_profile
from .tool_errors import CallIdConflict, conflict_error
from .runtime_service import RuntimeService
from .motion_check import (CONTROL_DT, JOINT_SPEED_LIMIT, JOINT_ACCEL_LIMIT,
                           TRACKING_LIMIT, RobotGeometry, prepare_check, state_id)

def atomic_json(path, value):
    from .run_setup import write_json
    write_json(path,value)


def portable_xml(xml,folder):
    """The loaded model's XML with absolute asset paths made relative to `folder`, so a
    saved copy still loads after the run moves to another machine or directory."""
    root=ET.fromstring(xml)
    compiler=root.find('compiler')
    for element,key in [(compiler,'meshdir'),(compiler,'texturedir')]+[(t,'file') for t in root.iter('texture')]+[(m,'file') for m in root.iter('mesh')]:
        value=element.get(key) if element is not None else None
        if value and os.path.isabs(value):element.set(key,os.path.relpath(value,folder))
    return ET.tostring(root,encoding='unicode')

class Arm(PandaArm):
    def __init__(self,model,data,name,base_y=None,initialized=False):
        self.base_y=float(model.body(name+'_link0').pos[1]) if base_y is None else base_y
        super().__init__(model,data,name,None if initialized else [.40,self.base_y,.68])


class World:
    segment=0
    def __init__(self,directory,task=None):
        self.directory=Path(directory);self.task=task or load_task();segment_restore=None
        self.command_bounds=copy.deepcopy(self.task.get('workspace_world_m'))
        folder=self.directory/Path(self.task['scene_asset']).parent
        root=ET.parse(self.directory/self.task['scene_asset']).getroot()
        compiler=root.find('compiler')
        compiler.set('meshdir',str((folder/compiler.get('meshdir','')).resolve()) if (folder/'workstation.json').exists() else str(folder/'model-assets'))
        for texture in root.findall('asset/texture'):
            if texture.get('file'):texture.set('file',str(folder/texture.get('file')))
        self.xml=ET.tostring(root,encoding='unicode');self.model=mujoco.MjModel.from_xml_string(self.xml)
        self.data=mujoco.MjData(self.model)
        mujoco.mj_resetDataKeyframe(self.model,self.data,self.model.key('initial').id);mujoco.mj_forward(self.model,self.data)
        from .run_segments import restore_world
        # A continued run (docs/running/run-segments.md) rebuilds its world from the last recorded pose.
        segment_restore=restore_world(self.directory,self.task,self.model,self.data)
        if segment_restore:self.segment=segment_restore['segment'];mujoco.mj_forward(self.model,self.data)
        self.arms={a:Arm(self.model,self.data,a,initialized=True) for a in self.task['arms']}
        if segment_restore:
            # Reinitialize references to measured positions. No old action
            # or force-controlled grasp is inferred or replayed.
            for arm in self.arms.values():
                arm.qref=self.data.qpos[arm.qids].copy();self.data.ctrl[arm.act]=arm.qref
                control=arm.width_to_grip(arm.observe()['gripper_width_m'])
                arm.gripper=control;arm.grip_goal=control;self.data.ctrl[arm.grip]=control
        mujoco.mj_forward(self.model,self.data)
        hand_cfg=self.directory/'private/inputs/harness.json'
        frozen_cfg=json.loads(hand_cfg.read_text()) if hand_cfg.exists() else {}
        from .physics_profile import attach
        self.physics_profile=attach(self,frozen_cfg)
        self.observation_image=observation_profile(frozen_cfg)
        if frozen_cfg.get('robot_labels')=='beside-robot-v1':
            from .factory.labels import place_robot_labels
            place_robot_labels(self.model,self.data,self.task)
        profile=frozen_cfg.get('gripper_position_servo','legacy')
        for arm in self.arms.values():arm.configure_hand_position_servo(profile)
        if segment_restore:
            # Only recent, independently logged completed grasps are
            # approximated. This is not restoration of actuator history.
            holds=segment_restore.get('held_grasps',{})
            self.restored_holds=[]
            for name,evidence in holds.items():
                if name not in self.arms:raise ValueError('Recorded grasp names an absent arm')
                arm=self.arms[name];width=arm.observe()['gripper_width_m']
                # A hold snapshot can predate a release; keep only grasps the pose shows.
                if abs(width-evidence['observed_width_m'])>.005:continue
                self.restored_holds.append(name)
                force=float(evidence['force_n']);arm.grasp_force=force
                arm.grasp_width=float(evidence['target_width_m'])
                arm.grasp_epsilon=(float(evidence['epsilon_inner_m']),float(evidence['epsilon_outer_m']))
                arm.grasp_phase='hold';arm.grasp_confirmed=True;arm.gripper_command_mode='grasp'
                arm.grasp_force_started=-.4;arm.grasp_drive_force=force
                self.model.actuator_gainprm[arm.grip,:]=0;self.model.actuator_gainprm[arm.grip,0]=1
                self.model.actuator_biasprm[arm.grip,:]=0
                ceiling=min(70.,-arm.grip_position_parameters[3][0],arm.grip_position_parameters[3][1])
                self.model.actuator_forcerange[arm.grip]=[-ceiling,ceiling]
                self.model.actuator_ctrlrange[arm.grip]=[-ceiling,ceiling]
                self.data.ctrl[arm.grip]=-min(force,ceiling-1e-6)
        self.suite_sampler=None;self.motion_recorder=None
        output=self.directory/'private/outputs';output.mkdir(parents=True,exist_ok=True)
        (output/'scene.xml').write_text(portable_xml(self.xml,output))

    @property
    def time(self):return float(self.data.time)

    def held_grasps(self):
        """Arms holding a confirmed grasp, as a continued segment would restore them."""
        holds={}
        for name,arm in self.arms.items():
            if arm.job is None and arm.gripper_command_mode=='grasp' and arm.grasp_phase=='hold' and arm.grasp_confirmed:
                holds[name]=dict(sim_s=self.time,observed_width_m=arm.observe()['gripper_width_m'],force_n=arm.grasp_force,
                                 target_width_m=arm.grasp_width,epsilon_inner_m=arm.grasp_epsilon[0],epsilon_outer_m=arm.grasp_epsilon[1])
        return holds

    def tcp_command_bounds(self,actor,cfg):
        bounds=getattr(self,'command_bounds',None)
        if bounds:return np.array(bounds['lower']),np.array(bounds['upper'])
        y=self.arms[actor].base_y
        return (np.array([cfg['workspace_x_m'][0],y-cfg['workspace_y_radius_m'],cfg['workspace_z_m'][0]]),
                np.array([cfg['workspace_x_m'][1],y+cfg['workspace_y_radius_m'],cfg['workspace_z_m'][1]]))

    def robot_facts(self,cfg):
        """Small static planning context, without querying live MjData or objects."""
        robots={}
        for name,arm in self.arms.items():
            base=self.model.body(name+'_link0').id
            if self.model.body_parentid[base]!=0 or self.model.body_jntnum[base]!=0:
                raise ValueError('This adapter requires fixed world-root robot bases')
            lower,upper=self.tcp_command_bounds(name,cfg)
            robots[name]={'base_pose_world':{'position_m':self.model.body_pos[base].tolist(),
                                             'quaternion_wxyz':self.model.body_quat[base].tolist()},
                          'arm_dof':len(arm.qids),'grippers':1,
                          'gripper_width_range_m':[arm.grip_min,arm.grip_max],
                          'tcp_command_bounds_world_m':{'lower':lower.tolist(),'upper':upper.tolist()}}
        width_ranges={tuple(r['gripper_width_range_m']) for r in robots.values()}
        shared_width=list(next(iter(width_ranges))) if len(width_ranges)==1 else None
        return {'coordinate_frame':'world','base_poses':'fixed throughout this run',
                'shared_capabilities':{'move':'TCP position and optional quaternion_wxyz using robot-only IK, or joint_rad mode; omitted orientation holds the current reference',
                    'tcp_reference':'move.target_m and observation.robot[robot].tcp_m refer to the same world-frame center between the fingertip pads. The controller already applies the hand-to-TCP offset. This is a robot point, not a measured object center.',
                    'robot_status':'moving/holding describe controller motion or pose holding, not whether an object is grasped. Verify payload with RGB; gripper width alone is not grasp proof.',
                    'gripper':{'state':['open','close'],
                        'width_m':shared_width,
                        'width_limits_source':'Each robots entry gives its installed mechanical gripper_width_range_m; use that robot-specific range.',
                        'speed_m_s':action_limits(cfg)['allowed_gripper_speed_m_s'],
                        'mode':['move','grasp'],'grasp':{'force_n':action_limits(cfg)['allowed_grasp_force_n'],
                            'width_m':'expected object width, not zero-close','epsilon_inner_m':{'min_exclusive':0,'max':.01,'default':.005},'epsilon_outer_m':{'min_exclusive':0,'max':.01,'default':.005},
                            'force_convention':'total opposing finger drive; each finger receives half; no measured contact-force feedback',
                            'is_grasped_source':'drive width/settling inference, not verified payload support',
                            'measured_force_sensor_available':False,
                            'holding':'continues after completed grasp and during arm moves until another gripper command'}},
                    'stop':'Bounded braking of the named own call; query its terminal result',
                    'quaternion_convention':'world-frame wxyz; normalized on input',
                    'angular_speed_rad_s':action_limits(cfg)['allowed_angular_speed_rad_s'],
                    'joint_rad':{'count':7,'speed_limit_rad_s':JOINT_SPEED_LIMIT},
                    'action_contract':'pose-aperture-grasp-v2','force_control':False,
                    'force_control_scope':'continuous arm torque/wrench; Hand grasp force is separately supported',
                    'gripper_force_control':True,'robot_gravity_feedforward':True,'max_in_flight_physical_actions_per_robot':1,
                    'interface_allows_different_robot_actions_concurrently':True,'nonblocking_submission':{'wait':False}},
                'robots':robots,'control_profile':panda_control_profile(cfg),
                'camera_configuration':{'render_size_pixel':[self.observation_image['width'],self.observation_image['height']],'cameras':{self.model.camera(i).name:{'position_world_m':self.model.cam_pos[i].tolist(),'quaternion_wxyz':self.model.cam_quat[i].tolist(),'fovy_deg':float(self.model.cam_fovy[i])} for i in range(self.model.ncam)}},
                'bounds_scope':'Admitted TCP command bounds, not whole-link envelopes, guaranteed IK reachability or collision-free zones.',
                'state_sources':'Current robot state: observe; work/commitments: role notes and messages. No object state, occupancy or task plan is included.'}

    def robot_model(self,cfg):
        return RobotGeometry(self.model,self.arms).describe(self,cfg)

    def check_motion(self,parameters,cfg):
        return prepare_check(self,parameters,cfg)

    def motion_state_id(self):
        return state_id(self)

    def step(self):
        if getattr(self,'physics_profile',None) is not None:self.physics_profile.before_step()
        substeps=max(1,round(.02/self.model.opt.timestep))
        control_dt=substeps*self.model.opt.timestep
        for arm in self.arms.values():arm.control(control_dt)
        for _ in range(substeps):
            for arm in self.arms.values():
                if arm.grasp_force is not None:arm.physics_control()
            before=float(self.data.time);mujoco.mj_step(self.model,self.data)
            from .physics_health import require_valid_step
            require_valid_step(self.data,before)
            if getattr(self,'suite_sampler',None) is not None:self.suite_sampler.physical_step()
            if getattr(self,'motion_recorder',None) is not None and not self.motion_recorder.closed:self.motion_recorder.capture(self.data)
        if getattr(self,'physics_profile_active',False):
            from .physics_profile import forward_after_step
            forward_after_step(self)
        else:mujoco.mj_forward(self.model,self.data)

    def start_trial(self):
        if self.task.get('execution_readiness')=='environment_preview_only':
            raise ValueError('This v2 scene is an environment preview. Mechanism-specific evaluation and recording commissioning are required before starting a policy trial.')
        if self.task.get('execution_readiness')=='prepared_policy_trial':
            from .task_families import validate_frozen_policy
            validate_frozen_policy(self.task,self.directory)
        if self.task.get('kind')=='frontier_suite':
            from .suite.evaluate import Monitor
            secret=json.loads((self.directory/'private/inputs/suite-code.json').read_text())['code_symbols'] if self.task['family']=='dial' else None
            # Runs frozen before process_log existed keep the original 0.1 s full snapshots.
            harness=self.directory/'private/inputs/harness.json'
            frozen=json.loads(harness.read_text()) if harness.exists() else {}
            self.suite_sampler=Monitor(self,secret=secret,log_path=self.directory/'private/outputs/suite-process.jsonl',
                                       log_format=frozen.get('process_log','full'),append=self.segment>0)
            source=self.directory/Path(self.task['scene_asset']).parent
            if (source/'workstation.json').exists():
                from .motion_recording import MotionWriter
                # Runs frozen before motion_hz existed keep the original 60 Hz.
                hz=frozen.get('motion_hz',60)
                from .run_segments import output_dir
                folder=output_dir(self.directory,self.segment);folder.mkdir(parents=True,exist_ok=True)
                self.motion_recorder=MotionWriter(folder/'motion',source,self.model,self.data,hz=hz,
                                                  cache=ROOT/'runs/state-assets')

    def end_trial(self):
        if getattr(self,'suite_sampler',None) is not None:self.suite_sampler.finish()
        if getattr(self,'motion_recorder',None) is not None:self.motion_recorder.close(self.data)

    def close(self):
        if getattr(self,'motion_recorder',None) is not None and not self.motion_recorder.closed:self.motion_recorder.close(self.data,status='interrupted')
        if getattr(self,'suite_sampler',None) is not None:self.suite_sampler.close()

    def validate_action(self,actor,op,p,cfg):
        lower,upper=self.tcp_command_bounds(actor,cfg)
        return self.arms[actor].validate(op,p,cfg,lower,upper)

    def start_action(self,actor,call_id,command):
        self.arms[actor].start(call_id,command,self.time)

    def inject_fault(self,actor,call_id,op):
        """Apply this run's engineering fault, if any, to an independent action just started."""
        if not hasattr(self,'fault'):
            from .fault_injection import load
            self.fault=load(self.directory);self.fault_moves={}
        spec=self.fault
        if not spec or spec.get('applied') or op!=spec['op'] or spec['robot'] not in ('*',actor):return None
        counter='*' if spec['robot']=='*' else actor
        self.fault_moves[counter]=self.fault_moves.get(counter,0)+1
        if self.fault_moves[counter]!=spec['action_index']:return None
        arm=self.arms[actor];arm.execution_timeout_s=spec['timeout_sim_s'];arm.fault_hold_s=spec['hold_unsettled_sim_s']
        spec['applied']=True
        return {'call_id':call_id,'arm':actor,**{k:spec[k] for k in ('kind','robot','op','action_index','timeout_sim_s','hold_unsettled_sim_s')}}

    def request_stop(self,actor,call_id):
        arm=self.arms[actor]
        if arm.job!=call_id:raise ValueError('Stop target is not the active action on this robot')
        arm.request_stop(self.time)

    def recover_action(self,actor,call_id):
        return self.arms[actor].recover_stopped(call_id)

    def _stop_action(self,arm,status,reason=None):
        return arm.end(status,reason)

    def poll_actions(self,timeout):
        return [r for arm in self.arms.values() if (r:=arm.poll(self.time,timeout)) is not None]

    def abort_actions(self,reason):
        return [a.end('failed',reason) for a in self.arms.values() if a.job]

    def evaluation_evidence(self):
        """Private bounded final window, for audit only; never policy feedback."""
        if getattr(self,'suite_sampler',None) is not None:return {'result':self.suite_sampler.result(),'process_ref':'private/outputs/suite-process.jsonl'}
        return None

    def evaluate(self):
        if self.task.get('kind')=='frontier_suite':
            if self.suite_sampler is None:return {'all_goals_met':False,'task_success':False,'scope':'Trial not started'}
            return self.suite_sampler.result()
        raise ValueError('Unsupported task kind: '+str(self.task.get('kind')))


class Service(RuntimeService):
    @staticmethod
    def image_save_options(profile):
        return {'quality': profile['quality'], 'subsampling': 2, 'optimize': True} if profile['format']=='JPEG' else {}

    def __init__(self,directory,hidden=False):
        self.hidden=hidden;self.obs=0;self.render_worker=None
        self.perf={'world_step_wall_s':0.,'world_steps':0,'capture_wall_s':0.,'captures':0,'pump_wall_s':0.}
        cfg = json.loads((Path(directory)/'private/inputs/harness.json').read_text())
        self.observation_image = observation_profile(cfg)
        from .run_segments import output_dir
        video_factory = (lambda:Video(output_dir(Path(directory).resolve(),self.world.segment)/
                         (self.task.get('recording_camera','global')+'-realtime.mp4'),1280,800,self.config['video_fps'])) \
                         if cfg.get('record_realtime_video', True) else None
        super().__init__(directory,World,self.capture,video_factory)
        # This owner closes the world when the host that started it is gone, so an
        # unexpected host exit never leaves an orphan holding the world.
        self.parent_pid=os.getppid()

    def capture_in_worker(self,cameras):
        """Queue this capture's images; a response waits for the files, not the world."""
        world=self.world;self.obs+=1;images=[];paths={}
        for name in cameras:
            path=self.directory/'public/observations'/f"obs-{uuid.uuid4().hex[:8]}-{self.obs:05d}-{name}{self.observation_image['extension']}"
            images.append((world.model.camera(name).id,str(path)));paths[name]=str(path)
        data,model=world.data,world.model
        state={'qpos':data.qpos.copy(),'geom_rgba':model.geom_rgba.copy()}
        if model.nmocap:state.update(mocap_pos=data.mocap_pos.copy(),mocap_quat=data.mocap_quat.copy())
        request={'state':state,'images':images,'width':self.observation_image['width'],'height':self.observation_image['height'],
                 'format':self.observation_image['format'],'save_options':Service.image_save_options(self.observation_image)}
        if not self.render_worker.submit(request):self.render_here(request)
        return {'sim_time_s':world.time,'captured_at':time.time(),'images':paths,
                'robot':{a:r.observe() for a,r in world.arms.items()}}

    def render_here(self,request):
        """A capture the worker could not finish, drawn from its own recorded state."""
        from .render_worker import apply_state,render_images
        model=self.world.model;scratch=mujoco.MjData(model);colors=model.geom_rgba.copy()
        mujoco.mjr_setBuffer(mujoco.mjtFramebuffer.mjFB_OFFSCREEN,self.context)
        try:
            apply_state(mujoco,model,scratch,request['state'])
            render_images(mujoco,Image,model,scratch,self.scene,self.options,self.context,request)
        finally:
            model.geom_rgba[:]=colors
            if not getattr(self,'offscreen_context',None):mujoco.mjr_setBuffer(mujoco.mjtFramebuffer.mjFB_WINDOW,self.context)

    def finish_failed_captures(self):
        requests=self.render_worker.failed_captures()
        for request in requests:self.render_here(request)
        if requests:self.render_worker.rendered_locally()

    def capture(self,cameras):
        capture_start=time.perf_counter()
        if getattr(self,'render_worker',None) is not None:
            result=self.capture_in_worker(cameras)
            self.perf['capture_wall_s']+=time.perf_counter()-capture_start;self.perf['captures']+=1
            return result
        self.obs+=1;paths={}
        mujoco.mjr_setBuffer(mujoco.mjtFramebuffer.mjFB_OFFSCREEN,self.context)
        width, height = self.observation_image['width'], self.observation_image['height']
        viewport=mujoco.MjrRect(0,0,width,height)
        for name in cameras:
            cam=mujoco.MjvCamera();cam.type=mujoco.mjtCamera.mjCAMERA_FIXED;cam.fixedcamid=self.world.model.camera(name).id
            mujoco.mjv_updateScene(self.world.model,self.world.data,self.options,None,cam,mujoco.mjtCatBit.mjCAT_ALL,self.scene)
            mujoco.mjr_render(viewport,self.scene,self.context)
            rgb=np.empty((height,width,3),dtype=np.uint8);mujoco.mjr_readPixels(rgb,None,viewport,self.context)
            path=self.directory/'public/observations'/f"obs-{uuid.uuid4().hex[:8]}-{self.obs:05d}-{name}{self.observation_image['extension']}"
            Image.fromarray(rgb[::-1]).save(path, format=self.observation_image['format'], **Service.image_save_options(self.observation_image));paths[name]=str(path)
        if not getattr(self,'offscreen_context',None):
            mujoco.mjr_setBuffer(mujoco.mjtFramebuffer.mjFB_WINDOW,self.context)
        result={'sim_time_s':self.world.time,'captured_at':time.time(),'images':paths,
                'robot':{a:r.observe() for a,r in self.world.arms.items()}}
        self.perf['capture_wall_s']+=time.perf_counter()-capture_start;self.perf['captures']+=1
        return result

    def http_handler(self, observer):
        from http.cookies import SimpleCookie
        from urllib.parse import urlsplit
        service=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                path=urlsplit(self.path).path
                if path=='/viewer/'+observer:
                    self.send_response(302);self.send_header('Set-Cookie','rf_observer='+observer+'; HttpOnly; SameSite=Strict; Path=/')
                    self.send_header('Location','/');self.end_headers();return
                cookie=SimpleCookie();cookie.load(self.headers.get('Cookie',''))
                if not cookie.get('rf_observer') or cookie['rf_observer'].value!=observer:
                    self.send_error(403,'Use the observer link saved for Meta');return
                if path=='/':raw=(ROOT/'assets/pipeline_dashboard.html').read_bytes();kind='text/html; charset=utf-8'
                elif path=='/state':
                    with service.lock:raw=json.dumps(service.snapshot(),ensure_ascii=False).encode()
                    kind='application/json'
                else:self.send_error(404);return
                self.send_response(200);self.send_header('Content-Type',kind);self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(raw)
            def do_POST(self):
                if self.path!='/op':self.send_error(404);return
                try:
                    length=int(self.headers.get('Content-Length','0'))
                    if not 0<length<=65536:raise ValueError('Invalid request size')
                    body=json.loads(self.rfile.read(length));actor=body['actor']
                    if service.tokens.get(actor)!=self.headers.get('X-Token'):self.send_error(403);return
                    if body.get('run_id')!=service.directory.name or body.get('schema_version')!=3:raise ValueError('Wrong run/protocol')
                    job=service.accept(actor,body['op'],body.get('data',{}),body['call_id'],body.get('ack_delivery'))
                    worker=getattr(service,'render_worker',None);finished=job['done'].wait(40) and (worker is None or worker.wait(40))
                    answer=job['result'] if finished else {'call_id':job['id'],'execution_status':'pending','note':'Query/retry original call ID; do not create duplicate motion'}
                    raw=json.dumps(answer,ensure_ascii=False).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(raw)
                except CallIdConflict as error:
                    raw=json.dumps(conflict_error(error.call_id)).encode()
                    self.send_response(409);self.send_header('Content-Type','application/json')
                    self.end_headers();self.wfile.write(raw)
                except (ValueError,KeyError,TypeError) as error:self.send_error(400,str(error))
                except (BrokenPipeError,ConnectionResetError):pass
        return Handler

    def run(self):
        observer=secrets.token_urlsafe(24)
        Handler=self.http_handler(observer)
        try:
            backend=os.environ.get('MUJOCO_GL','').lower()
            if self.hidden and backend in ('osmesa','egl'):
                if backend=='egl':
                    from mujoco.egl import GLContext
                else:
                    from mujoco.osmesa import GLContext
                self.offscreen_context=GLContext(1280,800)
                self.offscreen_context.make_current()
            else:
                if not glfw.init():raise RuntimeError('GLFW init failed')
                glfw.window_hint(glfw.VISIBLE,not self.hidden)
                self.window=glfw.create_window(1280,800,'RoboFrontier — Shared World',None,None)
                if not self.window:raise RuntimeError('GLFW window creation failed')
                glfw.make_context_current(self.window);glfw.swap_interval(1)
            from .render_backend import current_backend
            atomic_json(self.directory/'private/outputs/render-backend.json',current_backend(self.config.get('render_device')))
            self.context=mujoco.MjrContext(self.world.model,mujoco.mjtFontScale.mjFONTSCALE_150)
            self.scene=mujoco.MjvScene(self.world.model,maxgeom=5000);self.options=mujoco.MjvOption();self.options.geomgroup[3]=0
            self.cam=mujoco.MjvCamera();self.cam.type=mujoco.mjtCamera.mjCAMERA_FIXED
            self.cam.fixedcamid=self.world.model.camera(self.task.get('view_camera','global')).id
            self.record_cam=mujoco.MjvCamera();self.record_cam.type=mujoco.mjtCamera.mjCAMERA_FIXED
            self.record_cam.fixedcamid=self.world.model.camera(self.task.get('recording_camera','global')).id
            # Only runs that froze a physics profile render apart; others keep their frozen behaviour.
            lazy=bool(getattr(self.world,'physics_profile_active',False))
            if lazy:
                from .render_worker import RenderWorker
                self.render_worker=RenderWorker(self.world.model)
            self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler);self.server.daemon_threads=True
            threading.Thread(target=self.server.serve_forever,daemon=True).start()
            url=f'http://127.0.0.1:{self.server.server_port}'
            for actor in self.roles:
                p=self.directory/'private/state/connections'/f'{actor}.json'
                connection=json.loads(p.read_text());connection['url']=url;atomic_json(p,connection);p.chmod(0o600)
            atomic_json(self.directory/'private/state/observer.json',{'url':url+'/viewer/'+observer,'read_only':True})
            print(json.dumps({'url':url,'directory':str(self.directory),'ready':True}),flush=True)
            previous=time.monotonic();acc=0.;next_frame=previous;next_state=previous;next_record=previous;next_perf=previous
            perf_file=self.directory/'private/outputs/cpu-performance.jsonl'
            while not self.shutdown and (not hasattr(self,'window') or not glfw.window_should_close(self.window)):
                # The world closes by itself once its host is gone, so a crashed host
                # leaves no orphan holding the world lock (docs/running/run-segments.md).
                if os.getppid()!=self.parent_pid:
                    self.store.event('HOST_LOST','Meta',{'parent_pid':self.parent_pid});break
                now=time.monotonic();acc+=min(now-previous,.1);previous=now
                # Between steps nothing changes unless a request arrived or a motion check runs.
                due=not lazy or acc>=.02 or not self.queue.empty() or self.motion_check is not None or self.ended
                if hasattr(self,'window') and due:glfw.poll_events()
                with self.lock:
                    if self.render_worker is not None:self.finish_failed_captures()
                    if due:
                        tick=time.perf_counter();self.pump();self.perf['pump_wall_s']+=time.perf_counter()-tick
                    while acc>=.02 and not self.ended:
                        tick=time.perf_counter()
                        if not self.step_physics():acc=0.;break
                        self.perf['world_step_wall_s']+=time.perf_counter()-tick
                        self.perf['world_steps']+=1;acc-=.02
                    if now>=next_state:self.periodic();next_state=now+1
                    if now>=next_perf:
                        with perf_file.open('a') as stream:stream.write(json.dumps({'at':time.time(),**self.perf})+'\n')
                        next_perf=now+5
                    if not self.hidden and now>=next_frame:
                        mujoco.mjr_setBuffer(mujoco.mjtFramebuffer.mjFB_WINDOW,self.context)
                        w,h=glfw.get_framebuffer_size(self.window);viewport=mujoco.MjrRect(0,0,w,h)
                        mujoco.mjv_updateScene(self.world.model,self.world.data,self.options,None,self.cam,mujoco.mjtCatBit.mjCAT_ALL,self.scene)
                        mujoco.mjr_render(viewport,self.scene,self.context);glfw.swap_buffers(self.window);next_frame=now+1/30
                    if self.video and now>=next_record:
                        mujoco.mjr_setBuffer(mujoco.mjtFramebuffer.mjFB_OFFSCREEN,self.context);viewport=mujoco.MjrRect(0,0,1280,800)
                        mujoco.mjv_updateScene(self.world.model,self.world.data,self.options,None,self.record_cam,mujoco.mjtCatBit.mjCAT_ALL,self.scene)
                        mujoco.mjr_render(viewport,self.scene,self.context)
                        rgb=np.empty((800,1280,3),dtype=np.uint8);mujoco.mjr_readPixels(rgb,None,viewport,self.context)
                        frame=np.ascontiguousarray(rgb[::-1]);fps=self.config['video_fps']
                        self.video.frame(frame);next_record+=1/fps
                        while next_record<=now:self.video.frame(frame);next_record+=1/fps
                    elif not self.video:next_record=now
                time.sleep(.001)
        finally:
            if hasattr(self,'context'):
                with (self.directory/'private/outputs/cpu-performance.jsonl').open('a') as stream:
                    stream.write(json.dumps({'at':time.time(),**self.perf})+'\n')
            if hasattr(self,'server'):self.server.shutdown()
            if self.render_worker is not None:
                self.render_worker.wait(60);self.finish_failed_captures();self.render_worker.close()
            if hasattr(self,'offscreen_context'):
                if hasattr(self,'context'):self.context.free()
                self.offscreen_context.free()
            if hasattr(self,'window'):glfw.destroy_window(self.window)
            if not hasattr(self,'offscreen_context'):glfw.terminate()
            self.close()


def main():
    parser=argparse.ArgumentParser(description='Shared MuJoCo owner; starting it is an explicit engineering action')
    parser.add_argument('--run-dir',type=Path,required=True)
    parser.add_argument('--hidden',action='store_true')
    args=parser.parse_args();Service(args.run_dir,args.hidden).run()

if __name__=='__main__':main()
