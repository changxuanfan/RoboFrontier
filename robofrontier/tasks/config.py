"""One task definition feeds both the scene and public task instructions."""
import json
import math
from pathlib import Path
import hashlib
from ..io import ROOT

DEFAULT_CASE = 'transport-a04-d1'  # The smallest released case; tests and bare prepare_run use it.
DEFAULT_HARNESS = ROOT / 'configs/harness.json'



def execution_timing(config):
    """One timing contract for validation, READY and the physical executor."""
    return {'base_timeout_sim_s':config['action_timeout_sim_s'],
            'max_timeout_sim_s':config.get('max_action_timeout_sim_s',600.),
            'reference_time_factor':1.5,
            'scope':'base + factor * estimated reference duration; bounded execution budget, not a success prediction'}


def action_limits():
    """The arm and hand limits every action is checked against (physics/franka_limits.py)."""
    from ..physics.franka_limits import describe
    return describe()

# The shared execution code, keyed by the names it had before the package layout, so
# the fingerprint of unchanged code stays the same.
CONTROL_FILES={'robot_control.py':'physics/robot_control.py','sim.py':'physics/kinematics.py',
               'motion_check.py':'physics/motion_check.py','task_config.py':'tasks/config.py','pipeline.py':'runtime/pipeline.py',
               'physics_profile.py':'physics/profile.py'}


def physical_control_fingerprint(source_hashes,config):
    """Compare shared execution, independently of policy model/topology."""
    code={name:source_hashes['robofrontier/'+path] for name,path in CONTROL_FILES.items()}
    value=dict(code=code,action_limits=action_limits(),timing=execution_timing(config))
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def panda_control_profile(config):
    """Declared current adapter subset; not a complete real-hardware driver."""
    from ..physics.robot_control import hand_position_profile
    return {'hand_position_servo':hand_position_profile(),'limits':action_limits(),
            'supported_arm_modes':['cartesian_pose_target','joint_position_target'],
            'supported_hand_modes':['aperture_move','force_setpoint_grasp'],
            'arm_parameters':['target_m','delta_m','quaternion_wxyz','speed_m_s','acceleration_m_s2','angular_speed_rad_s',
                              'angular_acceleration_rad_s2','joint_rad','joint_speed_rad_s','joint_acceleration_rad_s2'],
            'hand_parameters':['state','width_m','speed_m_s','force_n','epsilon_inner_m','epsilon_outer_m'],
            'not_supported':['independent_joint_or_cartesian_velocity_mode','joint_torque_or_arm_wrench_control',
                'agent_configurable_impedance','gripper_homing','agent_tcp_or_load_model_calibration',
                'agent_collision_threshold_configuration','measured_contact_forces_or_external_wrench_feedback'],
            'limits_origin':'The published Franka Panda and Hand limits (physics/franka_limits.py); every action states its own speed, acceleration or force.',
            'hardware_adapter_validated':False,'grasp_force_is_measured':False,
            'simulation_parameters_mutable_by_policy':False,
            'software_tools':'IK, motion screening and synchronized submission are software capabilities, not extra physical actuators.'}


def load_task(path=None):
    """A released task (kind frontier_suite); by default the policy task of DEFAULT_CASE."""
    if path is None:
        from .families import policy_task
        task = policy_task(DEFAULT_CASE)
    else:
        task = json.loads(Path(path).read_text())
    if task.get('kind') != 'frontier_suite' or not task.get('scene_asset'):
        raise ValueError('Only released tasks (kind frontier_suite) are supported')
    from .public import validate
    return validate(task)


def check_position(value):
    if len(value) != 3 or not all(math.isfinite(float(x)) for x in value):
        raise ValueError('Finite xyz required')


def public_task(task):
    from .public import public_task as project
    return project(task)


def startup_protocol(topology):
    """The start protocol a topology uses: standing teams start together, a Controller alone."""
    return 'direct_team_v3' if topology in ('hierarchical', 'peer') else 'direct_controller_v2'


def load_harness(path=None):
    c = json.loads(Path(path or DEFAULT_HARNESS).read_text())
    if c['manager'] != 'Meta' or c['coordinator'] not in ('Controller', 'Coordinator'):
        raise ValueError('Use Meta and Controller; legacy Coordinator is accepted for frozen runs')
    if c['topology'] not in ('hierarchical','peer','centralized','adaptive'):
        raise ValueError('Unknown topology')
    if c.get('engine','codex') not in ('codex','claude','antigravity'):
        raise ValueError('Unknown policy engine')
    from ..runtime.tool_mode import of as tool_mode
    tool_mode(c)  # Absent in every earlier run, which is a full run.
    if c.get('startup_protocol') not in ('direct_controller_v2', 'direct_team_v3'):
        raise ValueError('Unknown startup protocol')
    if c['startup_protocol'] == 'direct_controller_v2' and c['topology'] not in ('adaptive', 'centralized'):
        raise ValueError('Direct startup requires a single Controller')
    if c['startup_protocol'] == 'direct_team_v3' and c['topology'] not in ('hierarchical', 'peer'):
        raise ValueError('Direct team startup requires standing Workers')
    for key in ('poll_interval_s','integrity_check_interval_s','session_observation_ttl_s','manager_lease_s','max_batch_messages','max_batch_bytes','max_message_chars','min_check_interval_s','max_check_interval_s','action_timeout_sim_s','video_fps','max_unacknowledged_wakes'):
        if not math.isfinite(float(c[key])) or c[key] <= 0:
            raise ValueError('Invalid harness limit: ' + key)
    if c['min_check_interval_s'] > c['max_check_interval_s']:
        raise ValueError('Invalid check interval range')
    maximum=float(c.get('max_action_timeout_sim_s',600.))
    if not math.isfinite(maximum) or maximum<c['action_timeout_sim_s']:
        raise ValueError('Maximum action timeout must be finite and at least the base timeout')
    c['max_action_timeout_sim_s']=maximum
    setup_timeout=float(c.get('native_setup_timeout_s',120))
    if not math.isfinite(setup_timeout) or setup_timeout<=0:
        raise ValueError('Invalid native setup timeout')
    if 'native_setup_timeout_s' in c:c['native_setup_timeout_s']=setup_timeout
    # Visual-reconstruction sampling only; scoring keeps its own detection rate.
    if 'motion_hz' in c and (isinstance(c['motion_hz'],bool) or not math.isfinite(float(c['motion_hz'])) or c['motion_hz']<=0):
        raise ValueError('Invalid motion sampling rate')
    # Keys of suite.evaluate.PROCESS_LOG_FORMATS (kept literal: no MuJoCo import here).
    if c.get('process_log','full') not in ('full','events-1s','events-10s','events-60s'):raise ValueError('Unknown process log format')
    screening = c['motion_check']
    for key in ('max_horizon_s','default_sample_dt_s','max_sample_dt_s','clearance_m'):
        if not math.isfinite(float(screening[key])) or screening[key]<=0:
            raise ValueError('Invalid motion check limit: '+key)
    if not .02 <= screening['default_sample_dt_s'] <= screening['max_sample_dt_s'] <= .2:
        raise ValueError('Invalid motion check sample range')
    if screening['max_horizon_s']>15:
        raise ValueError('Motion check computational horizon exceeds 15 s')
    for key in ('default_sample_dt_s','max_horizon_s'):
        if abs(round(screening[key]/.02)*.02-screening[key])>1e-8:
            raise ValueError('Motion check '+key+' must be a multiple of 20 ms')
    return c
