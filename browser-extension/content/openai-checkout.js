// content/openai-checkout.js — pay.openai.com / checkout.stripe.com 页面
// 选择 PayPal + 填写日本账单地址 + 勾选条款 + 点订阅，跳转到 PayPal。
// 复刻 FlowPilot 机制：simulateClick(requestSubmit) + performOperationWithDelay + waitUntil。

(function () {
  const H = window.PPHelper;
  const JP = window.JPData;
  if (!H || !JP) return;

  H.log('OpenAI/Stripe checkout content script 已加载: ' + location.href);

  function findPaypalControl() {
    let el = document.querySelector('[data-testid="paypal-accordion-item-button"]')
      || document.querySelector('.paypal-accordion-item button')
      || document.getElementById('payment-method-accordion-item-title-paypal')
      || document.querySelector('input[value="paypal"]')
      || document.querySelector('input[id*="paypal" i]')
      || document.querySelector('input[name*="payment"][value*="paypal" i]');
    if (el) return el;
    const cands = Array.from(document.querySelectorAll('button, label, [role="button"], [role="radio"], div'));
    for (const c of cands) {
      const meta = [c.textContent || '', c.getAttribute && c.getAttribute('aria-label') || '', c.id || '', c.className || ''].join(' ');
      if (/paypal/i.test(meta) && (c.textContent || '').trim().length < 40) return c;
    }
    return null;
  }

  function paypalSelected() {
    const sel = document.getElementById('payment-method-accordion-item-title-paypal')
      || document.querySelector('input[value="paypal"]');
    return Boolean(sel && sel.checked);
  }

  async function selectPaypal() {
    if (paypalSelected()) { H.log('PayPal 已选中'); return true; }
    const el = findPaypalControl();
    if (!el) { H.log('未找到 PayPal 选项'); return false; }
    await H.performOperationWithDelay({ stepKey: 'select-paypal', delayMs: 800 }, async () => {
      H.simulateClick(el);
      const label = el.closest && el.closest('label');
      if (label && label !== el) { try { label.click(); } catch (_) {} }
    });
    return true;
  }

  function fillAddress(addr) {
    H.hideAddressAutocomplete();
    const ok1 = H.setAnyField('地址行', [
      'billingAddressLine1', 'billing-address-line1', 'addressLine1', 'address-line1', 'line1',
      'shippingAddressLine1', 'address', '地址', '住所', '輸入地址', '输入地址',
    ], addr.street);
    const okCity = H.setAnyField('城市', ['billingLocality', 'locality', 'city', 'address-level2', '市区町村'], addr.city);
    const okZip = H.setAnyField('邮编', ['billingPostalCode', 'postalCode', 'postal-code', 'zip', '郵便番号'], addr.zip);
    const okState = H.setAnySelect('都道府县', [
      'billingAdministrativeArea', 'administrativeArea', 'state', 'province', 'prefecture', 'address-level1', '都道府県',
    ], addr.stateValues || addr.state);
    const cb = document.getElementById('termsOfServiceConsentCheckbox')
      || document.querySelector('input[type="checkbox"][name*="terms" i]')
      || document.querySelector('input[type="checkbox"]');
    if (cb && !cb.checked) { try { cb.click(); H.log('勾选条款'); } catch (_) {} }
    H.hideAddressAutocomplete();
    return { ok1, okCity, okZip, okState };
  }

  async function run() {
    const enabled = await H.isAutoEnabled();
    if (!enabled) { H.log('自动模式未开启，跳过 OpenAI 页面自动操作'); return; }
    H.resetStop();

    const addr = JP.randomAddress();
    H.log('使用日本地址: ' + addr.state + ' ' + addr.city + ' ' + addr.zip);

    // 等待 PayPal 选项出现
    const paypalCtl = await H.waitUntil(() => findPaypalControl(), { intervalMs: 500, timeoutMs: 30000 });
    if (!paypalCtl) { H.log('超时未出现 PayPal 选项（确认长链地区显示 PayPal）'); return; }

    await selectPaypal();

    // 多次尝试填地址（每轮带操作延迟），等字段渲染
    let filled = false;
    for (let attempt = 0; attempt < 15; attempt++) {
      H.throwIfStopped();
      const r = await H.performOperationWithDelay({ stepKey: 'fill-address', delayMs: 1000 }, async () => fillAddress(addr));
      if (r.ok1 && r.okZip) { filled = true; H.log('账单地址已填写'); break; }
    }
    if (!filled) H.log('账单地址未完全填写（可能页面字段变化），仍尝试提交');

    H.hideAddressAutocomplete();
    await H.submitAndConfirmNavigation({
      stayHostPattern: /pay\.openai\.com|checkout\.stripe\.com/i,
      maxRounds: 6,
    });
  }

  setTimeout(() => {
    run().catch((err) => {
      if (H.isStopError(err)) { H.log('已停止'); return; }
      H.log('OpenAI 页执行异常: ' + (err && err.message ? err.message : err));
    });
  }, 1500);
})();
