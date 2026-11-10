"""The motion and grasp limits of a real Franka Panda and Franka Hand.

Every arm and hand action states its speed, acceleration or force; nothing has a
default. A value must be above MINIMUM and at most the limit below.

Sources:
- Panda datasheet (Franka Emika, 2018-05): joint speed 150 deg/s (joints 1-4) and
  180 deg/s (joints 5-7), Cartesian speed up to 2 m/s, hand continuous force 70 N and
  maximum 140 N, 80 mm stroke, 50 mm/s per finger.
- libfranka 0.9.2, include/franka/rate_limiting.h: the joint speed limits
  2.175 / 2.61 rad/s (the datasheet values, rounded), joint accelerations, and the
  Cartesian acceleration and rotation limits. The file states each limit as a base
  value minus a safety margin; these are the base values.

The hand force has libfranka's meaning: the force each finger presses on the object.
Above the continuous 70 N a real hand may hold only briefly; the simulation does not
model the motor heating that limits it.
"""

JOINT_SPEED_RAD_S = (2.175, 2.175, 2.175, 2.175, 2.61, 2.61, 2.61)
JOINT_ACCEL_RAD_S2 = (15., 7.5, 10., 12.5, 15., 20., 20.)
TCP_SPEED_M_S = 2.
TCP_ACCEL_M_S2 = 13.
TCP_ANGULAR_SPEED_RAD_S = 2.5
TCP_ANGULAR_ACCEL_RAD_S2 = 25.
GRIPPER_SPEED_M_S = .1        # total aperture: 50 mm/s per finger
GRASP_FORCE_N = 140.          # per finger
GRASP_FORCE_CONTINUOUS_N = 70.
# Real hardware has no published lower bound. This one only keeps the slowest allowed
# action finishing within the longest action time limit (600 s of simulation).
MINIMUM = .001

LIMITS = {
    'joint_speed_rad_s': JOINT_SPEED_RAD_S,
    'joint_acceleration_rad_s2': JOINT_ACCEL_RAD_S2,
    'speed_m_s': TCP_SPEED_M_S,
    'acceleration_m_s2': TCP_ACCEL_M_S2,
    'angular_speed_rad_s': TCP_ANGULAR_SPEED_RAD_S,
    'angular_acceleration_rad_s2': TCP_ANGULAR_ACCEL_RAD_S2,
    'gripper_speed_m_s': GRIPPER_SPEED_M_S,
    'force_n': GRASP_FORCE_N,
}


def describe():
    """The limits as the tool description and run records state them."""
    return {
        'joint_speed_rad_s': list(JOINT_SPEED_RAD_S),
        'joint_acceleration_rad_s2': list(JOINT_ACCEL_RAD_S2),
        'tcp_speed_m_s': TCP_SPEED_M_S, 'tcp_acceleration_m_s2': TCP_ACCEL_M_S2,
        'tcp_angular_speed_rad_s': TCP_ANGULAR_SPEED_RAD_S, 'tcp_angular_acceleration_rad_s2': TCP_ANGULAR_ACCEL_RAD_S2,
        'gripper_speed_m_s': GRIPPER_SPEED_M_S, 'grasp_force_n': GRASP_FORCE_N,
        'grasp_force_continuous_n': GRASP_FORCE_CONTINUOUS_N, 'minimum': MINIMUM,
        'source': 'Franka Panda datasheet (2018-05) and libfranka 0.9.2 rate_limiting.h',
    }
