/* 每个窗口独立持有 Babylon 场景；生成流程只需提供统一的 GLB 与清单接口。 */
(() => {
  const $ = s => document.querySelector(s);
  const host = $('#viewers'), template = $('#panel-template'), notice = $('#notice');
  const dataset = $('#dataset'), object = $('#object'), seed = $('#seed'), kind = $('#kind');
  const presetBar = $('#preset-bar'), toggle = $('#preset-toggle');
  const inputVariant = $('#input-variant'), inputImage = $('#input-image'), inputMessage = $('#input-message');
  const presetMessage = $('#preset-message');
  const panels = [];
  let catalog = [];
  let refreshSequence = 0;

  function option(value, label) {
    const el = document.createElement('option'); el.value = String(value); el.textContent = label; return el;
  }
  function selectedDataset() { return catalog.find(d => d.id === dataset.value); }
  function presetUnavailable(message) {
    notice.textContent = message;
    presetMessage.textContent = message;
    presetMessage.hidden = false;
    inputImage.hidden = true;
    inputMessage.hidden = false;
    inputMessage.textContent = '没有可显示的输入图片';
    [dataset, object, seed, kind, inputVariant, $('#load-preset')].forEach(el => { el.disabled = true; });
  }
  function variantLabel(entry) {
    const match = /^hunyuan2_steps(\d+)$/.exec(entry.label || entry.id);
    return match ? `${match[1]} 步` : (entry.label || entry.id);
  }
  function values(select, items, previous) {
    select.replaceChildren(...items.map(item => option(item.id, item.label)));
    if (!items.length) select.append(option('', '暂无可用选项'));
    select.disabled = items.length === 0;
    if (items.some(item => String(item.id) === String(previous))) select.value = previous;
  }
  function updateObjects() {
    const data = selectedDataset(); if (!data) return;
    const actual = (data.objects || []).filter(o => o.reference || (data.runs || []).some(r => r.object === o.id));
    values(object, actual, object.value);
    updateSeeds();
  }
  function objectRuns() {
    return (selectedDataset()?.runs || []).filter(r => r.object === object.value);
  }
  function updateSeeds() {
    const seeds = [...new Set(objectRuns().map(r => String(r.seed)).filter(Boolean))].sort((a,b) => a.localeCompare(b, undefined, {numeric:true}));
    values(seed, seeds.map(s => ({id:s,label:s === 'None' ? '无随机种子' : s})), seed.value);
    updateKinds();
  }
  function updateKinds() {
    const data = selectedDataset(); if (!data) return;
    const runs = objectRuns().filter(r => String(r.seed) === seed.value);
    const availableKinds = new Set(runs.flatMap(r => r.kinds || []));
    values(kind, (data.kinds || []).filter(k => availableKinds.has(k.id)), kind.value);
    const variants = new Set(runs.map(r => String(r.variant)));
    values(inputVariant, (data.variants || []).filter(v => variants.has(String(v.id))).map(v => ({...v,label:variantLabel(v)})), inputVariant.value);
    updateVariants();
    updateInput();
  }
  function updateInput() {
    const data = selectedDataset();
    if (!data || !object.value || !seed.value || !inputVariant.value) {
      inputImage.hidden = true; inputMessage.hidden = false; inputMessage.textContent = '没有可用的输入图片'; return;
    }
    inputImage.hidden = true; inputMessage.hidden = false; inputMessage.textContent = '正在读取输入图片';
    const params = new URLSearchParams({dataset:data.id, object:object.value, variant:inputVariant.value, seed:seed.value});
    inputImage.src = `/api/input?${params}`;
  }
  inputImage.addEventListener('load', () => { inputImage.hidden = false; inputMessage.hidden = true; });
  inputImage.addEventListener('error', () => { inputImage.hidden = true; inputMessage.hidden = false; inputMessage.textContent = '当前方案的输入图片缺失'; });
  function updateVariants() {
    const data = selectedDataset(); if (!data) return;
    const current = data.objects.find(item => item.id === object.value);
    // 每个候选都标出实际文件是否存在，缺失项仍可加载以查看原因。
    const variants = [{id:'__reference__', label:`参考模型${current?.reference ? '' : '（缺失）'}`}];
    const objectVariants = new Set(objectRuns().map(r => String(r.variant)));
    for (const entry of (data.variants || []).filter(v => objectVariants.has(String(v.id)))) {
      const run = (data.runs || []).find(r => r.object === object.value && String(r.variant) === String(entry.id) && String(r.seed) === seed.value);
      const available = run && (run.kinds || []).includes(kind.value);
      const count = new Set((data.runs || []).filter(r => r.object === object.value && String(r.variant) === String(entry.id) && (r.kinds || []).includes(kind.value)).map(r => String(r.seed))).size;
      variants.push({id:entry.id, label:`${variantLabel(entry)} · ${count} 个种子${available ? '' : '（当前种子缺失）'}`});
    }
    panels.forEach(panel => { values(panel.variant, variants, panel.variant.value); panel.preset.hidden = presetBar.hidden; });
    $('#load-preset').disabled = !object.value || (!current?.reference && !objectRuns().some(r => String(r.seed) === seed.value && (r.kinds || []).includes(kind.value)));
  }
  function makeScene(engine, canvas) {
    const scene = new BABYLON.Scene(engine);
    scene.clearColor = new BABYLON.Color4(.91,.94,.95,1);
    const camera = new BABYLON.ArcRotateCamera('camera', -Math.PI / 2, Math.PI / 2.5, 5, BABYLON.Vector3.Zero(), scene);
    new BABYLON.HemisphericLight('ambient', new BABYLON.Vector3(0,1,0), scene).intensity = .85;
    new BABYLON.DirectionalLight('key', new BABYLON.Vector3(-1,-2,-1), scene).intensity = 1.2;
    return {scene, camera};
  }
  function reset(panel) {
    if (!panel.camera || !panel.initial) return;
    Object.assign(panel.camera, {alpha:panel.initial.alpha, beta:panel.initial.beta, radius:panel.initial.radius});
    panel.camera.setTarget(panel.initial.target.clone());
  }
  function setOverlay(panel, text, type) {
    panel.overlay.className = `overlay ${type || ''}`;
    panel.overlay.textContent = text;
  }
  async function loadBlob(panel, source, title, subtitle) {
    const run = ++panel.run;
    setOverlay(panel, '正在加载模型…', 'loading');
    const {scene, camera} = makeScene(panel.engine, panel.canvas);
    let url;
    try {
      const blob = await source();
      if (run !== panel.run || panel.removed) { scene.dispose(); return; }
      url = URL.createObjectURL(blob);
      // GLB 地址可能没有扩展名，明确指定 glTF 插件。
      const result = await BABYLON.SceneLoader.ImportMeshAsync('', '', url, scene, undefined, '.glb');
      if (run !== panel.run || panel.removed) { scene.dispose(); return; }
      const meshes = result.meshes.filter(m => m.getTotalVertices && m.getTotalVertices() > 0);
      if (!meshes.length) throw new Error('文件没有可显示的网格');
      let min = new BABYLON.Vector3(Infinity,Infinity,Infinity), max = new BABYLON.Vector3(-Infinity,-Infinity,-Infinity);
      for (const mesh of meshes) {
        mesh.computeWorldMatrix(true); const box = mesh.getBoundingInfo().boundingBox;
        min = BABYLON.Vector3.Minimize(min, box.minimumWorld); max = BABYLON.Vector3.Maximize(max, box.maximumWorld);
      }
      const center = min.add(max).scale(.5), span = max.subtract(min), radius = Math.max(span.x,span.y,span.z) * 2.2 || 2;
      camera.setTarget(center); camera.radius = radius; camera.minZ = Math.max(radius / 10000,.0001); camera.maxZ = Math.max(radius * 100,100);
      camera.lowerRadiusLimit = radius * .08; camera.upperRadiusLimit = radius * 20; camera.wheelPrecision = 100 / radius;
      if (panel.scene) panel.scene.dispose();
      panel.scene = scene; panel.camera = camera; camera.attachControl(panel.canvas,true);
      panel.initial = {alpha:camera.alpha,beta:camera.beta,radius,target:center.clone()};
      panel.title.textContent = title; panel.subtitle.textContent = subtitle;
      panel.title.title = title; panel.subtitle.title = subtitle;
      panel.overlay.className = 'overlay hidden'; panel.engine.resize();
    } catch (error) {
      scene.dispose();
      if (run !== panel.run || panel.removed) return;
      if (panel.scene) { panel.scene.dispose(); panel.scene = null; panel.camera = null; }
      panel.title.textContent = title; panel.subtitle.textContent = subtitle;
      setOverlay(panel, `加载失败：${error.message}。可点击右上角＋重新选择文件。`, 'error');
      console.error(error);
    } finally { if (url) URL.revokeObjectURL(url); }
  }
  function loadFile(panel, file) {
    if (!file) return;
    if (!file.name.toLowerCase().endsWith('.glb')) { setOverlay(panel,'请选择 .glb 格式文件。点击右上角＋重试。','error'); return; }
    loadBlob(panel, async () => file, file.name, '本地文件');
  }
  function loadPreset(panel) {
    const data = selectedDataset(); if (!data || !object.value) return;
    const ref = panel.variant.value === '__reference__';
    const params = new URLSearchParams({dataset:data.id,object:object.value,variant:ref ? '' : panel.variant.value,seed:seed.value,kind:ref ? 'reference' : kind.value});
    const title = panel.variant.selectedOptions[0]?.textContent || '模型';
    loadBlob(panel, async () => {
      const res = await fetch(`/api/model?${params}`);
      if (!res.ok) throw new Error(res.status === 404 ? '该对象对应的文件未找到，请检查参考或实验结果目录' : `服务返回 ${res.status}`);
      return res.blob();
    }, title, `${data.label} · ${object.value} · ${ref ? '参考模型' : `种子 ${seed.value} · ${kind.selectedOptions[0]?.textContent}`}`);
  }
  function remove(panel) {
    panel.removed = true; panel.run++;
    if (panel.scene) panel.scene.dispose();
    panel.engine.dispose(); panel.card.remove();
    const index = panels.indexOf(panel); if (index >= 0) panels.splice(index,1);
    panels.forEach(p => p.engine.resize());
  }
  function addPanel() {
    const card = template.content.firstElementChild.cloneNode(true); host.append(card);
    const canvas = card.querySelector('canvas');
    const engine = new BABYLON.Engine(canvas,true,{stencil:true});
    const panel = {card,canvas,engine,overlay:card.querySelector('.overlay'),title:card.querySelector('strong'),subtitle:card.querySelector('small'),variant:card.querySelector('.variant'),preset:card.querySelector('.panel-presets'),scene:null,camera:null,run:0,removed:false};
    panels.push(panel); engine.runRenderLoop(() => { if (panel.scene) panel.scene.render(); });
    const file = card.querySelector('.file');
    card.querySelector('.choose').addEventListener('click',()=>file.click());
    card.querySelector('.replace').addEventListener('click',()=>file.click());
    card.querySelector('.panel-reset').addEventListener('click',()=>reset(panel));
    card.querySelector('.remove').addEventListener('click',()=>remove(panel));
    card.querySelector('.load-one').addEventListener('click',()=>loadPreset(panel));
    file.addEventListener('change',()=>{ loadFile(panel,file.files[0]); file.value=''; });
    const viewport=card.querySelector('.viewport');
    viewport.addEventListener('dragover',event=>{event.preventDefault();viewport.classList.add('dragging');});
    viewport.addEventListener('dragleave',()=>viewport.classList.remove('dragging'));
    viewport.addEventListener('drop',event=>{event.preventDefault();viewport.classList.remove('dragging');loadFile(panel,event.dataTransfer.files[0]);});
    updateVariants(); panels.forEach(p => p.engine.resize()); return panel;
  }
  $('#add-panel').addEventListener('click',addPanel);
  $('#reset').addEventListener('click',()=>panels.forEach(reset));
  toggle.addEventListener('click',()=>{presetBar.hidden=!presetBar.hidden;toggle.setAttribute('aria-expanded',String(!presetBar.hidden));updateVariants();});
  dataset.addEventListener('change',updateObjects);
  object.addEventListener('change',updateSeeds);
  seed.addEventListener('change',updateKinds);
  kind.addEventListener('change',updateVariants);
  inputVariant.addEventListener('change',updateInput);
  $('#load-preset').addEventListener('click',()=>{
    const data=selectedDataset(); if(!data)return;
    // 批量操作由用户主动触发，单个窗口仍可分别选择本地文件或其他方案。
    while(panels.length) remove(panels[0]);
    const available = new Set(objectRuns().filter(r => String(r.seed) === seed.value && (r.kinds || []).includes(kind.value)).map(r => String(r.variant)));
    const variants = (data.variants || []).filter(v => available.has(String(v.id))).map(v => v.id);
    for(const value of ['__reference__',...variants]){
      const panel=addPanel(); panel.variant.value=value; loadPreset(panel);
    }
  });
  window.addEventListener('resize',()=>panels.forEach(p=>p.engine.resize()));
  async function refreshCatalog() {
    const sequence = ++refreshSequence;
    const refresh = $('#refresh-catalog'); refresh.disabled = true;
    try {
      const response=await fetch('/api/catalog', {cache:'no-store'}); if(!response.ok) throw new Error(`HTTP ${response.status}`);
      const body=await response.json(); if(sequence !== refreshSequence) return;
      if(!Array.isArray(body.datasets)) {
        presetUnavailable('预设服务版本不匹配。请关闭旧的启动窗口，再从项目中的 gso-viewer/start.bat 重新启动。');
        return;
      }
      catalog=body.datasets;
      if(!catalog.length) { presetUnavailable('没有找到实验预设。请检查实验数据目录，或先手动打开本地 GLB。'); return; }
      const warnings = Array.isArray(body.warnings) ? body.warnings : [];
      presetMessage.hidden = !warnings.length;
      presetMessage.textContent = warnings.length ? `部分实验清单无法读取：${warnings.join('；')}` : '';
      notice.textContent = warnings.length ? '实验列表已更新，部分清单无法读取。' : '实验列表已更新。';
      values(dataset,catalog,dataset.value); updateObjects();
    } catch(error) {
      if(sequence === refreshSequence) { presetUnavailable('无法读取实验预设，请检查启动窗口是否仍在运行，然后点击刷新实验列表。'); console.error(error); }
    } finally { if(sequence === refreshSequence) refresh.disabled = false; }
  }
  $('#refresh-catalog').addEventListener('click',refreshCatalog);
  async function initialize() {
    if(!window.BABYLON || !BABYLON.SceneLoader) throw new Error('Babylon.js 加载失败，请检查本地依赖文件。');
    for(let i=0;i<3;i++) addPanel();
    await refreshCatalog();
  }
  $('#single-mode').onclick = () => { $('#single-form').hidden = !$('#single-form').hidden; $('#batch-form').hidden = true; };
  $('#batch-mode').onclick = () => { $('#batch-form').hidden = !$('#batch-form').hidden; $('#single-form').hidden = true; };
  $('#batch-submit').onclick = async () => {
    const message = $('#batch-message');
    $('#batch-submit').disabled = true;
    try {
      const config = $('#batch-config').files[0];
      if (!config) throw new Error('请选择配置文件');
      const body = JSON.parse(await config.text());
      const spec = body.experiment;
      const files = [...$('#batch-images').files];
      if (spec.dataset && files.length) throw new Error('本配置使用服务器图片，请清空手动选择的图片。');
      if (!spec.dataset && (files.length !== spec.images.length || new Set(files.map(f=>f.name)).size !== files.length || files.some(f=>!spec.images.includes(f.name)))) throw new Error('图片文件名必须与配置 images 一致');
      if (files.reduce((n,f)=>n+f.size,0) > 70*1024*1024) throw new Error('所选图片合计请小于 70 MiB');
      const generations = spec.images.length * spec.seeds.length;
      const count = generations * spec.variants.length;
      if (!confirm(`实验 ${spec.name}：${spec.images.length} 张图片 × ${spec.seeds.length} 个种子 × ${spec.variants.length} 个方案 = ${count} 个输出（${spec.export_plugin === 'shared_lod' ? generations : count} 次推理）。提交 GPU 作业？`)) return;
      body.images = {};
      for (const file of files) {
        const encoded = await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result.split(',')[1]);reader.onerror=reject;reader.readAsDataURL(file);});
        body.images[file.name] = encoded;
      }
      const response = await fetch('/api/generate-batch',{method:'POST',headers:{'X-Asset3D':'workbench','Content-Type':'application/json'},body:JSON.stringify(body)});
      const result = await response.json();
      if (!response.ok) throw new Error(result.error);
      message.textContent = `已提交 ${count} 个输出，完成后在实验预设查看。`;
    } catch(error) { message.textContent=error.message; }
    finally { $('#batch-submit').disabled=false; }
  };
  const displayedJobs = new Set();
  async function displayGenerated(id) {
    const panel = addPanel();
    await loadBlob(panel, async () => {
      const response = await fetch('/api/generated/' + id);
      if (!response.ok) throw new Error('下载模型失败');
      return response.blob();
    }, 'TRELLIS.2 生成结果', id.slice(0, 8));
  }
  $('#generate-submit').addEventListener('click', async () => {
    const file = $('#generate-image').files[0];
    const message = $('#generate-message');
    if (!file) { message.textContent = '请先选择照片'; return; }
    if (file.size > 20 * 1024 * 1024) { message.textContent = '图片请小于 20 MiB'; return; }
    $('#generate-submit').disabled = true;
    try {
      const options = {host:$('#generate-host').value.trim(), project:$('#generate-project').value.trim(),
        time_limit:$('#generate-time').value.trim(), download_shape:String($('#generate-shape').checked)};
      const response = await fetch('/api/generate?' + new URLSearchParams(options), {method:'POST', headers:{'X-Asset3D':'workbench'}, body:file});
      const result = await response.json();
      if (!response.ok) throw new Error(result.error);
      message.textContent = '任务已创建，可在下方查看进度。';
    } catch (error) { message.textContent = error.message; }
    finally { $('#generate-submit').disabled = false; }
  });
  async function pollGeneration() {
    try {
      const response = await fetch('/api/generation-jobs', {cache:'no-store'});
      if (!response.ok) throw new Error('任务服务不可用');
      const jobs = await response.json();
      const target = $('#generation-jobs'); target.replaceChildren();
      for (const job of jobs) {
        const row = document.createElement('div');
        const text = document.createElement('span');
        text.textContent = (job.name || job.id.slice(0,8)) + ' · ' + job.state + (job.job_id ? ' · 作业 ' + job.job_id : '') + (job.error ? ' · ' + job.error : '');
        if (Number.isInteger(job.downloaded_models)) text.textContent += ' · 已收到 ' + job.downloaded_models + ' 个模型';
        if (job.checked_at) text.textContent += ' · 最近同步 ' + new Date(job.checked_at*1000).toLocaleTimeString();
        row.append(text);
        if (job.state === '完成') {
          const button = document.createElement('button'); button.textContent = job.mode === 'batch' ? '刷新实验预设' : '查看模型';
          button.onclick = () => job.mode === 'batch' ? refreshCatalog() : displayGenerated(job.id); row.append(button);
          if (job.failures?.length) text.textContent += ` · ${job.failures.length} 项失败，详见 failures.json`;
          if (!displayedJobs.has(job.id)) { displayedJobs.add(job.id); if(job.mode === 'batch') void refreshCatalog(); else if(!job.failures?.length) void displayGenerated(job.id).catch(console.error); }
        } else if (job.error && job.job_id) {
          const button = document.createElement('button'); button.textContent = '重新查询 / 下载';
          button.onclick = () => fetch('/api/generation-retry/' + job.id, {method:'POST',headers:{'X-Asset3D':'workbench'}});
          row.append(button);
        }
        target.append(row);
      }
    } catch(error) { $('#generation-jobs').textContent = '任务列表暂时不可用，正在重试：' + error.message; }
    finally { setTimeout(pollGeneration, 3000); }
  }
  fetch('/api/generation-settings').then(r => { if (!r.ok) throw new Error('无法读取生成设置'); return r.json(); }).then(c => {
    $('#generate-host').value = c.host;
    $('#generate-project').value = c.project;
    $('#generate-time').value = c.time_limit;
    $('#generate-shape').checked = c.download_shape;
  }).catch(error => { $('#generate-message').textContent = error.message; });
  pollGeneration();
  initialize().catch(error=>{notice.textContent=error.message;console.error(error);});
})();
