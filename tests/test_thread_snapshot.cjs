const assert = require('node:assert/strict');
const vm = require('node:vm');
const {execFileSync} = require('node:child_process');
const source = JSON.parse(execFileSync('python', ['-c', "import ast,json,pathlib; tree=ast.parse(pathlib.Path('core/muse_thread.py').read_text(encoding='utf-8')); print(json.dumps(next(n.value.value for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='THREAD_SNAPSHOT_JS' for t in n.targets))))"], {encoding:'utf8'}));
let video = {currentSrc:'https://media.test/result.mp4', src:'', readyState:4, duration:15, videoWidth:480, videoHeight:480, closest:()=>null, querySelector:()=>null};
let assistant = null;
let missingRoot = false;
let editorEnabled = true;
const send = {getClientRects:()=>[1], getAttribute:()=> 'Send', disabled:false, type:'submit'};
const root = {innerText:'User prompt: Generating... render a video', querySelectorAll: selector => {
  if (selector === 'video') return video ? [video] : [];
  if (selector.includes('data-message-author-role')) return assistant ? [assistant] : [];
  return [];
}};
const context = vm.createContext({
  document: {body:root, getElementById:()=>missingRoot ? null : root, querySelector:selector=> ['main','[role="main"]'].includes(selector) || !editorEnabled ? null : ({value:'',textContent:''}), querySelectorAll: selector=> selector === 'video' ? (video ? [video] : []) : selector.startsWith('button') ? [send] : []},
  navigator:{onLine:true}, location:{href:'https://muse.ai/thread/abc'}, getComputedStyle:()=>({visibility:'visible'})
});
const square = vm.runInContext(source, context);
assert.equal(square.src, video.currentSrc);
assert.equal(square.playable, true, '480x480 result must not be classified as avatar');
assert.equal(square.busy, false, 'Generation words in the user prompt are not a busy signal');
missingRoot = true;
context.navigator.onLine = false;
assert.equal(vm.runInContext(source, context).src, video.currentSrc,
  'Missing chat wrapper and offline hint must not block reading an existing video');
video = null;
assistant = {innerText:'Cannot create this video.', matches:()=>true, querySelectorAll:()=>[]};
assert.equal(vm.runInContext(source, context).responseComplete, true);
assistant = null;
context.window = {__museExpectedPrompt: 'Generate my video'};
root.innerText = 'You: Generate my video Sorry, I cannot generate this video. Message Muse';
assert.equal(vm.runInContext(source, context).responseComplete, true,
  'An unlabelled finished reply after the submitted prompt is recognized');
root.innerText = '';
root.tagName = 'BODY';
root.textContent = 'inert script text';
editorEnabled = false;
assert.equal(vm.runInContext(source, context).ready, false, 'A blank body is not a loaded chat');
console.log('PASS: playable square video, stale prompt words, and completed text-only reply.');
