"""Public measurements for an action whose live controller is still stopping."""


def stop_diagnostics(world, robot, call_id, action=None):
    """Describe current stop criteria without changing the physical controller."""
    if hasattr(world, 'stop_diagnostics'):
        return world.stop_diagnostics(robot, call_id)
    arm = getattr(world, 'arms', {}).get(robot)
    if arm is None or arm.job != call_id or not arm.stopping:
        raise ValueError('No live stopping action for this robot')
    now = float(world.time)
    reference = [float(v) for v in arm.velocity]
    actual = [float(v) for v in arm.data.qvel[arm.dofs]]
    reference_max = max(abs(v) for v in reference)
    actual_max = max(abs(v) for v in actual)
    unmet = []
    if reference_max >= 1e-5: unmet.append('reference_joint_speed')
    fingers = None
    if arm.job_op == 'gripper':
        samples = list(arm.grasp_settling)
        current = [float(arm.data.joint(arm.name+'_'+s).qpos[0]) for s in ('finger_joint1','finger_joint2')]
        if not samples or now > samples[-1][0]+1e-9:samples.append((now,current))
        while len(samples)>1 and now-samples[1][0]>=.18:samples.pop(0)
        if samples:
            elapsed = now-float(samples[0][0])
            spans = [max(float(row[1][i]) for row in samples)-min(float(row[1][i]) for row in samples)
                     for i in (0,1)]
            drift = [abs(current[i]-float(samples[0][1][i]))/max(elapsed,1e-9) for i in (0,1)]
            fingers = elapsed >= .18-1e-9 and max(spans) < .00015 and max(drift) < .001
        else:
            elapsed,spans,drift = 0.,[],[]
            fingers = False
        if not fingers: unmet.append('finger_position_stability')
    elif actual_max >= .03:
        unmet.append('actual_joint_speed')
    if arm.stable < 3: unmet.append('consecutive_stable_samples')
    result = {'robot':robot,'action_id':call_id,'stop_reason':arm.stop_reason,
              'stopping_for_sim_s':max(0.,now-arm.stop_started_at),
              'reference_joint_velocity_rad_s':reference,'actual_joint_velocity_rad_s':actual,
              'max_reference_joint_speed_rad_s':reference_max,'reference_speed_limit_rad_s':1e-5,
              'max_actual_joint_speed_rad_s':actual_max,'actual_speed_limit_rad_s':.03,
              'finger_position_stable':fingers,'stable_samples':arm.stable,
              'required_stable_samples':3,'unmet_conditions':unmet}
    if fingers is not None:
        result['finger_stability']={'window_sim_s':elapsed,'position_spans_m':spans,'drift_m_s':drift,
                                    'finger_velocities_m_s':[float(arm.data.joint(arm.name+'_'+s).qvel[0])
                                                             for s in ('finger_joint1','finger_joint2')],
                                    'min_window_sim_s':.18,'max_span_m':.00015,'max_drift_m_s':.001}
    parameters=(action or {}).get('parameters',{})
    target=parameters.get('joint_rad')
    if isinstance(target,list) and len(target)==len(arm.qids):
        error=[float(arm.data.qpos[q])-float(goal) for q,goal in zip(arm.qids,target)]
        result['joint_target_error_rad']=error
        result['max_joint_target_error_rad']=max(abs(v) for v in error)
        result['joint_target_tolerance_rad']=.004
    return result
