"""One task definition feeds both the scene and public task instructions."""

import hashlib
import json
import math
from pathlib import Path

from ..io import ROOT
from ..sim.timing import execution_timing

DEFAULT_CASE = 'transport-small-l1'  # The smallest released case; tests and bare prepare_run use it.
# The policy runtime's settings; a batch sets the harness, system, model and effort over them.
DEFAULT_RUN_SETTINGS = ROOT / 'roboteam/runtime/run/defaults.json'
# The lead role: the one agent of a single-agent or adaptive run, and the lead of a hierarchical team.
CONTROLLER = 'Controller'
# The one trial clock: only time the world runs unpaused counts toward the limit.
ACTIVE_CLOCK = 'active_time_v1'


def action_limits():
    """The arm and hand limits every action is checked against (sim/franka_limits.py)."""
    from roboteam.sim.franka_limits import describe

    return describe()


# The shared execution code, keyed by the names it had before the package layout, so
# the fingerprint of unchanged code stays the same.
CONTROL_FILES = {
    'robot_control.py': 'sim/robot_control.py',
    'sim.py': 'sim/kinematics.py',
    'motion_check.py': 'sim/motion_check.py',
    'task_config.py': 'tasks/config.py',
    'pipeline.py': 'runtime/world/pipeline.py',
    'physics_profile.py': 'sim/profile.py',
}


def physical_control_fingerprint(source_hashes, config):
    """Compare shared execution, independently of policy model/system."""
    code = {name: source_hashes['roboteam/' + path] for name, path in CONTROL_FILES.items()}
    value = dict(code=code, action_limits=action_limits(), timing=execution_timing(config))
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def panda_control_profile(config):
    """Declared current adapter subset; not a complete real-hardware driver."""
    from roboteam.sim.robot_control import hand_position_profile

    return {
        'hand_position_servo': hand_position_profile(),
        'limits': action_limits(),
        'supported_arm_modes': ['cartesian_pose_target', 'joint_position_target'],
        'supported_hand_modes': ['aperture_move', 'force_setpoint_grasp'],
        'arm_parameters': [
            'target_m',
            'delta_m',
            'quaternion_wxyz',
            'speed_m_s',
            'acceleration_m_s2',
            'angular_speed_rad_s',
            'angular_acceleration_rad_s2',
            'joint_rad',
            'joint_speed_rad_s',
            'joint_acceleration_rad_s2',
        ],
        'hand_parameters': ['state', 'width_m', 'speed_m_s', 'force_n', 'epsilon_inner_m', 'epsilon_outer_m'],
        'not_supported': [
            'independent_joint_or_cartesian_velocity_mode',
            'joint_torque_or_arm_wrench_control',
            'agent_configurable_impedance',
            'gripper_homing',
            'agent_tcp_or_load_model_calibration',
            'agent_collision_threshold_configuration',
            'measured_contact_forces_or_external_wrench_feedback',
        ],
        'limits_origin': 'The published Franka Panda and Hand limits (sim/franka_limits.py); every action states its own speed, acceleration or force.',
        'hardware_adapter_validated': False,
        'grasp_force_is_measured': False,
        'simulation_parameters_mutable_by_policy': False,
        'software_tools': 'IK, motion screening and synchronized submission are software capabilities, not extra physical actuators.',
    }


def load_task(path=None):
    """A released task; by default the policy task of DEFAULT_CASE."""
    if path is None:
        from .task_types import policy_task

        task = policy_task(DEFAULT_CASE)
    else:
        task = json.loads(Path(path).read_text())
    if not task.get('scene_asset'):
        raise ValueError('Only released tasks are supported')
    from .public import validate

    return validate(task)


def check_position(value):
    if len(value) != 3 or not all(math.isfinite(float(x)) for x in value):
        raise ValueError('Finite xyz required')


def public_task(task):
    from .public import public_task as project

    return project(task)


def startup_protocol(system):
    """The start protocol a system uses: standing teams start together, a Controller alone."""
    return 'direct_team' if system in ('hierarchical', 'decentralized') else 'direct_controller'


