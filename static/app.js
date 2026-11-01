/**
 * Muse ai tool — Frontend Reactive Application
 * Triển khai đầy đủ các yêu cầu từ Mục 1 đến Mục 10 (AC-01 -> AC-12)
 */

// =========================================================================
// Global State
// =========================================================================
const AppState = {
  currentModule: 'queue', // 'queue' | 'studio'
  refImages: [],          // Kho ảnh tham chiếu
  accounts: [],           // Danh sách tài khoản
  systemState: null,      // Trạng thái tổng quan từ /api/state
  concurrencyInitialized: false,
  concurrencyDirty: false,
  
  // Batch Manager
  lastEnqueuedTaskIds: [],// Phục vụ Hoàn tác (Undo)
  
  // Status filter & Pagination
  statusFilter: 'Tất cả',
  searchQuery: '',
  
  // Autocomplete
  mentionActive: false,
  mentionQuery: '',
  mentionIndex: 0,
  mentionStartPos: 0,
  
  // Flow Studio
  studioCards: [],
  zoomLevel: 1.0,
  panX: 0,
  panY: 0,
  isPanning: false,
  panStartX: 0,
  panStartY: 0,
};

// =========================================================================
// Initialization
// =========================================================================
document.addEventListener('DOMContentLoaded', () => {
  initEvents();
  loadRefImages();
  loadAccounts();
  loadJobs();
  loadMachineInfo();
  startStatePolling();
});

function initEvents() {
  document.getElementById('inpConcurrency').addEventListener('input', () => {
    AppState.concurrencyInitialized = true;
    AppState.concurrencyDirty = true;
    clearTimeout(concurrencyApplyTimer);
    const status = document.getElementById('concurrencyStatus');
    status.textContent = 'Đang chờ áp dụng…';
    concurrencyApplyTimer = setTimeout(() => applyConcurrency(false), 400);
  });
  // Bắt sự kiện bàn phím trên textarea cho Mention Dropdown
  const txt = document.getElementById('txtBatchPrompts');
  txt.addEventListener('click', () => closeMentionDropdown());
  document.addEventListener('click', event => {
    if (!document.getElementById('batchRefPicker').contains(event.target)) closeBatchRefPicker();
  });
  document.getElementById('batchRefTrigger').addEventListener('keydown', event => {
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      toggleBatchRefPicker(true);
    } else if (event.key === 'Escape') closeBatchRefPicker();
  });
  document.getElementById('batchRefOptions').addEventListener('keydown', event => {
    const buttons = [...event.currentTarget.querySelectorAll('button')];
    const index = buttons.indexOf(document.activeElement);
    if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
      event.preventDefault();
      const next = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1
        : (index + (event.key === 'ArrowDown' ? 1 : -1) + buttons.length) % buttons.length;
      buttons[next]?.focus();
    } else if (event.key === 'Escape') {
      closeBatchRefPicker();
      document.getElementById('batchRefTrigger').focus();
    } else if (event.key === 'Tab') closeBatchRefPicker();
  });
  
  // Flow Studio Canvas Pan & Drag
  // Studio is hidden; queue is the only active workspace.
}

// =========================================================================
// 1. Module Navigation (Mục 1.2 & 7.4)
// =========================================================================
function switchModule(mod) {
  AppState.currentModule = 'queue';
  document.getElementById('moduleQueue').classList.remove('hidden');
  document.getElementById('moduleStudio').classList.add('hidden');
  loadJobs();
}

// =========================================================================
// 2. Reference Library (Kho ảnh tham chiếu) (Mục 3 & AC-04)
// =========================================================================
async function loadRefImages() {
  try {
    const res = await fetch('/api/refs');
    const data = await res.json();
    AppState.refImages = data || [];
    renderRefChips();
    updateBatchCommonRefSelect();
    checkPromptTags();
  } catch (e) {
    console.error('Lỗi tải kho ảnh:', e);
  }
}

function renderRefChips() {
  const container = document.getElementById('refChipsList');
  const headerTxt = document.getElementById('txtRefHeader');
  headerTxt.textContent = `Kho ảnh tham chiếu · ${AppState.refImages.length} ảnh`;

  if (!AppState.refImages.length) {
    container.innerHTML = '<span class="text-xs text-slate-500 italic">Chưa có ảnh tham chiếu nào trong kho.</span>';
    return;
  }

  container.innerHTML = AppState.refImages.map(img => `
    <div class="ref-chip" title="${escapeHtml(img.filename)} (${img.size_kb} KB)">
      <img src="${img.url}" alt="${img.tag}">
      <span class="tag-text">@${img.tag}</span>
      <button type="button" class="btn-del-chip" onclick="deleteRefImage('${img.tag}')" title="Xóa ảnh" aria-label="Xóa ảnh @${img.tag}">Xóa</button>
    </div>
  `).join('');
}

function updateBatchCommonRefSelect() {
  const sel = document.getElementById('selBatchCommonRef');
  const currentVal = sel.value;
  sel.innerHTML = '<option value="">(Không dùng)</option>' + 
    AppState.refImages.map(img => `
      <option value="${escapeHtml(img.tag)}" ${img.tag === currentVal ? 'selected' : ''}>@${escapeHtml(img.tag)} (${escapeHtml(img.filename)})</option>
    `).join('');
  renderBatchRefPicker();
}

function renderBatchRefPicker() {
  const select = document.getElementById('selBatchCommonRef');
  const selected = select.selectedOptions[0];
  const label = document.getElementById('batchRefLabel');
  label.textContent = selected?.textContent || '(Không dùng)';
  document.getElementById('batchRefTrigger').title = label.textContent;
  const popup = document.getElementById('batchRefOptions');
  popup.replaceChildren();
  [...select.options].forEach((option, index) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.id = `batchRefOption${index}`;
    button.setAttribute('role', 'option');
    button.setAttribute('aria-selected', String(option.value === select.value));
    button.textContent = option.textContent;
    button.title = option.textContent;
    button.onclick = () => {
      select.value = option.value;
      renderBatchRefPicker();
      closeBatchRefPicker();
      document.getElementById('batchRefTrigger').focus();
    };
    popup.appendChild(button);
  });
}

function closeBatchRefPicker() {
  document.getElementById('batchRefOptions').classList.add('hidden');
  document.getElementById('batchRefTrigger').setAttribute('aria-expanded', 'false');
}

function toggleBatchRefPicker(forceOpen = false) {
  const popup = document.getElementById('batchRefOptions');
  if (!forceOpen && !popup.classList.contains('hidden')) return closeBatchRefPicker();
  renderBatchRefPicker();
  popup.classList.remove('hidden');
  document.getElementById('batchRefTrigger').setAttribute('aria-expanded', 'true');
  (popup.querySelector('[aria-selected="true"]') || popup.firstElementChild)?.focus();
}

async function deleteRefImage(tag) {
  try {
    const res = await fetch(`/api/refs/${encodeURIComponent(tag)}`, { method: 'DELETE' });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Không thể xóa ảnh');
    if (data.warning) {
      showToast(data.warning, 'warn');
    } else {
      showToast(`Đã xóa ảnh @${tag}`, 'info');
    }
    await loadRefImages();
  } catch (e) {
    showToast('Lỗi xóa ảnh: ' + e.message, 'error');
  }
}

// --- Upload nhiều ảnh tham chiếu (Mục 3.2 & AC-04) ---
let pendingUploadFiles = [];

function openUploadModal() {
  pendingUploadFiles = [];
  document.getElementById('fileInputRefs').value = '';
  document.getElementById('uploadPreviewList').innerHTML = '';
  document.getElementById('btnSaveUploadedRefs').disabled = true;
  document.getElementById('txtUploadSummary').textContent = 'Chưa chọn ảnh nào.';
  const modal = document.getElementById('modalUpload');
  modal.classList.remove('hidden');
  modal.classList.add('flex');
}

