/**
 * app.js — chat front-end
 *
 * Rewritten to match the new static/index.html + static/css/style.css, and to
 * use SERVER-SIDE conversation memory instead of localStorage.
 *
 * WHAT CHANGED AND WHY
 * --------------------
 * BEFORE: every conversation lived in `localStorage` (`law_convs`). The whole
 * message history was shipped to the browser and back on every render, it was
 * lost on "clear site data" or a new device, and — most importantly — the
 * server saw ONE message per request, so a follow-up like
 * "واش كاين شي استثناء؟" ("is there an exception?") had no idea what it was
 * referring to.
 *
 * AFTER: `conversation_id` is sent with /ask. `app/main.py` loads the last N
 * turns and puts them in the prompt, then writes the turn back. The browser
 * keeps only the active id in localStorage; the transcript lives in
 * PostgreSQL. Re-opening a conversation from another device now works.
 *
 * The class names below are a CONTRACT with style.css, not decoration:
 *   .msg-row(.user/.assistant)  .bubble-user  .bubble-assistant  .bubble-error
 *   .article-badge  .sources-toggle  .sources-panel  .source-item
 *   .followup-row  .followup-chip  .typing-dots  #conv-list li(.active)
 */

const chatContainer = document.getElementById('chat-container');
const input        = document.getElementById('q');
const btn         = document.getElementById('send-btn');
const convList    = document.getElementById('conv-list');
const newChatBtn  = document.getElementById('new-chat');
const tplTyping   = document.getElementById('typing-indicator');
const tplWelcome  = document.getElementById('welcome');

const ACTIVE_KEY = 'lm3assidak_active_conversation';
let activeId = localStorage.getItem(ACTIVE_KEY) || null;
let conversations = [];
let busy = false;          // guards double submits while a request is in flight

// ---------------------------------------------------------------- helpers ----
const $  = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));

/** Escape before ANY interpolation into innerHTML. Answers are model output and
 *  can contain <, > or &; the old code escaped only the user text. */
