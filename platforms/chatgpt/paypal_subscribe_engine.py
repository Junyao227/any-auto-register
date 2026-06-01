"""PayPal 自动订阅引擎（Playwright，日区 JP）。

链路（移植自 FlowPilot content scripts + 用户提供的日区 PayPal Auto Filler）：
  1. 用 headed Playwright + 代理打开 pay.openai.com 长链
  2. OpenAI/Stripe 托管页：选 PayPal → 填账单地址 → 勾选条款 → 提交，跳转 PayPal
  3. PayPal 登录页 /pay：填随机邮箱 → 下一步（走 guest/注册分支）
  4. PayPal guest checkout /checkoutweb：country=JP → 填日区注册信息（假名+汉字+生日+
     都道府县+卡号）→ 提交完成订阅

注意：这是有头自动化，选择器随 PayPal/OpenAI 页面改版会失效，需在真实环境校准。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from core.browser_runtime import ensure_browser_display_available, resolve_browser_headless
from core.proxy_utils import build_playwright_proxy_config, normalize_proxy_url

from . import paypal_jp_data as jp

logger = logging.getLogger(__name__)


@dataclass
class PayPalSubscribeResult:
    success: bool
    stage: str = ""
    error_message: str = ""
    logs: list[str] = field(default_factory=list)


# OpenAI / Stripe 托管页选择器
_OAI_PAYPAL_BUTTON = [
    '[data-testid="paypal-accordion-item-button"]',
    '.paypal-accordion-item button',
    '#payment-method-accordion-item-title-paypal',
    'input[value="paypal"]',
]
_OAI_SUBMIT_BUTTON = [
    'button[data-testid="submit-button"]',
    'button[data-testid="hosted-payment-submit-button"]',
    'button[data-atomic-wait-intent="Submit_Email"]',
    'button.SubmitButton--complete',
    'button[type="submit"]',
]


class PayPalSubscribeEngine:
    def __init__(
        self,
        *,
        long_link: str,
        proxy_url: Optional[str] = None,
        card_number: str,
        card_expiry: str,
        card_cvv: str,
        phone: str = "987654321",
        region: str = "JP",
        headless: bool = False,
        callback_logger: Optional[Callable[[str], None]] = None,
        nav_timeout_ms: int = 60000,
    ):
        self.long_link = str(long_link or "").strip()
        self.proxy_url = normalize_proxy_url(proxy_url) if proxy_url else None
        self.card_number = str(card_number or "").strip()
        self.card_expiry = str(card_expiry or "").strip()
        self.card_cvv = str(card_cvv or "").strip()
        self.phone = str(phone or "987654321").strip()
        self.region = str(region or "JP").strip().upper()
        self.headless = headless
        self.nav_timeout_ms = int(nav_timeout_ms or 60000)
        self._cb = callback_logger or (lambda msg: logger.info(msg))
        self.logs: list[str] = []

    def _log(self, message: str) -> None:
        self.logs.append(message)
        self._cb(f"[PayPal订阅] {message}")

    # ── 通用 DOM 工具 ─────────────────────────────────────────────
    @staticmethod
    def _fill(page, selector: str, value: str) -> bool:
        try:
            el = page.query_selector(selector)
            if not el:
                return False
            el.fill(str(value or ""))
            el.dispatch_event("input")
            el.dispatch_event("change")
            el.dispatch_event("blur")
            return True
        except Exception:
            return False

    @staticmethod
    def _fill_by_id(page, element_id: str, value: str) -> bool:
        return PayPalSubscribeEngine._fill(page, f"#{element_id}", value)

    def _select_option_by_values(self, page, element_id: str, values: list[str]) -> bool:
        """按候选值/文本匹配下拉选项（移植脚本的两轮匹配：先精确后包含）。"""
        try:
            select = page.query_selector(f"#{element_id}")
            if not select:
                return False
            options = select.query_selector_all("option")
            opt_data = []
            for opt in options:
                opt_data.append((
                    (opt.get_attribute("value") or "").strip(),
                    (opt.inner_text() or "").strip(),
                ))
            # 第一轮精确
            for want in values:
                w = str(want or "").strip().lower()
                for val, text in opt_data:
                    if val.lower() == w or text.lower() == w:
                        select.select_option(value=val)
                        return True
            # 第二轮包含
            for want in values:
                w = str(want or "").strip().lower()
                if not w:
                    continue
                for val, text in opt_data:
                    if w in val.lower() or w in text.lower():
                        select.select_option(value=val)
                        return True
        except Exception as exc:
            self._log(f"下拉选择异常 {element_id}: {exc}")
        return False

    def _click_submit(self, page, selectors: list[str], texts: list[str]) -> bool:
        for sel in selectors:
            try:
                el = page.query_selector(sel)
                if el and el.is_enabled() and el.is_visible():
                    el.click()
                    return True
            except Exception:
                continue
        # 兜底按文本
        try:
            for btn in page.query_selector_all("button"):
                t = (btn.inner_text() or "").strip()
                if any(t == x or x in t for x in texts):
                    if btn.is_enabled() and btn.is_visible():
                        btn.click()
                        return True
        except Exception:
            pass
        return False

    @staticmethod
    def _host_path(page) -> tuple[str, str]:
        try:
            from urllib.parse import urlparse

            parsed = urlparse(page.url)
            return (parsed.netloc or "").lower(), parsed.path or ""
        except Exception:
            return "", ""

    # ── 阶段 1：OpenAI 托管页选 PayPal + 提交 ──────────────────────
    def _find_paypal_control(self, page):
        """在 OpenAI/Stripe 托管页查找 PayPal 选项（accordion 按钮 / radio / 文本行）。"""
        for s in _OAI_PAYPAL_BUTTON:
            el = page.query_selector(s)
            if el:
                return el, s
        # 文本兜底：找含 PayPal 文案的可点行/标签/单选
        try:
            for el in page.query_selector_all('label, [role="radio"], [role="button"], button, div'):
                try:
                    if not el.is_visible():
                        continue
                    txt = (el.inner_text() or "").strip().lower()
                except Exception:
                    continue
                if "paypal" in txt and len(txt) < 40:
                    return el, "text:paypal"
        except Exception:
            pass
        return None, ""

    def _select_paypal(self, page) -> bool:
        el, how = self._find_paypal_control(page)
        if not el:
            return False
        for attempt in range(3):
            try:
                el.click()
                self._log(f"已点击 PayPal 选项（{how}，第{attempt + 1}次）")
            except Exception as exc:
                self._log(f"点击 PayPal 异常: {exc}")
            page.wait_for_timeout(700)
            # 验证是否已选中（radio checked 或出现 PayPal 文案被选中态）
            try:
                radio = page.query_selector('input[value="paypal"]') or page.query_selector('#payment-method-accordion-item-title-paypal')
                if radio and radio.is_checked():
                    return True
            except Exception:
                pass
            # 重新定位（DOM 可能刷新）
            el, how = self._find_paypal_control(page)
            if not el:
                return True  # 找不到通常说明已切换/选中
        return True

    def _check_consent(self, page) -> None:
        try:
            consent = page.query_selector("#termsOfServiceConsentCheckbox") or page.query_selector('input[type="checkbox"]')
            if consent and not consent.is_checked():
                consent.click()
                self._log("已勾选条款")
        except Exception:
            pass

    def _handle_openai_page(self, page, address: dict) -> bool:
        """OpenAI/Stripe 托管页：选 PayPal + 模糊匹配填账单地址 + 勾选条款 + 点订阅。

        采用 page.evaluate 注入 JS，复刻用户验证过的脚本逻辑（按 id/name/placeholder/
        aria-label/autocomplete 多候选模糊匹配字段），以适配 PayPal 模式下展开的
        国家下拉 + 地址自动补全输入框。
        """
        self._log("OpenAI 托管页：选 PayPal 并填写日本账单地址...")
        deadline = time.time() + 40
        while time.time() < deadline:
            el, how = self._find_paypal_control(page)
            if el:
                self._log(f"检测到 PayPal 选项（{how}）")
                break
            page.wait_for_timeout(800)

        js = r"""
        (addr) => {
          const log = [];
          function isVisible(el){ if(!el) return false; return !!(el.offsetWidth||el.offsetHeight||(el.getClientRects&&el.getClientRects().length)); }
          function setVal(el, value){
            if(!el) return false;
            let proto = el instanceof HTMLSelectElement ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
            if(window.HTMLTextAreaElement && el instanceof HTMLTextAreaElement) proto = HTMLTextAreaElement.prototype;
            const desc = Object.getOwnPropertyDescriptor(proto, 'value');
            if(desc && desc.set) desc.set.call(el, value); else el.value = value;
            el.dispatchEvent(new Event('input',{bubbles:true}));
            el.dispatchEvent(new Event('change',{bubbles:true}));
            el.dispatchEvent(new Event('blur',{bubbles:true}));
            return true;
          }
          function fieldText(el){
            return [el.id, el.name, el.getAttribute&&el.getAttribute('autocomplete'),
              el.getAttribute&&el.getAttribute('placeholder'), el.getAttribute&&el.getAttribute('aria-label'),
              el.getAttribute&&el.getAttribute('data-testid'),
              el.closest&&el.closest('label')&&el.closest('label').textContent].join(' ').toLowerCase();
          }
          function findField(cands, selector){
            const fields = Array.from(document.querySelectorAll(selector||'input, textarea, select')).filter(el=>!el.disabled&&isVisible(el));
            for(const c of cands){ const key=String(c).toLowerCase(); for(const f of fields){ if(fieldText(f).indexOf(key)!==-1) return f; } }
            return null;
          }
          function setAnyField(label, cands, value){
            const el = findField(cands, 'input, textarea');
            if(!el){ log.push('NOT FOUND '+label); return false; }
            setVal(el, value); log.push(label+' -> '+(el.id||el.name||el.getAttribute('placeholder')||'')); return true;
          }
          function setAnySelect(label, cands, values){
            const el = findField(cands, 'select');
            if(!el){ log.push('NOT FOUND select '+label); return false; }
            values = Array.isArray(values)?values:[values];
            for(const want of values){ const w=String(want).toLowerCase();
              for(const opt of el.options){ const t=String(opt.text||opt.textContent||'').toLowerCase(); const v=String(opt.value||'').toLowerCase();
                if(t.indexOf(w)!==-1||v.indexOf(w)!==-1){ setVal(el, opt.value); log.push(label+' -> '+opt.text); return true; } } }
            log.push('NO OPTION '+label); return false;
          }
          function clickPaypal(){
            const sel = document.getElementById('payment-method-accordion-item-title-paypal')||document.querySelector('input[value="paypal"]');
            if(sel && sel.checked){ log.push('PayPal already selected'); return true; }
            let btn = document.querySelector('[data-testid="paypal-accordion-item-button"]')||document.querySelector('.paypal-accordion-item button');
            if(btn){ btn.click(); log.push('clicked paypal accordion'); return true; }
            const radio = document.getElementById('payment-method-accordion-item-title-paypal')||document.querySelector('input[value="paypal"]')||document.querySelector('input[id*="paypal" i]');
            if(radio){ radio.click(); radio.checked=true; radio.dispatchEvent(new Event('input',{bubbles:true})); radio.dispatchEvent(new Event('change',{bubbles:true})); const lb=radio.closest&&radio.closest('label'); if(lb) lb.click(); log.push('clicked paypal radio'); return true; }
            const cands = Array.from(document.querySelectorAll('button,label,[role="button"],[role="radio"],div'));
            for(const el of cands){ const meta=[el.textContent||'', el.getAttribute&&el.getAttribute('aria-label')||'', el.id||''].join(' '); if(/paypal/i.test(meta)){ el.click(); log.push('clicked paypal fallback'); return true; } }
            log.push('paypal not found'); return false;
          }
          function hideAutocomplete(){
            ['.AddressAutocomplete-results','[class*="AddressAutocomplete"]','#billing-address-autocomplete-results'].forEach(s=>{
              document.querySelectorAll(s).forEach(n=>{ try{ n.style.setProperty('display','none','important'); n.style.setProperty('pointer-events','none','important'); }catch(e){} });
            });
          }
          clickPaypal();
          hideAutocomplete();
          const ok1 = setAnyField('addressLine1', ['billingAddressLine1','billing-address-line1','addressLine1','address-line1','line1','shippingAddressLine1','address','地址','住所','輸入地址','输入地址'], addr.street);
          const okCity = setAnyField('city', ['billingLocality','locality','city','address-level2','市区町村'], addr.city);
          const okZip = setAnyField('zip', ['billingPostalCode','postalCode','postal-code','zip','郵便番号'], addr.zip);
          const okState = setAnySelect('state', ['billingAdministrativeArea','administrativeArea','state','province','prefecture','address-level1','都道府県'], addr.state_values||addr.state);
          const cb = document.getElementById('termsOfServiceConsentCheckbox')||document.querySelector('input[type="checkbox"][name*="terms" i]')||document.querySelector('input[type="checkbox"]');
          if(cb && !cb.checked){ cb.click(); log.push('checkbox checked'); }
          hideAutocomplete();
          return { ok1, okCity, okZip, okState, log };
        }
        """
        last = {}
        for attempt in range(15):
            try:
                last = page.evaluate(js, address)
            except Exception as exc:
                self._log(f"注入填表异常: {exc}")
                last = {}
            ok1 = last.get("ok1")
            ok_zip = last.get("okZip")
            ok_state = last.get("okState")
            if attempt == 0 and last.get("log"):
                self._log("填表诊断: " + " | ".join(last.get("log", [])[:12]))
            # 地址+邮编填上即可（city/state 视页面而定）
            if ok1 and ok_zip:
                self._log(f"OpenAI 账单地址已填写 (state={ok_state})")
                break
            page.wait_for_timeout(1000)

        page.wait_for_timeout(500)
        clicked = self._click_submit(
            page,
            _OAI_SUBMIT_BUTTON,
            ["订阅", "下一页", "Subscribe", "Pay", "Continue", "Next", "Agree", "確定", "確認"],
        )
        self._log(f"OpenAI 订阅/提交按钮点击: {clicked}")
        return clicked

    # ── 阶段 2：PayPal 登录页 /pay ─────────────────────────────────
    def _handle_paypal_login(self, page) -> bool:
        self._log("PayPal 登录页：填随机邮箱并下一步...")
        deadline = time.time() + 40
        email = jp.random_email()
        while time.time() < deadline:
            email_el = page.query_selector("#email") or page.query_selector('input[type="email"], input[name="login_email"]')
            next_btn = page.query_selector("#btnNext")
            if email_el and next_btn:
                self._fill(page, "#email", email)
                self._log(f"PayPal 登录邮箱: {email}")
                try:
                    next_btn.click()
                except Exception:
                    self._click_submit(page, ["#btnNext"], ["次へ", "Next"])
                return True
            page.wait_for_timeout(500)
        return False

    # ── 阶段 3：PayPal guest checkout /checkoutweb（日区注册）──────
    def _handle_paypal_checkout_jp(self, page, address: dict) -> bool:
        self._log("PayPal guest checkout：设置 country=JP 并等待日区字段...")
        # 设 country=JP
        try:
            country = page.query_selector("#country")
            if country:
                country.select_option(value="JP")
                country.dispatch_event("change")
                page.wait_for_timeout(800)
        except Exception:
            pass

        required = [
            "email", "phone", "cardNumber", "cardExpiry", "cardCvv",
            "billingPostalCode", "billingState", "billingLine1", "password",
            "dateOfBirth", "countrySpecificFirstName", "countrySpecificLastName",
            "firstName", "lastName",
        ]
        deadline = time.time() + 50
        while time.time() < deadline:
            missing = [rid for rid in required if not page.query_selector(f"#{rid}")]
            if not missing:
                self._log("PayPal 日区字段已就绪")
                break
            page.wait_for_timeout(500)

        for attempt in range(5):
            email = jp.random_email()
            password = jp.random_password()
            name = jp.random_jp_name()
            self._fill_by_id(page, "email", email)
            self._fill_by_id(page, "phone", self.phone)
            self._fill_by_id(page, "cardNumber", self.card_number)
            self._fill_by_id(page, "cardExpiry", self.card_expiry)
            self._fill_by_id(page, "cardCvv", self.card_cvv)
            self._fill_by_id(page, "password", password)
            self._fill_by_id(page, "dateOfBirth", jp.random_birthdate())
            # 日区：假名 + 汉字
            self._fill_by_id(page, "countrySpecificFirstName", name["kana_first"])
            self._fill_by_id(page, "countrySpecificLastName", name["kana_last"])
            self._fill_by_id(page, "firstName", name["kanji_first"])
            self._fill_by_id(page, "lastName", name["kanji_last"])
            self._fill_by_id(page, "billingLine1", address["street"])
            self._fill_by_id(page, "billingCity", address["city"])
            self._fill_by_id(page, "billingPostalCode", address["zip"])
            self._select_option_by_values(page, "billingState", address.get("state_values") or [address["state"]])

            # 校验非空
            empty = []
            for rid in required:
                el = page.query_selector(f"#{rid}")
                value = ""
                if el is not None:
                    try:
                        value = el.input_value()
                    except Exception:
                        value = el.get_attribute("value") or ""
                if not value:
                    empty.append(rid)
            if not empty:
                self._log("PayPal 日区注册信息已填写完整")
                break
            self._log(f"字段未填满，重试: {empty}")
            page.wait_for_timeout(1000)

        clicked = self._click_submit(
            page,
            [
                'button[data-testid="submit-button"]',
                'button[data-testid="hosted-payment-submit-button"]',
                'button[data-atomic-wait-intent="Submit_Email"]',
                'button.SubmitButton--complete',
            ],
            ["下一页", "Next", "Subscribe", "Pay", "Continue", "Agree"],
        )
        self._log(f"PayPal checkout 提交点击: {clicked}")
        return clicked

    # ── 主流程 ────────────────────────────────────────────────────
    def run(self) -> PayPalSubscribeResult:
        result = PayPalSubscribeResult(success=False, logs=self.logs)
        if not self.long_link:
            result.error_message = "缺少支付长链"
            return result
        if not (self.card_number and self.card_expiry and self.card_cvv):
            result.error_message = "缺少卡信息（请在全局配置 PayPal 订阅里填写卡号/有效期/CVV）"
            return result
        if self.region != "JP":
            result.error_message = f"当前仅支持日区(JP)自动订阅，收到: {self.region}"
            return result

        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            result.error_message = "playwright 未安装"
            return result

        headless, reason = resolve_browser_headless(self.headless)
        try:
            ensure_browser_display_available(headless)
        except RuntimeError as exc:
            result.error_message = str(exc)
            return result

        address = jp.random_jp_address()
        self._log(f"使用日区地址: {address['state']} {address['city']} {address['zip']}")
        self._log(f"浏览器模式: {'headless' if headless else 'headed'} ({reason})")
        if self.proxy_url:
            self._log(f"使用代理: {self.proxy_url}")

        with sync_playwright() as p:
            launch_opts: dict = {"headless": headless}
            proxy_cfg = build_playwright_proxy_config(self.proxy_url) if self.proxy_url else None
            if proxy_cfg:
                launch_opts["proxy"] = proxy_cfg
            browser = p.chromium.launch(**launch_opts)
            context = browser.new_context()
            page = context.new_page()
            page.set_default_navigation_timeout(self.nav_timeout_ms)
            page.set_default_timeout(self.nav_timeout_ms)
            try:
                self._log("打开支付长链...")
                page.goto(self.long_link)
                page.wait_for_load_state("domcontentloaded")
                page.wait_for_timeout(1500)

                # 阶段机：按页面 host/path 推进，最多巡检若干轮
                stage_deadline = time.time() + 240
                openai_attempts = 0
                handled_login = False
                while time.time() < stage_deadline:
                    host, path = self._host_path(page)
                    self._log(f"当前页面: host={host} path={path}")

                    if "pay.openai.com" in host or "checkout.stripe.com" in host:
                        if openai_attempts < 3:
                            result.stage = "openai_checkout"
                            openai_attempts += 1
                            self._handle_openai_page(page, address)
                            # 等待跳转 PayPal
                            try:
                                page.wait_for_url("**paypal.com**", timeout=15000)
                            except Exception:
                                page.wait_for_timeout(2000)
                        else:
                            self._log("OpenAI 页多次尝试仍未跳转 PayPal，请检查页面是否需要人工操作")
                            page.wait_for_timeout(3000)
                    elif "paypal.com" in host and "/checkoutweb/" in path:
                        result.stage = "paypal_checkout_jp"
                        self._handle_paypal_checkout_jp(page, address)
                        page.wait_for_timeout(3000)
                        result.success = True
                        self._log("已完成日区 PayPal 信息提交")
                        break
                    elif "paypal.com" in host and (path == "/pay" or "/agreements/approve" in path or page.query_selector("#email")):
                        if not handled_login:
                            result.stage = "paypal_login"
                            self._handle_paypal_login(page)
                            handled_login = True
                            page.wait_for_timeout(3000)
                        else:
                            page.wait_for_timeout(2000)
                    else:
                        page.wait_for_timeout(2000)

                if not result.success and result.stage == "paypal_checkout_jp":
                    result.success = True

                if not result.success and not result.error_message:
                    result.error_message = f"订阅流程未走到完成阶段（最后停在 {result.stage or 'unknown'}）"
            except Exception as exc:
                logger.exception("PayPal 订阅异常")
                result.error_message = f"订阅异常: {exc}"
            finally:
                # headed 模式下保留窗口一会，便于人工接管/观察
                if not headless:
                    page.wait_for_timeout(5000)
                browser.close()

        return result