function closeUploadModal() {
  const modal = document.getElementById('modalUpload');
  modal.classList.add('hidden');
  modal.classList.remove('flex');
}

function onRefFilesSelected(e) {
  const files = Array.from(e.target.files);
  pendingUploadFiles = files.map(file => {
    // Tự sinh tag từ tên file (Mục 3.2.4)
    const baseName = file.name.substring(0, file.name.lastIndexOf('.')) || file.name;
    let tag = baseName.toLowerCase().replace(/[\s_]+/g, '-').replace(/[^a-z0-9-]/g, '').replace(/^-+|-+$/g, '');
    if (!tag) tag = 'ref';
    
    // Kiểm tra định dạng & dung lượng (Mục 3.2.2: max 8MB, PNG/JPG/WebP)
    const ext = file.name.substring(file.name.lastIndexOf('.')).toLowerCase();
    const validExt = ['.png', '.jpg', '.jpeg', '.webp'].includes(ext);
    const validSize = file.size <= 8 * 1024 * 1024;
    
    let error = '';
    if (!validExt) error = `Định dạng ${ext} không hợp lệ (chỉ nhận PNG, JPG, WebP)`;
    else if (!validSize) error = `Dung lượng ${(file.size / (1024*1024)).toFixed(2)} MB vượt quá 8 MB`;

    return {
      file,
      tag,
      error,
      valid: validExt && validSize,
      previewUrl: URL.createObjectURL(file)
    };
  });

  renderUploadPreviewList();
}

function renderUploadPreviewList() {
  const container = document.getElementById('uploadPreviewList');
  const btnSave = document.getElementById('btnSaveUploadedRefs');
  const summary = document.getElementById('txtUploadSummary');

  if (!pendingUploadFiles.length) {
    container.innerHTML = '<div class="text-xs text-slate-500 py-4 text-center">Chưa có tệp nào được chọn.</div>';
    btnSave.disabled = true;
    summary.textContent = 'Chưa chọn ảnh nào.';
    return;
  }

  // Kiểm tra trùng tag trong đợt upload hoặc trong kho
  const existingTags = AppState.refImages.map(img => img.tag);
  const tagCounts = {};
  pendingUploadFiles.forEach(item => {
    if (item.valid) tagCounts[item.tag] = (tagCounts[item.tag] || 0) + 1;
  });

  container.innerHTML = pendingUploadFiles.map((item, idx) => {
    let tagError = item.error;
    if (!tagError) {
      if (!item.tag || !/^[a-z0-9-_]+$/.test(item.tag)) {
        tagError = 'Tag không hợp lệ (chỉ chấp nhận [a-z0-9-_])';
      } else if (existingTags.includes(item.tag)) {
        tagError = `Tag '@${item.tag}' đã có trong kho`;
      } else if (tagCounts[item.tag] > 1) {
        tagError = `Tag '@${item.tag}' bị trùng trong đợt upload`;
      }
    }

    const isValid = !tagError;

    return `
      <div class="flex items-center gap-3 p-2 rounded-xl bg-slate-900 border ${isValid ? 'border-slate-800' : 'border-red-500/40'}">
        <img src="${item.previewUrl}" class="w-10 h-10 rounded-lg object-cover bg-black flex-shrink-0">
        <div class="flex-1 min-w-0">
          <div class="flex justify-between text-xs text-slate-300">
            <span class="truncate font-medium">${item.file.name}</span>
            <span class="text-slate-500">${(item.file.size / 1024).toFixed(1)} KB</span>
          </div>
          <div class="flex items-center gap-2 mt-1">
            <span class="text-xs text-slate-400 font-mono">@</span>
            <input type="text" value="${item.tag}" oninput="onEditUploadTag(${idx}, this.value)"
              class="bg-slate-950 border border-slate-700 rounded px-2 py-0.5 text-xs font-mono text-indigo-300 focus:outline-none focus:border-indigo-500 w-44">
            ${tagError ? `<span class="text-[11px] text-red-400 truncate">${tagError}</span>` : '<span class="text-[11px] text-emerald-400">✓ Hợp lệ</span>'}
          </div>
        </div>
      </div>
    `;
  }).join('');

  const validCount = pendingUploadFiles.filter(i => {
    const isTagValid = i.tag && /^[a-z0-9-_]+$/.test(i.tag) && !existingTags.includes(i.tag) && tagCounts[i.tag] <= 1;
    return i.valid && isTagValid;
  }).length;

  summary.textContent = `Hợp lệ ${validCount} / ${pendingUploadFiles.length} ảnh`;
  btnSave.disabled = validCount === 0;
  btnSave.textContent = `Lưu ${validCount} ảnh vào kho`;
}

function onEditUploadTag(idx, newTag) {
  if (pendingUploadFiles[idx]) {
    pendingUploadFiles[idx].tag = newTag.trim().toLowerCase();
    renderUploadPreviewList();
  }
}

async function saveSelectedRefImages() {
  const existingTags = AppState.refImages.map(img => img.tag);
  const tagCounts = {};
  pendingUploadFiles.forEach(item => {
    if (item.valid) tagCounts[item.tag] = (tagCounts[item.tag] || 0) + 1;
  });

  const validFiles = pendingUploadFiles.filter(item => {
    const isTagValid = item.tag && /^[a-z0-9-_]+$/.test(item.tag) && !existingTags.includes(item.tag) && tagCounts[item.tag] <= 1;
    return item.valid && isTagValid;
  });

  if (!validFiles.length) return;

  const btn = document.getElementById('btnSaveUploadedRefs');
  btn.disabled = true;
  btn.textContent = 'Đang lưu...';

  const formData = new FormData();
  validFiles.forEach(item => {
    formData.append('files', item.file, `${item.tag}.${item.file.name.split('.').pop()}`);
  });

  try {
    const res = await fetch('/api/refs/upload', {
      method: 'POST',
      body: formData,
    });
    const data = await res.json();
    showToast(`Đã lưu thành công ${data.savedCount} ảnh vào kho!`, 'success');
    closeUploadModal();
    loadRefImages();
  } catch (e) {
    showToast('Lỗi khi lưu ảnh: ' + e.message, 'error');
  } finally {
    btn.disabled = false;
  }
}

// =========================================================================
// 3. Batch Prompt, Split Mode & Live Counting (Mục 4 & AC-01, AC-02, AC-03)
// =========================================================================
let promptInputDebounce = null;

function onPromptInput(e) {
  clearTimeout(promptInputDebounce);
  promptInputDebounce = setTimeout(() => {
    updatePromptCountBadge();
    checkPromptTags();
  }, 200); // Debounce ~200ms (Mục 4.2 & AC-01)

  handleMentionTrigger(e);
}

function updatePromptCountBadge() {
  const text = document.getElementById('txtBatchPrompts').value;
  const count = getPromptCount(text, 'line');
  const badge = document.getElementById('badgePromptCount');
  badge.textContent = `${count} prompt`;
}

function getPromptCount(text, mode) {
  text = (text || '').trim();
  if (!text) return 0;
  if (mode === 'paragraph') {
    return text.split(/\n\s*\n/).map(s => s.trim()).filter(Boolean).length;
  }
  if (mode === 'all') {
    return 1;
  }
  // line
  return text.split('\n').map(s => s.trim()).filter(Boolean).length;
}

