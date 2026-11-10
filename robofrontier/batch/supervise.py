"""What both batch supervisors do for each run (batch/codex_batch.py, batch/claude_batch.py):
launch it, and after every end ask the stop table whether it continues by itself
(runtime/segments.py). Each engine launches its own host and keeps its own records; this
module holds the loop between them."""


def supervise_run(run, launch, *, continuing, lifecycle, try_continue, final, reason, record,
                  exited='batch supervisor exited'):
    """Run one run until it ends for good. Returns (outcome, value, pending):

    - ('refused', why, pending): a continuing batch found the run stopped and it may not continue;
    - ('ended', result, pending): the last launch's result, final or not continued.

    `pending` is whether a prepared continuation segment was or is about to be run. With
    `continuing`, a run that had started before the supervisor died is first prepared for its
    next segment (a segment already prepared starts as it is); a run that never started starts.
    `final(result)` says a result needs no question (the host's own limit, a STOP, a finish);
    `reason(result)` names the end for the segment record; `record(result, continued, why)`
    stores each question's answer (result None for the supervisor's own exit)."""
    pending = False
    if continuing:
        state = lifecycle(run)
        pending = state == 'resuming'
        if state not in ('prepared', 'resuming'):
            continued, why = try_continue(run, exited)
            record(None, continued, why)
            if not continued: return 'refused', why, pending
            pending = True
    while True:
        result = launch()
        if final(result): return 'ended', result, pending
        continued, why = try_continue(run, reason(result))
        record(result, continued, why)
        if not continued: return 'ended', result, pending
        pending = True
