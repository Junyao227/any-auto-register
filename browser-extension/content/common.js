// content/common.js — 共享 DOM 工具 / 配置 / 运行控制（复刻 FlowPilot 机制）
// 暴露到 window.PPHelper。
//
// 复刻自 FlowPilot 的核心机制：
//  - getActivationStrategy / simulateClick：提交按钮优先 form.requestSubmit，回退 click
//  - waitUntil：轮询等待元素/状态就绪
//  - 可中断 sleep + stop flag：支持中途停止
//  - performOperationWithDelay：每个关键操作后统一延迟（默认 2000ms），拟人化节奏

(function attachCommon(root) {
  const STORAGE_KEYS = {
    config: 'gpt_paypal_config',
    enabled: 'gpt_paypal_auto_enabled',
  };

  const DEFAULT_CONFIG = {
    cardNumber: '',
    cardExpiry: '',
    cardCvv: '',
    phone: '987654321',
  };

  const OPERATION_DELAY_MS = 2000;
  const STOP_ERROR_MESSAGE = '__PP_FLOW_STOPPED__';
  let flowStopped = false;

  function requestStop() { flowStopped = true; }
  function resetStop() { flowStopped = false; }
  function isStopError(err) { return err && String(err.message || err) === STOP_ERROR_MESSAGE; }
  function throwIfStopped() { if (flowStopped) throw new Error(STOP_ERROR_MESSAGE); }

  // 侧边栏关闭“自动模式”时，正在执行的 content script 立即停止
  try {
    chrome.storage.onChanged.addListener((changes, area) => {
      if (area === 'local' && changes[STORAGE_KEYS.enabled]) {
        if (changes[STORAGE_KEYS.enabled].newValue === false) {
          flowStopped = true;
        }
      }
    });
  } catch (_) { /* ignore */ }

  function log(msg) {
    const line = '[GPT-PayPal] ' + msg;
    console.log(line);
    try {
      chrome.runtime.sendMessage({ type: 'PP_LOG', line, ts: Date.now() });
    } catch (_) { /* sidepanel 未打开时忽略 */ }
  }

  async function getConfig() {
    return new Promise((resolve) => {
      try {
        chrome.storage.local.get([STORAGE_KEYS.config], (data) => {
          resolve(Object.assign({}, DEFAULT_CONFIG, (data && data[STORAGE_KEYS.config]) || {}));
        });
      } catch (_) {
        resolve(Object.assign({}, DEFAULT_CONFIG));
      }
    });
  }

  async function isAutoEnabled() {
    return new Promise((resolve) => {
      try {
        chrome.storage.local.get([STORAGE_KEYS.enabled], (data) => {
          resolve(Boolean(data && data[STORAGE_KEYS.enabled]));
        });
      } catch (_) {
        resolve(false);
      }
    });
  }

  // 可中断 sleep（复刻 FlowPilot：分片轮询 flowStopped）
  function sleep(ms) {
    return new Promise((resolve, reject) => {
      const start = Date.now();
      function tick() {
        if (flowStopped) { reject(new Error(STOP_ERROR_MESSAGE)); return; }
        if (Date.now() - start >= ms) { resolve(); return; }
        setTimeout(tick, Math.min(100, Math.max(25, ms - (Date.now() - start))));
      }
      tick();
    });
  }

  // 轮询等待（复刻 FlowPilot waitUntil）
  async function waitUntil(predicate, options = {}) {
    const intervalMs = Math.max(50, Math.floor(Number(options.intervalMs) || 300));
    const timeoutMs = Math.max(0, Math.floor(Number(options.timeoutMs) || 0));
    const startedAt = Date.now();
    while (true) {
      throwIfStopped();
      let value;
      try { value = await predicate(); } catch (_) { value = null; }
      if (value) return value;
      if (timeoutMs > 0 && Date.now() - startedAt >= timeoutMs) {
        if (options.throwOnTimeout) throw new Error(options.timeoutMessage || '等待超时');
        return null;
      }
      await sleep(intervalMs);
    }
  }

  // 操作后统一延迟（复刻 FlowPilot performOperationWithDelay）
  async function performOperationWithDelay(metadata, operation) {
    const result = await operation();
    const skip = metadata && metadata.skipDelay === true;
    if (!skip) {
      const ms = (metadata && metadata.delayMs) || OPERATION_DELAY_MS;
      await sleep(ms);
    }
    return result;
  }

  function isVisible(el) {
    if (!el) return false;
    const style = window.getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return style.display !== 'none'
      && style.visibility !== 'hidden'
      && Number(rect.width) > 0
      && Number(rect.height) > 0;
  }

  function isEnabled(el) {
    return Boolean(el) && !el.disabled && el.getAttribute && el.getAttribute('aria-disabled') !== 'true';
  }

  function normalizeText(text) {
    return String(text || '').replace(/\s+/g, ' ').trim();
  }

  // 综合可点元素的多维度文本（复刻 FlowPilot getCombinedSearchText）
  function getActionText(el) {
    if (!el) return '';
    return normalizeText([
      el.textContent, el.value,
      el.getAttribute && el.getAttribute('aria-label'),
      el.getAttribute && el.getAttribute('title'),
      el.getAttribute && el.getAttribute('placeholder'),
      el.getAttribute && el.getAttribute('name'),
      el.getAttribute && el.getAttribute('data-testid'),
      el.id,
    ].filter(Boolean).join(' '));
  }

  function getCombinedSearchText(el) {
    if (!el) return '';
    const datasetValues = el.dataset ? Object.values(el.dataset) : [];
    const labels = [];
    const id = el.id || '';
    if (id) {
      try {
        Array.from(document.querySelectorAll(`label[for="${CSS.escape(id)}"]`)).forEach((l) => labels.push(l.textContent));
      } catch (_) { /* ignore */ }
    }
    const wrapLabel = el.closest && el.closest('label');
    if (wrapLabel) labels.push(wrapLabel.textContent);
    return normalizeText([
      getActionText(el),
      el.getAttribute && el.getAttribute('role'),
      typeof el.className === 'string' ? el.className : (el.getAttribute && el.getAttribute('class')),
      ...datasetValues,
      ...labels,
    ].filter(Boolean).join(' '));
  }

  function getVisibleControls(selector) {
    return Array.from(document.querySelectorAll(selector)).filter(isVisible);
  }

  // 按文本/属性匹配可点元素（复刻 FlowPilot findClickableByText）
  function findClickableByText(patterns) {
    const pats = (Array.isArray(patterns) ? patterns : [patterns]).filter(Boolean);
    const candidates = getVisibleControls('button, a, [role="button"], [role="tab"], input[type="button"], input[type="submit"], [tabindex]');
    return candidates.find((el) => {
      const text = getCombinedSearchText(el);
      return pats.some((p) => p.test(text));
    }) || null;
  }

  // 填表（复刻 FlowPilot fillInput：nativeInputValueSetter + input/change）
  function fillInput(el, value) {
    if (!el) return false;
    let proto = HTMLInputElement.prototype;
    if (el instanceof HTMLSelectElement) proto = HTMLSelectElement.prototype;
    else if (root.HTMLTextAreaElement && el instanceof HTMLTextAreaElement) proto = HTMLTextAreaElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(proto, 'value');
    if (setter && setter.set) setter.set.call(el, value); else el.value = value;
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
    el.dispatchEvent(new Event('blur', { bubbles: true }));
    return true;
  }

  // 兼容旧名
  const setValue = fillInput;

  // 激活策略（复刻 FlowPilot getActivationStrategy）：表单提交按钮优先 requestSubmit
  function getActivationStrategy(target = {}) {
    const tagName = String(target.tagName || '').trim().toLowerCase();
    const type = String(target.type || '').trim().toLowerCase();
    const hasForm = Boolean(target.hasForm);
    const isSubmitButton = hasForm && (
      (tagName === 'button' && (!type || type === 'submit'))
      || (tagName === 'input' && type === 'submit')
    );
    if (isSubmitButton) return { method: 'requestSubmit' };
    return { method: 'click' };
  }

  // 真实点击（复刻 FlowPilot simulateClick）：表单按钮走 form.requestSubmit，回退 click/dispatch
  function simulateClick(el) {
    if (!el) throw new Error('无法点击空元素');
    const form = el.form || (el.closest && el.closest('form')) || null;
    const strategy = getActivationStrategy({
      tagName: el.tagName,
      type: (el.getAttribute && el.getAttribute('type')) || el.type || '',
      hasForm: Boolean(form),
    });
    let method = strategy.method || 'click';
    const text = (el.textContent || el.value || '').trim().slice(0, 30);
    try {
      if (method === 'requestSubmit' && form && typeof form.requestSubmit === 'function') {
        form.requestSubmit(el);
      } else if (typeof el.click === 'function') {
        method = 'click';
        el.click();
      } else {
        method = 'dispatchEvent';
        el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
      }
    } catch (_) {
      try { el.click(); method = 'click(fallback)'; } catch (e) { /* ignore */ }
    }
    log(`已点击(${method}) [${el.tagName}] "${text}"`);
    return method;
  }

  function fillById(id, value) {
    const el = document.getElementById(id);
    if (!el) { log('NOT FOUND: ' + id); return false; }
    fillInput(el, value);
    return true;
  }

  function fieldText(el) {
    return [
      el.id, el.name,
      el.getAttribute && el.getAttribute('autocomplete'),
      el.getAttribute && el.getAttribute('placeholder'),
      el.getAttribute && el.getAttribute('aria-label'),
      el.getAttribute && el.getAttribute('data-testid'),
      el.closest && el.closest('label') && el.closest('label').textContent,
    ].join(' ').toLowerCase();
  }

  function findField(candidates, selector) {
    const fields = Array.from(document.querySelectorAll(selector || 'input, textarea, select'))
      .filter((el) => !el.disabled && isVisible(el));
    for (const c of candidates) {
      const key = String(c).toLowerCase();
      for (const f of fields) {
        if (fieldText(f).indexOf(key) !== -1) return f;
      }
    }
    return null;
  }

  function setAnyField(label, candidates, value) {
    const el = findField(candidates, 'input, textarea');
    if (!el) { log('未找到字段: ' + label); return false; }
    fillInput(el, value);
    log(label + ' = ' + (el.id || el.name || el.getAttribute('placeholder') || el.getAttribute('aria-label') || ''));
    return true;
  }

  function setAnySelect(label, candidates, values) {
    const el = findField(candidates, 'select');
    if (!el) { log('未找到下拉: ' + label); return false; }
    values = Array.isArray(values) ? values : [values];
    for (const want of values) {
      const w = String(want).toLowerCase();
      for (const opt of el.options) {
        const t = String(opt.text || opt.textContent || '').toLowerCase();
        const v = String(opt.value || '').toLowerCase();
        if (t.indexOf(w) !== -1 || v.indexOf(w) !== -1) {
          fillInput(el, opt.value);
          log(label + ' = ' + opt.text);
          return true;
        }
      }
    }
    log('下拉无匹配项: ' + label);
    return false;
  }

  function fillSelectById(id, values) {
    const el = document.getElementById(id);
    if (!el) { log('NOT FOUND select: ' + id); return false; }
    values = Array.isArray(values) ? values : [values];
    const norm = (x) => String(x || '').trim().toLowerCase();
    const optText = (o) => String(o.text || o.textContent || '').trim();
    for (const want of values) {
      const w = norm(want);
      for (const o of el.options) {
        if (norm(optText(o)) === w || norm(o.value) === w) {
          fillInput(el, o.value); log(id + ' = ' + optText(o)); return true;
        }
      }
    }
    for (const want of values) {
      const w = norm(want);
      if (!w) continue;
      for (const o of el.options) {
        if (norm(optText(o)).indexOf(w) !== -1 || norm(o.value).indexOf(w) !== -1) {
          fillInput(el, o.value); log(id + ' = ' + optText(o)); return true;
        }
      }
    }
    log('select 无匹配: ' + id);
    return false;
  }

  // 复刻 FlowPilot findSubscribeButton：先找 submit 类型按钮（文本含订阅/subscribe），再按文本兜底
  const SUBSCRIBE_READY_PATTERN = /订阅|继续|确认|支付|同意|下一页|下一步|次へ|確定|確認|subscribe|continue|confirm|pay|agree|next|start\s*subscription|place\s*order/i;

  function findSubmitButton() {
    // 1) 明确的 testid/class（OpenAI hosted checkout 的订阅按钮）
    const direct = document.querySelector('button[data-testid="hosted-payment-submit-button"]')
      || document.querySelector('button[data-testid="submit-button"]')
      || document.querySelector('button[data-atomic-wait-intent="Submit_Email"]')
      || document.querySelector('button.SubmitButton--complete');
    if (direct && isVisible(direct)) return direct;

    // 2) 可见的 submit 类型按钮，文本含订阅/subscribe（含“订阅正在处理”这类已点击态）
    const submitButtons = getVisibleControls('button[type="submit"], input[type="submit"], button:not([type])');
    const exact = submitButtons.find((b) => isEnabled(b) && SUBSCRIBE_READY_PATTERN.test(getCombinedSearchText(b)));
    if (exact) return exact;

    // 3) 文本兜底（任意可点元素）
    return findClickableByText([SUBSCRIBE_READY_PATTERN]);
  }

  // 注意：不再用“处理中文案”判定按钮不可点。
  // FlowPilot 的做法是只看 disabled/aria-disabled；“订阅正在处理”是点击后的正常态，
  // 若据此跳过会导致永远点不到按钮。仅保留显式禁用判断。
  function isSubmitProcessing(btn) {
    if (!btn) return false;
    return Boolean(
      (btn.getAttribute && btn.getAttribute('aria-busy') === 'true' && !isEnabled(btn))
    );
  }

  function hideAddressAutocomplete() {
    ['.AddressAutocomplete-results', '[class*="AddressAutocomplete"]', '#billing-address-autocomplete-results']
      .forEach((s) => {
        document.querySelectorAll(s).forEach((n) => {
          try {
            n.style.setProperty('display', 'none', 'important');
            n.style.setProperty('pointer-events', 'none', 'important');
          } catch (_) { /* best effort */ }
        });
      });
  }

  // 请求 background 监听标签页跳转（独立于页面，不被整页导航销毁）
  function waitForRedirectViaBackground(messageType) {
    return new Promise((resolve) => {
      try {
        chrome.runtime.sendMessage({ type: messageType }, (res) => {
          if (chrome.runtime.lastError) { resolve({ ok: false, reason: String(chrome.runtime.lastError.message || '') }); return; }
          resolve(res || { ok: false });
        });
      } catch (e) {
        resolve({ ok: false, reason: String(e) });
      }
    });
  }

  // 提交（复刻 FlowPilot 分工）：content 只负责点击订阅，跳转由 background 监听标签页 URL 确认。
  //  - 按钮“就绪”只看 可见 + 未禁用（不看“处理中”文案，Stripe 按钮内含隐藏处理中 span）
  //  - 点击后整页会导航到 paypal.com，本 content script 随之销毁；跳转确认放到 background
  async function submitAndConfirmNavigation(opts) {
    opts = opts || {};
    const waitMessage = opts.waitMessage || 'PP_WAIT_PAYPAL_REDIRECT';
    const maxRounds = opts.maxRounds || 4;

    for (let round = 0; round < maxRounds; round++) {
      throwIfStopped();
      hideAddressAutocomplete();

      // 等待提交按钮：可见 + 未禁用
      const btn = await waitUntil(() => {
        hideAddressAutocomplete();
        const b = findSubmitButton();
        return (b && isVisible(b) && isEnabled(b)) ? b : null;
      }, { intervalMs: 500, timeoutMs: 15000 });

      if (!btn) {
        try {
          const btns = getVisibleControls('button, [role="button"], input[type="submit"]')
            .map((b) => '"' + (getActionText(b) || '').slice(0, 24) + '"' + (b.disabled ? '(disabled)' : ''))
            .slice(0, 12);
          log('未找到可用提交按钮，当前可见按钮: ' + (btns.join(', ') || '无'));
        } catch (_) { log('未找到可用提交按钮，重试...'); }
        await sleep(1200);
        continue;
      }

      // blur 触发校验 + 短延迟，然后点击
      try { if (document.activeElement && document.activeElement.blur) document.activeElement.blur(); } catch (_) {}
      await sleep(800);
      hideAddressAutocomplete();
      const current = findSubmitButton() || btn;

      // 先让 background 开始监听跳转，再点击（避免点击后页面瞬间销毁来不及发起监听）
      const pending = waitForRedirectViaBackground(waitMessage);
      await performOperationWithDelay(
        { stepKey: 'submit', delayMs: 300 },
        async () => { simulateClick(current); }
      );
      log('已点击订阅（第 ' + (round + 1) + ' 次），后台监听跳转中...');

      const res = await pending;
      if (res && res.ok) { log('已跳转：' + (res.url || '').slice(0, 60)); return true; }
      log('本轮未跳转（' + ((res && res.reason) || 'unknown') + '），重试...');
    }
    log('多次提交仍未跳转，请检查页面是否有未通过的校验项');
    return false;
  }

  root.PPHelper = {
    STORAGE_KEYS,
    DEFAULT_CONFIG,
    OPERATION_DELAY_MS,
    log,
    getConfig,
    isAutoEnabled,
    sleep,
    waitUntil,
    performOperationWithDelay,
    requestStop,
    resetStop,
    isStopError,
    throwIfStopped,
    isVisible,
    isEnabled,
    fillInput,
    setValue,
    simulateClick,
    getActivationStrategy,
    fillById,
    findField,
    setAnyField,
    setAnySelect,
    fillSelectById,
    findSubmitButton,
    isSubmitProcessing,
    submitAndConfirmNavigation,
    hideAddressAutocomplete,
  };
})(typeof window !== 'undefined' ? window : globalThis);
