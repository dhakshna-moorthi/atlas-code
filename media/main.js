const vscode = acquireVsCodeApi();

// ── main UI ──
const chat = document.getElementById('chat');
const input = document.getElementById('input');
const sendBtn = document.getElementById('send-btn');
const contextBar = document.getElementById('context-bar');
const clearBtn = document.getElementById('clear-btn');
const inputRow = document.getElementById('input-row');

let attachedFiles = [];
let empty = document.getElementById('empty');
let waiting = false;

const ATLAS_ICON = `<svg width="13" height="13" viewBox="0 0 22 22" fill="none" xmlns="http://www.w3.org/2000/svg">
  <line x1="11" y1="4.5" x2="11" y2="13" stroke="#3bbfb0" stroke-width="1.3" stroke-linecap="round"/>
  <line x1="11" y1="4.5" x2="3.5" y2="19" stroke="#3bbfb0" stroke-width="1.3" stroke-linecap="round"/>
  <line x1="11" y1="4.5" x2="18.5" y2="19" stroke="#3bbfb0" stroke-width="1.3" stroke-linecap="round"/>
  <line x1="11" y1="13" x2="3.5" y2="19" stroke="#3bbfb0" stroke-width="1.3" stroke-linecap="round"/>
  <line x1="11" y1="13" x2="18.5" y2="19" stroke="#3bbfb0" stroke-width="1.3" stroke-linecap="round"/>
  <circle cx="11" cy="4.5" r="2" fill="#3bbfb0"/>
  <circle cx="11" cy="13" r="2" fill="#3bbfb0"/>
  <circle cx="3.5" cy="19" r="2" fill="#3bbfb0"/>
  <circle cx="18.5" cy="19" r="2" fill="#3bbfb0"/>
</svg>`;

function escHtml(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function inlineFormat(s) {
  return escHtml(s)
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/\*([^*]+)\*/g, '<em>$1</em>');
}

