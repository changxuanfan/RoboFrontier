"""One task definition feeds both the scene and public task instructions."""
import json
import math
from pathlib import Path
import hashlib

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASE = 'transport-a04-d1'  # The smallest released case; tests and bare prepare_run use it.
DEFAULT_HARNESS = ROOT / 'configs/harness.json'



ACTION_DEFAULTS = {
    'allowed_angular_speed_rad_s': [.05, 1.5], 'default_angular_speed_rad_s': .6,
    'allowed_gripper_speed_m_s': [.005, .10], 'default_gripper_speed_m_s': .08,
    'allowed_grasp_force_n': [30., 70.],
}


def execution_timing(config):
    """One timing contract for validation, READY and the physical executor."""
    return {'base_timeout_sim_s':config['action_timeout_sim_s'],
            'max_timeout_sim_s':config.get('max_action_timeout_sim_s',600.),
            'reference_time_factor':1.5,
            'scope':'base + factor * estimated reference duration; bounded execution budget, not a success prediction'}


def action_limits(config):
    return {key: config.get(key, value) for key, value in ACTION_DEFAULTS.items()}

def physical_control_fingerprint(source_hashes,config):
    """Compare shared execution, independently of policy model/topology."""
    names=('robot_control.py','sim.py','motion_check.py','task_config.py','pipeline.py')
    code={name:source_hashes['robofrontier/'+name] for name in names}
    value=dict(code=code,gripper_position_servo=config.get('gripper_position_servo','legacy'),action_limits=action_limits(config),timing=execution_timing(config),allowed_tcp_speed_m_s=config['allowed_tcp_speed_m_s'],default_tcp_speed_m_s=config['default_tcp_speed_m_s'])
    # A frozen physics profile changes contacts and settle counting. Only a harness that
    # names one adds it, so every fingerprint without a profile stays as it was.
    if config.get('physics_profile') is not None:
        value['physics_profile']=config['physics_profile'];code['physics_profile.py']=source_hashes.get('robofrontier/physics_profile.py')
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def panda_control_profile(config):
    """Declared current adapter subset; not a complete real-hardware driver."""
    from .robot_control import hand_position_profile
    return {'hand_position_servo':hand_position_profile(config.get('gripper_position_servo','legacy')),
            'supported_arm_modes':['cartesian_pose_target','joint_position_target'],
            'supported_hand_modes':['aperture_move','force_setpoint_grasp'],
            'arm_parameters':['target_m','delta_m','quaternion_wxyz','speed_m_s','angular_speed_rad_s','joint_rad','joint_speed_rad_s'],
            'hand_parameters':['state','width_m','speed_m_s','force_n','epsilon_inner_m','epsilon_outer_m'],
            'not_supported':['independent_joint_or_cartesian_velocity_mode','joint_torque_or_arm_wrench_control',
                'agent_configurable_impedance','gripper_homing','agent_tcp_or_load_model_calibration',
                'agent_collision_threshold_configuration','measured_contact_forces_or_external_wrench_feedback'],
            'limits_origin':'Frozen benchmark software limits within a declared Panda/Hand profile; not the complete hardware operating envelope.',
            'hardware_adapter_validated':False,'grasp_force_is_measured':False,
            'simulation_parameters_mutable_by_policy':False,
            'software_tools':'IK, motion screening and synchronized submission are software capabilities, not extra physical actuators.'}


def load_task(path=None):
    """A released task (kind frontier_suite); by default the policy task of DEFAULT_CASE."""
    if path is None:
        from .task_families import policy_task
        task = policy_task(DEFAULT_CASE)
    else:
        task = json.loads(Path(path).read_text())
    if task.get('kind') != 'frontier_suite' or not task.get('scene_asset'):
        raise ValueError('Only released tasks (kind frontier_suite) are supported')
    from .suite.tasks import validate
    return validate(task)


def check_position(value):
    if len(value) != 3 or not all(math.isfinite(float(x)) for x in value):
        raise ValueError('Finite xyz required')


def public_task(task):
    from .suite.tasks import public_task as project
    return project(task)


def load_harness(path=None):
    c = json.loads(Path(path or DEFAULT_HARNESS).read_text())
    if c.get('gripper_position_servo','legacy') not in ('legacy','pd1000-v1'):raise ValueError('Unknown hand position-servo profile')
    if c['manager'] != 'Meta' or c['coordinator'] not in ('Controller', 'Coordinator'):
        raise ValueError('Use Meta and Controller; legacy Coordinator is accepted for frozen runs')
    if c['topology'] not in ('hierarchical','peer','centralized','adaptive'):
        raise ValueError('Unknown topology')
    if c.get('engine','codex') not in ('codex','claude'):
        raise ValueError('Unknown policy engine')
    if c.get('startup_protocol', 'ready_barrier_v1') not in ('ready_barrier_v1', 'direct_controller_v2', 'direct_team_v3'):
        raise ValueError('Unknown startup protocol')
    if c.get('startup_protocol') == 'direct_controller_v2' and c['topology'] not in ('adaptive', 'centralized'):
        raise ValueError('Direct startup requires a single Controller')
    if c.get('startup_protocol') == 'direct_team_v3' and c['topology'] not in ('hierarchical', 'peer'):
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
    # Keys of physics_profile.PROFILES (kept literal for the same reason).
    if c.get('physics_profile') not in (None,'realtime-v1','realtime-v2'):raise ValueError('Unknown physics profile')
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
    c.update(action_limits(c))
    for kind in ('angular_speed_rad_s','gripper_speed_m_s'):
        bounds=c['allowed_'+kind];default=c['default_'+kind]
        if len(bounds)!=2 or not all(math.isfinite(float(v)) and v>0 for v in bounds) or not bounds[0]<=default<=bounds[1]:
            raise ValueError('Invalid '+kind+' limits')
    force=c['allowed_grasp_force_n']
    if len(force)!=2 or not all(math.isfinite(float(v)) for v in force) or not 30<=force[0]<=force[1]<=70:
        raise ValueError('Grasp force range must stay within the configured Franka Hand 30..70 N profile')
    if c['allowed_gripper_speed_m_s'][1]>.10:
        raise ValueError('Total aperture reference speed exceeds the Franka Hand profile')
    return c