function splitPromptText(text, mode) {
  text = (text || '').trim();
  if (!text) return [];
  if (mode === 'paragraph') {
    return text.split(/\n\s*\n/).map(s => s.trim()).filter(Boolean);
  }
  if (mode === 'all') {
    return [text];
  }
  return text.split('\n').map(s => s.trim()).filter(Boolean);
}

// --- Gõ @ gợi ý & tự gắn ảnh (Mục 4.3 & AC-02, AC-03) ---
function handleMentionTrigger(e) {
  const txt = e.target;
  const val = txt.value;
  const selStart = txt.selectionStart;
  
  // Tìm ký tự @ gần nhất trước con trỏ
  const beforeCursor = val.substring(0, selStart);
  const lastAt = beforeCursor.lastIndexOf('@');

  if (lastAt !== -1 && !/\s/.test(beforeCursor.substring(lastAt + 1))) {
    const query = beforeCursor.substring(lastAt + 1).toLowerCase();
    showMentionDropdown(query, lastAt);
  } else {
    closeMentionDropdown();
  }
}

function showMentionDropdown(query, atPos) {
  const dropdown = document.getElementById('mentionDropdown');
  const filtered = AppState.refImages.filter(img => img.tag.toLowerCase().includes(query));

  if (!filtered.length) {
    closeMentionDropdown();
    return;
  }

  AppState.mentionActive = true;
  AppState.mentionQuery = query;
  AppState.mentionStartPos = atPos;
  AppState.mentionIndex = 0;

  dropdown.innerHTML = filtered.map((img, idx) => `
    <div class="mention-item ${idx === 0 ? 'selected' : ''}" onclick="selectMention('${img.tag}')">
      <img src="${img.url}">
      <div>
        <div class="text-xs font-bold text-slate-200">@${img.tag}</div>
        <div class="text-[10px] text-slate-400 truncate">${img.filename}</div>
      </div>
    </div>
  `).join('');

  dropdown.classList.remove('hidden');
}

function closeMentionDropdown() {
  AppState.mentionActive = false;
  const dropdown = document.getElementById('mentionDropdown');
  dropdown.classList.add('hidden');
}

function selectMention(tag) {
  const txt = document.getElementById('txtBatchPrompts');
  const val = txt.value;
  const before = val.substring(0, AppState.mentionStartPos);
  const after = val.substring(txt.selectionStart);
  
  txt.value = `${before}@${tag} ${after}`;
  closeMentionDropdown();
  txt.focus();
  updatePromptCountBadge();
  checkPromptTags();
}

function onPromptKeyDown(e) {
  if (!AppState.mentionActive) return;
  const dropdown = document.getElementById('mentionDropdown');
  const items = dropdown.querySelectorAll('.mention-item');
  if (!items.length) return;

  if (e.key === 'ArrowDown') {
    e.preventDefault();
    AppState.mentionIndex = (AppState.mentionIndex + 1) % items.length;
    updateMentionSelection(items);
  } else if (e.key === 'ArrowUp') {
    e.preventDefault();
    AppState.mentionIndex = (AppState.mentionIndex - 1 + items.length) % items.length;
    updateMentionSelection(items);
  } else if (e.key === 'Enter') {
    e.preventDefault();
    items[AppState.mentionIndex]?.click();
  } else if (e.key === 'Escape') {
    closeMentionDropdown();
  }
}

function updateMentionSelection(items) {
  items.forEach((el, i) => {
    el.classList.toggle('selected', i === AppState.mentionIndex);
  });
}

// --- Kiểm tra tag tồn tại & Báo đỏ tag lạ (Mục 4.3.4 & 4.3.6 & AC-02, AC-03) ---
function checkPromptTags() {
  const text = document.getElementById('txtBatchPrompts').value;
  const matches = Array.from(text.matchAll(/@([a-z0-9-_]+)/gi)).map(m => m[1].toLowerCase());
  const uniqueTags = Array.from(new Set(matches));

  const detectedArea = document.getElementById('detectedTagsArea');
  const warningBox = document.getElementById('missingTagsWarning');
  const warningMsg = document.getElementById('txtMissingTagsMsg');

  if (!uniqueTags.length) {
    detectedArea.innerHTML = '';
    warningBox.classList.add('hidden');
    return;
  }

  const existingTags = AppState.refImages.map(img => img.tag);
  const missingTags = uniqueTags.filter(t => !existingTags.includes(t));
  const validTags = uniqueTags.filter(t => existingTags.includes(t));

  // Render chip xác nhận đã tự gắn ảnh (Mục 4.3.4 & AC-02)
  detectedArea.innerHTML = validTags.map(t => {
    const img = AppState.refImages.find(i => i.tag === t);
    return `
      <div class="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-indigo-500/10 border border-indigo-500/30 text-indigo-300 text-xs">
        <img src="${img.url}" class="w-4 h-4 rounded-full object-cover">
        <span>@${t} · đã tự gắn ảnh</span>
      </div>
    `;
  }).join('');

  // Báo đỏ ngay khi gõ tag lạ (Mục 4.3.6 & AC-03)
  if (missingTags.length) {
    warningBox.classList.remove('hidden');
    warningMsg.textContent = `Tag chưa có trong kho: @${missingTags.join(', @')} — Vui lòng thêm ảnh vào kho hoặc sửa tag trước khi chạy!`;
  } else {
    warningBox.classList.add('hidden');
  }
}

// =========================================================================
// 5. Chạy hàng đợi & Dispatcher (Mục 5 & AC-06)
// =========================================================================
async function enqueueCurrentBatch() {
  const text = document.getElementById('txtBatchPrompts').value.trim();
  if (!text) {
    showToast('Vui lòng nhập prompt trước khi thêm vào hàng đợi!', 'warn');
    return;
  }

  const prompts = splitPromptText(text, 'line');
  if (!prompts.length) return;

  const duration = parseInt(document.getElementById('selDuration').value);
  const ratio = document.getElementById('selRatio').value;
  const batchRefTag = document.getElementById('selBatchCommonRef').value;

  try {
    const res = await fetch('/api/queue/batch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        prompts,
        duration,
        ratio,
        batchRefTag,
      })
    });
    const data = await res.json();
    AppState.lastEnqueuedTaskIds = data.taskIds || [];

    // Reset prompt box
    document.getElementById('txtBatchPrompts').value = '';
    updatePromptCountBadge();
    checkPromptTags();

    // Hiện toast thông báo
    showToast(
      `Đã thêm ${prompts.length} job vào hàng đợi! Bấm "▶ Chạy hàng đợi" để bắt đầu.`,
      'success'
    );

    await loadJobs();
    // Cập nhật ngay lập tức state và dải trực tiếp
    try {
      const sRes = await fetch('/api/state');
      const sData = await sRes.json();
      AppState.systemState = sData;
      updateHeaderCounters(sData);
      renderLiveRunningStrip(sData.runningJobs || []);
    } catch (_) {}
  } catch (e) {
    showToast('Lỗi thêm job: ' + e.message, 'error');
  }
}

async function undoLastEnqueue() {
  if (!AppState.lastEnqueuedTaskIds.length) return;
  try {
    for (const tid of AppState.lastEnqueuedTaskIds) {
      await fetch(`/api/queue/jobs/${tid}`, { method: 'DELETE' });
    }
    showToast(`Đã hoàn tác: rút lại ${AppState.lastEnqueuedTaskIds.length} job!`, 'info');
    AppState.lastEnqueuedTaskIds = [];
    loadJobs();
  } catch (e) {
    showToast('Lỗi khi hoàn tác: ' + e.message, 'error');
  }
}

function readConcurrency() {
  const value = Number(document.getElementById('inpConcurrency').value);
  if (!Number.isInteger(value) || value < 1 || value > 20) {
    throw new Error('Số luồng phải là số nguyên từ 1 đến 20');
  }
  return value;
}

