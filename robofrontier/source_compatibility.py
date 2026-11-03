"""Explicit compatibility of historical Oracle checks with shared integration.

The returned hash identifies the historical source, never the current file.
Current bytes and the unaffected AST must both match the reviewed receipt.
This does not certify Relay's changed scoring or produce new physical evidence.
"""
import ast
import hashlib
import json
from pathlib import Path
import textwrap

RECEIPT = 'benchmark/source-compatibility.json'


def _revert(tree, current, original, what, count=1):
    """Put back the original statements where the reviewed `current` sequence is.

    The sequence may sit in any statement list of `tree` and must occur exactly
    `count` times. Bytes written before the reviewed change do not contain it, which
    is allowed; any other variant fails the digest comparison."""
    expected = [ast.dump(node) for node in ast.parse(textwrap.dedent(current)).body]
    found = []
    for node in ast.walk(tree):
        for field in ('body', 'orelse'):
            body = getattr(node, field, None)
            if not isinstance(body, list): continue
            for i in range(len(body)-len(expected)+1):
                if [ast.dump(n) for n in body[i:i+len(expected)]] == expected: found.append((body, i))
    if found and len(found) != count: raise ValueError(what+' differs from reviewed source')
    for body, i in reversed(found):
        body[i:i+len(expected)] = ast.parse(textwrap.dedent(original)).body if original else []


