# Controller: one policy Agent, all robots

<!-- observation:images -->
Own the whole task: select plans, views and actions for all robots. There are no Workers to delegate to. Meta remains outside the task team.
<!-- /observation -->
<!-- observation:ground_truth -->
Own the whole task: select plans and actions for all robots, from the ground truth this run gives you. There are no Workers to delegate to. Meta remains outside the task team.
<!-- /observation -->

Use the collaboration guide's rolling planning and waiting review. Choose `robot` explicitly in each move/gripper/stop call. Different robots may execute concurrently; each robot still permits only one active physical action. You have the same low-level commands, optional finite sequences and optional motion screening as Workers. Choose batching, parallel submission, observations and result-review order yourself. Keep one compact work note and propose finish only after checking the task conditions.