let concurrencyApplyTimer;

function renderConcurrencyStatus(value, active = null) {
  const status = document.getElementById('concurrencyStatus');
  if (status) status.textContent = `Đã áp dụng: ${value} luồng${active == null ? '' : ` · đang chạy: ${active}`}`;
}

async function applyConcurrency(showFeedback = true) {
  clearTimeout(concurrencyApplyTimer);
  try {
    const n = readConcurrency();
    const res = await fetch('/api/config/concurrency', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ concurrency: n })
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Could not apply concurrency');
    if (data.concurrencyProtocol !== 2) {
      throw new Error('Server đang chạy code cũ. Hãy khởi động lại tool để dùng nhiều luồng.');
    }
    if (data.concurrency !== n) throw new Error('Backend chưa nhận đúng số luồng đã chọn');
    if (Number(document.getElementById('inpConcurrency').value) === n) {
      AppState.concurrencyDirty = false;
      renderConcurrencyStatus(n);
    }
    if (showFeedback) showToast(`Đã áp dụng ${n} luồng`, 'success');
    return true;
  } catch (e) {
    const status = document.getElementById('concurrencyStatus');
    if (status) status.textContent = e.message;
    showToast('Lỗi: ' + e.message, 'error');
    return false;
  }
}

async function startDispatcher() {
  let concurrency;
  try {
    concurrency = readConcurrency();
  } catch (e) {
    showToast(e.message, 'error');
    return;
  }
  if (!await applyConcurrency(false)) return;
  const text = document.getElementById('txtBatchPrompts').value.trim();
  // Nếu trong ô prompt có nội dung, tự động thêm vào hàng đợi trước khi chạy
  if (text) {
    await enqueueCurrentBatch();
  }

  try {
    const res = await fetch('/api/queue/process', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ concurrency })
    });
    if (!res.ok) {
      let errMsg = 'Không thể khởi động hàng đợi!';
      try {
        const err = await res.json();
        errMsg = err.detail || errMsg;
      } catch (_) {
        errMsg = `Lỗi máy chủ (${res.status}): Vui lòng kiểm tra tài khoản Online trong pool`;
      }
      showToast(errMsg, 'error');
      return;
    }
    showToast('▶ Hàng đợi bắt đầu chạy cuốn chiếu!', 'success');
    loadJobs();
  } catch (e) {
    showToast('Lỗi kết nối dispatcher: ' + e.message, 'error');
  }
}

async function stopDispatcher() {
  try {
    await fetch('/api/queue/stop', { method: 'POST' });
    showToast('⏹ Đã dừng toàn bộ hàng đợi!', 'warn');
    loadJobs();
  } catch (e) {
    showToast('Lỗi dừng: ' + e.message, 'error');
  }
}

// =========================================================================
// 6. Danh Sách Video & Dải Trực Tiếp (Mục 6 & AC-06, AC-07, AC-10)
// =========================================================================
let searchDebounce = null;

function onSearchInput() {
  clearTimeout(searchDebounce);
  searchDebounce = setTimeout(() => {
    AppState.searchQuery = document.getElementById('inpSearchJobs').value.trim();

    loadJobs();
  }, 250);
}

function setStatusFilter(filter) {
  AppState.statusFilter = filter;


  // Active state trên tabs
  const tabs = document.querySelectorAll('.status-tab-btn');
  tabs.forEach(t => {
    if (t.textContent.includes(filter)) {
      t.className = 'status-tab-btn active px-3 py-1.5 rounded-lg text-xs font-semibold bg-indigo-600 text-white';
    } else {
      t.className = 'status-tab-btn px-3 py-1.5 rounded-lg text-xs font-semibold text-slate-400 hover:text-slate-200';
    }
  });

  loadJobs();
}

async function fetchAllJobs(status, search) {
  const base = `/api/queue/jobs?status=${encodeURIComponent(status)}&search=${encodeURIComponent(search)}&allRecords=true&pageSize=100`;
  async function read(page) {
    const response = await fetch(`${base}&page=${page}`);
    if (!response.ok) throw new Error('Không tải được danh sách record');
    return response.json();
  }
  const first = await read(1);
  const records = new Map(first.jobs.map(job => [job.id, job]));
  // Compatibility with a backend process that still paginates: collect every
  // page before rendering one scrollable list. No page controls in the UI.
  let page = 1;
  let total = first.total;
  while (records.size < total) {
    const next = await read(++page);
    const previousSize = records.size;
    next.jobs.forEach(job => records.set(job.id, job));
    total = next.total;
    if (records.size === previousSize && records.size < total) {
      throw new Error('Backend không trả đủ record; hãy khởi động lại server của tool');
    }
  }
  return { ...first, jobs: [...records.values()], total: records.size };
}

let jobsLoadRequest = 0;
async function loadJobs() {
  const request = ++jobsLoadRequest;
  try {
    const data = await fetchAllJobs(AppState.statusFilter, AppState.searchQuery);
    if (request !== jobsLoadRequest) return;

    renderFilterCounters(data.counts);
    document.getElementById('txtRecordsTotal').textContent = `${data.total} record`;
    renderVideoRows(data.jobs);
  } catch (e) {
    if (request === jobsLoadRequest) showToast(e.message, 'error');
    console.error('Lỗi tải danh sách job:', e);
  }
}

function renderFilterCounters(counts) {
  if (!counts) return;
  document.getElementById('fCntAll').textContent = `(${counts['Tất cả'] || 0})`;
  document.getElementById('fCntWaiting').textContent = `(${counts['Chờ'] || 0})`;
  document.getElementById('fCntRunning').textContent = `(${counts['Đang chạy'] || 0})`;
  document.getElementById('fCntCompleted').textContent = `(${counts['Hoàn thành'] || 0})`;
  document.getElementById('fCntFailed').textContent = `(${counts['Thất bại'] || 0})`;
  document.getElementById('fCntStopped').textContent = `(${counts['Đã dừng'] || 0})`;
}

const rescanningJobs = new Set();

async function rescanThread(event, jobId) {
  event.stopPropagation();
  if (rescanningJobs.has(jobId)) return;
  rescanningJobs.add(jobId);
  const button = event.currentTarget;
  button.disabled = true;
  button.textContent = 'Đang quét lại…';
  try {
    const response = await fetch(`/api/queue/rescan/${encodeURIComponent(jobId)}`, {method: 'POST'});
    if (!response.ok) {
      if (response.status === 405) throw new Error('Server chưa nạp API Quét lại thread. Hãy tắt cửa sổ server cũ, chạy lại start.bat rồi tải lại trang. Ctrl + F5 riêng lẻ không cập nhật server.');
      if (response.status === 404) throw new Error('Chưa có chức năng quét lại trên server; cần khởi động lại server để nạp bản mới');
      const data = await response.json();
      throw new Error(data.detail || 'Không thể quét lại thread');
    }
    showToast('Đã khởi động lại bộ quét thread cũ; không gửi lại prompt', 'success');
  } catch (error) {
    showToast(error.message, 'error');
  } finally {
    rescanningJobs.delete(jobId);
    button.disabled = false;
    button.textContent = 'Quét lại thread';
    await loadJobs();
  }
}

async function copyThreadId(event, threadId) {
  event.stopPropagation();
  try {
    try {
      await navigator.clipboard.writeText(threadId);
    } catch (_) {
      const input = document.createElement('textarea');
      input.value = threadId;
      input.style.cssText = 'position:fixed;left:-9999px;top:0';
      document.body.appendChild(input);
      try {
        input.select();
        if (!document.execCommand('copy')) throw new Error('Không thể copy ID');
      } finally { input.remove(); }
    }
    showToast('Đã copy ID thread', 'success');
  } catch (error) {
    showToast(error.message, 'error');
  }
}

