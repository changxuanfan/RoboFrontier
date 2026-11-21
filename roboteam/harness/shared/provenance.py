"""Fork lineage of a role's session, in the evidence format of the run's harness."""

from roboteam.runtime.run.admin import fork_provenance


def native_fork_provenance(store, parent, child):
    """Verify that session `child` was forked from `parent`, reading this run's own harness files."""
    if store.get('config').get('harness', 'codex') == 'claude':
        from roboteam.harness.claude.session.native_home import history_directory
        from roboteam.harness.claude.systems.provenance import fork_provenance as claude_provenance

        return claude_provenance(parent, child, history_directory(store.path.parents[2]))
    return fork_provenance(parent, child)