function renderMarkdown(raw) {
  const segments = [];
  const codeRe = /```(\w*)\r?\n?([\s\S]*?)```/g;
  let last = 0, m;
  while ((m = codeRe.exec(raw)) !== null) {
    if (m.index > last) segments.push({ type: 'text', src: raw.slice(last, m.index) });
    segments.push({ type: 'code', lang: m[1] || '', src: m[2].trimEnd() });
    last = m.index + m[0].length;
  }
  if (last < raw.length) segments.push({ type: 'text', src: raw.slice(last) });

  function processText(src) {
    let html = '';
    const lines = src.split('\n');
    let listItems = [];

    function flushList() {
      if (listItems.length) {
        html += '<ul>' + listItems.map(li => `<li>${li}</li>`).join('') + '</ul>';
        listItems = [];
      }
    }

    for (const line of lines) {
      const h3 = line.match(/^###\s+(.+)/);
      const h2 = line.match(/^##\s+(.+)/);
      const h1 = line.match(/^#\s+(.+)/);
      const li = line.match(/^[-*]\s+(.+)/);

      if (h3)             { flushList(); html += `<h3>${inlineFormat(h3[1])}</h3>`; }
      else if (h2)        { flushList(); html += `<h2>${inlineFormat(h2[1])}</h2>`; }
      else if (h1)        { flushList(); html += `<h1>${inlineFormat(h1[1])}</h1>`; }
      else if (li)        { listItems.push(inlineFormat(li[1])); }
      else if (!line.trim()) { flushList(); html += '<div class="md-gap"></div>'; }
      else                { flushList(); html += `<p>${inlineFormat(line)}</p>`; }
    }
    flushList();
    return html;
  }

  let html = '';
  for (const seg of segments) {
    if (seg.type === 'code') {
      const lang = escHtml(seg.lang);
      html += `<div class="code-block">
        <div class="code-header">
          <span class="code-lang">${lang || 'code'}</span>
          <button class="copy-btn">copy</button>
        </div>
        <pre><code>${escHtml(seg.src)}</code></pre>
      </div>`;
    } else {
      html += processText(seg.src);
    }
  }
  return html;
}

chat.addEventListener('click', e => {
  const btn = e.target.closest('.copy-btn');
  if (!btn) return;
  const code = btn.closest('.code-block').querySelector('code').textContent;
  navigator.clipboard.writeText(code).then(() => {
    btn.textContent = 'copied!';
    setTimeout(() => { btn.textContent = 'copy'; }, 2000);
  });
});

function makeEmptyState() {
  const e = document.createElement('div');
  e.id = 'empty';
  e.innerHTML = `
    <div class="big-logo">
      <svg width="64" height="64" viewBox="0 0 22 22" fill="none" xmlns="http://www.w3.org/2000/svg">
        <line x1="11" y1="4.5" x2="11" y2="13" stroke="#3bbfb0" stroke-width="1.3" stroke-linecap="round"/>
        <line x1="11" y1="4.5" x2="3.5" y2="19" stroke="#3bbfb0" stroke-width="1.3" stroke-linecap="round"/>
        <line x1="11" y1="4.5" x2="18.5" y2="19" stroke="#3bbfb0" stroke-width="1.3" stroke-linecap="round"/>
        <line x1="11" y1="13" x2="3.5" y2="19" stroke="#3bbfb0" stroke-width="1.3" stroke-linecap="round"/>
        <line x1="11" y1="13" x2="18.5" y2="19" stroke="#3bbfb0" stroke-width="1.3" stroke-linecap="round"/>
        <circle cx="11" cy="4.5" r="2" fill="#3bbfb0"/>
        <circle cx="11" cy="13" r="2" fill="#3bbfb0"/>
        <circle cx="3.5" cy="19" r="2" fill="#3bbfb0"/>
        <circle cx="18.5" cy="19" r="2" fill="#3bbfb0"/>
      </svg>
    </div>
    <div class="empty-title">What do you want to build?</div>
    <div class="tagline">Read, write, debug, and refactor<br>your code with Atlas.</div>`;
  return e;
}

clearBtn.addEventListener('click', () => {
  vscode.postMessage({ type: 'clearChat' });
  chat.innerHTML = '';
  attachedFiles = [];
  contextBar.innerHTML = '';
  const e = makeEmptyState();
  chat.appendChild(e);
  empty = e;
});

function removeEmpty() {
  if (empty) { empty.remove(); empty = null; }
}

function addPill(filename) {
  const pill = document.createElement('div');
  pill.className = 'pill';
  pill.innerHTML = `${escHtml(filename)} <button title="Remove">×</button>`;
  pill.querySelector('button').addEventListener('click', () => {
    attachedFiles = attachedFiles.filter(f => f !== filename);
    pill.remove();
  });
  contextBar.appendChild(pill);
}

function appendMessage(role, text, files = []) {
  removeEmpty();
  const msg = document.createElement('div');
  msg.className = 'msg ' + role;

  if (role === 'user') {
    let html = '';
    if (files.length > 0) {
      html += `<div class="context-pills">${files.map(f => `<div class="pill">${escHtml(f)}</div>`).join('')}</div>`;
    }
    html += `<div class="msg-body">${escHtml(text)}</div>`;
    msg.innerHTML = html;
  } else {
    msg.innerHTML = `
      <div class="msg-header">
        ${ATLAS_ICON}
        <span class="msg-label">Atlas</span>
      </div>
      <div class="msg-content">${renderMarkdown(text)}</div>`;
  }

  chat.appendChild(msg);
  chat.scrollTop = chat.scrollHeight;
}

function showThinking() {
  removeEmpty();
  const t = document.createElement('div');
  t.className = 'msg agent';
  t.id = 'thinking';
  t.innerHTML = `
    <div class="msg-header">
      ${ATLAS_ICON}
      <span class="msg-label">Atlas</span>
    </div>
    <details class="steps-thread" open>
      <summary class="steps-summary">
        <span class="steps-chevron">›</span>
        <span class="steps-label">Working</span>
      </summary>
      <div class="steps-list"></div>
    </details>`;
  chat.appendChild(t);
  chat.scrollTop = chat.scrollHeight;
}

// #input is contenteditable, so it grows/shrinks with its content natively
// (CSS min/max-height + overflow-y handle the bounds) — no manual resize JS needed.

function setWaiting(on) {
  waiting = on;
  sendBtn.disabled = on;
  input.contentEditable = on ? 'false' : 'true';
  clearBtn.disabled = on;
}

function send() {
  if (waiting) return;
  const text = input.textContent.trim();
  if (!text) return;
  hideMentionDropdown();
  const pillFiles = [...attachedFiles];
  const mentionFiles = [...new Set([...input.querySelectorAll('.mention-token')].map(el => el.dataset.file))];
  const allFiles = [...new Set([...pillFiles, ...mentionFiles])];
  // inline @mentions are real chip elements in the input already, so only
  // externally-attached files get a pill in the chat log — no duplicate tagging
  appendMessage('user', text, pillFiles);
  input.innerHTML = '';
  attachedFiles = [];
  contextBar.innerHTML = '';
  setWaiting(true);
  showThinking();
  vscode.postMessage({ type: 'userMessage', text, files: allFiles, model: 'gpt-5.4-nano' });
}

sendBtn.addEventListener('click', send);

// ── @ file mentions ──
// Typing '@' opens a dropdown of workspace files (fetched from the extension
// host); picking one turns it into a real, atomic chip element (.mention-token)
// inserted at the caret — a genuine part of the contenteditable content, so
// the browser's own cursor/selection logic handles it correctly.
let mentionDropdown = null;
let mentionItems = [];
let mentionIndex = 0;
let mentionActive = false;
let mentionQueryLen = 0;   // characters typed after '@' so far, for backspacing on select
let workspaceFiles = null;

function ensureMentionDropdown() {
  if (!mentionDropdown) {
    mentionDropdown = document.createElement('div');
    mentionDropdown.id = 'file-dropdown';
    inputRow.appendChild(mentionDropdown);
  }
  return mentionDropdown;
}

function hideMentionDropdown() {
  if (mentionDropdown) mentionDropdown.style.display = 'none';
  mentionActive = false;
  mentionQueryLen = 0;
  mentionItems = [];
  mentionIndex = 0;
}

// Text from the start of the input up to the caret, as a plain string —
// the contenteditable equivalent of `input.value.slice(0, selectionStart)`.
function textBeforeCaret() {
  const sel = window.getSelection();
  if (!sel || sel.rangeCount === 0 || !input.contains(sel.anchorNode)) return '';
  const caret = sel.getRangeAt(0);
  const range = document.createRange();
  range.selectNodeContents(input);
  range.setEnd(caret.endContainer, caret.endOffset);
  return range.toString();
}

function detectMention() {
  const before = textBeforeCaret();
  const m = before.match(/(?:^|[\s])@([^\s@]*)$/);
  if (!m) { hideMentionDropdown(); return; }
  mentionActive = true;
  mentionQueryLen = m[1].length;
  // Always re-request so newly created files show up; render immediately from
  // cache when we have one, and again when the fresh list arrives.
  vscode.postMessage({ type: 'requestFiles' });
  if (workspaceFiles !== null) {
    renderMentionDropdown();
  }
}

// Derives the current @query itself from the live caret position, so every
// call site (typing, or the fileList response arriving mid-type) stays in sync.
function renderMentionDropdown() {
  if (!mentionActive || workspaceFiles === null) { hideMentionDropdown(); return; }
  const before = textBeforeCaret();
  const m = before.match(/(?:^|[\s])@([^\s@]*)$/);
  if (!m) { hideMentionDropdown(); return; }
  mentionQueryLen = m[1].length;

  const query = m[1].toLowerCase();
  const scored = [];
  for (const f of workspaceFiles) {
    const lower = f.toLowerCase();
    const base = lower.split(/[\\/]/).pop();
    if (!query) { scored.push({ f, s: 0 }); }
    else if (base.startsWith(query)) { scored.push({ f, s: 2 }); }
    else if (lower.includes(query)) { scored.push({ f, s: 1 }); }
  }
  scored.sort((a, b) => b.s - a.s || a.f.localeCompare(b.f));
  mentionItems = scored.slice(0, 30).map(x => x.f);
  mentionIndex = 0;

  if (!mentionItems.length) { hideMentionDropdown(); return; }

  const dd = ensureMentionDropdown();
  dd.innerHTML = mentionItems.map((f, i) => {
    const parts = f.split(/[\\/]/);
    const base = parts.pop();
    const dir = parts.join('/');
    return `<div class="file-option${i === mentionIndex ? ' selected' : ''}" data-index="${i}">
      <span class="file-name">${escHtml(base)}</span>${dir ? `<span class="file-dir">${escHtml(dir)}</span>` : ''}
    </div>`;
  }).join('');
  dd.style.display = 'block';

  dd.querySelectorAll('.file-option').forEach(el => {
    el.addEventListener('mousedown', e => {
      e.preventDefault(); // keep focus in the textarea
      selectMention(Number(el.dataset.index));
    });
  });
}

function highlightMention() {
  if (!mentionDropdown) return;
  mentionDropdown.querySelectorAll('.file-option').forEach((el, i) => {
    el.classList.toggle('selected', i === mentionIndex);
    if (i === mentionIndex) el.scrollIntoView({ block: 'nearest' });
  });
}

function selectMention(index) {
  const file = mentionItems[index];
  const sel = window.getSelection();
  if (!file || !mentionActive || !sel || sel.rangeCount === 0) return;

  // Remove the typed '@query' just before the caret (+1 for the '@' itself).
  // Selection.modify walks backward by real characters/nodes, so it correctly
  // treats an earlier mention chip as one atomic unit rather than text to split.
  sel.collapseToEnd();
  const deleteCount = mentionQueryLen + 1;
  for (let i = 0; i < deleteCount; i++) sel.modify('extend', 'backward', 'character');
  let range = sel.getRangeAt(0);
  range.deleteContents();

  // Insert a real, atomic chip (not editable itself) plus a trailing space
  // text node so the caret lands in normal editable text right after it.
  const chip = document.createElement('span');
  chip.className = 'mention-token';
  chip.setAttribute('contenteditable', 'false');
  chip.dataset.file = file;
  chip.textContent = '@' + file;
  range.insertNode(chip);

  const space = document.createTextNode(' ');
  chip.after(space);

  range = document.createRange();
  range.setStartAfter(space);
  range.collapse(true);
  sel.removeAllRanges();
  sel.addRange(range);

  hideMentionDropdown();
  input.focus();
}

input.addEventListener('input', () => {
  // Chromium sometimes leaves a stray empty node after the last character is
  // deleted, which defeats the #input:empty::before placeholder — force it.
  if (!input.textContent) input.innerHTML = '';
  detectMention();
});

input.addEventListener('blur', () => {
  // slight delay so a mousedown on the dropdown can land first
  setTimeout(hideMentionDropdown, 150);
});

// Insert a literal newline character (not a <br>/<div>) so white-space:pre-wrap
// renders it as a line break while input.textContent stays plain, lossless text.
function insertNewlineAtCaret() {
  const sel = window.getSelection();
  if (!sel || sel.rangeCount === 0) return;
  const range = sel.getRangeAt(0);
  range.deleteContents();
  const node = document.createTextNode('\n');
  range.insertNode(node);
  range.setStartAfter(node);
  range.collapse(true);
  sel.removeAllRanges();
  sel.addRange(range);
}

input.addEventListener('keydown', e => {
  const dropdownOpen = mentionActive && mentionDropdown && mentionDropdown.style.display === 'block' && mentionItems.length;
  if (dropdownOpen) {
    if (e.key === 'ArrowDown') { e.preventDefault(); mentionIndex = (mentionIndex + 1) % mentionItems.length; highlightMention(); return; }
    if (e.key === 'ArrowUp')   { e.preventDefault(); mentionIndex = (mentionIndex - 1 + mentionItems.length) % mentionItems.length; highlightMention(); return; }
    if (e.key === 'Enter' || e.key === 'Tab') { e.preventDefault(); selectMention(mentionIndex); return; }
    if (e.key === 'Escape') { e.preventDefault(); hideMentionDropdown(); return; }
  }
  if (e.key === 'Enter' && e.shiftKey) { e.preventDefault(); insertNewlineAtCaret(); return; }
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
});

// ── finalize an agent turn (success or error) ──
// Both paths run through here so the input is ALWAYS unlocked at the end.
function finalizeTurn(text, isError) {
  const thinking = document.getElementById('thinking');
  const contentHtml = isError
    ? `<div class="error-note">${escHtml(text)}</div>`
    : renderMarkdown(text);

  if (thinking) {
    thinking.removeAttribute('id');
    const details = thinking.querySelector('.steps-thread');
    const stepsList = thinking.querySelector('.steps-list');
    const stepCount = stepsList ? stepsList.children.length : 0;
    if (stepCount > 0) {
      const currentStep = thinking.querySelector('.step-current');
      if (currentStep) {
        currentStep.classList.remove('step-current');
        const stepDots = currentStep.querySelector('.step-dots');
        if (stepDots) stepDots.remove();
      }
      const label = thinking.querySelector('.steps-label');
      if (label) label.textContent = `${stepCount} step${stepCount !== 1 ? 's' : ''}`;
      if (details) details.removeAttribute('open');
    } else {
      if (details) details.remove();
    }
    const content = document.createElement('div');
    content.className = 'msg-content';
    content.innerHTML = contentHtml;
    thinking.appendChild(content);
  } else {
    removeEmpty();
    const msg = document.createElement('div');
    msg.className = 'msg agent';
    msg.innerHTML = `
      <div class="msg-header">
        ${ATLAS_ICON}
        <span class="msg-label">Atlas</span>
      </div>
      <div class="msg-content">${contentHtml}</div>`;
    chat.appendChild(msg);
  }
  chat.scrollTop = chat.scrollHeight;
  setWaiting(false);
}

window.addEventListener('message', e => {
  const msg = e.data;
  if (msg.type === 'activityUpdate') {
    const stepsList = document.querySelector('#thinking .steps-list');
    if (stepsList) {
      const prev = stepsList.querySelector('.step-current');
      if (prev) {
        prev.classList.remove('step-current');
        const prevDots = prev.querySelector('.step-dots');
        if (prevDots) prevDots.remove();
      }
      const item = document.createElement('div');
      item.className = 'step-item step-current';
      item.innerHTML = `<span class="step-dot">•</span><span>${escHtml(msg.text)}</span><div class="step-dots"><span></span><span></span><span></span></div>`;
      stepsList.appendChild(item);
      chat.scrollTop = chat.scrollHeight;
    }
    return;
  }
  if (msg.type === 'agentMessage') {
    finalizeTurn(msg.text || '', false);
    return;
  }
  if (msg.type === 'agentError') {
    finalizeTurn(msg.text || 'Something went wrong. Please try again.', true);
    return;
  }
  if (msg.type === 'fileList') {
    workspaceFiles = Array.isArray(msg.files) ? msg.files : [];
    if (mentionActive) renderMentionDropdown();
    return;
  }
  if (msg.type === 'fileAttached') {
    attachedFiles.push(msg.filename);
    addPill(msg.filename);
    return;
  }
});
