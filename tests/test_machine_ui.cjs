const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const machineId = 'MUSE-AAAA-BBBB-CCCC-DDDD';
const controls = {machineId: {value:''}, btnCopyMachineId: {disabled:true}, machineLicenseInfo: {textContent:''}};
const urls = [];
let copied;
const context = vm.createContext({
  document: {addEventListener() {}, getElementById: id => controls[id]},
  fetch: async url => {
    urls.push(url);
    return {ok: true, json: async () => ({machineId, firebaseConfigured:true, savedAccounts:2, lastCheck:null})};
  },
  navigator: {clipboard: {writeText: async value => {copied = value;}}},
  event: {stopPropagation() {}}, console
});
vm.runInContext(fs.readFileSync('static/app.js', 'utf8'), context);
vm.runInContext('showToast = () => {};', context);
(async () => {
  await vm.runInContext('loadMachineInfo()', context);
  assert.equal(controls.machineId.value, machineId);
  assert.equal(controls.btnCopyMachineId.disabled, false);
  assert.deepEqual(urls, ['/api/machine']);
  await vm.runInContext('copyMachineId(event)', context);
  assert.equal(copied, machineId);
  console.log('PASS: displays and copies machine ID with one local info request.');
})().catch(error => {console.error(error); process.exitCode = 1;});
