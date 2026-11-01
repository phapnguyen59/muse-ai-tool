const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const controls = { inpConcurrency: { value: '3' }, txtBatchPrompts: { value: '' }, concurrencyStatus: {} };
const calls = [];
const events = {};
let scheduled;
controls.inpConcurrency.addEventListener = (name, callback) => { events[name] = callback; };
controls.txtBatchPrompts.addEventListener = () => {};
controls.batchRefTrigger = {addEventListener() {}};
controls.batchRefOptions = {addEventListener() {}};
const context = vm.createContext({
  document: { addEventListener() {}, getElementById(id) { return controls[id]; } },
  fetch: async (url, options) => {
    calls.push({url, options});
    return {ok: true, json: async () => ({ok: true, concurrency: 3, concurrencyProtocol: 2})};
  },
  console,
  clearTimeout,
  setTimeout: callback => { scheduled = callback; return 1; },
});
vm.runInContext(fs.readFileSync('static/app.js', 'utf8'), context);
vm.runInContext('showToast = () => {}; loadJobs = async () => {};', context);
(async () => {
  await vm.runInContext('startDispatcher()', context);
  assert.equal(calls.length, 2);
  assert.equal(calls[0].url, '/api/config/concurrency');
  assert.equal(calls[1].url, '/api/queue/process');
  assert.deepEqual(JSON.parse(calls[1].options.body), {concurrency: 3});
  controls.inpConcurrency.value = '1.5';
  await vm.runInContext('startDispatcher()', context);
  assert.equal(calls.length, 2, 'Invalid settings must not start the queue');
  controls.inpConcurrency.value = '3';
  vm.runInContext('initEvents()', context);
  events.input();
  await scheduled();
  assert.equal(calls[2].url, '/api/config/concurrency', 'Editing the input applies while queue is running');
  context.fetch = async () => ({ok: true, json: async () => ({concurrency: 3})});
  const applied = await vm.runInContext('applyConcurrency(false)', context);
  assert.equal(applied, false, 'Old backend must not silently acknowledge the new UI');
  console.log('PASS: Start sends selected concurrency without Apply; invalid value does not start.');
})().catch(error => { console.error(error); process.exitCode = 1; });
