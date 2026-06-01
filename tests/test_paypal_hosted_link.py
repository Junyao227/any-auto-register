import unittest
from unittest import mock

from platforms.chatgpt import payment


class _Account:
    def __init__(self, access_token="AT", cookies=""):
        self.access_token = access_token
        self.token = access_token
        self.cookies = cookies


class CurrencyResolveTests(unittest.TestCase):
    def test_explicit_currency_wins(self):
        self.assertEqual(payment.resolve_currency_for_country("US", "EUR"), "EUR")

    def test_country_maps_to_currency(self):
        self.assertEqual(payment.resolve_currency_for_country("DE"), "EUR")
        self.assertEqual(payment.resolve_currency_for_country("JP"), "JPY")
        self.assertEqual(payment.resolve_currency_for_country("GB"), "GBP")

    def test_unknown_country_defaults_usd(self):
        self.assertEqual(payment.resolve_currency_for_country("ZZ"), "USD")


class ExtractLongLinkTests(unittest.TestCase):
    def test_prefers_openai_payurl(self):
        data = {
            "url": "https://pay.openai.com/c/pay/cs_live_abc",
            "checkout_session_id": "cs_abc",
            "processor_entity": "openai_llc",
        }
        links = payment._extract_long_link(data)
        self.assertEqual(links["openai_payurl"], "https://pay.openai.com/c/pay/cs_live_abc")
        self.assertEqual(links["chatgpt_checkout_url"], "https://chatgpt.com/checkout/openai_llc/cs_abc")
        self.assertEqual(links["primary"], "https://pay.openai.com/c/pay/cs_live_abc")

    def test_falls_back_to_chatgpt_checkout(self):
        data = {"checkout_session_id": "cs_xyz", "processor_entity": "stripe"}
        links = payment._extract_long_link(data)
        self.assertNotIn("openai_payurl", links)
        self.assertEqual(links["chatgpt_checkout_url"], "https://chatgpt.com/checkout/stripe/cs_xyz")
        self.assertEqual(links["primary"], "https://chatgpt.com/checkout/stripe/cs_xyz")


class GenerateHostedLinkTests(unittest.TestCase):
    def _patch_post(self, response_json):
        fake_resp = mock.Mock()
        fake_resp.raise_for_status = mock.Mock()
        fake_resp.json = mock.Mock(return_value=response_json)
        return mock.patch.object(payment.cffi_requests, "post", return_value=fake_resp)

    def test_hosted_payload_uses_hosted_mode_and_promo(self):
        captured = {}

        def _fake_post(url, headers=None, json=None, proxies=None, timeout=None, impersonate=None):
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers
            resp = mock.Mock()
            resp.raise_for_status = mock.Mock()
            resp.json = mock.Mock(return_value={"url": "https://pay.openai.com/c/pay/cs_1"})
            return resp

        with mock.patch.object(payment.cffi_requests, "post", side_effect=_fake_post):
            links = payment.generate_paypal_hosted_link(
                _Account(), proxy=None, country="DE", use_promo=True, plan="plus"
            )

        self.assertEqual(captured["json"]["checkout_ui_mode"], "hosted")
        self.assertEqual(captured["json"]["plan_name"], "chatgptplusplan")
        self.assertEqual(captured["json"]["billing_details"], {"country": "DE", "currency": "EUR"})
        self.assertIn("promo_campaign", captured["json"])
        self.assertEqual(links["primary"], "https://pay.openai.com/c/pay/cs_1")

    def test_team_plan_no_plus_promo(self):
        captured = {}

        def _fake_post(url, headers=None, json=None, proxies=None, timeout=None, impersonate=None):
            captured["json"] = json
            resp = mock.Mock()
            resp.raise_for_status = mock.Mock()
            resp.json = mock.Mock(return_value={"checkout_session_id": "cs_2", "processor_entity": "openai_llc"})
            return resp

        with mock.patch.object(payment.cffi_requests, "post", side_effect=_fake_post):
            links = payment.generate_paypal_hosted_link(
                _Account(), country="US", use_promo=True, plan="team"
            )

        self.assertEqual(captured["json"]["plan_name"], "chatgptteamplan")
        # plus 专属 promo 不应加到 team
        self.assertNotIn("promo_campaign", captured["json"])
        self.assertEqual(links["primary"], "https://chatgpt.com/checkout/openai_llc/cs_2")

    def test_missing_access_token_raises(self):
        with self.assertRaises(ValueError):
            payment.generate_paypal_hosted_link(_Account(access_token=""))

    def test_no_usable_link_raises(self):
        with self._patch_post({"detail": "no link"}):
            with self.assertRaises(ValueError):
                payment.generate_paypal_hosted_link(_Account(), country="DE")

    def test_custom_mode_passed_through(self):
        captured = {}

        def _fake_post(url, headers=None, json=None, proxies=None, timeout=None, impersonate=None):
            captured["json"] = json
            resp = mock.Mock()
            resp.raise_for_status = mock.Mock()
            resp.json = mock.Mock(return_value={"checkout_session_id": "cs_3", "processor_entity": "openai_llc"})
            return resp

        with mock.patch.object(payment.cffi_requests, "post", side_effect=_fake_post):
            payment.generate_paypal_hosted_link(_Account(), country="US", checkout_ui_mode="custom")

        self.assertEqual(captured["json"]["checkout_ui_mode"], "custom")

    def test_invalid_mode_falls_back_to_hosted(self):
        captured = {}

        def _fake_post(url, headers=None, json=None, proxies=None, timeout=None, impersonate=None):
            captured["json"] = json
            resp = mock.Mock()
            resp.raise_for_status = mock.Mock()
            resp.json = mock.Mock(return_value={"url": "https://pay.openai.com/c/pay/cs_4"})
            return resp

        with mock.patch.object(payment.cffi_requests, "post", side_effect=_fake_post):
            payment.generate_paypal_hosted_link(_Account(), country="US", checkout_ui_mode="bogus")

        self.assertEqual(captured["json"]["checkout_ui_mode"], "hosted")


class ProxyEgressCheckTests(unittest.TestCase):
    def test_normalizes_ipwho_response(self):
        fake_resp = mock.Mock()
        fake_resp.status_code = 200
        fake_resp.json = mock.Mock(return_value={
            "ip": "1.2.3.4", "country": "Germany", "country_code": "DE",
            "region": "Berlin", "city": "Berlin", "connection": {"isp": "Foo ISP"},
        })
        with mock.patch.object(payment.cffi_requests, "get", return_value=fake_resp):
            result = payment.check_proxy_egress("http://127.0.0.1:7890")
        self.assertEqual(result["ip"], "1.2.3.4")
        self.assertEqual(result["country_code"], "DE")
        self.assertEqual(result["isp"], "Foo ISP")
        self.assertEqual(result["proxy_used"], "http://127.0.0.1:7890")

    def test_all_services_fail_raises(self):
        with mock.patch.object(payment.cffi_requests, "get", side_effect=Exception("boom")):
            with self.assertRaises(RuntimeError):
                payment.check_proxy_egress(None)


if __name__ == "__main__":
    unittest.main()
