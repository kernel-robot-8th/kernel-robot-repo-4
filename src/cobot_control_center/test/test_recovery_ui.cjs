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

function zoneUi(robot, extra = {}) {
  const context = ui('release.js', extra);
  context.view.controllerOnline = true;
  context.view.snapshot = { robots: { pinky1: robot }, queues: { A: ['pinky2'] } };
  return context;
}

test('zone release only for offline robot or one that forgot its token', () => {
  // 연결 끊김: 마지막 상태가 잡고 있다고 해도 보인다 (현장 확인에 맡김)
  assert.equal(zoneUi({ online: false, extra: { held_zone: 'A', busy: true } })
    .zoneReleaseAllowed('A', 'pinky1'), true);
  // 다시 켜져 잊음
  assert.equal(zoneUi({ online: true, extra: { held_zone: null, busy: false } })
    .zoneReleaseAllowed('A', 'pinky1'), true);
  // 살아 있고 아직 잡고 있음 → 나가기
  assert.equal(zoneUi({ online: true, extra: { held_zone: 'A', busy: false } })
    .zoneReleaseAllowed('A', 'pinky1'), false);
  // 움직이는 중, held_zone 보고 없음, 읽기 전용
  assert.equal(zoneUi({ online: true, extra: { held_zone: null, busy: true } })
    .zoneReleaseAllowed('A', 'pinky1'), false);
  assert.equal(zoneUi({ online: true, extra: { busy: false } })
    .zoneReleaseAllowed('A', 'pinky1'), false);
  const readOnly = zoneUi({ online: false, extra: {} });
  readOnly.view.readOnly = true;
  assert.equal(readOnly.zoneReleaseAllowed('A', 'pinky1'), false);
});

test('zone release asks on-site check and posts robot id', async () => {
  const questions = [], posts = [], messages = [];
  const context = zoneUi({ online: false, extra: {} }, {
    confirm: (q) => { questions.push(q); return true; },
    postJson: async (...args) => { posts.push(args); return { ok: true, status: 202, data: {} }; },
    showMessage: (...args) => messages.push(args),
  });
  await context.openZoneRelease('A', 'pinky1');
  assert.match(questions[0], /구역 A 밖에 있는지/);
  assert.match(questions[0], /pinky2/);
  assert.equal(posts[0][0], '/api/zones/A/release');
  assert.equal(JSON.stringify(posts[0][1]), JSON.stringify({ robot_id: 'pinky1', client_request_id: 'click1' }));
  assert.equal(messages[0][2], false);
  // 취소하면 보내지 않는다
  const declined = zoneUi({ online: false, extra: {} }, { confirm: () => false,
    postJson: async (...args) => { posts.push(args); return { ok: true }; } });
  await declined.openZoneRelease('A', 'pinky1');
  assert.equal(posts.length, 1);
});

function loadBarUi(order) {
  const el = {};
  const $ = id => (el[id] ||= { id, hidden: true, checked: false, value: '', textContent: '',
    disabled: false, focus() {}, addEventListener() {} });
  const host = { appendChild() {} };
  const context = ui('load.js', { $, barHost: () => host, focusCard() {}, savedOperator: () => '' });
  context.view.orders = [order];
  return { context, el: $ };
}

test('load bar offers order cancel only for a blocked order', () => {
  const blocked = { order_id: 'o1', robot_id: 'pinky1', sku: 'SHOE42', blocked: true,
    load_confirmable: true, load_waiting: true, resumable: false };
  const shown = loadBarUi(blocked);
  shown.context.openLoad('pinky1');
  assert.equal(shown.el('load-abort').hidden, false);

  const waiting = loadBarUi({ ...blocked, blocked: false });
  waiting.context.openLoad('pinky1');
  assert.equal(waiting.el('load-abort').hidden, true);
});

test('load bar order cancel closes the bar and sends confirmed cleanup evidence', () => {
  const order = { order_id: 'o1', robot_id: 'pinky1', sku: 'SHOE42', blocked: true,
    load_confirmable: true, load_waiting: true, resumable: false };
  const { context, el } = loadBarUi(order);
  const requests = [];
  context.sendOrderRecover = (...args) => requests.push(args);
  context.openLoad('pinky1');
  context.abortLoad();
  assert.equal(el('load-bar').hidden, true);
  assert.equal(context.view.loading, null);
  assert.equal(requests.length, 1);
  assert.equal(requests[0][1], 'fail');
  assert.deepEqual(JSON.parse(JSON.stringify(requests[0][2])),
    { arms_safe: true, cargo_reconciled: true, resources_clear: true });
});
