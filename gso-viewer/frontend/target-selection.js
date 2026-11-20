/* Prompts use the displayed, EXIF-oriented photo's normalized coordinates. */
(() => {
  const clamp = value => Math.max(0, Math.min(1, value));
  function photoPoint(x, y, rect) {
    if (!(rect.width > 0 && rect.height > 0)) return null;
    return [clamp((x - rect.left) / rect.width), clamp((y - rect.top) / rect.height)];
  }
  function selectionBox(start, end) {
    const box = [Math.min(start[0], end[0]), Math.min(start[1], end[1]),
      Math.max(start[0], end[0]), Math.max(start[1], end[1])];
    return box[2] - box[0] >= .02 && box[3] - box[1] >= .02 ? box : null;
  }
  function createTargetSelection({document, URL, onChange, ImageCtor = Image}) {
    const $ = selector => document.querySelector(selector);
    const panel = $('#target-selection'), canvas = $('#target-canvas');
    const status = $('#target-status'), undo = $('#target-undo'), clear = $('#target-clear');
    const modes = ['box', 'include', 'exclude'];
    const buttons = modes.map(mode => $('#target-' + mode));
    const context = canvas.getContext('2d');
    let picture = null, sourceURL = null, imageVersion = 0, loaded = false, disabled = false;
    let box = null, marks = [], mode = 'box', drag = null, invalidBox = false;

    function value() {
      return box ? {box:[...box],
        include_points:marks.filter(mark => mark.mode === 'include').map(mark => [...mark.point]),
        exclude_points:marks.filter(mark => mark.mode === 'exclude').map(mark => [...mark.point])} : null;
    }
    function refresh() {
      buttons.forEach((button, index) => {
        button.disabled = disabled || !loaded || (index > 0 && !box);
        button.setAttribute('aria-pressed', String(mode === modes[index]));
      });
      clear.disabled = disabled || !loaded || (!box && !marks.length && !invalidBox && !drag);
      undo.disabled = disabled || !marks.length;
      canvas.setAttribute('aria-disabled', String(disabled || !loaded));
      if (!loaded) return;
      if (drag) status.textContent = '拖动圈出要保留的整个物体，松开完成。';
      else if (invalidBox) status.textContent = '主体框太小，请重新拖框，或清除选择恢复自动抠图。';
      else if (!box) status.textContent = '当前使用自动抠图。需要去除手或杂物时，先拖框圈出主体。';
      else {
        const included = marks.filter(mark => mark.mode === 'include').length;
        status.textContent = `已圈选主体 · 保留点 ${included}/16 · 排除点 ${marks.length - included}/16。修改后请重新预处理。`;
      }
    }
    function draw() {
      if (!loaded) return;
      const w = canvas.width, h = canvas.height;
      context.clearRect(0, 0, w, h);
      context.drawImage(picture, 0, 0, w, h);
      const currentBox = drag ? [Math.min(drag.start[0], drag.end[0]), Math.min(drag.start[1], drag.end[1]),
        Math.max(drag.start[0], drag.end[0]), Math.max(drag.start[1], drag.end[1])] : box;
      const scale = w / Math.max(1, canvas.getBoundingClientRect().width);
      if (currentBox) {
        const [x1, y1, x2, y2] = currentBox;
        context.strokeStyle = '#14b8d4'; context.lineWidth = 3 * scale;
        context.strokeRect(x1 * w, y1 * h, (x2 - x1) * w, (y2 - y1) * h);
      }
      for (const mark of marks) {
        const x = mark.point[0] * w, y = mark.point[1] * h, r = 8 * scale;
        context.beginPath(); context.arc(x, y, r, 0, Math.PI * 2);
        context.fillStyle = mark.mode === 'include' ? '#087f55' : '#c52b39'; context.fill();
        context.strokeStyle = '#fff'; context.lineWidth = 2 * scale; context.stroke();
        context.beginPath(); context.moveTo(x - r / 2, y); context.lineTo(x + r / 2, y);
        if (mark.mode === 'include') { context.moveTo(x, y - r / 2); context.lineTo(x, y + r / 2); }
        context.stroke();
      }
    }
    function changed() { refresh(); draw(); onChange(); }
    function setFile(file, {restored = false} = {}) {
      imageVersion++;
      if (sourceURL) URL.revokeObjectURL(sourceURL);
      sourceURL = null; picture = null; loaded = false;
      box = null; marks = []; drag = null; invalidBox = false; mode = 'box';
      panel.hidden = !file && !restored; canvas.hidden = true;
      status.textContent = restored ? '这是已保存的预览。若要修改主体范围，请重新选择原始照片。' : '正在读取原图…';
      refresh();
      if (!file) return;
      const current = imageVersion, image = new ImageCtor();
      picture = image; sourceURL = URL.createObjectURL(file);
      image.onload = () => {
        if (current !== imageVersion) return;
        if (!image.naturalWidth || !image.naturalHeight) { image.onerror(); return; }
        // HTML images and drawImage apply EXIF orientation before these dimensions
        // are used. The canvas has no letterboxing; CSS preserves its aspect ratio.
        const ratio = image.naturalWidth / image.naturalHeight;
        canvas.width = Math.max(1, Math.round(Math.min(1280, 1280 * ratio)));
        canvas.height = Math.max(1, Math.round(canvas.width / ratio));
        canvas.style.width = Math.min(600, 520 * ratio) + 'px';
        loaded = true; canvas.hidden = false; refresh(); draw();
      };
      image.onerror = () => {
        if (current !== imageVersion) return;
        loaded = false; canvas.hidden = true;
        status.textContent = '无法显示选区画布，请重新选择 JPG 或 PNG 原图。'; refresh();
      };
      image.src = sourceURL;
    }
    buttons.forEach((button, index) => button.addEventListener('click', () => {
      if (button.disabled) return;
      mode = modes[index]; refresh();
    }));
    clear.addEventListener('click', () => {
      if (clear.disabled) return;
      box = null; marks = []; drag = null; invalidBox = false; mode = 'box'; changed();
    });
    undo.addEventListener('click', () => { if (!undo.disabled) { marks.pop(); changed(); } });
    canvas.addEventListener('pointerdown', event => {
      if (disabled || !loaded || event.button !== 0) return;
      const point = photoPoint(event.clientX, event.clientY, canvas.getBoundingClientRect());
      if (!point) return;
      event.preventDefault();
      if (mode === 'box') {
        box = null; marks = []; invalidBox = false;
        drag = {pointer:event.pointerId, start:point, end:point};
        canvas.setPointerCapture(event.pointerId); changed();
      } else if (box) {
        if (marks.filter(mark => mark.mode === mode).length >= 16) {
          status.textContent = '同类标记最多 16 个，请先撤销一个点或清除选择。'; return;
        }
        marks.push({mode, point}); changed();
      }
    });
    canvas.addEventListener('pointermove', event => {
      if (!drag || event.pointerId !== drag.pointer || disabled) return;
      const point = photoPoint(event.clientX, event.clientY, canvas.getBoundingClientRect());
      if (point) { drag.end = point; draw(); }
    });
    canvas.addEventListener('pointerup', event => {
      if (!drag || event.pointerId !== drag.pointer) return;
      const point = photoPoint(event.clientX, event.clientY, canvas.getBoundingClientRect());
      box = point ? selectionBox(drag.start, point) : null;
      drag = null; invalidBox = !box; changed();
    });
    canvas.addEventListener('pointercancel', () => {
      if (drag) { drag = null; invalidBox = true; changed(); }
    });
    refresh();
    return {setFile, value, canPrepare:() => !drag && !invalidBox,
      setDisabled(value) { disabled = value; refresh(); }};
  }
  if (typeof module !== 'undefined' && module.exports) module.exports = {photoPoint, selectionBox, createTargetSelection};
  else window.createTargetSelection = createTargetSelection;
})();
