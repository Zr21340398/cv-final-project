const {test} = require('node:test');
const assert = require('node:assert/strict');
const {photoPoint, selectionBox, createTargetSelection} = require('../gso-viewer/frontend/target-selection.js');

class Element {
  constructor() { this.events = {}; this.style = {}; this.disabled = false; this.rect = {left:100,top:50,width:300,height:400}; }
  addEventListener(name, fn) { this.events[name] = fn; }
  emit(name, values = {}) { this.events[name]?.({pointerId:1,button:0,preventDefault() {},...values}); }
  setAttribute(name, value) { this[name] = value; }
  setPointerCapture() {}
  getBoundingClientRect() { return this.rect; }
  getContext() { return new Proxy({}, {get:() => () => {}}); }
}
function setup() {
  const elements = new Map(), images = [], revoked = [];
  let changes = 0;
  const $ = name => {
    if (!elements.has(name)) elements.set(name, new Element());
    return elements.get(name);
  };
  class Photo { constructor() { images.push(this); } }
  const editor = createTargetSelection({document:{querySelector:$},
    URL:{createObjectURL:file => 'blob:' + file.name, revokeObjectURL:url => revoked.push(url)},
    ImageCtor:Photo, onChange:() => changes++});
  function load(width = 3024, height = 4032) {
    Object.assign(images.at(-1), {naturalWidth:width,naturalHeight:height}); images.at(-1).onload();
  }
  function box(start = [130,90], end = [340,410]) {
    $('#target-canvas').emit('pointerdown', {clientX:start[0],clientY:start[1]});
    $('#target-canvas').emit('pointerup', {clientX:end[0],clientY:end[1]});
  }
  editor.setFile({name:'cup.jpg'}); load();
  return {$, editor, load, box, images, revoked, changes:() => changes};
}

test('displayed photo coordinates remain normalized after resizing and reverse drags', () => {
  assert.deepEqual(photoPoint(250,250,{left:100,top:50,width:300,height:400}), [.5,.5]);
  assert.deepEqual(photoPoint(400,450,{left:100,top:50,width:600,height:800}), [.5,.5]);
  assert.deepEqual(photoPoint(-50,999,{left:100,top:50,width:300,height:400}), [0,1]);
  assert.equal(photoPoint(1,1,{left:0,top:0,width:0,height:0}), null);
  assert.deepEqual(selectionBox([.8,.9],[.1,.2]), [.1,.2,.8,.9]);
  assert.equal(selectionBox([.1,.1],[.11,.9]), null);
});

test('oriented image dimensions are used and invalid drags never silently fall back to automatic mode', () => {
  const env = setup(), canvas = env.$('#target-canvas');
  assert.equal(canvas.width / canvas.height, .75);
  assert.equal(canvas.style.width, '390px');
  assert.equal(env.editor.value(), null);
  canvas.emit('pointerdown', {clientX:150,clientY:150});
  assert.equal(env.editor.canPrepare(), false);
  assert.equal(env.changes(), 1);
  canvas.emit('pointerup', {clientX:151,clientY:151});
  assert.equal(env.editor.canPrepare(), false);
  assert.match(env.$('#target-status').textContent, /太小/);
  env.$('#target-clear').emit('click');
  assert.equal(env.editor.canPrepare(), true);
  assert.equal(env.editor.value(), null);
});

test('box and keep/exclude points serialize with limits, undo and reset', () => {
  const env = setup(); env.box();
  env.$('#target-include').emit('click');
  env.$('#target-canvas').emit('pointerdown', {clientX:250,clientY:210});
  env.$('#target-exclude').emit('click');
  for (let i = 0; i < 17; i++) env.$('#target-canvas').emit('pointerdown', {clientX:370,clientY:430});
  assert.deepEqual(env.editor.value().box, [.1,.1,.8,.9]);
  assert.deepEqual(env.editor.value().include_points, [[.5,.4]]);
  assert.equal(env.editor.value().exclude_points.length, 16);
  assert.match(env.$('#target-status').textContent, /最多 16/);
  env.$('#target-undo').emit('click');
  assert.equal(env.editor.value().exclude_points.length, 15);
  env.$('#target-box').emit('click'); env.box([340,410],[130,90]);
  assert.equal(env.editor.value().include_points.length, 0);
  assert.equal(env.editor.value().exclude_points.length, 0);
  env.$('#target-clear').emit('click');
  assert.equal(env.editor.value(), null);
});

test('late image loads cannot restore old geometry and restored previews are not editable', () => {
  const env = setup(); const old = env.images[0]; env.box();
  env.editor.setFile({name:'new.jpg'});
  old.onload();
  assert.equal(env.$('#target-canvas').hidden, true);
  assert.equal(env.editor.value(), null);
  env.load(1200,600);
  assert.equal(env.$('#target-canvas').width / env.$('#target-canvas').height, 2);
  env.editor.setFile(null,{restored:true});
  assert.equal(env.$('#target-selection').hidden, false);
  assert.equal(env.$('#target-canvas').hidden, true);
  assert.equal(env.$('#target-box').disabled, true);
  assert.match(env.$('#target-status').textContent, /重新选择原始照片/);
  assert.equal(env.revoked.length, 2);
});

test('disabled editor cannot mutate prompts during confirmation', () => {
  const env = setup(); env.box();
  const before = env.editor.value(), changes = env.changes();
  env.editor.setDisabled(true);
  env.$('#target-canvas').emit('pointerdown', {clientX:200,clientY:200});
  env.$('#target-clear').emit('click');
  assert.deepEqual(env.editor.value(), before);
  assert.equal(env.changes(), changes);
});
