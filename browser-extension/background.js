// background.js — service worker
// 职责：点击扩展图标打开侧边栏；把 content script 的日志转发给侧边栏。

chrome.runtime.onInstalled.addListener(() => {
  try {
    chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true });
  } catch (_) { /* 旧版本浏览器忽略 */ }
});

// 转发日志：content script -> sidepanel
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message && message.type === 'PP_LOG') {
    // 广播给所有打开的扩展页面（侧边栏会监听）
    chrome.runtime.sendMessage({ type: 'PP_LOG_BROADCAST', line: message.line, ts: message.ts }).catch(() => {});
  }
  if (message && message.type === 'PP_OPEN_LINK' && message.url) {
    chrome.tabs.create({ url: message.url });
    sendResponse({ ok: true });
  }
  return false;
});
