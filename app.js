/* ══════════════════════════════════════════
   VERIFYMED — App Logic
   ══════════════════════════════════════════ */

const API_BASE = 'https://verifymed-ai.onrender.com';

// ── Haptics ───────────────────────────────
function vibrate(pattern) {
  if (navigator.vibrate) {
    // Only vibrate if supported (e.g. mobile devices)
    navigator.vibrate(pattern);
  }
}

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

  // Initialize VanillaTilt if we enter processing or verdict screen
  if (name === 'processing' && window.VanillaTilt) {
    VanillaTilt.init(document.querySelectorAll(".agent-card"), {
      max: 8,
      speed: 400,
      glare: true,
      "max-glare": 0.15,
      scale: 1.02
    });
  } else if (name === 'verdict' && window.VanillaTilt) {
    VanillaTilt.init(document.querySelectorAll(".verdict-card, .suspicion-score-card, .contact-block"), {
      max: 5,
      speed: 400,
      glare: true,
      "max-glare": 0.05
    });
  }
}

// ── Navigation & Scanning ─────────────────
let html5QrcodeScanner = null;

document.getElementById('btn-scan-barcode').addEventListener('click', () => {
  vibrate(50); // Light tap
  showScreen('scanner');
  html5QrcodeScanner = new Html5QrcodeScanner("reader", { fps: 10, qrbox: {width: 250, height: 250} }, false);
  html5QrcodeScanner.render(onScanSuccess, onScanFailure);
});

function parseGS1(rawString) {
  if (!rawString) return null;
  let clean = rawString.trim();
  
  // Try parenthesized format first, e.g., (01)08901111222234(17)260531(10)BATCH123
  const parenRegex = /\((01|17|10)\)([^()]+)/g;
  let matches = [...clean.matchAll(parenRegex)];
  if (matches.length > 0) {
    let result = { gtin: null, expiry: null, batch: null };
    matches.forEach(m => {
      let ai = m[1];
      let val = m[2];
      if (ai === "01") result.gtin = val;
      else if (ai === "17") result.expiry = val;
      else if (ai === "10") result.batch = val;
    });
    if (result.gtin || result.expiry || result.batch) {
      return result;
    }
  }

  // Try raw numeric sequence format (e.g. GS1-128 or DataMatrix without parentheses)
  let gtinMatch = clean.match(/01(\d{14})/);
  let gtin = gtinMatch ? gtinMatch[1] : null;

  let expiryMatch = clean.match(/17(\d{6})/);
  let expiry = expiryMatch ? expiryMatch[1] : null;

  let batchMatch = clean.match(/10([A-Za-z0-9\-]{4,20})/);
  let batch = batchMatch ? batchMatch[1] : null;
  
  // Fallback: If it's a simple 13-digit EAN GTIN, treat it as GTIN
  if (!gtin && /^\d{13,14}$/.test(clean)) {
    gtin = clean;
  }

  return { gtin, expiry, batch };
}

function onScanSuccess(decodedText, decodedResult) {
  vibrate([100, 50, 100]); // Success double-tap
  if (html5QrcodeScanner) html5QrcodeScanner.clear();
  
  const parsed = parseGS1(decodedText);
  window._preflight = {
    barcode_raw: decodedText,
    barcode_gtin: parsed?.gtin || null,
    barcode_batch: parsed?.batch || null,
    barcode_expiry: parsed?.expiry || null,
    printed_batch: null,
    printed_expiry: null,
    printed_manufacturer: null
  };
  
  showScreen('chat');
  initChat(decodedText);
}

function onScanFailure(error) {
  // handle scan failure, usually better to ignore and keep scanning
}

const barcodeModal = document.getElementById('barcode-modal');
document.getElementById('btn-no-barcode').addEventListener('click', () => {
  vibrate(50);
  barcodeModal.classList.add('active');
});
document.getElementById('btn-modal-cancel').addEventListener('click', () => {
  vibrate(50);
  barcodeModal.classList.remove('active');
});
document.getElementById('btn-modal-proceed').addEventListener('click', () => {
  vibrate([100, 50, 100]);
  barcodeModal.classList.remove('active');
  if(html5QrcodeScanner) html5QrcodeScanner.clear();
  showScreen('chat');
  initChat("NO_BARCODE_FOUND");
});

