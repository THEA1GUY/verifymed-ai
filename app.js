/* ══════════════════════════════════════════
   VERIFYMED — App Logic
   ══════════════════════════════════════════ */

const API_BASE = 'https://verifymed-ai.onrender.com';

// ── Screen Manager ────────────────────────
const screens = {
  home:       document.getElementById('screen-home'),
  scanner:    document.getElementById('screen-scanner'),
  chat:       document.getElementById('screen-chat'),
  processing: document.getElementById('screen-processing'),
  verdict:    document.getElementById('screen-verdict'),
};

function showScreen(name) {
  Object.entries(screens).forEach(([key, el]) => {
    if (key === name) {
      el.classList.remove('exit');
      el.classList.add('active');
    } else if (el.classList.contains('active')) {
      el.classList.add('exit');
      setTimeout(() => el.classList.remove('active', 'exit'), 350);
    }
  });
}

// ── Navigation & Scanning ─────────────────
let html5QrcodeScanner = null;

document.getElementById('btn-scan-barcode').addEventListener('click', () => {
  showScreen('scanner');
  html5QrcodeScanner = new Html5QrcodeScanner("reader", { fps: 10, qrbox: {width: 250, height: 250} }, false);
  html5QrcodeScanner.render(onScanSuccess, onScanFailure);
});

function onScanSuccess(decodedText, decodedResult) {
  html5QrcodeScanner.clear();
  showScreen('chat');
  initChat(decodedText);
}

function onScanFailure(error) {
  // handle scan failure, usually better to ignore and keep scanning
}

const barcodeModal = document.getElementById('barcode-modal');
document.getElementById('btn-no-barcode').addEventListener('click', () => {
  barcodeModal.classList.add('active');
});
document.getElementById('btn-modal-cancel').addEventListener('click', () => {
  barcodeModal.classList.remove('active');
});
document.getElementById('btn-modal-proceed').addEventListener('click', () => {
  barcodeModal.classList.remove('active');
  if(html5QrcodeScanner) html5QrcodeScanner.clear();
  showScreen('chat');
  initChat("NO_BARCODE_FOUND");
});

document.getElementById('back-from-scanner').addEventListener('click', () => {
  if(html5QrcodeScanner) html5QrcodeScanner.clear();
  showScreen('home');
});
document.getElementById('back-from-chat').addEventListener('click', () => showScreen('home'));
document.getElementById('back-from-verdict').addEventListener('click', () => showScreen('home'));
document.getElementById('btn-scan-again').addEventListener('click', () => showScreen('home'));

// ── Chat Intake Logic ─────────────────────
let chatMessages = [];
const chatHistory = document.getElementById('chat-history');
const chatInput = document.getElementById('chat-input');
const chatForm = document.getElementById('chat-form');

function initChat(barcodeValue = null) {
  chatMessages = [];
  chatHistory.innerHTML = '';
  
  if (barcodeValue === "NO_BARCODE_FOUND") {
    addMessage("system", "System Note: User bypassed barcode scanning. This is a potential risk indicator.");
    addMessage("assistant", "⚠️ I see you don't have a barcode. Please proceed with extreme caution.\n\nTo continue verification using just the text on the box, what are your symptoms and what is the name of the medication?");
  } else if (barcodeValue) {
    addMessage("system", `System Note: Barcode scanned: ${barcodeValue}`);
    addMessage("assistant", `I successfully read the barcode: **${barcodeValue}**. \n\nTo continue verification, what are your symptoms and what is the name of the medication?`);
  } else {
    addMessage("assistant", "Hello! I'm your VerifyMed Intake Assistant. To get started, what symptoms are you experiencing, and what medication(s) were you given?");
  }
}

function addMessage(role, text) {
  if (role !== "system") {
    chatMessages.push({ role, content: text });
    const div = document.createElement('div');
    div.className = `chat-msg msg-${role}`;
    div.textContent = text;
    chatHistory.appendChild(div);
    chatHistory.scrollTop = chatHistory.scrollHeight;
  }
}

chatForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  const text = chatInput.value.trim();
  if (!text) return;
  chatInput.value = '';
  
  addMessage("user", text);

  try {
    const res = await fetch(`${API_BASE}/chat_intake`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ messages: chatMessages })
    });
    const data = await res.json();
    
    if (data.reply) {
      addMessage("assistant", data.reply);
    }
    
    if (data.status === "complete" && data.extracted_data) {
      // Transition to verification
      await delay(1000);
      runVerification(data.extracted_data, null);
    }
  } catch (err) {
    console.error(err);
    addMessage("assistant", "Sorry, I'm having trouble connecting to the server.");
  }
});

// ── File / Camera Input ───────────────────
document.getElementById('file-input').addEventListener('change', async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  
  // OCR skips the chat and goes straight to verification
  await runVerification(null, file);
});


// ── Agent Pipeline Animator ───────────────
const agentIds = ['agent-stage0', 'agent-1', 'agent-2', 'agent-3', 'agent-4', 'agent-5'];
const agentStatuses = {
  'agent-stage0': { active: 'Reading drug package data...', done: 'Package data extracted ✓' },
  'agent-1':      { active: 'Querying NAFDAC & WHO registry...', done: 'Registry check complete ✓', warn: 'Anomalies detected in registry ⚠' },
  'agent-2':      { active: 'Scanning global alerts & recalls...', done: 'Intelligence check complete ✓', warn: 'Alerts found ⚠' },
  'agent-3':      { active: 'Analyzing pharmacological consistency...', done: 'Science check complete ✓', warn: 'Inconsistencies found ⚠' },
  'agent-4':      { active: 'Checking OpenFDA for side effects...', done: 'Pharmacovigilance check complete ✓', warn: 'Interactions found ⚠' },
  'agent-5':      { active: 'Building your safety report...', done: 'Report ready ✓' },
};

function setAgentState(id, state) {
  const card = document.getElementById(id);
  if (!card) return;
  card.dataset.state = state;
  const statusEl = card.querySelector('.agent-status');
  if (statusEl && agentStatuses[id]?.[state]) {
    statusEl.textContent = agentStatuses[id][state];
  }
}

function resetAgents() {
  agentIds.forEach(id => setAgentState(id, 'idle'));
}

async function animateAgents(results) {
  resetAgents();
  // Stage 0 — instant
  setAgentState('agent-stage0', 'active');
  await delay(600);
  setAgentState('agent-stage0', 'done');

  // Agents 1, 2, 3 — parallel (show as active at once)
  setAgentState('agent-1', 'active');
  setAgentState('agent-2', 'active');
  setAgentState('agent-3', 'active');
  await delay(2000);

  // Resolve 1
  const a1 = results?.agent_outputs?.agent_1_identity;
  // Note: a1 is a list now because of multi-drug
  const a1Success = a1?.every(r => r.registry_match_found);
  setAgentState('agent-1', a1Success ? 'done' : 'warn');

  // Resolve 2
  const a2 = results?.agent_outputs?.agent_2_intelligence;
  const a2Warn = a2?.some(r => r.counterfeit_alerts_found);
  setAgentState('agent-2', a2Warn ? 'warn' : 'done');

  // Resolve 3
  const a3 = results?.agent_outputs?.agent_3_science;
  const a3Success = a3?.every(r => r.pharmacologically_consistent);
  setAgentState('agent-3', a3Success ? 'done' : 'warn');

  await delay(600);
  
  // Resolve 4
  setAgentState('agent-4', 'active');
  await delay(1500);
  setAgentState('agent-4', 'done');
  
  // Resolve 5
  setAgentState('agent-5', 'active');
  await delay(1500);
  setAgentState('agent-5', 'done');
  await delay(400);
}

// ── Main Verification Flow ────────────────
async function runVerification(payload, imageFile) {
  showScreen('processing');
  resetAgents();

  let finalPayload = payload;

  // Stage 0: OCR
  if (imageFile) {
    setAgentState('agent-stage0', 'active');
    try {
      const formData = new FormData();
      formData.append('file', imageFile);
      const res = await fetch(`${API_BASE}/ocr`, { method: 'POST', body: formData });
      if (res.ok) {
        const drugData = await res.json();
        finalPayload = {
          patient_symptoms: "Not provided (OCR Scan)",
          drugs: [drugData]
        };
        setAgentState('agent-stage0', 'done');
      } else {
        throw new Error('OCR failed');
      }
    } catch {
      setAgentState('agent-stage0', 'warn');
      await delay(800);
      showScreen('chat');
      showToast('Image scan failed! Please chat with the assistant.');
      return;
    }
  } else {
    setAgentState('agent-stage0', 'done');
  }

  // Call /verify
  let results;
  try {
    const res = await fetch(`${API_BASE}/verify`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(finalPayload),
    });
    if (!res.ok) throw new Error(`Server error: ${res.status}`);
    results = await res.json();
  } catch (err) {
    console.error(err);
    showToast('Could not connect to VerifyMed API.');
    showScreen('chat');
    return;
  }

  // Animate pipeline
  await animateAgents(results);

  // Render verdict
  renderVerdict(results.verdict);
  showScreen('verdict');
}

