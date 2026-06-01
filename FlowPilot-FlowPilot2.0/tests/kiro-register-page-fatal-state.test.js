const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync('content/kiro/register-page.js', 'utf8');

function createTextNode(textContent = '') {
  return { textContent };
}

function createInputElement({
  id = '',
  type = 'text',
  placeholder = '',
  label = '',
  value = '',
} = {}) {
  const attributes = {
    id,
    type,
    placeholder,
    autocomplete: 'off',
  };
  return {
    tagName: 'INPUT',
    id,
    type,
    value,
    labels: label ? [createTextNode(label)] : [],
    disabled: false,
    readOnly: false,
    form: null,
    getAttribute(name) {
      return attributes[name] || '';
    },
    getBoundingClientRect() {
      return { width: 455, height: 32 };
    },
    closest(selector) {
      if (selector === 'label') {
        return null;
      }
      return null;
    },
  };
}

function createButtonElement({ text = 'Continue', testId = 'test-primary-button' } = {}) {
  return {
    tagName: 'BUTTON',
    textContent: text,
    value: '',
    disabled: false,
    form: null,
    getAttribute(name) {
      if (name === 'data-testid') return testId;
      if (name === 'type') return 'submit';
      return '';
    },
    getBoundingClientRect() {
      return { width: 455, height: 32 };
    },
    closest() {
      return null;
    },
  };
}

function createHarness({ href, hostname, title = '', bodyText = '' }) {
  return createDomHarness({ href, hostname, title, bodyText });
}

function createDomHarness({
  href,
  hostname,
  title = '',
  bodyText = '',
  inputs = [],
  buttons = [],
} = {}) {
  const elementsById = new Map();
  for (const element of [...inputs, ...buttons]) {
    if (element.id) {
      elementsById.set(element.id, element);
    }
  }
  const context = {
    console: { log() {}, warn() {}, error() {}, info() {} },
    location: { href, hostname },
    document: {
      title,
      body: {
        textContent: bodyText,
      },
      documentElement: {
        getAttribute() {
          return '1';
        },
        setAttribute() {},
      },
      getElementById(id) {
        return elementsById.get(id) || null;
      },
      querySelector() {
        return null;
      },
      querySelectorAll(selector) {
        if (String(selector).startsWith('label[for=')) {
          return [];
        }
        if (String(selector).trim().startsWith('input')) {
          return inputs;
        }
        if (String(selector).includes('button') || String(selector).includes('[role="button"]')) {
          return buttons;
        }
        return [];
      },
    },
    window: {},
    globalThis: null,
    resetStopState() {},
    isStopError() {
      return false;
    },
    throwIfStopped() {},
    sleep() {
      return Promise.resolve();
    },
    fillInput(element, value) {
      element.value = value;
    },
    MouseEvent: class {},
    PointerEvent: class {},
    KeyboardEvent: class {},
    Event: class {},
  };
  context.window = context;
  context.globalThis = context;
  context.window.getComputedStyle = () => ({ display: 'block', visibility: 'visible' });
  context.CSS = { escape: (value) => String(value) };

  vm.createContext(context);
  vm.runInContext(source, context);
  return context;
}

test('kiro register content detects aws request error page as a proxy failure', () => {
  const harness = createHarness({
    href: 'https://profile.aws.amazon.com/signup',
    hostname: 'profile.aws.amazon.com',
    title: '错误',
    bodyText: '抱歉，处理您的请求时出错。请重试。',
  });

  const detected = harness.detectKiroRegisterPageState();

  assert.equal(detected.state, 'proxy_error_page');
  assert.match(detected.fatalMessage, /切换代理/);
});

test('kiro register content does not misclassify the normal name page as a proxy failure', () => {
  const harness = createHarness({
    href: 'https://profile.aws.amazon.com/signup',
    hostname: 'profile.aws.amazon.com',
    title: 'Enter your name',
    bodyText: '输入您的姓名 继续',
  });

  const fatal = harness.detectKiroFatalPageState('输入您的姓名 继续', harness.location.href, harness.document.title);

  assert.equal(fatal, null);
});

test('kiro register content treats Kiro web success callback as signed in', () => {
  const harness = createHarness({
    href: 'https://app.kiro.dev/signin?auth_status=success&redirect_from=KiroIDE',
    hostname: 'app.kiro.dev',
    title: 'Kiro',
    bodyText: 'Signed in',
  });

  const detected = harness.detectKiroRegisterPageState();

  assert.equal(detected.state, 'kiro_web_signed_in');
});

test('kiro register content extracts signed-in account email from Kiro account page text', () => {
  const harness = createHarness({
    href: 'https://app.kiro.dev/settings/account',
    hostname: 'app.kiro.dev',
    title: 'Account',
    bodyText: 'Account Email scrap-aged-quirk@duck.com support@kiro.dev',
  });

  const detected = harness.detectKiroRegisterPageState();

  assert.equal(detected.state, 'kiro_web_signed_in');
  assert.equal(detected.accountEmail, 'scrap-aged-quirk@duck.com');
  assert.equal(detected.email, 'scrap-aged-quirk@duck.com');
});

test('kiro register content fills primary and confirm password fields separately', async () => {
  const passwordInput = createInputElement({
    id: 'formField15-1779204320095-7559',
    type: 'text',
    placeholder: 'Enter password',
    label: '\u5bc6\u7801',
  });
  const confirmPasswordInput = createInputElement({
    id: 'formField16-1779204320096-1309',
    type: 'text',
    placeholder: 'Re-enter password',
    label: '\u786e\u8ba4\u5bc6\u7801',
  });
  const checkboxInput = createInputElement({
    id: '17-1779204320097-4334',
    type: 'checkbox',
    label: '\u663e\u793a\u5bc6\u7801',
    value: 'on',
  });
  const continueButton = createButtonElement();
  const clicks = [];

  const harness = createDomHarness({
    href: 'https://us-east-1.signin.aws/platform/d-9067642ac7/signup',
    hostname: 'us-east-1.signin.aws',
    title: 'Amazon Web Services',
    bodyText: 'Create your password',
    inputs: [passwordInput, confirmPasswordInput, checkboxInput],
    buttons: [continueButton],
  });
  harness.simulateClick = (element) => clicks.push(element);

  const detected = harness.detectKiroRegisterPageState();
  assert.equal(detected.state, 'password_page');
  assert.equal(detected.passwordInput, passwordInput);
  assert.equal(detected.confirmPasswordInput, confirmPasswordInput);

  const result = await harness.submitKiroPassword({ password: 'mdy8U9_rzqhw6D' });

  assert.equal(result.state, 'password_submitted');
  assert.equal(passwordInput.value, 'mdy8U9_rzqhw6D');
  assert.equal(confirmPasswordInput.value, 'mdy8U9_rzqhw6D');
  assert.deepEqual(clicks, [continueButton]);
});
