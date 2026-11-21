/* 每个窗口独立持有 Babylon 场景；生成流程只需提供统一的 GLB 与清单接口。 */
(() => {
  const $ = s => document.querySelector(s);
  const host = $('#viewers'), template = $('#panel-template'), notice = $('#notice');
  const dataset = $('#dataset'), object = $('#object'), seed = $('#seed'), kind = $('#kind');
  const presetBar = $('#preset-bar'), toggle = $('#preset-toggle');
  const inputVariant = $('#input-variant'), inputImage = $('#input-image'), inputMessage = $('#input-message');
  const presetMessage = $('#preset-message');
  const resetAll = $('#reset');
  const views = [
    {button:$('#compare-mode'), section:$('#comparison')},
    {button:$('#single-mode'), section:$('#single-form')},
    {button:$('#batch-mode'), section:$('#batch-form')},
  ];
  const panels = [];
  const generatedPanels = new Map();
  let catalog = [];
  let refreshSequence = 0;
  let nextWindow = 1;

  function showView(active) {
    const changed = active.section.hidden;
    for (const view of views) {
      view.section.hidden = view !== active;
      if (view === active) view.button.setAttribute('aria-current', 'page');
      else view.button.removeAttribute('aria-current');
    }
    $('#current-view').textContent = active.button.textContent.trim();
    if (changed) window.scrollTo(0, 0);
  }
  for (const view of views) view.button.addEventListener('click', () => showView(view));

  function showNotice(message) {
    notice.hidden = false;
    notice.textContent = message;
  }

  const viewportObserver = new ResizeObserver(entries => {
    for (const {target, contentRect} of entries) {
      const panel = panels.find(item => item.canvas.parentElement === target);
      if (contentRect.width && contentRect.height) panel?.engine?.resize();
    }
  });

  function updateWindowControls() {
    $('#window-count').textContent = `${panels.length} 个窗口`;
    $('#empty-board').hidden = panels.length !== 0;
    resetAll.disabled = !panels.some(panel => panel.camera);
  }

  function option(value, label) {
    const el = document.createElement('option'); el.value = String(value); el.textContent = label; return el;
  }
  function selectedDataset() { return catalog.find(d => d.id === dataset.value); }
  function presetUnavailable(message) {
    catalog = [];
    presetMessage.textContent = message;
    presetMessage.hidden = false;
    inputImage.removeAttribute('src');
    inputImage.hidden = true;
    inputMessage.hidden = false;
    inputMessage.textContent = '没有可显示的输入图片';
    for (const select of [dataset, object, seed, kind, inputVariant]) values(select, []);
    $('#load-preset').disabled = true;
    updateVariants();
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
      inputImage.removeAttribute('src');
      inputImage.hidden = true; inputMessage.hidden = false; inputMessage.textContent = '没有可用的输入图片'; return;
    }
    inputImage.hidden = true; inputMessage.hidden = false; inputMessage.textContent = '正在读取输入图片';
    const params = new URLSearchParams({dataset:data.id, object:object.value, variant:inputVariant.value, seed:seed.value});
    inputImage.src = `/api/input?${params}`;
  }
  inputImage.addEventListener('load', () => {
    if (!inputImage.hasAttribute('src')) return;
    inputImage.hidden = false; inputMessage.hidden = true;
  });
  inputImage.addEventListener('error', () => {
    if (!inputImage.hasAttribute('src')) return;
    inputImage.hidden = true; inputMessage.hidden = false; inputMessage.textContent = '当前方案的输入图片缺失';
  });
  function updateVariants() {
    const data = selectedDataset();
    for (const panel of panels) panel.preset.hidden = presetBar.hidden || !data || !object.value;
    if (!data) return;
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
    panels.forEach(panel => values(panel.variant, variants, panel.variant.value));
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
    panel.overlay.hidden = false;
    panel.overlay.className = `overlay ${type}`;
    panel.overlayMessage.hidden = false;
    panel.overlayMessage.textContent = text;
    panel.choose.hidden = type === 'loading';
    panel.choose.querySelector('strong').textContent = '重新选择 GLB';
    panel.canvas.tabIndex = -1;
  }
  function getEngine(panel) {
    if (panel.engine) return panel.engine;
    if (!window.BABYLON?.SceneLoader) throw new Error('3D 查看器未加载，请刷新页面后重试');
    try {
      panel.engine = new BABYLON.Engine(panel.canvas, true, {stencil:true});
    } catch {
      throw new Error('浏览器无法启用 WebGL，请检查浏览器的硬件加速设置');
    }
    panel.engine.runRenderLoop(() => {
      if (panel.scene && !views[0].section.hidden) panel.scene.render();
    });
    return panel.engine;
  }
  async function loadBlob(panel, source, title, subtitle) {
    const run = ++panel.run;
    setOverlay(panel, '正在加载模型…', 'loading');
    let scene, camera, url;
    try {
      const blob = await source();
      if (run !== panel.run || panel.removed) return;
      ({scene, camera} = makeScene(getEngine(panel), panel.canvas));
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
      panel.overlay.hidden = true;
      panel.canvas.tabIndex = 0;
      panel.resetButton.disabled = false;
      if (panel.canvas.clientWidth) panel.engine.resize();
    } catch (error) {
      scene?.dispose();
      if (run !== panel.run || panel.removed) return;
      if (panel.scene) { panel.scene.dispose(); panel.scene = null; panel.camera = null; }
      panel.title.textContent = title; panel.subtitle.textContent = subtitle;
      panel.title.title = title; panel.subtitle.title = subtitle;
      panel.resetButton.disabled = true;
      setOverlay(panel, `加载失败：${error.message}`, 'error');
      console.error(error);
    } finally {
      if (url) URL.revokeObjectURL(url);
      updateWindowControls();
    }
  }
  function loadFile(panel, file) {
    if (!file) return;
    if (!file.name.toLowerCase().endsWith('.glb')) { setOverlay(panel, '请选择 .glb 格式的文件。', 'error'); return; }
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
    viewportObserver.unobserve(panel.canvas.parentElement);
    if (generatedPanels.get(panel.generatedId)?.panel === panel) generatedPanels.delete(panel.generatedId);
    if (panel.scene) panel.scene.dispose();
    panel.engine?.dispose(); panel.card.remove();
    const index = panels.indexOf(panel); if (index >= 0) panels.splice(index,1);
    updateWindowControls();
  }
  function addPanel() {
    const card = template.content.firstElementChild.cloneNode(true);
    const canvas = card.querySelector('canvas');
    const panel = {
      card, canvas, engine:null, overlay:card.querySelector('.overlay'), overlayMessage:card.querySelector('.overlay-message'),
      choose:card.querySelector('.choose'), resetButton:card.querySelector('.panel-reset'),
      title:card.querySelector('.card-title strong'), subtitle:card.querySelector('.card-title small'),
      variant:card.querySelector('.variant'), preset:card.querySelector('.panel-presets'),
      scene:null, camera:null, run:0, removed:false,
    };
    const windowLabel = `窗口 ${String(nextWindow++).padStart(2, '0')}`;
    card.setAttribute('aria-label', windowLabel);
    panel.title.textContent = windowLabel;
    host.append(card);
    panels.push(panel);
    const file = card.querySelector('.file');
    panel.choose.addEventListener('click',()=>file.click());
    card.querySelector('.replace').addEventListener('click',()=>file.click());
    panel.resetButton.addEventListener('click',()=>reset(panel));
    card.querySelector('.remove').addEventListener('click', () => {
      remove(panel);
      $('#add-panel').focus();
    });
    card.querySelector('.load-one').addEventListener('click',()=>loadPreset(panel));
    file.addEventListener('change',()=>{ loadFile(panel,file.files[0]); file.value=''; });
    const viewport=card.querySelector('.viewport');
    viewport.addEventListener('dragover',event=>{event.preventDefault();viewport.classList.add('dragging');});
    viewport.addEventListener('dragleave', event => {
      if (!viewport.contains(event.relatedTarget)) viewport.classList.remove('dragging');
    });
    viewport.addEventListener('drop',event=>{event.preventDefault();viewport.classList.remove('dragging');loadFile(panel,event.dataTransfer.files[0]);});
    viewportObserver.observe(viewport);
    updateVariants();
    updateWindowControls();
    return panel;
  }
  for (const button of [$('#add-panel'), $('#add-first-panel')]) {
    button.addEventListener('click', () => addPanel().choose.focus());
  }
  resetAll.addEventListener('click',()=>panels.forEach(reset));
  function showPresets(visible) {
    presetBar.hidden = !visible;
    toggle.setAttribute('aria-expanded', String(visible));
    updateVariants();
  }
  toggle.addEventListener('click', () => showPresets(presetBar.hidden));
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
  async function refreshCatalog(announce = false) {
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
      if (announce) showNotice(warnings.length ? '实验列表已更新，部分清单无法读取。' : '实验列表已更新。');
      values(dataset,catalog,dataset.value); updateObjects();
    } catch(error) {
      if(sequence === refreshSequence) { presetUnavailable('无法读取实验预设，请检查启动窗口是否仍在运行，然后点击刷新实验列表。'); console.error(error); }
    } finally { if(sequence === refreshSequence) refresh.disabled = false; }
  }
  $('#refresh-catalog').addEventListener('click', () => refreshCatalog(true));
  async function initialize() {
    for(let i=0;i<3;i++) addPanel();
    await refreshCatalog();
  }
  $('#batch-submit').onclick = async () => {
    const message = $('#batch-message');
    $('#batch-submit').disabled = true;
    try {
      const config = $('#batch-config').files[0];
      if (!config) throw new Error('请选择配置文件');
      const body = JSON.parse(await config.text());
      const spec = body.experiment;
      if (!spec || !Array.isArray(spec.images) || !Array.isArray(spec.seeds) || !Array.isArray(spec.variants)) {
        throw new Error('实验配置需包含 images、seeds 和 variants 列表。');
      }
      const files = [...$('#batch-images').files];
      if (spec.dataset && files.length) throw new Error('本配置使用服务器图片，请清空手动选择的图片。');
      if (!spec.dataset && (files.length !== spec.images.length || new Set(files.map(f=>f.name)).size !== files.length || files.some(f=>!spec.images.includes(f.name)))) throw new Error('图片文件名必须与配置 images 一致');
      if (files.reduce((n,f)=>n+f.size,0) > 70*1024*1024) throw new Error('所选图片合计请小于 70 MiB');
      const generations = spec.images.length * spec.seeds.length;
      const count = generations * spec.variants.length;
      if (!confirm(`实验 ${spec.name}：${spec.images.length} 张图片 × ${spec.seeds.length} 个种子 × ${spec.variants.length} 个方案 = ${count} 个输出（${spec.export_plugin === 'shared_lod' ? generations : count} 次推理）。提交 GPU 作业？`)) return;
      body.images = {};
      message.hidden = false;
      message.textContent = '正在上传实验文件…';
      for (const file of files) {
        const encoded = await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result.split(',')[1]);reader.onerror=reject;reader.readAsDataURL(file);});
        body.images[file.name] = encoded;
      }
      const response = await fetch('/api/generate-batch',{method:'POST',headers:{'X-Asset3D':'workbench','Content-Type':'application/json'},body:JSON.stringify(body)});
      const result = await response.json();
      if (!response.ok) throw new Error(result.error);
      message.textContent = `已提交 ${count} 个输出，完成后在实验预设查看。`;
    } catch(error) {
      message.hidden = false;
      message.textContent = error.message;
    }
    finally { $('#batch-submit').disabled=false; }
  };
  const displayedJobs = new Set();
  const jobRows = new Map();
  const jobList = $('#job-list');
  const jobs = $('#generation-jobs');
  const jobsMessage = $('#jobs-message');
  function showJobsMessage(message) {
    jobs.hidden = false;
    jobsMessage.hidden = false;
    jobsMessage.textContent = message;
  }
  function displayGenerated(id, reveal = false) {
    if (reveal) showView(views[0]);
    const existing = generatedPanels.get(id);
    if (existing && existing.panel.run === existing.run) {
      const {panel} = existing;
      if (!panel.overlay.classList.contains('error')) {
        if (reveal && panel.overlay.hidden) panel.canvas.focus();
        else if (reveal) panel.card.scrollIntoView({block:'nearest'});
        return;
      }
      remove(panel);
    }
    const panel = addPanel();
    panel.generatedId = id;
    generatedPanels.set(id, {panel, run:panel.run + 1});
    if (reveal) panel.card.scrollIntoView({block:'nearest'});
    void loadBlob(panel, async () => {
      const response = await fetch('/api/generated/' + id);
      if (!response.ok) throw new Error('下载模型失败');
      return response.blob();
    }, 'TRELLIS.2 生成结果', id.slice(0, 8));
  }
  const foregroundReview = createForegroundReview({
    document, fetch, URL, AbortController, setTimeout, clearTimeout,
    showSingleView: () => showView(views[1]),
  });
  async function retryJob(job, button) {
    button.disabled = true;
    try {
      const response = await fetch('/api/generation-retry/' + job.id, {method:'POST', headers:{'X-Asset3D':'workbench'}});
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || '重新查询失败');
      showJobsMessage(`正在重新查询任务 ${job.id.slice(0, 8)}。`);
    } catch (error) {
      showJobsMessage(`任务 ${job.id.slice(0, 8)}：${error.message}`);
    } finally {
      button.disabled = false;
    }
  }
  function updateJobRow(job) {
    let row = jobRows.get(job.id);
    if (!row) {
      row = $('#job-template').content.firstElementChild.cloneNode(true);
      jobRows.set(job.id, row);
      jobList.prepend(row);
    }
    const complete = job.state === '完成';
    const activeJob = job.phase === 'preview' ? job.preview_job_id : job.job_id;
    row.querySelector('strong').textContent = job.name || job.id.slice(0, 8);
    const status = row.querySelector('.job-state');
    status.textContent = job.state;
    status.classList.toggle('error', Boolean(job.error));
    status.classList.toggle('complete', complete && !job.error);
    const details = [];
    if (activeJob) details.push((job.phase === 'preview' ? '预处理作业 ' : '作业 ') + activeJob);
    if (job.error) details.push(job.error);
    if (Number.isInteger(job.downloaded_models)) details.push(`已收到 ${job.downloaded_models} 个模型`);
    if (job.failures?.length) details.push(`${job.failures.length} 项失败，详见 failures.json`);
    if (job.checked_at) details.push('最近同步 ' + new Date(job.checked_at * 1000).toLocaleTimeString());
    row.querySelector('p').textContent = details.join(' · ');

    const button = row.querySelector('button');
    let action, label;
    if (job.phase === 'awaiting_confirmation') {
      label = '检查前景';
      action = () => {
        void foregroundReview.open(job);
        $('#review-title').focus();
      };
    } else if (complete && job.mode === 'batch') {
      label = '查看实验预设';
      action = () => { showView(views[0]); showPresets(true); void refreshCatalog(true); };
    } else if (complete) {
      label = '查看模型';
      action = () => displayGenerated(job.id, true);
    } else if (job.error && activeJob) {
      label = '重新查询 / 下载';
      action = () => retryJob(job, button);
    }
    button.hidden = !action;
    button.textContent = label || '';
    button.onclick = action || null;
  }
  let jobsUnavailable = false;
  async function pollGeneration() {
    try {
      const response = await fetch('/api/generation-jobs', {cache:'no-store'});
      if (!response.ok) throw new Error('任务服务不可用');
      const updates = await response.json();
      for (const job of updates.slice().reverse()) {
        foregroundReview.observe(job);
        updateJobRow(job);
        if (job.state === '完成' && !displayedJobs.has(job.id)) {
          displayedJobs.add(job.id);
          if (job.mode === 'batch') void refreshCatalog();
          else if (!job.failures?.length) displayGenerated(job.id);
        }
      }
      const ids = new Set(updates.map(job => job.id));
      for (const [id, row] of jobRows) {
        if (ids.has(id)) continue;
        row.remove();
        jobRows.delete(id);
      }
      if (jobsUnavailable) jobsMessage.hidden = true;
      jobsUnavailable = false;
      jobs.hidden = !updates.length && jobsMessage.hidden;
    } catch (error) {
      jobsUnavailable = true;
      showJobsMessage('任务列表暂时不可用，正在重试：' + error.message);
    }
    finally { setTimeout(pollGeneration, 3000); }
  }
  fetch('/api/generation-settings').then(r => { if (!r.ok) throw new Error('无法读取生成设置'); return r.json(); }).then(c => {
    foregroundReview.configure(c);
  }).catch(error => { $('#generate-message').textContent = error.message; });
  pollGeneration();
  initialize().catch(error => { showNotice(error.message); console.error(error); });
})();