// ── Verdict Renderer ──────────────────────
function renderVerdict(verdict) {
  const riskLabel   = verdict.risk_level || '—';
  const score       = parseInt(verdict.confidence_score_percentage) || 0;
  const summary     = verdict.patient_summary || '—';
  const steps       = verdict.actionable_steps || [];
  const sideEffects = verdict.side_effects_and_interactions || '—';
  const packCheck   = verdict.what_to_check_on_pack || '—';
  const contact     = verdict.who_to_contact || '—';

  // Risk badge
  const badge = document.getElementById('risk-badge');
  const icon  = document.getElementById('risk-icon');
  const label = document.getElementById('risk-label');
  const orb   = document.getElementById('orb-verdict');

  badge.className = 'risk-badge';
  orb.className   = 'bg-orb orb-verdict';

  if (riskLabel.includes('VERIFIED')) {
    badge.classList.add('verified');
    orb.classList.add('verified');
    icon.textContent = '✔';
  } else if (riskLabel.includes('SUSPICIOUS')) {
    badge.classList.add('suspicious');
    orb.classList.add('suspicious');
    icon.textContent = '⚠';
  } else {
    badge.classList.add('critical');
    orb.classList.add('critical');
    icon.textContent = '✕';
  }
  label.textContent = riskLabel;

  // Gauge
  animateGauge(score);

  // Text content
  document.getElementById('verdict-summary').textContent = summary;
  document.getElementById('side-effects-summary').textContent = sideEffects;
  document.getElementById('check-pack-text').textContent = packCheck;
  document.getElementById('contact-value').textContent   = contact;

  // Actionable steps
  const list = document.getElementById('action-list');
  list.innerHTML = '';
  const stepsArr = Array.isArray(steps) ? steps : [steps];
  stepsArr.forEach(step => {
    const li = document.createElement('li');
    li.textContent = step;
    list.appendChild(li);
  });

  // NAFDAC call button
  const btn = document.getElementById('nafdac-btn');
  const phoneMatch = contact.match(/(\d[\d\s\-]{7,})/);
  if (phoneMatch) {
    btn.href = `tel:${phoneMatch[1].replace(/\s/g, '')}`;
  }
}

// ── Gauge Animator ────────────────────────
function animateGauge(targetPercent) {
  const fill    = document.getElementById('gauge-fill');
  const numEl   = document.getElementById('gauge-number');
  const total   = 251.2; // half-circle circumference
  const offset  = total - (total * Math.min(targetPercent, 100) / 100);

  fill.style.strokeDashoffset = total;
  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      fill.style.strokeDashoffset = offset;
    });
  });

  let current = 0;
  const step  = targetPercent / 50;
  const timer = setInterval(() => {
    current = Math.min(current + step, targetPercent);
    numEl.textContent = `${Math.round(current)}%`;
    if (current >= targetPercent) clearInterval(timer);
  }, 24);
}

// ── Toast ─────────────────────────────────
function showToast(message) {
  const toast = document.createElement('div');
  toast.style.cssText = `
    position: fixed; bottom: 32px; left: 50%; transform: translateX(-50%);
    background: rgba(15,22,41,0.95); border: 1px solid rgba(255,255,255,0.12);
    color: #fff; padding: 12px 20px; border-radius: 100px; font-size: 13px;
    font-family: Inter, sans-serif; backdrop-filter: blur(10px);
    z-index: 9999; white-space: nowrap; max-width: 90vw;
    animation: slide-in 0.3s ease both;
  `;
  toast.textContent = message;
  document.body.appendChild(toast);
  setTimeout(() => toast.remove(), 4000);
}

// ── Helpers ───────────────────────────────
function delay(ms) { return new Promise(resolve => setTimeout(resolve, ms)); }
