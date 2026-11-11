# Robot-only runs

`policy.tool_mode = "robot_only"` (or `--tool-mode robot_only`) prepares runs whose policy roles
have the bound robot tool and nothing else: no shell, no code execution and no file tool. It is
the comparison for the default `full` mode, where each engine also gives its own file and shell
tools. Everything else is the same: task inputs, robot operations, physics, scoring, time
budget, context window and compaction.

```sh
.venv/bin/robofrontier prepare --output runs/policy/<batch> --engine claude --tool-mode robot_only
```

## What a role has

| Purpose | `full` | `robot_only` |
|---|---|---|
| Observe, move, grasp, check motion, messages, work note, delegation | robot tool | robot tool |
| Reread the task, rules, Skills, calibration; view reference images, saved observations and delegate reports | file tools | `robot` op `public_file` (read-only, this run's `public/` folder) |
| Read and extend the run's shared lessons (`workspace/skills.md`) | file tools | `robot` op `skills` (headings, read, append, revise; earlier text cannot be changed) |
| A returned delegate's report | Claude: inline in `work`; Codex: read the file | inline in `work` on both engines |
| Shell, Python, scripts, scratch files, cropping or measuring images in code | yes | no |

The two operations exist only in a robot-only run; a full run refuses them, and its inputs are
byte for byte what they were before the mode existed. Both engines' roles receive the same
first message in a robot-only run.

## How each engine is restricted

- **Claude Code** starts with `--tools ""`, pre-allows only `mcp__robot__robot`, loads no user,
  project or local settings, and keeps the fork gate hook. No file settings are rendered.
- **Codex** switches its own tools off with the feature flags and model catalog the Landlock tool
  worker uses, and registers `robot` as the only dynamic tool. `runtime.codex_tool_backend` is
  `native` on every host, since there is nothing to confine. A robot-only profile needs its own
  `robofrontier preflight`: the receipt is tied to the launch profile.

No policy Python environment is frozen for a robot-only run.

## Checks

`tests/runtime/test_robot_only.py` covers preparation and the two operations.
`tests/engines/test_claude_robot_only.py` and `tests/engines/test_codex_robot_only.py` run the
installed CLIs against a local stub model and read the tool list the model is sent on a first
turn, a fork and a resumed session: it is the robot tool alone, and the engines' own tools are
refused.

## Not supported yet

The Slurm subscription route for Codex (`slurm.auth_mode = "subscription"`) requires the
`landlock-v1` backend and its job gateway, which expect the file tools; preparation refuses
that combination with `robot_only`.
