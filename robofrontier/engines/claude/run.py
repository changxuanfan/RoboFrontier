"""Claude entry point for the shared native CLI run supervisor."""
from robofrontier.engines.common.run import *
from robofrontier.engines.common.run import (_ledger, _positive, _concurrent_roles, _check_shared_budget,
    _evaluation_present, _run_protocol, _time_rule, run_task as _run_task)


def run_task(*args, **kwargs):
    kwargs.setdefault('_verifier', verify_inputs)
    kwargs.setdefault('_supervisor', CentralizedSupervisor)
    return _run_task(*args, **kwargs)
