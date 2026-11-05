"""Shape a current configuration like one frozen before schema version 5.

The options are listed here rather than taken from robofrontier/configuration.py, so a test
using this checks the validator against what older files actually hold.
"""
LATER_OPTIONS = {'runtime': ('codex_tool_backend',),
                 'slurm': ('auth_mode', 'credential_store', 'egress_mode', 'egress_root', 'egress_wait_s', 'egress_pause_s')}


def without_later_options(config):
    for section, names in LATER_OPTIONS.items():
        for name in names:
            del config[section][name]
    return config