function renderVideoRows(jobs) {
  const container = document.getElementById('videoRowsContainer');
  if (!jobs || !jobs.length) {
    container.innerHTML = '<div class="text-center py-16 text-slate-500 text-sm">Không có video nào trong bộ lọc này.</div>';
    return;
  }

  container.innerHTML = jobs.map(job => {
    const statusClass = {
      'Chờ': 'cho',
      'Đang chạy': 'dang-chay',
      'Hoàn thành': 'hoan-thanh',
      'Thất bại': 'that-bai',
      'Đã dừng': 'da-dung'
    }[job.status] || 'cho';

    return `
      <div class="video-row" id="row_${job.id}">
        <!-- Thumbnail / Player nhúng (Mục 6.3 & 6.5 & AC-07) -->
        <div class="video-thumbnail-box" onclick="toggleRowPlayer(event, '${job.id}')">
          ${job.status === 'Hoàn thành' && job.videoUrl ? `
            <img src="${job.thumbnailUrl || '/api/media/' + job.id + '_thumb.svg'}" alt="Thumb" class="row-thumb-img">
            <div class="play-icon">▶</div>
          ` : `
            <div class="w-full h-full flex items-center justify-center bg-slate-900 text-slate-600 text-xs font-mono">
              ${job.status === 'Đang chạy' ? `${job.progress}%` : 'Video'}
            </div>
          `}
        </div>

        <!-- Nội dung chính rút gọn 1 dòng (Mục 6.3 & AC-10) -->
        <div class="flex-1 min-w-0" onclick="toggleRowExpand('${job.id}')">
          <div class="flex items-center gap-2">
            <span class="text-xs font-bold text-slate-200 truncate font-sans">${escapeHtml(job.prompt)}</span>
          </div>
          <div class="flex items-center gap-3 text-[11px] text-slate-500 font-mono mt-0.5">
            <span>${job.id}</span>
            <span>${escapeHtml(job.assignedAccountId || job.accountId || '')}</span>
            ${job.threadId ? `<a href="https://muse.ai/thread/${encodeURIComponent(job.threadId)}" target="_blank" rel="noopener noreferrer" onclick="event.stopPropagation()">Thread: ${escapeHtml(job.threadId)}</a><button type="button" class="copy-thread-btn" data-thread-id="${escapeHtml(job.threadId)}" onclick="copyThreadId(event, this.dataset.threadId)" title="Copy ID thread" aria-label="Copy ID thread">Copy ID</button>` : ''}
            <span>·</span>
            <span>${job.duration}s · ${job.ratio}</span>
            ${job.refTags && job.refTags.length ? `
              <span>·</span>
              <span class="text-indigo-400">@${job.refTags.join(', @')}</span>
            ` : ''}
            ${job.status === 'Đang chạy' ? `<span class="text-sky-400 font-bold">(${job.elapsedSec}s)</span>` : ''}
          </div>
        </div>

        <!-- Trạng thái & tiến độ % -->
        <div class="flex items-center gap-3 flex-shrink-0" onclick="toggleRowExpand('${job.id}')">
          <span class="status-badge ${statusClass}">
            ${job.status === 'Đang chạy' ? `<span class="w-1.5 h-1.5 rounded-full bg-sky-400 animate-ping"></span>` : ''}
            ${job.status} ${job.status === 'Đang chạy' ? `${job.progress}%` : ''}
          </span>
        </div>

        <!-- Thao tác: Tải MP4 & Xóa (Mục 6.3) -->
        <div class="flex items-center gap-2 flex-shrink-0">
          ${job.status === 'Hoàn thành' && job.videoUrl ? `
            <a href="${job.videoUrl}" download="${job.id}.mp4" onclick="event.stopPropagation()"
              class="btn-primary text-xs py-1.5 px-3 bg-gradient-to-r from-emerald-500 to-teal-600">
              ⬇ Tải MP4
            </a>
          ` : ''}
          ${job.status === 'Đang chạy' ? `
            <button type="button" onclick="rescanThread(event, '${job.id}')" class="btn-secondary text-xs py-1.5 px-2.5" ${!job.threadId || rescanningJobs.has(job.id) ? 'disabled' : ''} title="Mở lại thread cũ và quét kết quả, không gửi lại prompt">
              ${rescanningJobs.has(job.id) ? 'Đang quét lại…' : 'Quét lại thread'}
            </button>
          ` : ''}
          ${['Thất bại', 'Đã dừng'].includes(job.status) ? `
            <button onclick="retryJob(event, '${job.id}')" class="btn-secondary text-xs py-1.5 px-2.5" title="Chạy lại">
              🔄
            </button>
          ` : ''}
          <button onclick="deleteJob(event, '${job.id}')" class="text-slate-500 hover:text-red-400 text-lg px-1" title="Xóa job">
            &times;
          </button>
        </div>
      </div>

      <!-- Khung mở rộng xem full prompt, ảnh tham chiếu, player nhúng, lỗi (Mục 6.3) -->
      <div id="expand_${job.id}" class="hidden bg-slate-900/90 border border-t-0 border-slate-800 rounded-b-xl p-4 -mt-2 mb-2 text-xs space-y-3">
        <!-- Embedded Video Player khi phát (Mục 6.5) -->
        <div id="playerBox_${job.id}" class="hidden">
          <div class="flex justify-between items-center mb-2">
            <span class="font-bold text-slate-300">Xem trước video:</span>
            <button onclick="closeRowPlayer('${job.id}')" class="btn-secondary text-[11px] py-1 px-2">Đóng player ✕</button>
          </div>
          <video id="playerEl_${job.id}" controls class="w-full max-h-72 rounded-lg bg-black object-contain"></video>
        </div>

        <div>
          <span class="text-slate-400 font-semibold">Prompt đầy đủ:</span>
          <p class="text-slate-200 mt-1 font-sans bg-slate-950 p-2.5 rounded-lg border border-slate-800">${escapeHtml(job.prompt)}</p>
        </div>

        ${job.refTags && job.refTags.length ? `
          <div>
            <span class="text-slate-400 font-semibold">Ảnh tham chiếu đã gắn:</span>
            <div class="flex gap-2 mt-1">
              ${job.refTags.map(t => {
                const img = AppState.refImages.find(i => i.tag === t);
                return `
                  <div class="flex items-center gap-1.5 bg-slate-950 px-2 py-1 rounded border border-slate-800">
                    ${img ? `<img src="${img.url}" class="w-5 h-5 rounded object-cover">` : ''}
                    <span class="font-mono text-indigo-300">@${t}</span>
                  </div>
                `;
              }).join('')}
            </div>
          </div>
        ` : ''}

        ${job.error ? `
          <div class="p-2.5 rounded-lg bg-red-950/40 border border-red-500/30 text-red-300">
            <div class="font-bold">Chi tiết lỗi:</div>
            <div>${escapeHtml(job.error)}</div>
            ${job.errorCode ? `<div class="text-[10px] text-red-400 font-mono mt-1">Mã lỗi: ${job.errorCode}</div>` : ''}
          </div>
        ` : ''}
      </div>
    `;
  }).join('');
}

function toggleRowExpand(jobId) {
  const expandBox = document.getElementById(`expand_${jobId}`);
  const row = document.getElementById(`row_${jobId}`);
  if (expandBox) {
    const isHidden = expandBox.classList.contains('hidden');
    expandBox.classList.toggle('hidden');
    row.classList.toggle('expanded', isHidden);
  }
}

