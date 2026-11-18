"""An offline session adapter and one dispatch round, for tests of the scheduler."""

from roboteam.runtime.tools.scheduling import Scheduler


class FakeSessionAdapter:
    """Offline contract adapter. No Codex connections, inference or robot actions."""

    def __init__(self, observations):
        self.observations = observations
        self.sent = []

    def observe(self, actor):
        return self.observations[actor]

    def send(self, command):
        if self.observations[command['actor']]['status'] != 'idle':
            raise ValueError('Fake receiver became active')
        self.sent.append(command)
        return {'threadId': command['thread_id']}


def dispatch_once(store, adapter, owner, now):
    """One round as live Meta runs it: observe, plan, claim, send, record."""
    for actor, a in store.agents().items():
        if a['kind'] != 'manager' and a['thread_id']:
            observed = adapter.observe(actor)
            store.observe_session(actor, observed['status'], observed['turn_id'], now, 'codex.wait_threads')
    scheduler = Scheduler(store)
    results = []
    for command in scheduler.plan(owner, now):
        o = adapter.observe(command['actor'])
        store.observe_session(command['actor'], o['status'], o['turn_id'], now, 'codex.wait_threads')
        claimed = scheduler.claim(command['wake_id'], owner, now)
        if claimed:
            try:
                result = adapter.send(claimed)
            except Exception as exc:
                store.record_dispatch(command['wake_id'], 'uncertain', {'error': str(exc)})
            else:
                store.record_dispatch(command['wake_id'], 'sent', result)
            results.append(command['wake_id'])
    return results
