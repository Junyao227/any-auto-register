# GPT Plus 日区 PayPal 助手（Chrome 扩展）

配合主项目（any-auto-register）使用：主项目后端负责**生成 PayPal 支付长链**，本扩展在你的**真实浏览器**中打开长链并自动完成日区 PayPal 订阅。

> 为什么用扩展而不是后端无头浏览器？
> 后端 Playwright/无头浏览器带 `navigator.webdriver=true` 等自动化指纹，pay.openai.com / PayPal / Stripe 的风控会直接拦截。扩展运行在你日常使用的真实 Chrome 里，没有这些自动化标记，能从根本上绕开人机验证。

## 功能

- 侧边栏粘贴主项目生成的 `pay.openai.com` 长链并打开
- 自动开关：在 `pay.openai.com` / `paypal.com` 页面自动填写并推进
- 卡 / 电话信息配置（存浏览器本地 `chrome.storage.local`，不上传）
- 实时运行日志

## 链路

```
主项目后端：生成 pay.openai.com 长链（含 PayPal 选项，需用日本可显示 PayPal 的地区/代理）
        ↓ 手动复制长链
扩展侧边栏：粘贴长链 → 打开
        ↓
pay.openai.com：自动选 PayPal + 填日本账单地址 + 勾选条款 + 点订阅
        ↓
paypal.com /pay：填随机邮箱 → 下一步
        ↓
paypal.com /checkoutweb：country=JP → 填日区注册信息（假名+汉字+生日+卡号+都道府县）→ 提交
```

## 安装（开发者模式加载）

1. Chrome 打开 `chrome://extensions/`
2. 右上角开启「开发者模式」
3. 点「加载已解压的扩展程序」，选择本目录 `browser-extension/`
4. 固定扩展图标，点击图标打开侧边栏

## 使用

1. 侧边栏「卡 / 联系信息」填写卡号 / 有效期 / CVV / 电话 → 保存配置
2. 打开「自动化开关」
3. 在主项目里对某账号「生成 PayPal 订阅长链」，复制链接
4. 扩展侧边栏粘贴长链 → 点「打开并自动订阅」
5. 在弹出的页面观察自动填写过程，运行日志在侧边栏实时显示

## 注意

- 必须使用**能显示 PayPal 选项的地区长链**（如 US），日区长链的 OpenAI 页只显示银行卡。PayPal 自身的注册地区是日区（JP），由本扩展在 PayPal 页面填写。
- 选择器随 OpenAI / PayPal 页面改版可能失效，日志会显示「未找到字段」，据此校准。
- 请遵守 OpenAI / PayPal 服务条款，自负风险。

## 核心机制（复刻自 FlowPilot）

- **simulateClick（提交策略）**：表单提交按钮优先 `form.requestSubmit(button)`，回退 `el.click()` / dispatch。比纯 click 更可靠地触发 Stripe/PayPal 的原生表单提交与校验。
- **performOperationWithDelay**：每个关键操作后统一延迟（默认 2000ms），模拟真人节奏，避免「填完同一秒就点」导致提交无效。
- **waitUntil**：轮询等待元素/状态就绪（提交按钮可见、可用、非「处理中」）。
- **submitAndConfirmNavigation**：点击后确认是否真正跳转（URL/host 离开当前结账页），未跳转自动重试，最多 6 轮。
- **可中断执行**：侧边栏关闭「自动化开关」会立即停止正在执行的流程（content script 轮询停止标记）。
- **填表**：`nativeInputValueSetter` 原生 setter + `input/change/blur` 事件，绕过 React 受控组件。

## 文件结构

```
browser-extension/
├── manifest.json          # MV3 清单
├── background.js          # service worker（日志转发 / 侧边栏）
├── sidepanel/
│   ├── sidepanel.html     # 侧边栏 UI
│   └── sidepanel.js       # 侧边栏交互
└── content/
    ├── jp-data.js         # 日区地址/姓名/邮箱/密码/生日数据
    ├── common.js          # 共享 DOM 工具 / 配置 / 日志
    ├── openai-checkout.js # pay.openai.com 选 PayPal + 填账单地址
    └── paypal-flow.js     # paypal.com 登录 + 日区注册结账
```