function toggleRowPlayer(e, jobId) {
  e.stopPropagation();
  const playerBox = document.getElementById(`playerBox_${jobId}`);
  const playerEl = document.getElementById(`playerEl_${jobId}`);
  const expandBox = document.getElementById(`expand_${jobId}`);

  if (!playerBox || !playerEl) return;

  expandBox.classList.remove('hidden');
  playerBox.classList.remove('hidden');
  
  if (!playerEl.src) {
    playerEl.src = `/api/media/${jobId}.mp4`;
  }
  playerEl.play().catch(() => {});
}

function closeRowPlayer(jobId) {
  const playerBox = document.getElementById(`playerBox_${jobId}`);
  const playerEl = document.getElementById(`playerEl_${jobId}`);
  if (playerBox && playerEl) {
    playerEl.pause();
    playerBox.classList.add('hidden');
  }
}

async function retryJob(e, jobId) {
  e.stopPropagation();
  try {
    await fetch(`/api/queue/retry/${jobId}`, { method: 'POST' });
    showToast(`Đã đưa job ${jobId} về Chờ chạy lại`, 'info');
    loadJobs();
  } catch (e) {
    showToast('Lỗi: ' + e.message, 'error');
  }
}

async function deleteJob(e, jobId) {
  e.stopPropagation();
  try {
    await fetch(`/api/queue/jobs/${jobId}`, { method: 'DELETE' });
    loadJobs();
  } catch (e) {
    showToast('Lỗi xóa: ' + e.message, 'error');
  }
}

async function clearFinishedJobs() {
  try {
    const res = await fetch('/api/queue/clear-finished', { method: 'POST' });
    const data = await res.json();
    showToast(`Đã dọn ${data.clearedCount} job hoàn thành`, 'info');
    loadJobs();
  } catch (e) {
    showToast('Lỗi dọn: ' + e.message, 'error');
  }
}

// =========================================================================
// 7. State Polling & Dải Trực Tiếp (Mục 6.4 & 8.5)
// =========================================================================
function startStatePolling() {
  setInterval(async () => {
    try {
      const res = await fetch('/api/state');
      const state = await res.json();
      const prevRunning = AppState.systemState ? (AppState.systemState.counts['Đang chạy'] || 0) : -1;
      const prevCompleted = AppState.systemState ? (AppState.systemState.counts['Hoàn thành'] || 0) : -1;

      AppState.systemState = state;
      if (!AppState.concurrencyInitialized && Number.isInteger(state.configuredConcurrency)) {
        document.getElementById('inpConcurrency').value = state.configuredConcurrency;
        AppState.concurrencyInitialized = true;
      }
      if (!AppState.concurrencyDirty) {
        if (state.concurrencyProtocol === 2) {
          renderConcurrencyStatus(state.configuredConcurrency, state.activeTasksCount);
        } else {
          document.getElementById('concurrencyStatus').textContent = 'Server cũ: cần khởi động lại tool để nhận cấu hình mới';
        }
      }
      updateHeaderCounters(state);
      renderLiveRunningStrip(state.runningJobs || []);

      const currRunning = state.counts['Đang chạy'] || 0;
      const currCompleted = state.counts['Hoàn thành'] || 0;

      // Tự động làm mới bảng danh sách job nếu đang ở tab Hàng đợi
      const modQueue = document.getElementById('moduleQueue') || document.getElementById('modQueue');
      if (modQueue && !modQueue.classList.contains('hidden')) {
        const hasOpenPlayer = !!document.querySelector('[id^="playerBox_"]:not(.hidden)');
        if (!hasOpenPlayer) {
          // Cập nhật khi có job đang chạy hoặc trạng thái số lượng job thay đổi
          if (currRunning > 0 || currRunning !== prevRunning || currCompleted !== prevCompleted) {
            await loadJobs();
          }
        }
      }
    } catch (e) {
      document.getElementById('logConnectionStatus').textContent = 'Mất kết nối tới tool. Đang thử lại…';
      console.error('Polling state error:', e);
    }
  }, 2000); // Làm mới tiến độ mỗi 2 giây (Mục 6.4)
}

function updateHeaderCounters(state) {
  document.getElementById('cntRunning').textContent = state.counts['Đang chạy'] || 0;
  document.getElementById('cntWaiting').textContent = state.counts['Chờ'] || 0;
  document.getElementById('cntCompleted').textContent = state.counts['Hoàn thành'] || 0;

  const statusBadge = document.getElementById('connectionStatusBadge');
  const txtStatus = document.getElementById('txtConnectionStatus');
  if (state.isSystemOnline) {
    statusBadge.className = 'flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20';
    txtStatus.textContent = 'Online';
  } else {
    statusBadge.className = 'flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-red-500/10 text-red-400 border border-red-500/20';
    txtStatus.textContent = 'Offline';
  }
}

function renderLiveRunningStrip(runningJobs) {
  const strip = document.getElementById('liveRunningStrip');
  const countEl = document.getElementById('txtLiveStripCount');
  const itemsContainer = document.getElementById('liveRunningItems');

  if (!runningJobs.length) {
    strip.classList.add('hidden');
    return;
  }

  // Mục 6.4 & AC-06: Chỉ hiện khi có ít nhất 1 job đang chạy. Mọi video chạy phải hiện cùng lúc!
  strip.classList.remove('hidden');
  countEl.textContent = runningJobs.length;

  itemsContainer.innerHTML = runningJobs.map(j => `
    <div class="running-card">
      <div class="w-10 h-10 rounded-lg bg-slate-900 border border-slate-700 flex items-center justify-center font-bold text-xs text-sky-400 flex-shrink-0">
        ${j.progress}%
      </div>
      <div class="flex-1 min-w-0">
        <div class="flex justify-between items-center text-xs">
          <span class="font-mono text-slate-300 font-semibold truncate">${j.id}</span>
          <span class="font-mono text-sky-300 text-[11px] font-bold">${j.elapsedSec}s</span>
        </div>
        <p class="text-[11px] text-slate-400 truncate mt-0.5">${escapeHtml(j.prompt)}</p>
        <div class="progress-bar-bg">
          <div class="progress-bar-fill" style="width: ${j.progress}%"></div>
        </div>
      </div>
    </div>
  `).join('');
}

// =========================================================================
// 8. Account Pool Management (Mục 2.1 & AC-12)
// =========================================================================
async function loadAccounts() {
  try {
    const res = await fetch('/api/accounts');
    const data = await res.json();
    AppState.accounts = data || [];
    document.getElementById('txtAccountCount').textContent = AppState.accounts.length;
    renderAccountsModal();
  } catch (e) {
    console.error('Lỗi tải tài khoản:', e);
  }
}

function openAccountModal() {
  loadAccounts();
  loadMachineInfo();
  const m = document.getElementById('modalAccount');
  m.classList.remove('hidden');
  m.classList.add('flex');
}

function closeAccountModal() {
  const m = document.getElementById('modalAccount');
  m.classList.add('hidden');
  m.classList.remove('flex');
}

