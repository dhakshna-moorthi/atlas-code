const vscode = acquireVsCodeApi();

// ── login ──
const loginScreen = document.getElementById('login-screen');
const keyInput = document.getElementById('key-input');
const keySubmit = document.getElementById('key-submit');
const keyError = document.getElementById('key-error');

function submitKey() {
  const key = keyInput.value.trim();
  if (!key) return;
  keySubmit.disabled = true;
  keySubmit.textContent = 'Unlocking...';
  keyError.textContent = '';
  vscode.postMessage({ type: 'validateKey', key });
}

keySubmit.addEventListener('click', submitKey);
keyInput.addEventListener('keydown', e => {
  if (e.key === 'Enter') { e.preventDefault(); submitKey(); }
});

// ── main UI ──
const chat = document.getElementById('chat');
const input = document.getElementById('input');
const sendBtn = document.getElementById('send-btn');
const contextBar = document.getElementById('context-bar');
const clearBtn = document.getElementById('clear-btn');

let attachedFiles = [];
let empty = document.getElementById('empty');
let waiting = false;

const NEXUS_ICON = `<svg width="13" height="13" viewBox="0 0 22 22" fill="none" xmlns="http://www.w3.org/2000/svg">
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
    <div class="tagline">Read, write, debug, and refactor<br>your code with Nexus.</div>`;
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
  pill.innerHTML = `${filename} <button title="Remove">×</button>`;
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
        ${NEXUS_ICON}
        <span class="msg-label">Nexus</span>
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
      ${NEXUS_ICON}
      <span class="msg-label">Nexus</span>
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

function removeThinking() {
  const t = document.getElementById('thinking');
  if (t) t.remove();
}

function resizeInput() {
  input.style.overflowY = 'hidden';
  input.style.height = '0px';
  const scrollH = input.scrollHeight;
  const minH = 40;
  const maxH = 520;
  const targetH = Math.max(scrollH + 2, minH);
  if (targetH >= maxH) {
    input.style.height = maxH + 'px';
    input.style.overflowY = 'auto';
  } else {
    input.style.height = targetH + 'px';
  }
}

input.addEventListener('input', resizeInput);

function setWaiting(on) {
  waiting = on;
  sendBtn.disabled = on;
  input.disabled = on;
  clearBtn.disabled = on;
}

function send() {
  if (waiting) return;
  const text = input.value.trim();
  if (!text) return;
  const files = [...attachedFiles];
  appendMessage('user', text, files);
  input.value = '';
  input.style.height = '';
  attachedFiles = [];
  contextBar.innerHTML = '';
  setWaiting(true);
  showThinking();
  vscode.postMessage({ type: 'userMessage', text, files, model: 'gpt-5.4-nano' });
}

sendBtn.addEventListener('click', send);
input.addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
});

window.addEventListener('message', e => {
  const msg = e.data;
  if (msg.type === 'keyResult') {
    if (msg.valid) {
      loginScreen.classList.add('hidden');
      input.focus();
    } else {
      keyError.textContent = 'Incorrect app key.';
      keySubmit.disabled = false;
      keySubmit.textContent = 'Unlock';
      keyInput.select();
    }
    return;
  }
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
  }
  if (msg.type === 'agentMessage') {
    const thinking = document.getElementById('thinking');
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
      content.innerHTML = renderMarkdown(msg.text);
      thinking.appendChild(content);
    } else {
      appendMessage('agent', msg.text);
    }
    setWaiting(false);
  }
  if (msg.type === 'fileAttached') {
    attachedFiles.push(msg.filename);
    addPill(msg.filename);
  }
});
