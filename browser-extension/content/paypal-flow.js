// content/paypal-flow.js — paypal.com 页面
// /pay 登录页：填随机邮箱 → 下一步（走 guest/注册）
// /checkoutweb 结账页：country=JP → 填日区注册信息（假名+汉字+生日+卡号+都道府县）→ 提交
// 复刻 FlowPilot 机制：simulateClick(requestSubmit) + performOperationWithDelay + waitUntil。

(function () {
  const H = window.PPHelper;
  const JP = window.JPData;
  if (!H || !JP) return;

  const path = location.pathname;
  H.log('PayPal content script 已加载: host=' + location.host + ' path=' + path);

  function isLoginPage() {
    return !path.includes('/checkoutweb/')
      && (path === '/pay'
        || path.includes('/agreements/approve')
        || (document.getElementById('email') && document.getElementById('btnNext')));
  }

  function isCheckoutPage() {
    return path.includes('/checkoutweb/');
  }

  async function runLogin() {
    H.log('PayPal 登录页：填随机邮箱并下一步');
    const ready = await H.waitUntil(() => {
      const emailEl = document.getElementById('email')
        || document.querySelector('input[type="email"], input[name="login_email"]');
      const nextBtn = document.getElementById('btnNext')
        || Array.from(document.querySelectorAll('button')).find((b) => /次へ|Next/i.test(b.textContent || b.value || ''));
      return (emailEl && nextBtn) ? { emailEl, nextBtn } : null;
    }, { intervalMs: 500, timeoutMs: 30000 });

    if (!ready) { H.log('PayPal 登录页字段超时'); return; }

    const email = JP.randomEmail();
    H.log('PayPal 登录邮箱: ' + email);
    await H.performOperationWithDelay({ stepKey: 'paypal-login-email', delayMs: 800 }, async () => {
      H.fillById('email', email);
    });
    if (!ready.nextBtn.disabled) {
      await H.performOperationWithDelay({ stepKey: 'paypal-login-next', delayMs: 600 }, async () => {
        H.simulateClick(ready.nextBtn);
      });
    }
  }

  async function runCheckout() {
    H.log('PayPal guest checkout：设置 country=JP 并填写日区注册信息');
    const config = await H.getConfig();
    if (!config.cardNumber || !config.cardExpiry || !config.cardCvv) {
      H.log('未配置卡信息（卡号/有效期/CVV），请在侧边栏填写后重试');
      return;
    }

    // 设 country=JP，等待日区字段渲染
    const requiredIds = [
      'email', 'phone', 'cardNumber', 'cardExpiry', 'cardCvv',
      'billingPostalCode', 'billingState', 'billingLine1', 'password',
      'dateOfBirth', 'countrySpecificFirstName', 'countrySpecificLastName',
      'firstName', 'lastName',
    ];
    await H.waitUntil(() => {
      const country = document.getElementById('country');
      if (country && country.value !== 'JP') { H.fillInput(country, 'JP'); H.log('country -> JP'); }
      const missing = requiredIds.filter((id) => !document.getElementById(id));
      return missing.length === 0 ? true : null;
    }, { intervalMs: 500, timeoutMs: 40000 });

    for (let attempt = 0; attempt < 5; attempt++) {
      H.throwIfStopped();
      await H.performOperationWithDelay({ stepKey: 'paypal-fill', delayMs: 1000 }, async () => {
        const addr = JP.randomAddress();
        const name = JP.randomName();
        const email = JP.randomEmail();
        const password = JP.randomPassword();
        H.log('账号: ' + email + ' / 地址: ' + addr.state);
        H.fillById('email', email);
        H.fillById('phone', config.phone || '987654321');
        H.fillById('cardNumber', config.cardNumber);
        H.fillById('cardExpiry', config.cardExpiry);
        H.fillById('cardCvv', config.cardCvv);
        H.fillById('password', password);
        H.fillById('dateOfBirth', JP.randomBirthdate());
        H.fillById('countrySpecificFirstName', name.kanaFirst);
        H.fillById('countrySpecificLastName', name.kanaLast);
        H.fillById('firstName', name.kanjiFirst);
        H.fillById('lastName', name.kanjiLast);
        H.fillById('billingLine1', addr.street);
        H.fillById('billingCity', addr.city);
        H.fillById('billingPostalCode', addr.zip);
        H.fillSelectById('billingState', addr.stateValues || [addr.state]);
      });

      const empty = requiredIds.filter((id) => { const el = document.getElementById(id); return !el || !el.value; });
      if (empty.length === 0) { H.log('日区注册信息已填写完整'); break; }
      H.log('字段未填满，重试: ' + empty.join(','));
    }

    await H.submitAndConfirmNavigation({
      stayHostPattern: /\/checkoutweb\//i,
      maxRounds: 6,
    });
  }

  async function run() {
    const enabled = await H.isAutoEnabled();
    if (!enabled) { H.log('自动模式未开启，跳过 PayPal 自动操作'); return; }
    H.resetStop();
    if (isCheckoutPage()) { await runCheckout(); return; }
    if (isLoginPage()) { await runLogin(); return; }
    H.log('PayPal 页面未匹配登录/结账，跳过');
  }

  setTimeout(() => {
    run().catch((err) => {
      if (H.isStopError(err)) { H.log('已停止'); return; }
      H.log('PayPal 页执行异常: ' + (err && err.message ? err.message : err));
    });
  }, 1000);
})();
