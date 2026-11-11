"""Engineering lifecycle for an existing centralized Claude policy/world.

This does not admit benchmark batches or create worlds. The caller owns the
physical process; seal is the only normal shutdown path and never replays work.
"""
import math
import time

from robofrontier.runtime.bootstrap import STARTUP_TIMEOUT_S


# active_time_v1: the host ends a run on its own only this far past the world's limit, and
# waits this long after the world's cutoff for it to brake and close.
ACTIVE_BACKSTOP_S = 60.
ACTIVE_CLOSE_WAIT_S = 120.


class CentralizedSupervisor:
    def __init__(self, policy, owner_alive, *, stop_requested=lambda: False,
                 startup_timeout_s=STARTUP_TIMEOUT_S, wall_limit_s=86400, poll_s=1,
                 seal_timeout_s=30, finish_turn_grace_s=30, time_rule='START_wall_time',
                 wall_backstop_s=None, clock=time.monotonic, wall_clock=time.time, sleep=time.sleep):
        for name, value, maximum in (('startup_timeout_s', startup_timeout_s, 86400),
                                     ('wall_limit_s', wall_limit_s, 86400),
                                     ('poll_s', poll_s, 60)):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 < value <= maximum:
                raise ValueError('Invalid ' + name)
        if isinstance(seal_timeout_s, bool) or not isinstance(seal_timeout_s, (int, float)) or not math.isfinite(seal_timeout_s) or not 0 <= seal_timeout_s <= 120:
            raise ValueError('Invalid seal timeout')
        if (isinstance(finish_turn_grace_s, bool) or not isinstance(finish_turn_grace_s, (int, float))
                or not math.isfinite(finish_turn_grace_s) or not 0 <= finish_turn_grace_s <= 120):
            raise ValueError('Invalid finished-turn grace period')
        if time_rule not in ('START_wall_time', 'active_time_v1'):
            raise ValueError('Unknown run clock')
        if wall_backstop_s is not None and (isinstance(wall_backstop_s, bool) or not isinstance(wall_backstop_s, (int, float))
                                            or not math.isfinite(wall_backstop_s) or wall_backstop_s <= 0):
            raise ValueError('Invalid wall backstop')
        self.policy = policy
        self.owner_alive = owner_alive
        self.stop_requested = stop_requested
        self.startup_timeout_s = startup_timeout_s
        self.wall_limit_s = wall_limit_s
        self.poll_s = poll_s
        self.seal_timeout_s = seal_timeout_s
        self.finish_turn_grace_s = finish_turn_grace_s
        self.clock = clock
        self.wall_clock = wall_clock
        self.sleep = sleep
        # active_time_v1 (the run's frozen protocol clock): the world counts only active running
        # time and ends the run itself; this host never ends it on wall time.
        self.active_time = time_rule == 'active_time_v1'
        # The run's frozen wall backstop (policy_probe.BudgetGuard); only active-time runs have one.
        self.wall_backstop_s = wall_backstop_s if self.active_time else None
        self.cutoff_seen = None
        self.used = False

    def _wall_limit_reached(self):
        """The world's own wall-limit guard has fired: it pauses dispatch, stops the arms and
        then ends the run, so a pause seen in between is that normal end, not a review stop."""
        if self._backstopped(): return True
        if self._after_score(): return False
        db = getattr(self.policy.store, 'db', None)
        return bool(db and db.execute("SELECT 1 FROM events WHERE kind='POLICY_WALL_LIMIT' LIMIT 1").fetchone())

    def _after_score(self):
        """A continuation after the finish or the cutoff has no limit (run_segments.STOP_REASONS)."""
        return bool(self.policy.store.get('after_score'))

    def _backstopped(self):
        """The world's wall backstop has fired: it ends the run the same way as the cutoff."""
        return self.wall_backstop_s is not None and bool(self.policy.store.get('wall_backstop'))

    def _backstop_overdue(self):
        """The world did not end the run at its wall backstop, even after the closing wait: a hung
        owner. The host ends it itself, with the same reason."""
        if self.wall_backstop_s is None or self.policy.store.get('start_at') is None or self._after_score(): return False
        # The active-time cutoff already fired: the run is closing at its limit, not the backstop.
        if not self._backstopped() and self._wall_limit_reached(): return False
        from robofrontier.runtime.clock import backstop_elapsed
        return (backstop_elapsed(self.policy.store, self.wall_clock())
                >= self.wall_backstop_s + ACTIVE_CLOSE_WAIT_S + self.seal_timeout_s)

    def _limit_reached(self, now, started_at):
        if self._after_score(): return False
        if not self.active_time: return now - started_at >= self.wall_limit_s
        # The world's own guard fires at the limit; this is only a backstop if it did not.
        return float(self.policy.store.get('active_s', 0.) or 0.) >= self.wall_limit_s + ACTIVE_BACKSTOP_S

    def _await_world_close(self, began):
        """After the world's wall limit fired, wait for it to brake and end the run."""
        if not self.active_time:
            return self.clock()-began < self.startup_timeout_s+self.wall_limit_s+self.seal_timeout_s
        if self.cutoff_seen is None: self.cutoff_seen = self.clock()
        return self.clock()-self.cutoff_seen < ACTIVE_CLOSE_WAIT_S+self.seal_timeout_s

    def _turn_states(self):
        # Standing teams expose a team status; Adaptive also has child hosts
        # whose final API response can follow their physical handback.
        hosts = [self.policy.host]
        hosts.extend(getattr(self.policy, 'hosts', {}).values())
        setup = getattr(self.policy, 'setup', None)
        hosts.extend(getattr(setup, 'hosts', {}).values())
        return [host.observe()['status'] for host in hosts]

    def _projected_start(self):
        """The persisted START on the monotonic clock; downtime between segments is not counted."""
        started_wall = self.policy.store.get('start_at')
        if not isinstance(started_wall, (int, float)) or isinstance(started_wall, bool) or not math.isfinite(started_wall):
            raise ValueError('Running policy is missing a valid START time')
        return self.clock() - max(0., self.wall_clock() - started_wall - self.policy.store.get('downtime_s', 0.))

    def run(self):
        if self.used:
            raise ValueError('Supervisor cannot restart a world')
        self.used = True
        reason = 'supervisor_error'
        error_type = None
        error_message = None
        sealed = None
        seal_error_type = None
        started_at = None
        session_evidence = None
        finish_turns_drained = None
        began = self.clock()
        try:
            if self.stop_requested():
                reason = 'stop_requested'
            elif not self.owner_alive():
                reason = 'owner_unavailable'
            else:
                # A run continued after an unexpected exit resumes its sessions (docs/running/continuation.md).
                if getattr(self.policy, 'resuming', False): self.policy.resume_segment()
                else: self.policy.bind_and_bootstrap()
                if self.policy.store.get('lifecycle') == 'running':
                    started_at = self._projected_start()
                while True:
                    if self.stop_requested():
                        reason = 'stop_requested'; break
                    lifecycle = self.policy.store.get('lifecycle')
                    if lifecycle in ('ended', 'interrupted', 'recovery_required'):
                        reason = 'world_' + lifecycle; break
                    if not self.owner_alive():
                        reason = 'owner_unavailable'; break
                    if self._backstop_overdue():
                        reason = 'wall_backstop'; break
                    if self.policy.store.get('physics_state') == 'paused_by_egress':
                        # The world holds itself through a route or model-API outage (egress_pause);
                        # it resumes by itself and the paused time does not count.
                        self.sleep(self.poll_s); continue
                    if self.policy.store.get('dispatch_paused', False):
                        if self._wall_limit_reached() and self._await_world_close(began):
                            self.sleep(self.poll_s); continue
                        reason = 'dispatch_paused'; break
                    observation = self.policy.host.observe()
                    state = observation['status']
                    now = self.clock()
                    if started_at is not None and self._limit_reached(now, started_at):
                        reason = 'wall_limit'; break
                    recovering = (state == 'error' and hasattr(self.policy.host, 'recover_capacity')
                                  and self.policy.host.recover_capacity(self.policy.store))
                    if state in ('unknown', 'error') and not recovering:
                        session_evidence = {key: observation.get(key) for key in
                                            ('budget_status', 'last_result_subtype', 'last_turn_reported_cost_usd')}
                        reason = 'session_' + state; break
                    now = self.clock()
                    if started_at is None:
                        if now - began >= self.startup_timeout_s:
                            reason = 'startup_timeout'; break
                        if state == 'idle' and self.policy.store.agent('Controller')['ready']:
                            self.policy.start_when_ready()
                            started_at = self._projected_start()
                    else:
                        if self._limit_reached(now, started_at):
                            reason = 'wall_limit'; break
                        result = self.policy.cycle()
                        if result.get('paused') and not self._wall_limit_reached():
                            reason = 'dispatch_paused'; break
                    self.sleep(self.poll_s)
        except Exception as error:
            error_type = type(error).__name__
            error_message = str(error)[:300]
        finally:
            # finish has already frozen the terminal world. Allow only the
            # existing native turns to receive its reply and settle their
            # accounting before cancellation. No dispatch or physics occurs.
            # A wall-limit end cuts the turns off instead: no reply is due.
            ended_by = ('wall_backstop' if reason == 'world_ended' and self._backstopped()
                        else 'wall_limit' if reason == 'world_ended' and self._wall_limit_reached() else None)
            if reason == 'world_ended' and ended_by is None:
                try:
                    deadline = self.clock() + self.finish_turn_grace_s
                    while 'active' in self._turn_states():
                        remaining = deadline - self.clock()
                        if remaining <= 0 or self.stop_requested():
                            break
                        self.sleep(min(self.poll_s, remaining))
                    finish_turns_drained = all(state == 'idle' for state in self._turn_states())
                except Exception as error:
                    finish_turns_drained = False
                    error_type = error_type or type(error).__name__
            # Prevent further model turns before asking the physical owner to seal.
            # A killed CLI turn has an unknown outcome, never an automatic retry.
            try:
                self.policy.stop()
                if hasattr(self.policy.host, 'wait'):
                    from robofrontier.engines.claude.runner import STOP_WAIT_S
                    self.policy.host.wait(timeout=STOP_WAIT_S)
            except Exception as error:
                error_type = error_type or type(error).__name__
            try:
                # The shared seal leaves an unresolved live world paused rather
                # than force-closing or replaying uncertain physical actions.
                sealed = self.policy.dispatcher.admin('seal', {'timeout_s': self.seal_timeout_s}) if self.policy.dispatcher else None
                if sealed is None:
                    from robofrontier.runtime.seal import seal_run
                    sealed = seal_run(self.policy.store, self.seal_timeout_s)
            except Exception as error:
                seal_error_type = type(error).__name__
        return {'reason': reason, 'error_type': error_type, 'error': error_message, 'seal': sealed,
                'seal_error_type': seal_error_type, 'started': started_at is not None,
                'session_evidence': session_evidence,
                'finish_turns_drained': finish_turns_drained, 'ended_by': ended_by,
                # Stopped by wall time, not the active-time limit: needs review, never counted.
                'wall_backstop': reason == 'wall_backstop' or ended_by == 'wall_backstop',
                'scope': 'engineering lifecycle; task success requires runtime evaluation'}