# Reviewed run-storage and segment changes to World (docs/running/run-segments.md,
# docs/running/evidence-storage.md). Each acts only for a new run that freezes the setting
# or continues in a new segment; a historical run reaches the original statements.
WORLD_RUN_STORAGE = (
    ('portable scene copy', """
def portable_xml(xml,folder):
    '''The loaded model's XML with absolute asset paths made relative to `folder`, so a
    saved copy still loads after the run moves to another machine or directory.'''
    root=ET.fromstring(xml)
    compiler=root.find('compiler')
    for element,key in [(compiler,'meshdir'),(compiler,'texturedir')]+[(t,'file') for t in root.iter('texture')]+[(m,'file') for m in root.iter('mesh')]:
        value=element.get(key) if element is not None else None
        if value and os.path.isabs(value):element.set(key,os.path.relpath(value,folder))
    return ET.tostring(root,encoding='unicode')
""", None),
    ('segment default', "segment=0", None),
    ('segment restore default', "segment_restore=None", None),
    ('segment restore', """
from .run_segments import restore_world
segment_restore=restore_world(self.directory,self.task,self.model,self.data)
if segment_restore:self.segment=segment_restore['segment'];mujoco.mj_forward(self.model,self.data)
self.arms={a:Arm(self.model,self.data,a,initialized=True) for a in self.task['arms']}
if segment_restore:
    for arm in self.arms.values():
        arm.qref=self.data.qpos[arm.qids].copy();self.data.ctrl[arm.act]=arm.qref
        control=arm.width_to_grip(arm.observe()['gripper_width_m'])
        arm.gripper=control;arm.grip_goal=control;self.data.ctrl[arm.grip]=control
""", "self.arms={a:Arm(self.model,self.data,a,initialized=True) for a in self.task['arms']}"),
    ('restored grasp holds', """
if self.task.get('scene_asset') and segment_restore:
    holds=segment_restore.get('held_grasps',{})
    self.restored_holds=[]
    for name,evidence in holds.items():
        if name not in self.arms:raise ValueError('Recorded grasp names an absent arm')
        arm=self.arms[name];width=arm.observe()['gripper_width_m']
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
""", None),
    ('saved scene', "(output/'scene.xml').write_text(portable_xml(self.xml,output))", "(output/'scene.xml').write_text(self.xml)"),
    # Display only: letter labels are visual world geometry; a run that freezes the
    # setting shows them where its videos do (robofrontier/factory/labels.py).
    ('robot label display', """
if self.task.get('scene_asset') and frozen_cfg.get('robot_labels')=='beside-robot-v1':
    from .factory.labels import place_robot_labels
    place_robot_labels(self.model,self.data,self.task)
""", None),
    ('held grasp snapshot', """
def held_grasps(self):
    '''Arms holding a confirmed grasp, as a continued segment would restore them.'''
    holds={}
    for name,arm in self.arms.items():
        if arm.job is None and arm.gripper_command_mode=='grasp' and arm.grasp_phase=='hold' and arm.grasp_confirmed:
            holds[name]=dict(sim_s=self.time,observed_width_m=arm.observe()['gripper_width_m'],force_n=arm.grasp_force,
                             target_width_m=arm.grasp_width,epsilon_inner_m=arm.grasp_epsilon[0],epsilon_outer_m=arm.grasp_epsilon[1])
    return holds
""", None),
    ('engineering fault entry', """
def inject_fault(self,actor,call_id,op):
    '''Apply this run's engineering fault, if any, to an independent action just started.'''
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
""", None),
    ('process log format', """
harness=self.directory/'private/inputs/harness.json'
frozen=json.loads(harness.read_text()) if harness.exists() else {}
self.suite_sampler=Monitor(self,secret=secret,log_path=self.directory/'private/outputs/suite-process.jsonl',
                           log_format=frozen.get('process_log','full'),append=self.segment>0)
""", "self.suite_sampler=Monitor(self,secret=secret,log_path=self.directory/'private/outputs/suite-process.jsonl')"),
    ('motion rate and segment folder', """
hz=frozen.get('motion_hz',60)
from .run_segments import output_dir
folder=output_dir(self.directory,self.segment);folder.mkdir(parents=True,exist_ok=True)
self.motion_recorder=MotionWriter(folder/'motion',source,self.model,self.data,hz=hz,
                                  cache=ROOT/'runs/state-assets')
""", "self.motion_recorder=MotionWriter(self.directory/'private/outputs/motion',source,self.model,self.data,cache=ROOT/'runs/state-assets')"),
)
# Reviewed additions to PandaArm: local recovery of an uncertain stop (recover_action)
# and the engineering fault hold. Both act only after a stop was reported uncertain or
# when a fault is frozen; a qualified historical trial reaches the original statements.
ARM_RECOVERY = (
    ('uncertain-stop sampling', """
if self.uncertainty_reported:
    if self.stopping:
        if self.recovery_last_sample is not None and now<=self.recovery_last_sample+1e-9:return None
        self.recovery_last_sample=now
        fingers_settled=self.finger_stationary(now) if self.job_op=='gripper' else False
        reached=(np.max(np.abs(self.velocity))<1e-5 and
                 (fingers_settled if self.job_op=='gripper' else np.max(np.abs(self.data.qvel[self.dofs]))<.03))
        if self.fault_hold_until is not None and now<self.fault_hold_until:reached=False
        self.stable=self.stable+1 if reached else 0
    return None
""", "if self.uncertainty_reported:return None", 1),
    ('fault hold check', "if self.fault_hold_until is not None and now<self.fault_hold_until:reached=False", None, 1),
    ('fault hold start', "if self.fault_hold_s is not None:self.fault_hold_until=now+3.+self.fault_hold_s", None, 1),
    ('fault hold reset', "self.fault_hold_s=None;self.fault_hold_until=None", None, 2),
    ('recovery sample default', "self.recovery_last_sample=None", None, 1),
    ('recovery sample start', "self.stable=0;self.recovery_last_sample=now", None, 1),
    ('local recovery entry', """
def recover_stopped(self,call_id):
    if self.job!=call_id or not self.stopping or not self.uncertainty_reported:
        raise ValueError('Original locally uncertain stopping action is not active')
    if self.stable<3:return None
    result=self.end('failed','Action timed out or was stopped; stop later confirmed during local recovery')
    self.uncertainty_reported=False
    return result
""", None, 1),
)
# Reviewed Mosaic Level 2/3 centre tolerance: read from the task with the original
# 5 mm default, so a task that does not declare mosaic-center-6mm-v1 is unchanged.
MOSAIC_CENTER_TOLERANCE = ("""
tolerance=task.get('completion',{}).get('xy_center_tolerance_m_inclusive',.005)
if isinstance(tolerance,bool) or not isinstance(tolerance,(int,float)) or not math.isfinite(tolerance) or not 0 < tolerance <= .05:
    raise ValueError('Invalid Mosaic center tolerance')
out&=~(np.linalg.norm(delta[:,:,:2],axis=2)>tolerance)
""", "out&=~(np.linalg.norm(delta[:,:,:2],axis=2)>.005)")
# Reviewed checks of two new frozen harness settings in load_harness.
HARNESS_RUN_STORAGE = """
if 'motion_hz' in c and (isinstance(c['motion_hz'],bool) or not math.isfinite(float(c['motion_hz'])) or c['motion_hz']<=0):
    raise ValueError('Invalid motion sampling rate')
if c.get('process_log','full') not in ('full','events-1s'):raise ValueError('Unknown process log format')
"""