def load_run_settings(path=None):
    c = json.loads(Path(path or DEFAULT_RUN_SETTINGS).read_text())
    from roboteam.sim.render.image import DEFAULT_PROFILE

    c.setdefault('observation_image_profile', DEFAULT_PROFILE)
    if c['manager'] != 'Meta':
        raise ValueError('The manager role is Meta')
    if c['system'] not in ('hierarchical', 'decentralized', 'single-agent', 'adaptive'):
        raise ValueError('Unknown system')
    if c.get('harness', 'codex') not in ('codex', 'claude'):
        raise ValueError('Unknown policy harness')
    from roboteam.tasks.tools_mode import of as tools_mode

    tools_mode(c)
    from roboteam.tasks.observation_mode import check_combination

    check_combination(c)
    if c.get('startup_protocol') not in ('direct_controller', 'direct_team'):
        raise ValueError('Unknown startup protocol')
    if c['startup_protocol'] == 'direct_controller' and c['system'] not in ('adaptive', 'single-agent'):
        raise ValueError('Direct startup requires a single Controller')
    if c['startup_protocol'] == 'direct_team' and c['system'] not in ('hierarchical', 'decentralized'):
        raise ValueError('Direct team startup requires standing Workers')
    for key in (
        'poll_interval_s',
        'integrity_check_interval_s',
        'session_observation_ttl_s',
        'manager_lease_s',
        'max_batch_messages',
        'max_batch_bytes',
        'max_message_chars',
        'min_check_interval_s',
        'max_check_interval_s',
        'action_timeout_sim_s',
        'video_fps',
        'max_unacknowledged_wakes',
    ):
        if not math.isfinite(float(c[key])) or c[key] <= 0:
            raise ValueError('Invalid run setting: ' + key)
    if c['min_check_interval_s'] > c['max_check_interval_s']:
        raise ValueError('Invalid check interval range')
    maximum = float(c.get('max_action_timeout_sim_s', 600.0))
    if not math.isfinite(maximum) or maximum < c['action_timeout_sim_s']:
        raise ValueError('Maximum action timeout must be finite and at least the base timeout')
    c['max_action_timeout_sim_s'] = maximum
    setup_timeout = float(c.get('native_setup_timeout_s', 120))
    if not math.isfinite(setup_timeout) or setup_timeout <= 0:
        raise ValueError('Invalid native setup timeout')
    if 'native_setup_timeout_s' in c:
        c['native_setup_timeout_s'] = setup_timeout
    # Visual-reconstruction sampling only; scoring keeps its own detection rate.
    if 'motion_hz' in c and (
        isinstance(c['motion_hz'], bool) or not math.isfinite(float(c['motion_hz'])) or c['motion_hz'] <= 0
    ):
        raise ValueError('Invalid motion sampling rate')
    # Keys of suite.evaluate.PROCESS_LOG_FORMATS (kept literal: no MuJoCo import here).
    if c.get('process_log', 'full') not in ('full', 'events-1s', 'events-10s', 'events-60s'):
        raise ValueError('Unknown process log format')
    screening = c['motion_check']
    for key in ('max_horizon_s', 'default_sample_dt_s', 'max_sample_dt_s', 'clearance_m'):
        if not math.isfinite(float(screening[key])) or screening[key] <= 0:
            raise ValueError('Invalid motion check limit: ' + key)
    if not 0.02 <= screening['default_sample_dt_s'] <= screening['max_sample_dt_s'] <= 0.2:
        raise ValueError('Invalid motion check sample range')
    if screening['max_horizon_s'] > 15:
        raise ValueError('Motion check computational horizon exceeds 15 s')
    for key in ('default_sample_dt_s', 'max_horizon_s'):
        if abs(round(screening[key] / 0.02) * 0.02 - screening[key]) > 1e-8:
            raise ValueError('Motion check ' + key + ' must be a multiple of 20 ms')
    return c
