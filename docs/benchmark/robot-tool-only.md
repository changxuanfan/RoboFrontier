# Robot-only runs

`policy.tools = "robot_only"` (or `--tools robot_only`) prepares runs whose agents have the
robot tool and nothing else: no shell, no code execution and no file tool. It is the comparison
for the default `full` mode, where each harness also gives its own file and shell tools.
Everything else is the same: task inputs, robot operations, physics, scoring, time limit,
context window and compaction.

```sh
.venv/bin/roboteam prepare --output runs/policy/<batch> --harness claude --tools robot_only
```

## What a role has

| Purpose | `full` | `robot_only` |
|---|---|---|
| Observe, move, grasp, check motion, messages, work note, delegation | robot tool | robot tool |
| Reread the task, rules, guides, calibration; view reference images, saved observations and delegate reports | file tools | `robot` op `public_file` (read-only, this run's `public/` folder) |
| Read and extend the run's shared lessons (`workspace/skills.md`) | file tools | `robot` op `skills` (headings, read, append, revise; earlier text cannot be changed) |
| A returned delegate's report | Claude: inline in `work`; Codex: read the file | inline in `work` on both harnesses |
| Shell, Python, scripts, scratch files, cropping or measuring images in code | yes | no |

The two operations exist only in a robot-only run; a full run refuses them. In a robot-only
run the roles of both harnesses receive the same first message.

## How each harness is restricted

- **Claude Code** starts with `--tools ""`, pre-allows only `mcp__robot__robot`, loads no user,
  project or local settings, and keeps the fork gate hook. No file settings are rendered.
- **Codex** switches its own tools off with its feature flags and model catalog, and registers
  `robot` as the only tool. `runtime.codex_tool_backend` is `native` on every host, since there
  is no shell or file tool to confine. A robot-only model needs its own
  `roboteam preflight --tools robot_only`: the receipt is tied to the launch model and
  is kept beside the full one, under `<model>.robot_only/`.

No policy Python environment is frozen for a robot-only run.

## Checks

`tests/runtime/tools/test_robot_only.py` covers preparation and the two operations.
`tests/harness/claude/test_claude_robot_only.py` and `tests/harness/codex/test_codex_robot_only.py` run the
installed CLIs against a local stub model and read the tool list the model is sent on a first
turn, a fork and a resumed session: it is the robot tool alone, and the harnesses' own tools are
refused.

## Limits

Codex subscription jobs on Slurm (`slurm.auth_mode = "subscription"`) require the `landlock-v1`
tool backend, which a robot-only run does not use. Preparation refuses that combination.
`--observation ground_truth` with `robot_only` is refused too: a ground-truth role needs its
code tools.
