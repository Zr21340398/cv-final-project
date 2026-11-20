/* Single-image review: only a loaded, current server preview can be confirmed. */
(() => {
  function createForegroundReview({document, fetch, URL, AbortController, setTimeout, clearTimeout}) {
    const $ = selector => document.querySelector(selector);
    const imageInput = $('#generate-image');
    const fields = ['host', 'project', 'time', 'shape'].map(name => $('#generate-' + name));
    const prepare = $('#generate-prepare'), submit = $('#generate-submit');
    const reselect = $('#generate-reselect'), checked = $('#foreground-confirm');
    const review = $('#foreground-review'), message = $('#generate-message');
    const pictures = ['original', 'foreground', 'model-input'].map(name => $('#review-' + name));
    let revision = 0, activeTask = null, ready = null, loading = false, failed = false;
    let busy = false, submitting = false, touched = false, controller = null, objectURL = null;

    function options() {
      return {host:fields[0].value.trim(), project:fields[1].value.trim(),
        time_limit:fields[2].value.trim(), download_shape:String(fields[3].checked)};
    }
    function refresh() {
      const settings = options();
      const file = imageInput.files[0];
      const validFile = file && file.size > 0 && file.size <= 20 * 1024 * 1024 && /\.(png|jpe?g)$/i.test(file.name);
      prepare.disabled = busy || submitting || Boolean(activeTask) || !validFile
        || !settings.host || !settings.project || !settings.time_limit;
      submit.disabled = submitting || !ready || !checked.checked;
      checked.disabled = submitting || !ready;
      reselect.disabled = submitting;
      [imageInput, ...fields].forEach(field => { field.disabled = submitting; });
      review.setAttribute('aria-busy', String(loading));
    }
    function clearPictures() {
      for (const picture of pictures) {
        picture.hidden = true;
        picture.removeAttribute('src');
        picture.parentElement.removeAttribute('href');
      }
      if (objectURL) { URL.revokeObjectURL(objectURL); objectURL = null; }
    }
    function invalidate(text = '图片或设置已更改，请重新预处理并检查前景。') {
      revision++;
      controller?.abort(); controller = null;
      activeTask = null; ready = null; loading = false; busy = false; failed = false;
      checked.checked = false;
      clearPictures();
      review.hidden = true;
      $('#foreground-context').textContent = '';
      message.textContent = text;
      refresh();
    }
    function showSelection() {
      touched = true;
      invalidate('先预处理图片，检查主体完整且背景干净后，再提交 3D 生成。');
      const file = imageInput.files[0];
      if (!file) return;
      if (file.size === 0 || file.size > 20 * 1024 * 1024 || !/\.(png|jpe?g)$/i.test(file.name)) {
        message.textContent = '请选择 20 MiB 以内的 JPG 或 PNG 图片。';
        prepare.disabled = true;
        return;
      }
      objectURL = URL.createObjectURL(file);
      pictures[0].src = objectURL;
      pictures[0].hidden = false;
      review.hidden = false;
      $('#foreground-context').textContent = file.name;
    }
    function loadPicture(picture, url, signal) {
      return new Promise((resolve, reject) => {
        let timer;
        const cleanup = () => {
          clearTimeout(timer);
          picture.removeEventListener('load', loaded);
          picture.removeEventListener('error', errored);
          signal.removeEventListener('abort', aborted);
        };
        const loaded = () => {
          cleanup();
          if (!picture.naturalWidth || !picture.naturalHeight) { reject(new Error('预览图片为空')); return; }
          picture.hidden = false;
          picture.parentElement.href = url;
          resolve();
        };
        const errored = () => { cleanup(); reject(new Error('预览图片加载失败，请在任务列表点击「检查前景」重试。')); };
        const aborted = () => { cleanup(); reject(new Error('预览已失效')); };
        picture.addEventListener('load', loaded);
        picture.addEventListener('error', errored);
        signal.addEventListener('abort', aborted, {once:true});
        timer = setTimeout(errored, 30000);
        if (signal.aborted) { aborted(); return; }
        picture.src = url;
      });
    }
    async function loadPreview(task) {
      const current = revision;
      if (loading || activeTask !== task.id) return;
      loading = true; failed = false; ready = null; checked.checked = false;
      controller?.abort();
      const request = new AbortController(); controller = request;
      clearPictures(); review.hidden = false;
      message.textContent = '正在加载原图、透明前景和模型输入，请稍候…';
      refresh();
      try {
        const response = await fetch('/api/generation-preview/' + task.id, {cache:'no-store', signal:request.signal});
        const data = await response.json();
        if (current !== revision || activeTask !== task.id) return;
        if (!response.ok) throw new Error(data.error || '无法读取前景预览');
        if (data.id !== task.id || !/^[0-9a-f]{64}$/.test(data.preview_sha256)) throw new Error('前景预览记录无效，请重新预处理。');
        const urls = [data.original_url, data.foreground_url, data.model_input_url];
        const suffixes = ['original', 'foreground', 'model-input'];
        if (urls.some((url, index) => url !== '/api/generation-preview/' + task.id + '/' + suffixes[index])) {
          throw new Error('前景预览地址无效');
        }
        await Promise.all(pictures.map((picture, index) => loadPicture(picture, urls[index], request.signal)));
        if (current !== revision || activeTask !== task.id) return;
        ready = {id:task.id, digest:data.preview_sha256};
        message.textContent = '请对比三张图：把手、边缘是否完整？桌面、杂物和阴影是否残留？有问题请重新选图。';
      } catch (error) {
        if (current === revision && activeTask === task.id) {
          failed = true; ready = null; request.abort();
          message.textContent = error.message;
        }
      } finally {
        if (current === revision) { loading = false; refresh(); }
      }
    }
    async function open(task) {
      if (submitting) return;
      touched = true;
      invalidate();
      imageInput.value = '';
      fields[0].value = task.host; fields[1].value = task.root;
      fields[2].value = task.time_limit; fields[3].checked = Boolean(task.download_shape);
      activeTask = task.id;
      $('#single-form').hidden = false; $('#batch-form').hidden = true;
      $('#foreground-context').textContent = '任务 ' + task.id.slice(0, 8) + ' · ' + task.host;
      await loadPreview(task);
    }
    function observe(task) {
      // Never reactivate an old task after a new file or setting was selected.
      if (activeTask !== task.id || submitting || ready || loading || failed) return;
      if (task.phase === 'awaiting_confirmation' && task.preview_sha256) {
        void loadPreview(task);
      } else if (task.error) {
        message.textContent = task.error; failed = true; busy = false;
        refresh();
      } else if (task.phase === 'preview') {
        message.textContent = task.state + '。预览准备好后再确认生成。';
      }
    }
    imageInput.addEventListener('change', showSelection);
    fields.forEach(field => field.addEventListener('input', () => { touched = true; invalidate(); }));
    checked.addEventListener('change', refresh);
    reselect.addEventListener('click', () => {
      if (submitting) return;
      touched = true;
      imageInput.value = '';
      invalidate('请选择新的照片。旧前景确认已清除。');
      imageInput.click();
    });
    prepare.addEventListener('click', async () => {
      if (prepare.disabled) return;
      const file = imageInput.files[0], current = revision;
      busy = true; ready = null; checked.checked = false; refresh();
      message.textContent = '正在上传照片并申请预处理。需要等待学校 GPU 排队，暂不进行 3D 生成。';
      const request = new AbortController(); controller = request;
      try {
        const response = await fetch('/api/generate?' + new URLSearchParams(options()), {
          method:'POST', headers:{'X-Asset3D':'workbench'}, body:file, signal:request.signal,
        });
        const task = await response.json();
        if (current !== revision) return;
        if (!response.ok) throw new Error(task.error || '预处理提交失败');
        activeTask = task.id;
        $('#foreground-context').textContent = file.name + ' · 任务 ' + task.id.slice(0, 8);
        message.textContent = '预处理任务已创建。前景准备好后会在这里显示，请保持工作台服务运行。';
        observe(task);
      } catch (error) {
        if (current === revision) message.textContent = error.message;
      } finally { if (current === revision) { busy = false; refresh(); } }
    });
    submit.addEventListener('click', async () => {
      if (submit.disabled || !ready || !checked.checked) return;
      const selected = ready, current = revision;
      submitting = true; refresh();
      message.textContent = '正在提交已确认的前景…';
      try {
        const response = await fetch('/api/generation-confirm/' + selected.id, {
          method:'POST', headers:{'X-Asset3D':'workbench','Content-Type':'application/json'},
          body:JSON.stringify({preview_sha256:selected.digest, confirmed:true}),
        });
        const task = await response.json();
        if (current !== revision) return;
        if (!response.ok) throw new Error(task.error || '确认提交失败');
        ready = null; activeTask = null; checked.checked = false; imageInput.value = '';
        message.textContent = task.error || (String(task.state).includes('未知')
          ? task.state : '已确认这份前景并提交 3D 生成，可在下方查看进度。');
      } catch (error) {
        if (current === revision) message.textContent = error.message;
      } finally { submitting = false; refresh(); }
    });
    function configure(settings) {
      // A slow settings response must not overwrite a selection or restored task.
      if (touched || activeTask) return;
      fields[0].value = settings.host; fields[1].value = settings.project;
      fields[2].value = settings.time_limit; fields[3].checked = Boolean(settings.download_shape);
      refresh();
    }
    refresh();
    return {observe, open, refresh, configure};
  }
  if (typeof module !== 'undefined' && module.exports) module.exports = {createForegroundReview};
  else window.createForegroundReview = createForegroundReview;
})();
