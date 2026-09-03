# Native Worker task boundary

For each fresh native task, treat only the current assignment and its current
task/context references as authoritative. Do not use recall, search, or prior-run
history, or messages and artifacts from another run to choose or repeat work.

Your first allowed work action is to read the current task/context references,
then invoke `native_worker_execute` exactly once through the
`testweaver-native-worker` MCP tool. Do not perform any other exploration or
repeat the invocation after it returns.

Keep native assignment, task state, room communication, delegation, and result
submission under the native TeamHarness contract. Missing process or provider
facts remain unavailable; never infer them from prior runs.
