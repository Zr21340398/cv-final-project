/* 三个视窗彼此独立：后台只负责提供清单和 GLB，可接入其他生成流程。 */
(() => {
  const object = document.querySelector('#object');
  const seed = document.querySelector('#seed');
  const kind = document.querySelector('#kind');
  const notice = document.querySelector('#notice');
  const viewers = document.querySelector('#viewers');
  const inputImage = document.querySelector('#input-image');
  const inputError = document.querySelector('#input-error');
  const panels = [];
  let generation = 0;

  function option(value, text) {
    const item = document.createElement('option');
    item.value = String(value); item.textContent = text;
    return item;
  }

  function makePanel(step) {
    const card = document.createElement('article');
    card.className = 'card';
    card.innerHTML = `<div class="card-head"><strong></strong><span>形状生成步数</span></div><div class="viewport"><canvas tabindex="0"></canvas><div class="overlay">等待加载</div></div>`;
    card.querySelector('strong').textContent = `${step} 步`;
    viewers.append(card);
    const canvas = card.querySelector('canvas');
    const overlay = card.querySelector('.overlay');
    const engine = new BABYLON.Engine(canvas, true, {preserveDrawingBuffer: false, stencil: true});
    const panel = {step, canvas, overlay, engine, scene: null, camera: null, initial: null};
    engine.runRenderLoop(() => { if (panel.scene) panel.scene.render(); });
    panels.push(panel);
    return panel;
  }

  async function load(panel, selection, run) {
    panel.overlay.textContent = '正在加载模型…';
    panel.overlay.classList.remove('hidden');
    const scene = new BABYLON.Scene(panel.engine);
    scene.clearColor = new BABYLON.Color4(0.91, 0.94, 0.95, 1);
    const camera = new BABYLON.ArcRotateCamera('camera', -Math.PI / 2, Math.PI / 2.5, 5, BABYLON.Vector3.Zero(), scene);
    camera.wheelPrecision = 50;
    new BABYLON.HemisphericLight('ambient', new BABYLON.Vector3(0, 1, 0), scene).intensity = 0.85;
    const light = new BABYLON.DirectionalLight('key', new BABYLON.Vector3(-1, -2, -1), scene);
    light.intensity = 1.2;
    const params = new URLSearchParams({...selection, step: String(panel.step)});
    try {
      // 显式指定 .glb：服务地址的查询参数没有文件扩展名。
      const result = await BABYLON.SceneLoader.ImportMeshAsync('', '', `/api/model?${params}`, scene, undefined, '.glb');
      if (run !== generation) { scene.dispose(); return; }
      const meshes = result.meshes.filter(m => m.getTotalVertices && m.getTotalVertices() > 0);
      if (!meshes.length) throw new Error('文件中没有可显示的网格');
      let min = new BABYLON.Vector3(Infinity, Infinity, Infinity);
      let max = new BABYLON.Vector3(-Infinity, -Infinity, -Infinity);
      for (const mesh of meshes) {
        mesh.computeWorldMatrix(true);
        const bounds = mesh.getBoundingInfo().boundingBox;
        min = BABYLON.Vector3.Minimize(min, bounds.minimumWorld);
        max = BABYLON.Vector3.Maximize(max, bounds.maximumWorld);
      }
      const center = min.add(max).scale(0.5);
      const span = max.subtract(min);
      const radius = Math.max(span.x, span.y, span.z) * 2.2 || 2;
      camera.setTarget(center); camera.radius = radius;
      camera.minZ = Math.max(radius / 10000, 0.0001);
      camera.maxZ = Math.max(radius * 100, 100);
      camera.lowerRadiusLimit = radius * 0.08;
      camera.upperRadiusLimit = radius * 20;
      camera.wheelPrecision = 100 / radius;
      if (panel.scene) panel.scene.dispose();
      panel.scene = scene; panel.camera = camera;
      camera.attachControl(panel.canvas, true);
      panel.initial = {alpha: camera.alpha, beta: camera.beta, radius, target: center.clone()};
      panel.overlay.classList.add('hidden');
      panel.engine.resize();
    } catch (error) {
      scene.dispose();
      if (run !== generation) return;
      if (panel.scene) { panel.scene.dispose(); panel.scene = null; }
      panel.camera = null;
      panel.overlay.textContent = '加载失败：请检查对应 GLB 是否存在，或查看浏览器控制台。';
      console.error(`${panel.step} 步模型加载失败`, error);
    }
  }

  function refresh() {
    if (!object.value || !seed.value) return;
    const run = ++generation;
    const selection = {object: object.value, seed: seed.value, kind: kind.value};
    notice.textContent = `${object.selectedOptions[0].textContent} · 种子 ${selection.seed} · ${kind.selectedOptions[0].textContent}`;
    inputImage.hidden = true; inputError.hidden = false; inputError.textContent = '加载中';
    const inputParams = new URLSearchParams({object: selection.object, step: '50', seed: selection.seed});
    inputImage.src = `/api/input?${inputParams}`;
    panels.forEach(panel => load(panel, selection, run));
  }

  inputImage.addEventListener('load', () => { inputImage.hidden = false; inputError.hidden = true; });
  inputImage.addEventListener('error', () => { inputImage.hidden = true; inputError.hidden = false; inputError.textContent = '输入图缺失'; });

  document.querySelector('#reset').addEventListener('click', () => {
    for (const panel of panels) {
      if (!panel.camera || !panel.initial) continue;
      Object.assign(panel.camera, {alpha: panel.initial.alpha, beta: panel.initial.beta, radius: panel.initial.radius});
      panel.camera.setTarget(panel.initial.target.clone());
    }
  });
  [object, seed, kind].forEach(input => input.addEventListener('change', refresh));
  window.addEventListener('resize', () => panels.forEach(p => p.engine.resize()));

  async function initialize() {
    if (!window.BABYLON || !BABYLON.SceneLoader) throw new Error('Babylon.js 加载失败，请检查本地依赖文件。');
    const response = await fetch('/api/catalog');
    if (!response.ok) throw new Error(`读取模型清单失败（${response.status}）`);
    const catalog = await response.json();
    if (!catalog.objects?.length || !catalog.steps?.length || !catalog.seeds?.length) throw new Error('没有找到可浏览的实验模型，请检查结果目录。');
    catalog.objects.forEach(item => object.append(option(item.id, `${item.id} · ${item.label || item.id}`)));
    catalog.seeds.forEach(value => seed.append(option(value, String(value))));
    catalog.steps.forEach(makePanel);
    object.disabled = false; seed.disabled = false;
    refresh();
  }
  initialize().catch(error => { notice.textContent = error.message; console.error(error); });
})();
