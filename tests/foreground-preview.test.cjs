const {test} = require('node:test');
const assert = require('node:assert/strict');
const {createForegroundReview} = require('../gso-viewer/frontend/foreground-preview.js');

class Element {
  constructor() {
    this.events = new Map(); this.files = []; this.hidden = false;
    this.disabled = false; this.checked = false; this._value = '';
    this.parentElement = {removeAttribute(name) { delete this[name]; }};
    this.naturalWidth = 0; this.naturalHeight = 0;
  }
  set value(value) { this._value = value; if (value === '') this.files = []; }
  get value() { return this._value; }
  addEventListener(name, callback) {
    if (!this.events.has(name)) this.events.set(name, new Set());
    this.events.get(name).add(callback);
  }
  removeEventListener(name, callback) { this.events.get(name)?.delete(callback); }
  emit(name) { return Promise.all([...(this.events.get(name) || [])].map(callback => callback())); }
  setAttribute(name, value) { this[name] = value; }
  removeAttribute(name) { delete this[name]; }
  click() { return this.emit('click'); }
}
const ID = 'a'.repeat(32), SHA = 'b'.repeat(64);
const task = {id:ID, host:'school', root:'/project', time_limit:'02:00:00',
  download_shape:false, phase:'awaiting_confirmation', preview_sha256:SHA};
const preview = {id:ID, preview_sha256:SHA,
  original_url:`/api/generation-preview/${ID}/original`,
  foreground_url:`/api/generation-preview/${ID}/foreground`,
  model_input_url:`/api/generation-preview/${ID}/model-input`};
const tick = () => new Promise(resolve => setImmediate(resolve));
function setup(respond = async () => ({ok:true, json:async () => preview})) {
  const elements = new Map(), calls = [], revoked = [];
  const $ = name => {
    if (!elements.has(name)) elements.set(name, new Element());
    return elements.get(name);
  };
  const review = createForegroundReview({
    document:{querySelector:$},
    fetch:async (url, options) => { calls.push({url, options}); return respond(url, options); },
    URL:{createObjectURL:() => 'blob:photo', revokeObjectURL:value => revoked.push(value)},
    AbortController, setTimeout, clearTimeout,
  });
  review.configure({host:'school', project:'/project', time_limit:'02:00:00', download_shape:false});
  async function loadPictures() {
    for (const name of ['original', 'foreground', 'model-input']) {
      const picture = $('#review-' + name);
      picture.naturalWidth = picture.naturalHeight = 1024;
      await picture.emit('load');
    }
  }
  async function ready() {
    const opening = review.open(task);
    await tick(); await loadPictures(); await opening;
  }
  async function choose(name = 'cup.jpg', size = 100) {
    $('#generate-image').files = [{name, size}];
    await $('#generate-image').emit('change');
  }
  return {$, review, calls, revoked, ready, choose, loadPictures};
}

test('requires all three loaded images and explicit review before sending the digest', async () => {
  const env = setup(async url => ({ok:true, json:async () => url.includes('confirm') ? {...task, phase:'generation'} : preview}));
  const {$, review} = env;
  const opening = review.open(task);
  await tick();
  $('#foreground-confirm').checked = true;
  await $('#foreground-confirm').emit('change');
  assert.equal($('#generate-submit').disabled, true);
  await env.loadPictures(); await opening;
  assert.equal($('#foreground-confirm').disabled, false);
  $('#foreground-confirm').checked = false;
  await $('#foreground-confirm').emit('change');
  assert.equal($('#generate-submit').disabled, true);
  $('#foreground-confirm').checked = true;
  await $('#foreground-confirm').emit('change');
  assert.equal($('#generate-submit').disabled, false);
  await $('#generate-submit').click();
  const confirmation = env.calls.find(call => call.url.includes('confirm'));
  assert.deepEqual(JSON.parse(confirmation.options.body), {preview_sha256:SHA, confirmed:true});
  assert.equal($('#generate-submit').disabled, true);
  const callCount = env.calls.length;
  review.observe(task); // A response from polling before submission is now stale.
  await tick();
  assert.equal(env.calls.length, callCount);
});