function esc(s) {
  return String(s ?? '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

/** Minimal markdown -> HTML for answer bodies. Input is escaped FIRST, so the
 *  only tags that can reach the DOM are the ones added here.
 *  The wrapping <p> matters: the blank-line rule below closes and reopens
 *  paragraphs, so the text has to start inside one. */
function renderAnswer(text) {
  return '<p>' + esc(text)
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')   // **bold**
    .replace(/^### (.+)$/gm, '</p><h4 class="mt-3 mb-1 font-bold">$1</h4><p>')
    .replace(/^## (.+)$/gm,  '</p><h3 class="mt-3 mb-1 font-bold">$1</h3><p>')
    .replace(/^[-•]\s+/gm,  '<span class="block mr-1">•</span>')
    .replace(/\n{2,}/g, '</p><p class="mt-2">')
    .replace(/\n/g, '<br>') + '</p>';
}

function scrollDown() {
  chatContainer.scrollTop = chatContainer.scrollHeight;
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

// -------------------------------------------------------------- rendering ----
function addUser(text) {
  const row = document.createElement('div');
  row.className = 'msg-row user';
  row.innerHTML = `<div class="bubble-user">${esc(text).replace(/\n/g, '<br>')}</div>`;
  chatContainer.appendChild(row);
  scrollDown();
}

function addAssistant(text, sources, scraped, retriever) {
  const row = document.createElement('div');
  row.className = 'msg-row assistant';
  const bubble = document.createElement('div');
  bubble.className = 'bubble-assistant';
  bubble.innerHTML = `<div>${renderAnswer(text)}</div>`;

  if (scraped) {
    const note = document.createElement('div');
    note.className = 'text-[11px] text-emerald-600 mt-2';
    note.textContent = '✓ معلومات إضافية من البحث الحي (مصادر .ma)';
    bubble.appendChild(note);
  }
  if (retriever) {
    const tag = document.createElement('div');
    tag.className = 'text-[10px] text-slate-400 mt-1';
    tag.textContent = `retriever: ${retriever}`;
    bubble.appendChild(tag);
  }
  if (sources && sources.length) bubble.appendChild(sourcesBlock(sources));
  row.appendChild(bubble);
  chatContainer.appendChild(row);
  scrollDown();
}

/** Collapsible source list. The <details>-free markup is deliberate: the CSS
 *  animates a chevron via aria-expanded, which <details> cannot drive. */
function sourcesBlock(sources) {
  const wrap = document.createElement('div');
  wrap.className = 'mt-3';
  const panelId = 'src-' + Math.random().toString(36).slice(2);

  const toggle = document.createElement('button');
  toggle.className = 'sources-toggle';
  toggle.setAttribute('aria-expanded', 'false');
  toggle.setAttribute('aria-controls', panelId);
  toggle.innerHTML =
    `<span>📂 المصادر (${sources.length})</span><span class="chevron">◀</span>`;

  const panel = document.createElement('div');
  panel.id = panelId;
  panel.className = 'sources-panel hidden';
  panel.innerHTML = sources.map((s) => {
    const sim = s.similarity != null ? ` · ${(s.similarity * 100).toFixed(0)}%` : '';
    const bm25 = s.bm25_score ? ` · bm25 ${s.bm25_score}` : '';
    const via = s.via ? ` · ${s.via}` : '';
    return `<div class="source-item">
      <span class="article-badge">${esc(s.article || '—')}</span>
      <span class="truncate">${esc((s.law || '').replace(/\.pdf$/, ''))}${sim}${bm25}${via}</span>
    </div>`;
  }).join('');

  toggle.addEventListener('click', () => {
    const open = toggle.getAttribute('aria-expanded') === 'true';
    toggle.setAttribute('aria-expanded', String(!open));
    panel.classList.toggle('hidden', open);
  });

  wrap.append(toggle, panel);
  return wrap;
}

function addFollowups(chips) {
  if (!chips || !chips.length) return;
  const row = document.createElement('div');
  row.className = 'followup-row';
  row.innerHTML = chips
    .map((c, i) => `<button class="followup-chip" data-i="${i}">${esc(c)}</button>`)
    .join('');
  $$('.followup-chip', row).forEach((b) => b.addEventListener('click', () => {
    input.value = chips[Number(b.dataset.i)];
    ask();
  }));
  chatContainer.appendChild(row);
  scrollDown();
}

function showTyping() {
  const node = tplTyping ? tplTyping.cloneNode(true) : null;
  if (!node) {
    const d = document.createElement('div');
    d.className = 'msg-row assistant';
    d.innerHTML = '<div class="bubble-assistant"><span class="typing-dots">' +
      '<span></span><span></span><span></span></span></div>';
    chatContainer.appendChild(d);
    scrollDown();
    return d;
  }
  const row = document.createElement('div');
  row.appendChild(node);
  chatContainer.appendChild(row);
  scrollDown();
  return row;
}

function showWelcome() {
  if (!tplWelcome) return;
  chatContainer.appendChild(tplWelcome.cloneNode(true));
  $$('[data-prompt]', chatContainer).forEach(bindPrompt);
  scrollDown();
}

function showError(message, retryFn) {
  const row = document.createElement('div');
  row.className = 'msg-row assistant';
  row.innerHTML = `<div class="bubble-error"><div class="error-body">
      <div>${renderAnswer(message)}</div>
      <button class="retry-btn">↻ إعادة المحاولة</button>
    </div></div>`;
  $('.retry-btn', row).addEventListener('click', retryFn);
  chatContainer.appendChild(row);
  scrollDown();
}

function bindPrompt(btn) {
  btn.addEventListener('click', () => {
    input.value = btn.dataset.prompt;
    ask();
  });
}

// --------------------------------------------------------------- sidebar ----
function renderSidebar() {
  if (!convList) return;
  if (!conversations.length) { convList.innerHTML = ''; return; }  // CSS :empty rule shows a hint
  convList.innerHTML = conversations.map((c) => `
    <li data-id="${esc(c.id)}" class="${c.id === activeId ? 'active' : ''}"
        title="${esc(c.title)}">
      <span class="truncate flex-1">${esc(c.title || 'محادثة جديدة')}</span>
      <button class="text-slate-300 hover:text-red-700 text-xs" data-del="${esc(c.id)}">×</button>
    </li>`).join('');

  $$('#conv-list li').forEach((li) => li.addEventListener('click', (ev) => {
    if (ev.target.dataset.del) return;
    openConversation(li.dataset.id);
  }));
  $$('#conv-list [data-del]').forEach((b) => b.addEventListener('click', async (ev) => {
    ev.stopPropagation();
    await deleteConversation(b.dataset.del);
  }));
}

async function loadConversations() {
  try {
    const j = await api('/conversations');
    conversations = j.conversations || [];
  } catch {
    conversations = [];       // server down: the chat still works, just no history
  }
  renderSidebar();
}

async function newConversation() {
  try {
    const j = await api(`/conversations?title=${encodeURIComponent('محادثة جديدة')}`,
                        { method: 'POST' });
    activeId = j.conversation_id;
  } catch {
    activeId = null;          // memory unavailable -> stateless but functional
  }
  localStorage.setItem(ACTIVE_KEY, activeId || '');
  await loadConversations();
  chatContainer.innerHTML = '';
  showWelcome();
  input.focus();
}

async function openConversation(id) {
  activeId = id;
  localStorage.setItem(ACTIVE_KEY, id);
  renderSidebar();
  chatContainer.innerHTML = '';
  try {
    const j = await api(`/conversations/${encodeURIComponent(id)}`);
    const msgs = j.messages || [];
    if (!msgs.length) { showWelcome(); return; }
    msgs.forEach((m) => {
      if (m.role === 'user') addUser(m.content);
      else addAssistant(m.content, m.sources || [], false, null);
    });
  } catch {
    showError('ما قدرناش نجيبو هاد المحادثة من السيرفر.', () => openConversation(id));
  }
}

async function deleteConversation(id) {
  const wasActive = id === activeId;   // capture BEFORE clearing activeId
  try {
    await api(`/conversations/${encodeURIComponent(id)}`, { method: 'DELETE' });
  } catch { /* already gone server-side */ }
  if (wasActive) { activeId = null; localStorage.removeItem(ACTIVE_KEY); }
  await loadConversations();
  if (wasActive) { chatContainer.innerHTML = ''; showWelcome(); }
}

// ------------------------------------------------------------------ ask ------
async function ask() {
  const question = input.value.trim();
  if (!question || busy) return;
  busy = true;
  btn.disabled = true;

  if (!chatContainer.querySelector('.msg-row')) chatContainer.innerHTML = '';
  addUser(question);
  input.value = '';
  const typing = showTyping();

  const send = async () => {
    try {
      const j = await api('/ask', {
        method: 'POST',
        body: JSON.stringify({ question, conversation_id: activeId }),
      });
      typing.remove();
      addAssistant(j.answer || 'ماكاينش جواب', j.sources, j.scraped, j.retriever);
      addFollowups(j.suggestions);
      if (j.conversation_id && j.conversation_id !== activeId) {
        activeId = j.conversation_id;                       // first turn creates it
        localStorage.setItem(ACTIVE_KEY, activeId);
      }
      loadConversations();                                    // title updates server-side
    } catch (e) {
      typing.remove();
      showError(`تعذر الاتصال بالسيرفر (${esc(e.message)}).`, send);
    } finally {
      busy = false;
      btn.disabled = false;
      input.focus();
    }
  };
  await send();
}

// ------------------------------------------------------------------ init -----
if (btn) btn.addEventListener('click', ask);
if (input) {
  input.addEventListener('keydown', (e) => {
    // Enter sends, Shift+Enter makes a new line. Both are expected in a chat box.
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); ask(); }
  });
  // Auto-grow so a 4-line question does not scroll inside a 2-row textarea.
  input.addEventListener('input', () => {
    input.style.height = 'auto';
    input.style.height = Math.min(input.scrollHeight, 160) + 'px';
  });
}
if (newChatBtn) newChatBtn.addEventListener('click', newConversation);
$$('[data-prompt]').forEach(bindPrompt);

(async function init() {
  await loadConversations();
  if (activeId && conversations.some((c) => c.id === activeId)) {
    await openConversation(activeId);
  } else {
    await newConversation();
  }
})();
