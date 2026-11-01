const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const rows = Array.from({length: 127}, (_, i) => ({id: `task_${i}`}));
let requests = [];
let size = 10;
const context = vm.createContext({
  document: {addEventListener() {}}, console,
  fetch: async url => {
    requests.push(url);
    const page = Number(new URL(url, 'http://localhost').searchParams.get('page'));
    return {ok: true, json: async () => ({jobs: rows.slice((page - 1) * size, page * size), total: rows.length, pageSize: size})};
  }
});
vm.runInContext(fs.readFileSync('static/app.js', 'utf8'), context);
(async () => {
  const all = await vm.runInContext("fetchAllJobs('Tất cả', '')", context);
  assert.equal(all.jobs.length, 127);
  assert.equal(new Set(all.jobs.map(row => row.id)).size, 127);
  assert.equal(requests.length, 13);
  requests = [];
  size = 127;
  const modern = await vm.runInContext("fetchAllJobs('Tất cả', '')", context);
  assert.equal(modern.jobs.length, 127);
  assert.equal(requests.length, 1);
  console.log('PASS: all 127 records are collected from a 10-per-page backend; new backend uses one request.');
})().catch(error => {console.error(error); process.exitCode = 1;});