document.getElementById('back-from-scanner').addEventListener('click', () => {
  vibrate(50);
  if(html5QrcodeScanner) html5QrcodeScanner.clear();
  showScreen('home');
});
document.getElementById('back-from-chat').addEventListener('click', () => { vibrate(50); showScreen('home'); });
document.getElementById('back-from-verdict').addEventListener('click', () => {
  vibrate(50);
  document.getElementById('screen-overlay').className = 'screen-overlay'; // Reset overlay
  showScreen('home');
});
document.getElementById('btn-scan-again').addEventListener('click', () => {
  vibrate(50);
  document.getElementById('screen-overlay').className = 'screen-overlay'; // Reset overlay
  showScreen('home');
});

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

  // Show typing indicator
  const typingDiv = document.createElement('div');
  typingDiv.className = 'chat-msg msg-assistant typing-indicator';
  typingDiv.innerHTML = '<span class="dot"></span><span class="dot"></span><span class="dot"></span>';
  chatHistory.appendChild(typingDiv);
  chatHistory.scrollTop = chatHistory.scrollHeight;

  try {
    const res = await fetch(`${API_BASE}/chat_intake`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ messages: chatMessages })
    });
    
    // Remove typing indicator
    if (typingDiv.parentNode) typingDiv.parentNode.removeChild(typingDiv);
    
    const data = await res.json();
    
    if (data.reply) {
      addMessage("assistant", data.reply);
    }
    
    if (data.status === "complete" && data.extracted_data) {
      // Transition to verification
      const drug = data.extracted_data.drugs?.[0];
      if (drug) {
        if (!window._preflight) {
          window._preflight = {
            barcode_raw: null,
            barcode_gtin: null,
            barcode_batch: null,
            barcode_expiry: null
          };
        }
        window._preflight.printed_batch = drug.batch_number || null;
        window._preflight.printed_manufacturer = drug.manufacturer || null;
      }
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
const agentIds = ['agent-preflight', 'agent-stage0', 'agent-1', 'agent-2', 'agent-3', 'agent-4', 'agent-5'];
const agentStatuses = {
  'agent-preflight': { active: 'Running pre-flight checks...', done: 'Pre-flight checks passed ✓', warn: 'Soft flags detected ⚠', fail: 'Hard mismatch detected ✕' },
  'agent-stage0': { active: 'Reading drug package data...', done: 'Package data extracted ✓' },
  'agent-1':      { active: 'Querying NAFDAC & WHO registry...', done: 'Registry check complete ✓', warn: 'Anomalies detected in registry ⚠', skipped: 'Skipped — not required' },
  'agent-2':      { active: 'Scanning global alerts & recalls...', done: 'Intelligence check complete ✓', warn: 'Alerts found ⚠' },
  'agent-3':      { active: 'Analyzing pharmacological consistency...', done: 'Science check complete ✓', warn: 'Inconsistencies found ⚠', skipped: 'Skipped — not required' },
  'agent-4':      { active: 'Checking OpenFDA for side effects...', done: 'Pharmacovigilance check complete ✓', warn: 'Interactions found ⚠', skipped: 'Skipped — not required' },
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
  
  // 1. Preflight animation
  setAgentState('agent-preflight', 'active');
  await delay(800);
  
  const preflight = results?.agent_outputs?.agent_preflight;
  const tier = results?.tier;
  
  if (tier === 'hard_fail') {
    setAgentState('agent-preflight', 'fail');
    await delay(600);
    
    // In hard fail, Stage 0, Agent 1, 3, 4 are skipped
    setAgentState('agent-stage0', 'done');
    setAgentState('agent-1', 'skipped');
    setAgentState('agent-3', 'skipped');
    setAgentState('agent-4', 'skipped');
    
    // Agent 2 runs
    setAgentState('agent-2', 'active');
    await delay(1200);
    const a2 = results?.agent_outputs?.agent_2_intelligence;
    const a2Warn = a2?.some(r => r.counterfeit_alerts_found);
    setAgentState('agent-2', a2Warn ? 'warn' : 'done');
    
    // Agent 5 runs
    setAgentState('agent-5', 'active');
    await delay(1000);
    setAgentState('agent-5', 'done');
    await delay(400);
    return;
  }
  
  // Clean or Soft Flag path
  const hasPreflightFlags = preflight?.flags && preflight.flags.length > 0;
  setAgentState('agent-preflight', hasPreflightFlags ? 'warn' : 'done');
  await delay(600);
  
  // Stage 0
  setAgentState('agent-stage0', 'active');
  await delay(600);
  setAgentState('agent-stage0', 'done');

  // Agents 1, 2, 3, 4 — parallel (show as active at once)
  setAgentState('agent-1', 'active');
  setAgentState('agent-2', 'active');
  setAgentState('agent-3', 'active');
  setAgentState('agent-4', 'active');
  await delay(2000);

  // Resolve 1
  const a1 = results?.agent_outputs?.agent_1_identity;
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
  
  // Resolve 4
  setAgentState('agent-4', 'done');
  await delay(600);
  
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
        
        // Build preflight using OCR extracted details
        window._preflight = {
          barcode_raw: null,
          barcode_gtin: null,
          barcode_batch: drugData.batch_number || null,
          barcode_expiry: null,
          printed_batch: drugData.batch_number || null,
          printed_expiry: null,
          printed_manufacturer: drugData.manufacturer || null
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

  // Ensure window._preflight exists
  if (!window._preflight) {
    window._preflight = {
      barcode_raw: null,
      barcode_gtin: null,
      barcode_batch: null,
      barcode_expiry: null,
      printed_batch: null,
      printed_expiry: null,
      printed_manufacturer: null
    };
  }

  // Call /verify with retry logic
  let results;
  let attempts = 0;
  const maxAttempts = 3;
  
  while (attempts < maxAttempts) {
    try {
      attempts++;
      const res = await fetch(`${API_BASE}/verify`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ...finalPayload,
          preflight: window._preflight
        }),
      });
      if (!res.ok) throw new Error(`Server error: ${res.status}`);
      results = await res.json();
      break; // Success, exit loop
    } catch (err) {
      console.error(`Attempt ${attempts} failed:`, err);
      if (attempts >= maxAttempts) {
        vibrate([300]); // Long warning pulse
        showToast('Network error. Could not connect to VerifyMed API.');
        showScreen('chat');
        return;
      }
      // Wait before retrying (exponential backoff: 1s, 2s)
      await delay(attempts * 1000);
    }
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
  const suspicion   = parseFloat(verdict.suspicion_score) || 0;
  const summary     = verdict.patient_summary || '—';
  const concerns    = verdict.investigators_concerns || 'None listed';
  const steps       = verdict.actionable_steps || [];
  const sideEffects = verdict.side_effects_and_interactions || '—';
  const packCheck   = verdict.what_to_check_on_pack || '—';
  const contact     = verdict.who_to_contact || '—';

  // Risk badge
  const badge = document.getElementById('risk-badge');
  const icon  = document.getElementById('risk-icon');
  const label = document.getElementById('risk-label');
  const orb   = document.getElementById('orb-verdict');
  const overlay = document.getElementById('screen-overlay');

  badge.className = 'risk-badge';
  orb.className   = 'bg-orb orb-verdict';
  overlay.className = 'screen-overlay'; // Reset

  if (riskLabel.includes('VERIFIED')) {
    badge.classList.add('verified');
    orb.classList.add('verified');
    overlay.classList.add('overlay-verified');
    icon.textContent = '✔';
  } else if (riskLabel.includes('SUSPICIOUS')) {
    badge.classList.add('suspicious');
    orb.classList.add('suspicious');
    icon.textContent = '⚠';
    vibrate([200, 100, 200]); // Two pulses
  } else {
    badge.classList.add('critical');
    orb.classList.add('critical');
    overlay.classList.add('overlay-critical');
    icon.textContent = '✕';
    vibrate([400, 100, 400]); // Heavy warning vibration
  }
  label.textContent = riskLabel;

  // Gauge
  animateGauge(score);

  // Suspicion score bar
  const suspFill = document.getElementById('suspicion-bar-fill');
  const suspText = document.getElementById('suspicion-score-value');
  if (suspFill && suspText) {
    const pct = Math.round(suspicion * 100);
    suspFill.style.width = `${pct}%`;
    suspText.textContent = `${pct}%`;
  }

  // Text content
  document.getElementById('verdict-summary').textContent = summary;
  document.getElementById('side-effects-summary').textContent = sideEffects;
  document.getElementById('check-pack-text').textContent = packCheck;
  document.getElementById('contact-value').textContent   = contact;

  // Investigator's Concerns
  const concernsEl = document.getElementById('investigators-concerns-content');
  if (concernsEl) {
    concernsEl.textContent = concerns;
  }

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

// ── Share Receipt ─────────────────────────
document.getElementById('btn-share-verdict').addEventListener('click', async () => {
  vibrate(50);
  const btn = document.getElementById('btn-share-verdict');
  const originalText = btn.innerHTML;
  btn.textContent = 'Generating...';
  
  try {
    // Hide buttons temporarily for the screenshot
    const actions = document.querySelector('.action-buttons');
    const originalDisplay = actions.style.display;
    actions.style.display = 'none';

    const canvas = await html2canvas(document.querySelector('.verdict-main'), {
      backgroundColor: '#0A0F1E',
      scale: 2,
      useCORS: true,
      logging: false
    });
    
    actions.style.display = originalDisplay;
    
    canvas.toBlob(async (blob) => {
      const file = new File([blob], 'verifymed-result.png', { type: 'image/png' });
      const shareData = {
        title: 'VerifyMed Result',
        text: 'I just verified my medication using VerifyMed AI.',
        files: [file]
      };

      if (navigator.canShare && navigator.canShare(shareData)) {
        await navigator.share(shareData);
      } else {
        // Fallback: download the image
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'verifymed-result.png';
        a.click();
        URL.revokeObjectURL(url);
        showToast('Image downloaded! You can now share it.');
      }
      btn.innerHTML = originalText;
    });
  } catch (err) {
    console.error('Error sharing:', err);
    showToast('Failed to generate shareable image.');
    btn.innerHTML = originalText;
  }
});

// ── Helpers ───────────────────────────────
function delay(ms) { return new Promise(resolve => setTimeout(resolve, ms)); }
