// sidepanel.js — 侧边栏交互：长链打开、自动开关、配置存储、日志展示

const KEYS = {
  config: 'gpt_paypal_config',
  enabled: 'gpt_paypal_auto_enabled',
};

const $ = (id) => document.getElementById(id);

function appendLog(line) {
  const box = $('logs');
  const ts = new Date().toLocaleTimeString();
  box.textContent += `[${ts}] ${line}\n`;
  box.scrollTop = box.scrollHeight;
}

function setAutoUI(enabled) {
  const toggle = $('autoToggle');
  const state = $('autoState');
  toggle.classList.toggle('on', enabled);
  state.textContent = enabled ? '已开启' : '已关闭';
  state.className = 'pill ' + (enabled ? 'on' : 'off');
}

function loadAll() {
  chrome.storage.local.get([KEYS.config, KEYS.enabled], (data) => {
    const cfg = data[KEYS.config] || {};
    $('cardNumber').value = cfg.cardNumber || '';
    $('cardExpiry').value = cfg.cardExpiry || '';
    $('cardCvv').value = cfg.cardCvv || '';
    $('phone').value = cfg.phone || '987654321';
    setAutoUI(Boolean(data[KEYS.enabled]));
  });
}

function saveConfig() {
  const cfg = {
    cardNumber: $('cardNumber').value.trim(),
    cardExpiry: $('cardExpiry').value.trim(),
    cardCvv: $('cardCvv').value.trim(),
    phone: $('phone').value.trim() || '987654321',
  };
  chrome.storage.local.set({ [KEYS.config]: cfg }, () => appendLog('配置已保存'));
}

$('saveBtn').addEventListener('click', saveConfig);

$('autoToggle').addEventListener('click', () => {
  chrome.storage.local.get([KEYS.enabled], (data) => {
    const next = !data[KEYS.enabled];
    chrome.storage.local.set({ [KEYS.enabled]: next }, () => {
      setAutoUI(next);
      appendLog('自动模式：' + (next ? '已开启' : '已关闭'));
    });
  });
});

$('pasteBtn').addEventListener('click', async () => {
  try {
    const text = await navigator.clipboard.readText();
    if (text) { $('longLink').value = text.trim(); appendLog('已读取剪贴板'); }
  } catch (_) {
    appendLog('读取剪贴板失败，请手动粘贴');
  }
});

$('openBtn').addEventListener('click', () => {
  const url = $('longLink').value.trim();
  if (!/^https:\/\/pay\.openai\.com\//.test(url) && !/^https:\/\/chatgpt\.com\/checkout\//.test(url)) {
    appendLog('请粘贴有效的 pay.openai.com 长链');
    return;
  }
  // 打开前确保自动模式已开启，否则提示
  chrome.storage.local.get([KEYS.enabled, KEYS.config], (data) => {
    if (!data[KEYS.enabled]) {
      appendLog('提示：自动模式未开启，页面打开后不会自动填写。请先打开开关。');
    }
    const cfg = data[KEYS.config] || {};
    if (!cfg.cardNumber || !cfg.cardExpiry || !cfg.cardCvv) {
      appendLog('提示：尚未配置完整卡信息，PayPal 结账页将无法自动填写。');
    }
    chrome.tabs.create({ url });
    appendLog('已打开长链: ' + url.slice(0, 60) + '...');
  });
});

$('clearLogBtn').addEventListener('click', () => { $('logs').textContent = ''; });

// 接收 content script 经 background 广播的日志
chrome.runtime.onMessage.addListener((message) => {
  if (message && message.type === 'PP_LOG_BROADCAST') {
    appendLog(message.line.replace(/^\[GPT-PayPal\]\s*/, ''));
  }
});

loadAll();
