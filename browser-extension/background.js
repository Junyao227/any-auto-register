// background.js — service worker
// 职责：
//  1. 点击扩展图标打开侧边栏
//  2. 转发 content script 日志给侧边栏
//  3. 监听标签页 URL 变化（复刻 FlowPilot：等跳转在 background 做，不会被整页导航销毁）

chrome.runtime.onInstalled.addListener(() => {
  try {
    chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true });
  } catch (_) { /* 旧版本浏览器忽略 */ }
});

function broadcastLog(line) {
  chrome.runtime.sendMessage({ type: 'PP_LOG_BROADCAST', line: `[BG] ${line}`, ts: Date.now() }).catch(() => {});
}

// 等待指定标签页 URL 匹配（轮询 chrome.tabs.get，独立于页面，不受整页导航影响）
function waitForTabUrlMatch(tabId, matcher, { timeoutMs = 60000, intervalMs = 600 } = {}) {
  return new Promise((resolve) => {
    const startedAt = Date.now();
    const timer = setInterval(async () => {
      let tab = null;
      try { tab = await chrome.tabs.get(tabId); } catch (_) { tab = null; }
      if (!tab) { clearInterval(timer); resolve({ ok: false, reason: 'tab_closed' }); return; }
      const url = tab.url || tab.pendingUrl || '';
      if (url && matcher(url)) { clearInterval(timer); resolve({ ok: true, url }); return; }
      if (Date.now() - startedAt >= timeoutMs) { clearInterval(timer); resolve({ ok: false, reason: 'timeout', url }); }
    }, intervalMs);
  });
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!message || !message.type) return false;

  // content script 日志 -> 广播给侧边栏
  if (message.type === 'PP_LOG') {
    chrome.runtime.sendMessage({ type: 'PP_LOG_BROADCAST', line: message.line, ts: message.ts }).catch(() => {});
    return false;
  }

  // 侧边栏请求打开链接
  if (message.type === 'PP_OPEN_LINK' && message.url) {
    chrome.tabs.create({ url: message.url });
    sendResponse({ ok: true });
    return true;
  }

  // content script 已在 OpenAI 页点击订阅 -> 由 background 监听跳转到 paypal.com
  if (message.type === 'PP_WAIT_PAYPAL_REDIRECT') {
    const tabId = sender.tab && sender.tab.id;
    if (!tabId) { sendResponse({ ok: false, reason: 'no_tab' }); return true; }
    broadcastLog('已在后台监听标签页跳转 PayPal...');
    waitForTabUrlMatch(tabId, (url) => /paypal\./i.test(url), { timeoutMs: 90000 })
      .then((res) => {
        if (res.ok) broadcastLog('检测到已跳转 PayPal：' + (res.url || '').slice(0, 60));
        else broadcastLog('等待跳转 PayPal 结束：' + (res.reason || ''));
        sendResponse(res);
      })
      .catch((e) => sendResponse({ ok: false, reason: String(e) }));
    return true; // 异步 sendResponse
  }

  // content script 已在 PayPal checkoutweb 点击提交 -> 监听离开 checkoutweb
  if (message.type === 'PP_WAIT_LEAVE_CHECKOUTWEB') {
    const tabId = sender.tab && sender.tab.id;
    if (!tabId) { sendResponse({ ok: false, reason: 'no_tab' }); return true; }
    broadcastLog('已在后台监听离开 PayPal checkoutweb...');
    waitForTabUrlMatch(tabId, (url) => /paypal\./i.test(url) && !/\/checkoutweb\//i.test(url), { timeoutMs: 90000 })
      .then((res) => { sendResponse(res); })
      .catch((e) => sendResponse({ ok: false, reason: String(e) }));
    return true;
  }

  return false;
});
