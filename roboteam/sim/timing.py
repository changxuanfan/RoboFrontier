"""The timing contract of one physical action, shared by validation, READY and the executor."""


def execution_timing(config):
    """One timing contract for validation, READY and the physical executor."""
    return {
        'base_timeout_sim_s': config['action_timeout_sim_s'],
        'max_timeout_sim_s': config.get('max_action_timeout_sim_s', 600.0),
        'reference_time_factor': 1.5,
        'scope': 'base + factor * estimated reference duration; bounded execution budget, not a success prediction',
    }