test('choosing a new file invalidates confirmation and ignores old polling results', async () => {
  const env = setup();
  await env.ready();
  env.$('#foreground-confirm').checked = true;
  await env.$('#foreground-confirm').emit('change');
  await env.choose('another.jpg');
  assert.equal(env.$('#generate-submit').disabled, true);
  assert.equal(env.$('#foreground-confirm').checked, false);
  const count = env.calls.length;
  env.review.observe(task);
  await tick();
  assert.equal(env.calls.length, count);
  assert.equal(env.$('#review-foreground').hidden, true);
});

test('a late preview response cannot populate a newer selection', async () => {
  let answer;
  const env = setup(() => new Promise(resolve => { answer = resolve; }));
  const opening = env.review.open(task);
  await tick();
  await env.choose();
  answer({ok:true, json:async () => preview});
  await opening;
  assert.equal(env.$('#generate-submit').disabled, true);
  assert.equal(env.$('#review-foreground').src, undefined);
  assert.equal(env.$('#foreground-context').textContent, 'cup.jpg');
});

test('a broken image cannot be confirmed and manual reinspection can recover', async () => {
  const env = setup();
  const opening = env.review.open(task);
  await tick();
  await env.$('#review-foreground').emit('error');
  await opening;
  assert.equal(env.$('#generate-submit').disabled, true);
  assert.equal(env.$('#foreground-confirm').disabled, true);
  assert.match(env.$('#generate-message').textContent, /加载失败/);
  await env.ready();
  assert.equal(env.$('#foreground-confirm').disabled, false);
});

test('changing any connection option invalidates a preview and late defaults cannot replace it', async () => {
  const env = setup();
  for (const field of ['host', 'project', 'time', 'shape']) {
    await env.ready();
    await env.$('#generate-' + field).emit('input');
    assert.equal(env.$('#generate-submit').disabled, true, field);
    assert.equal(env.$('#foreground-confirm').disabled, true, field);
  }
  await env.ready();
  env.review.configure({host:'wrong', project:'/wrong', time_limit:'01:00:00', download_shape:true});
  assert.equal(env.$('#generate-host').value, 'school');
  assert.equal(env.$('#generate-project').value, '/project');
  assert.equal(env.$('#generate-shape').checked, false);
});

test('invalid images remain blocked when settings change; preprocessing never sends confirmation', async () => {
  const env = setup(async () => ({ok:true, json:async () => ({...task, phase:'preview'})}));
  await env.choose('cup.heic');
  assert.equal(env.$('#generate-prepare').disabled, true);
  await env.$('#generate-host').emit('input');
  assert.equal(env.$('#generate-prepare').disabled, true);
  await env.choose();
  await env.$('#generate-prepare').click();
  assert.equal(env.calls.length, 1);
  assert.ok(env.calls[0].url.startsWith('/api/generate?'));
  assert.equal(env.calls[0].options.body.name, 'cup.jpg');
  assert.equal(env.$('#generate-submit').disabled, true);
});

test('an idempotent confirmation with an unknown submission result does not claim success', async () => {
  const error = '提交结果未知，请核对服务器队列，不要重复提交。';
  const env = setup(async url => ({ok:true, json:async () => url.includes('confirm')
    ? {...task, phase:'generation', state:'提交结果未知', error} : preview}));
  await env.ready();
  env.$('#foreground-confirm').checked = true;
  await env.$('#foreground-confirm').emit('change');
  await env.$('#generate-submit').click();
  assert.equal(env.$('#generate-message').textContent, error);
  assert.equal(env.$('#generate-submit').disabled, true);
  assert.doesNotMatch(env.$('#generate-message').textContent, /已确认这份前景并提交/);
});