function renderAccountsModal() {
  const container = document.getElementById('accountListContainer');
  if (!AppState.accounts.length) {
    container.innerHTML = '<div class="text-xs text-slate-500 py-3 text-center">Chưa có tài khoản nào trong pool.</div>';
    return;
  }

  container.innerHTML = AppState.accounts.map(acc => `
    <div class="flex items-center justify-between p-3 rounded-xl bg-slate-900 border border-slate-800 text-xs">
      <div class="space-y-0.5">
        <div class="flex items-center gap-2">
          <span class="font-bold text-slate-200">${acc.masked_identifier}</span>
          <span class="px-2 py-0.5 rounded text-[10px] font-bold ${acc.status === 'Online' ? 'bg-emerald-500/20 text-emerald-400' : 'bg-slate-700 text-slate-400'}">
            ${acc.status}
          </span>
          <span class="px-2 py-0.5 rounded text-[10px] font-semibold bg-slate-800 text-slate-300">
            ${acc.session_health}
          </span>
        </div>
        <div class="text-[11px] text-slate-400">
          Job đang chạy: <strong class="text-slate-200">${acc.active_jobs}</strong> / ${acc.max_slots} slot · ${acc.health_reason}
        </div>
      </div>

      <div class="flex items-center gap-2">
        <button onclick="toggleAccountEnabled('${acc.id}', ${!acc.enabled})" class="btn-secondary text-[11px] py-1 px-2.5">
          ${acc.enabled ? 'Tắt' : 'Bật'}
        </button>
        <button onclick="checkAccountHealth('${acc.id}')" class="btn-secondary text-[11px] py-1 px-2" title="Kiểm tra kết nối">
          🩺
        </button>
        <button onclick="deleteAccount('${acc.id}')" class="text-slate-500 hover:text-red-400 text-base px-2">
          &times;
        </button>
      </div>
    </div>
  `).join('');
}

async function loadMachineInfo() {
  const field = document.getElementById('machineId');
  const copy = document.getElementById('btnCopyMachineId');
  const info = document.getElementById('machineLicenseInfo');
  try {
    const response = await fetch('/api/machine');
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || 'Không đọc được mã máy');
    field.value = data.machineId;
    copy.disabled = false;
    const header = document.getElementById('headerMachineId');
    const headerButton = document.getElementById('btnHeaderMachineId');
    if (header && headerButton) {
      header.textContent = data.machineId;
      headerButton.title = `Copy mã máy: ${data.machineId}`;
      headerButton.disabled = false;
    }
    if (!data.firebaseConfigured) {
      info.textContent = data.configError || 'Chưa cấu hình Firebase: điền databaseURL trong firebase_config.json. Mã máy vẫn có thể copy để đăng ký.';
    } else if (data.lastCheck) {
      const limit = data.lastCheck.maxAccounts == null ? 'không giới hạn' : data.lastCheck.maxAccounts;
      info.textContent = `Đã lưu ${data.savedAccounts} tài khoản · lần kiểm tra gần nhất: ${data.lastCheck.status} (${limit}). Chỉ kiểm tra lại khi thêm tài khoản.`;
    } else {
      info.textContent = `Đã lưu ${data.savedAccounts} tài khoản · chưa kiểm tra Firebase. Status sẽ được đọc khi thêm tài khoản.`;
    }
  } catch (error) {
    field.value = '';
    copy.disabled = true;
    info.textContent = error.message;
    const header = document.getElementById('headerMachineId');
    const headerButton = document.getElementById('btnHeaderMachineId');
    if (header && headerButton) {
      header.textContent = 'Mã máy: chưa đọc được';
      headerButton.title = error.message;
      headerButton.disabled = true;
    }
  }
}

async function copyMachineId(event) {
  event.stopPropagation();
  const field = document.getElementById('machineId');
  if (!/^MUSE-(?:[0-9A-F]{4}-){3}[0-9A-F]{4}$/.test(field.value)) return;
  try {
    try {
      await navigator.clipboard.writeText(field.value);
    } catch (_) {
      field.focus();
      field.select();
      if (!document.execCommand('copy')) throw new Error('Không thể copy mã máy');
    }
    showToast('Đã copy mã máy', 'success');
  } catch (error) { showToast(error.message, 'error'); }
}

async function submitNewAccount() {
  const identifier = document.getElementById('inpAccIdentifier').value.trim();
  const credentials = document.getElementById('inpAccCredential').value.trim();

  if (!credentials) {
    showToast('Vui lòng nhập Session Token hoặc Cookie!', 'error');
    return;
  }

  const button = document.getElementById('btnAddAccount');
  if (button.disabled) return;
  button.disabled = true;
  button.textContent = 'Đang kiểm tra Firebase…';
  try {
    const res = await fetch('/api/accounts', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ identifier, credentials })
    });
    if (!res.ok) {
      const err = await res.json();
      const message = err.detail || 'Lỗi thêm tài khoản';
      document.getElementById('machineLicenseInfo').textContent = message;
      showToast(message, 'error');
      return;
    }
    document.getElementById('inpAccIdentifier').value = '';
    document.getElementById('inpAccCredential').value = '';
    showToast('Đã thêm tài khoản thành công (Mã hóa an toàn)!', 'success');
    loadAccounts();
    await loadMachineInfo();
  } catch (e) {
    showToast('Lỗi: ' + e.message, 'error');
  } finally {
    button.disabled = false;
    button.textContent = '+ Thêm vào Pool';
  }
}

