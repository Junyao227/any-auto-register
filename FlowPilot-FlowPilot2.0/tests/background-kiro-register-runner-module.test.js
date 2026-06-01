const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');

function loadRegisterRunnerApi() {
  const stateSource = fs.readFileSync('background/kiro/state.js', 'utf8');
  const runnerSource = fs.readFileSync('background/kiro/register-runner.js', 'utf8');
  const globalScope = {};
  new Function('self', `${stateSource}; ${runnerSource}; return self;`)(globalScope);
  return globalScope.MultiPageBackgroundKiroRegisterRunner;
}

test('kiro register runner module exposes a factory and Kiro official sign-in entry', () => {
  const api = loadRegisterRunnerApi();
  assert.equal(typeof api?.createKiroRegisterRunner, 'function');
  assert.equal(api?.KIRO_SIGNIN_URL, 'https://app.kiro.dev/signin');
});

test('kiro register runner removed the old AWS device authorization bootstrap', () => {
  const source = fs.readFileSync('background/kiro/register-runner.js', 'utf8');
  assert.doesNotMatch(source, /startBuilderIdDeviceLogin/);
  assert.doesNotMatch(source, /device_authorization/);
  assert.doesNotMatch(source, /verificationUriComplete/);
  assert.match(source, /https:\/\/app\.kiro\.dev\/signin/);
});

test('kiro register runner uses a shared 3-minute page-load timeout budget', () => {
  const source = fs.readFileSync('background/kiro/register-runner.js', 'utf8');
  assert.match(source, /DEFAULT_KIRO_PAGE_LOAD_TIMEOUT_MS/);
  assert.match(source, /createTimeoutBudget/);
  assert.match(source, /resolveTimeoutBudget/);
  assert.match(source, /timeoutBudget\.getRemainingMs\(1000\)/);
  assert.match(source, /onRetryableError: buildKiroRetryRecovery\(tabId, \{\s*\.\.\.options,\s*timeoutBudget,/);
});

test('kiro register consent step treats Kiro Web signed-in page as completion', () => {
  const source = fs.readFileSync('background/kiro/register-runner.js', 'utf8');
  assert.match(source, /targetStates: \['authorization_page', 'kiro_web_signed_in'\]/);
  assert.match(source, /landingResult\?\.state !== 'kiro_web_signed_in'/);
  assert.doesNotMatch(source, /landingResult\?\.state !== 'success_page'/);
});
