// A role's calls run one at a time in arrival order; other roles are not held up (E1).
const test = require('node:test');
const assert = require('node:assert');
const {PolicyHost, robotTool} = require('../../robofrontier/engines/codex/codex_policy_host.js');
const shared = require('../../robofrontier/engines/common/robot_tool.json');

test('calls of one role run in the order they arrived, one at a time', async () => {
  const host = Object.create(PolicyHost.prototype); const log = []; let running = 0, most = 0;
  host.runTool = async (method, p, sequence) => {
    running += 1; most = Math.max(most, running); log.push('start '+p.callId);
    await new Promise(resolve => setTimeout(resolve, p.delay));
    log.push('end '+p.callId); running -= 1; return {sequence};
  };
  const calls = [{threadId: 'A', callId: 'a1', delay: 30}, {threadId: 'A', callId: 'a2', delay: 1}, {threadId: 'A', callId: 'a3', delay: 5}];
  const results = await Promise.all(calls.map(p => host.toolRequest('item/tool/call', p)));
  assert.deepStrictEqual(log, ['start a1', 'end a1', 'start a2', 'end a2', 'start a3', 'end a3']);
  assert.strictEqual(most, 1);
  assert.deepStrictEqual(results.map(r => r.sequence), [1, 2, 3]);
});

test('a failed call does not stop the next one, and roles run independently', async () => {
  const host = Object.create(PolicyHost.prototype); const order = [];
  host.runTool = async (method, p) => {
    await new Promise(resolve => setTimeout(resolve, p.delay)); order.push(p.callId);
    if (p.fail) throw new Error('failed'); return p.callId;
  };
  const a1 = host.toolRequest('item/tool/call', {threadId: 'A', callId: 'a1', delay: 30, fail: true});
  const a2 = host.toolRequest('item/tool/call', {threadId: 'A', callId: 'a2', delay: 1});
  const b1 = host.toolRequest('item/tool/call', {threadId: 'B', callId: 'b1', delay: 1});
  await assert.rejects(a1); assert.strictEqual(await a2, 'a2'); assert.strictEqual(await b1, 'b1');
  assert.deepStrictEqual(order, ['b1', 'a1', 'a2']);
});

test('the Codex tool is the shared robot tool', () => {
  assert.strictEqual(robotTool.type, 'function');
  assert.strictEqual(robotTool.description, shared.description);
  assert.deepStrictEqual(robotTool.inputSchema, shared.inputSchema);
});