async function toggleAccountEnabled(aid, enabled) {
  try {
    await fetch(`/api/accounts/${aid}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled })
    });
    loadAccounts();
  } catch (e) {
    showToast('Lỗi: ' + e.message, 'error');
  }
}

async function checkAccountHealth(aid) {
  try {
    const res = await fetch(`/api/accounts/${aid}/health`);
    const data = await res.json();
    showToast(`Sức khỏe: ${data.status} — ${data.reason}`, data.online ? 'success' : 'warn');
    loadAccounts();
  } catch (e) {
    showToast('Lỗi: ' + e.message, 'error');
  }
}

async function deleteAccount(aid) {
  if (!confirm('Xác nhận xóa tài khoản này khỏi pool? Hành vi này không thể khôi phục.')) return;
  try {
    await fetch(`/api/accounts/${aid}`, { method: 'DELETE' });
    showToast('Đã xóa tài khoản khỏi pool!', 'info');
    loadAccounts();
  } catch (e) {
    showToast('Lỗi: ' + e.message, 'error');
  }
}

// =========================================================================
// 9. Flow Studio — Canvas Kéo Thả (Mục 7 & AC-11)
// =========================================================================
async function loadStudioCards() {
  try {
    const res = await fetch('/api/studio/cards');
    const data = await res.json();
    AppState.studioCards = data || [];
    renderStudioCards();
  } catch (e) {
    console.error('Lỗi tải thẻ studio:', e);
  }
}

function initCanvasEvents() {
  const container = document.getElementById('flowCanvasContainer');
  const viewport = document.getElementById('flowCanvasViewport');

  // Zoom bằng chuột lăn + Ctrl (Mục 7.1)
  container.addEventListener('wheel', (e) => {
    if (e.ctrlKey || e.metaKey) {
      e.preventDefault();
      if (e.deltaY < 0) zoomIn();
      else zoomOut();
    }
  }, { passive: false });

  // Pan Canvas
  container.addEventListener('mousedown', (e) => {
    if (e.target === container || e.target === viewport) {
      AppState.isPanning = true;
      AppState.panStartX = e.clientX - AppState.panX;
      AppState.panStartY = e.clientY - AppState.panY;
      viewport.classList.add('dragging');
    }
  });

  window.addEventListener('mousemove', (e) => {
    if (AppState.isPanning) {
      AppState.panX = e.clientX - AppState.panStartX;
      AppState.panY = e.clientY - AppState.panStartY;
      updateCanvasTransform();
    }
  });

  window.addEventListener('mouseup', () => {
    AppState.isPanning = false;
    viewport.classList.remove('dragging');
  });
}

function zoomIn() {
  AppState.zoomLevel = Math.min(2.0, AppState.zoomLevel + 0.1);
  updateCanvasTransform();
}

function zoomOut() {
  AppState.zoomLevel = Math.max(0.4, AppState.zoomLevel - 0.1);
  updateCanvasTransform();
}

function zoomFit() {
  AppState.zoomLevel = 1.0;
  AppState.panX = 0;
  AppState.panY = 0;
  updateCanvasTransform();
}

function updateCanvasTransform() {
  const viewport = document.getElementById('flowCanvasViewport');
  viewport.style.transform = `translate(${AppState.panX}px, ${AppState.panY}px) scale(${AppState.zoomLevel})`;
  document.getElementById('txtZoomLevel').textContent = `${Math.round(AppState.zoomLevel * 100)}%`;
}

function renderStudioCards() {
  const viewport = document.getElementById('flowCanvasViewport');
  viewport.innerHTML = AppState.studioCards.map(c => `
    <div class="studio-card" id="scard_${c.id}" style="left: ${c.x}px; top: ${c.y}px;" onmousedown="startDragCard(event, '${c.id}')">
      <!-- Header kéo thẻ (Mục 7.1) -->
      <div class="studio-card-header">
        <span class="text-xs font-bold text-slate-300 font-mono">Thẻ #${c.id.substring(5)}</span>
        <div class="flex items-center gap-2">
          <span class="px-2 py-0.5 rounded text-[10px] font-bold ${getStudioStatusClass(c.status)}">
            ${c.status}
          </span>
          <button onclick="deleteStudioCard('${c.id}')" class="text-slate-400 hover:text-red-400 text-sm">&times;</button>
        </div>
      </div>

      <!-- Preview ảnh hoặc Video kết quả nhúng (Mục 7.2 & AC-11) -->
      <div class="p-3 space-y-2.5">
        ${c.status === 'đã tạo' && c.videoUrl ? `
          <div class="space-y-2">
            <video src="${c.videoUrl}" controls autoplay class="w-full h-44 rounded-lg bg-black object-contain"></video>
            <div class="flex justify-between items-center text-xs">
              <span class="font-bold text-emerald-400 flex items-center gap-1">
                <span>✓</span> Video đã tạo
              </span>
              <span class="px-2 py-0.5 rounded bg-indigo-500/20 text-indigo-300 font-bold font-mono text-[10px]">
                ${c.qualityBadge || 'HD'}
              </span>
            </div>
            <a href="${c.videoUrl}" download="${c.id}.mp4" class="btn-primary w-full justify-center text-xs py-1.5 bg-gradient-to-r from-emerald-500 to-teal-600">
              ⬇ Tải xuống MP4
            </a>
          </div>
        ` : `
          <div class="relative w-full h-40 rounded-lg overflow-hidden bg-slate-900 border border-slate-800">
            <img src="${c.imageUrl}" class="w-full h-full object-cover">
          </div>
        `}

        <!-- Ô prompt riêng hỗ trợ @tag (Mục 7.2) -->
        <div>
          <label class="block text-[11px] font-semibold text-slate-400 mb-1">Mô tả video (Prompt):</label>
          <textarea rows="2" onchange="updateStudioCardPrompt('${c.id}', this.value)"
            class="w-full bg-slate-900 border border-slate-700 rounded-lg px-2.5 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-indigo-500 resize-none font-sans"
            placeholder="Nhập prompt hoặc gõ @tag...">${escapeHtml(c.prompt)}</textarea>
        </div>
      </div>
    </div>
  `).join('');
}

function getStudioStatusClass(st) {
  if (st === 'đã tạo') return 'bg-emerald-500/20 text-emerald-300';
  if (st === 'đang tạo') return 'bg-sky-500/20 text-sky-300 animate-pulse';
  if (st === 'lỗi') return 'bg-red-500/20 text-red-300';
  return 'bg-slate-800 text-slate-400';
}

function startDragCard(e, cardId) {
  if (['TEXTAREA', 'BUTTON', 'A', 'INPUT', 'VIDEO'].includes(e.target.tagName)) return;
  e.preventDefault();

  const cardEl = document.getElementById(`scard_${cardId}`);
  const startX = e.clientX;
  const startY = e.clientY;
  const origLeft = parseInt(cardEl.style.left) || 0;
  const origTop = parseInt(cardEl.style.top) || 0;

  function onMouseMove(moveEvent) {
    const dx = (moveEvent.clientX - startX) / AppState.zoomLevel;
    const dy = (moveEvent.clientY - startY) / AppState.zoomLevel;
    cardEl.style.left = `${origLeft + dx}px`;
    cardEl.style.top = `${origTop + dy}px`;
  }

  function onMouseUp() {
    window.removeEventListener('mousemove', onMouseMove);
    window.removeEventListener('mouseup', onMouseUp);
    // Lưu tọa độ thẻ vào backend
    const finalX = parseInt(cardEl.style.left) || 0;
    const finalY = parseInt(cardEl.style.top) || 0;
    fetch(`/api/studio/cards/${cardId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ x: finalX, y: finalY })
    });
  }

  window.addEventListener('mousemove', onMouseMove);
  window.addEventListener('mouseup', onMouseUp);
}

async function addCardFromUpload() {
  if (AppState.refImages.length) {
    // Cho chọn từ kho hoặc upload
    const img = AppState.refImages[0];
    await createStudioCard(img.url, `@${img.tag} chuyển động điện ảnh mượt mà`);
  } else {
    // Mở upload modal
    openUploadModal();
  }
}

async function createStudioCard(imageUrl, prompt = '') {
  try {
    const res = await fetch('/api/studio/cards', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ imageUrl, prompt })
    });
    const data = await res.json();
    AppState.studioCards.push(data.card);
    renderStudioCards();
    showToast('Đã thêm thẻ mới vào Flow Studio!', 'success');
  } catch (e) {
    showToast('Lỗi: ' + e.message, 'error');
  }
}

async function updateStudioCardPrompt(cardId, prompt) {
  try {
    await fetch(`/api/studio/cards/${cardId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt })
    });
  } catch (e) {
    console.error(e);
  }
}

async function deleteStudioCard(cardId) {
  try {
    await fetch(`/api/studio/cards/${cardId}`, { method: 'DELETE' });
    AppState.studioCards = AppState.studioCards.filter(c => c.id !== cardId);
    renderStudioCards();
  } catch (e) {
    showToast('Lỗi xóa thẻ: ' + e.message, 'error');
  }
}

async function generateAllStudioCards() {
  try {
    const res = await fetch('/api/studio/generate-all', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ duration: 15, ratio: '9:16' })
    });
    const data = await res.json();
    if (data.count > 0) {
      showToast(`▶ Đang đưa ${data.count} thẻ vào hàng đợi tạo video!`, 'success');
      loadStudioCards();
    } else {
      showToast('Không có thẻ nào cần tạo.', 'info');
    }
  } catch (e) {
    showToast('Lỗi: ' + e.message, 'error');
  }
}

// =========================================================================
// Helpers & Toasts
// =========================================================================
function showToast(msg, type = 'info', onUndo = null) {
  const container = document.getElementById('toastContainer');
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;

  const textSpan = document.createElement('span');
  textSpan.textContent = msg;
  toast.appendChild(textSpan);

  if (onUndo) {
    const undoBtn = document.createElement('button');
    undoBtn.className = 'px-2 py-0.5 rounded bg-white/20 hover:bg-white/30 text-white text-xs font-bold transition ml-2';
    undoBtn.textContent = 'Hoàn tác';
    undoBtn.onclick = () => {
      onUndo();
      toast.remove();
    };
    toast.appendChild(undoBtn);
  }

  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateY(20px)';
    setTimeout(() => toast.remove(), 300);
  }, onUndo ? 6000 : 4000);
}

function escapeHtml(text) {
  if (!text) return '';
  return String(text)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}
