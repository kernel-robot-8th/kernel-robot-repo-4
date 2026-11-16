// Run with: node --test src/cobot_control_center/test/test_recovery_ui.cjs
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

function ui(file, extra = {}) {
  const context = vm.createContext({
    view: { holds: { pinky1: 'ESTOP' }, orders: [], commandsArmed: true },
    closeBars() {}, confirm: () => true, newRequestId: () => 'click1',
    robotTask: () => null, UNKNOWN_TASK: new Set(), showMessage() {},
    ...extra,
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../web', file), 'utf8'), context);
  return context;
}

test('release keeps hold until server state confirms reset', async () => {
  const messages = [];
  const context = ui('release.js', {
    showMessage: (...args) => messages.push(args),
    postJson: async () => ({ ok: true, status: 202, data: { released: false, reset_pending: true } }),
  });
  await context.openRelease('pinky1');
  assert.equal(context.view.holds.pinky1, 'ESTOP');
  assert.match(messages[0][1], /응답 대기/);
});

test('cancel sends only individually confirmed cleanup evidence', () => {
  const order = { order_id: 'o1', robot_id: 'pinky1', sku: 'SHOE42', blocked: true };
  for (const declineAt of [1, 2, 3, -1]) {
    const questions = [], requests = [];
    const context = ui('load.js', {
      confirm: question => { questions.push(question); return questions.length - 1 !== declineAt; },
    });
    context.view.orders = [order];
    context.sendOrderRecover = (...args) => requests.push(args);
    context.recoverOrder('pinky1');
    if (declineAt !== -1) {
      assert.equal(requests.length, 0);
    } else {
      assert.equal(questions.length, 4);
      assert.equal(requests.length, 1);
      assert.deepEqual(JSON.parse(JSON.stringify(requests[0][2])),
        { arms_safe: true, cargo_reconciled: true, resources_clear: true });
    }
  }
});

test('order cancellation does not clear pending robot hold optimistically', async () => {
  const context = ui('load.js', { postJson: async () => ({ ok: true, data: { state: 'FAILED' } }) });
  const order = { order_id: 'o1', robot_id: 'pinky1' };
  context.view.orders = [order];
  await context.sendOrderRecover(order, 'fail', {});
  assert.equal(context.view.holds.pinky1, 'ESTOP');
});
