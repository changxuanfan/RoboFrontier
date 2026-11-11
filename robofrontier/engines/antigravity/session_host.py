"""Antigravity adapter: create a native ID before any model turn or START."""
import json
from pathlib import Path

from robofrontier.engines.common.session_host import SessionHost
from .driver import Driver
from .provenance import steps


class AntigravitySessionHost(SessionHost):
    def __init__(self, run_dir, actor, profile, base_env, *, binary='agy', python=None, runner=None,
                 native_session=None, **options):
        run = Path(run_dir).resolve()
        roles = json.loads((run/'public/inputs/roles.json').read_text())['roles']
        if actor == 'Meta' or actor not in roles and not options.get('_validated_delegate'):
            raise ValueError('Expected a frozen policy role or validated delegate')
        if options.get('max_budget_usd') is not None or options.get('total_budget_usd') is not None:
            raise ValueError('Antigravity cannot enforce a dollar budget')
        if native_session is None:
            from robofrontier.runtime.store import RuntimeStore
            store = RuntimeStore(run/'private/state/runtime.sqlite')
            try:
                native_session = store.agent(actor)['thread_id']
            finally:
                store.close()
        driver = runner or Driver(run, actor, profile, base_env, binary=binary, session=native_session, python=python)
        session = driver.open()
        super().__init__(run, actor, profile, base_env, binary=binary, runner=driver,
                         engine='antigravity', mcp=None, session_id=session, **options)

    def history_available(self):
        return bool(steps(self.runner.home, self.session_id))