def normalized_digest(source, rule):
    tree = ast.parse(source)
    if rule == 'exclude_relay_class':
        found = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'Relay']
        if len(found) != 1:
            raise ValueError('Expected one Relay class')
        tree.body.remove(found[0])
        _revert(tree, *MOSAIC_CENTER_TOLERANCE, 'Mosaic centre tolerance')
    elif rule in ('exclude_prepared_policy_guard', 'exclude_policy_service', 'exclude_policy_service_and_observation_metadata'):
        world = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'World')
        if rule == 'exclude_policy_service_and_observation_metadata':
            for what, current, original in WORLD_RUN_STORAGE: _revert(tree, current, original, what)
        method = next(n for n in world.body if isinstance(n, ast.FunctionDef) and n.name == 'start_trial')
        expected = ast.parse("if self.task.get('execution_readiness')=='prepared_policy_trial':\n from .task_families import validate_frozen_policy\n validate_frozen_policy(self.task,self.directory)").body[0]
        method.body = [n for n in method.body if ast.dump(n) != ast.dump(expected)]
        if rule in ('exclude_policy_service', 'exclude_policy_service_and_observation_metadata'):
            # CLI hosting changes only the GUI/service wrapper. World stepping,
            # robot control, task sampling and recording remain in the digest.
            service=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='Service')
            tree.body.remove(service)
        if rule == 'exclude_policy_service_and_observation_metadata':
            # Admit only these reviewed non-physical changes. Every remaining
            # AST node must still match the original receipt, including world
            # stepping, controls, task sampling and motion recording.
            imports = [ast.parse(text).body[0] for text in (
                'import os', 'from .observation_image import observation_profile',
                'from .tool_errors import CallIdConflict, conflict_error')]
            for expected_import in imports:
                matches = [node for node in tree.body if ast.dump(node) == ast.dump(expected_import)]
                if len(matches) != 1:
                    raise ValueError('Observation compatibility import differs from reviewed source')
                tree.body.remove(matches[0])
            init = next(node for node in world.body if isinstance(node, ast.FunctionDef) and node.name == '__init__')
            observed = ast.parse("frozen_cfg=json.loads(hand_cfg.read_text()) if hand_cfg.exists() else {}\n"
                                 "self.observation_image=observation_profile(frozen_cfg)\n"
                                 "profile=frozen_cfg.get('gripper_position_servo','legacy')").body
            indices = [i for i in range(len(init.body)-2)
                       if [ast.dump(n) for n in init.body[i:i+3]] == [ast.dump(n) for n in observed]]
            if len(indices) != 1:
                raise ValueError('Observation initialization differs from reviewed source')
            original = ast.parse("profile=json.loads(hand_cfg.read_text()).get('gripper_position_servo','legacy') if hand_cfg.exists() else 'legacy'").body
            init.body[indices[0]:indices[0]+3] = original
            # Reviewed addition: the owner's entry for single-arm recovery. It only reads
            # and ends an action whose timed-out stop is already uncertain; stepping,
            # control and every other World method are unchanged.
            recovery = ast.parse("def recover_action(self,actor,call_id):\n return self.arms[actor].recover_stopped(call_id)").body[0]
            found = [node for node in world.body if isinstance(node, ast.FunctionDef) and node.name == 'recover_action']
            if found:
                if len(found) != 1 or ast.dump(found[0]) != ast.dump(recovery):
                    raise ValueError('Single-arm recovery entry differs from reviewed source')
                world.body.remove(found[0])
            facts = next(node for node in world.body if isinstance(node, ast.FunctionDef) and node.name == 'robot_facts')
            expected_size = ast.parse("[self.observation_image['width'],self.observation_image['height']]", mode='eval').body
            sizes = [node for node in ast.walk(facts) if isinstance(node, ast.List) and ast.dump(node) == ast.dump(expected_size)]
            if len(sizes) != 1:
                raise ValueError('Observation camera metadata differs from reviewed source')
            sizes[0].elts = [ast.Constant(1280), ast.Constant(800)]
    elif rule == 'exclude_policy_harness_selection':
        method=next(node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name=='load_harness')
        _revert(method, HARNESS_RUN_STORAGE, None, 'Run storage harness checks')
        reviewed=ast.parse("if c['manager'] != 'Meta' or c['coordinator'] not in ('Controller', 'Coordinator'):\n"
                           " raise ValueError('Use Meta and Controller; legacy Coordinator is accepted for frozen runs')\n"
                           "if c.get('engine','codex') not in ('codex','claude'):\n"
                           " raise ValueError('Unknown policy engine')\n"
                           "if c.get('startup_protocol', 'ready_barrier_v1') not in ('ready_barrier_v1', 'direct_controller_v2', 'direct_team_v3'):\n"
                           " raise ValueError('Unknown startup protocol')\n"
                           "if c.get('startup_protocol') == 'direct_controller_v2' and c['topology'] not in ('adaptive', 'centralized'):\n"
                           " raise ValueError('Direct startup requires a single Controller')\n"
                           "if c.get('startup_protocol') == 'direct_team_v3' and c['topology'] not in ('hierarchical', 'peer'):\n"
                           " raise ValueError('Direct team startup requires standing Workers')").body
        original=ast.parse("if c['manager'] != 'Meta' or c['coordinator'] != 'Coordinator':\n"
                           " raise ValueError('Use explicit Meta / Coordinator role boundary')").body[0]
        for index,expected in enumerate(reviewed):
            matches=[i for i,node in enumerate(method.body) if ast.dump(node)==ast.dump(expected)]
            if len(matches)!=1:
                raise ValueError('Harness selection differs from reviewed configuration checks')
            if index==0:method.body[matches[0]]=original
            else:method.body.pop(matches[0])
    elif rule == 'exclude_local_recovery_and_engineering_fault':
        for what, current, original, count in ARM_RECOVERY: _revert(tree, current, original, what, count)
    elif rule == 'mosaic_public_projection':
        # This authenticates only the old review artifact's public projection.
        # Validator improvements and current scoring are explicitly not equated.
        names={'_public_boundary','project_public','_check_target','_target_image'}
        functions=[node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name in names]
        guards=[node for node in tree.body if isinstance(node,ast.Assign) and
                any(isinstance(target,ast.Name) and target.id=='FORBIDDEN_PUBLIC_KEYS' for target in node.targets)]
        if len(functions)!=4 or len(guards)!=1:
            raise ValueError('Mosaic public projection structure differs')
        tree.body=[node for node in tree.body if node in functions or node in guards]
    elif rule == 'mosaic_preview_display_text':
        # The receipt also pins the complete reviewed current bytes. Only this
        # display generator admits its caption translation; no controller does.
        class DisplayText(ast.NodeTransformer):
            def visit_Constant(self,node):
                if isinstance(node.value,str):node.value='TEXT'
                return node
        tree=DisplayText().visit(tree)
    else:
        raise ValueError('Unknown compatibility rule')
    return hashlib.sha256(ast.dump(tree).encode()).hexdigest()


def historical_digest(root, relative, family):
    root = Path(root)
    data = (root/relative).read_bytes()
    actual = hashlib.sha256(data).hexdigest()
    receipt = json.loads((root/RECEIPT).read_text())
    for item in receipt['files']:
        if item['path'] != relative or family not in item['families']:
            continue
        if actual == item['historical_sha256']:
            return actual
        if actual != item['integrated_sha256'] or normalized_digest(data, item['rule']) != item['unaffected_ast_sha256']:
            raise ValueError('Unreviewed shared source change: '+relative)
        return item['historical_sha256']
    return actual
