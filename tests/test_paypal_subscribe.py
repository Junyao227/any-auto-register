import unittest
from unittest import mock

from platforms.chatgpt import paypal_jp_data as jp
from platforms.chatgpt.paypal_subscribe_engine import PayPalSubscribeEngine, PayPalSubscribeResult


class JpDataTests(unittest.TestCase):
    def test_address_has_required_fields(self):
        addr = jp.random_jp_address()
        for key in ("street", "city", "state", "state_values", "zip"):
            self.assertIn(key, addr)
        self.assertTrue(addr["zip"].isdigit())
        self.assertIsInstance(addr["state_values"], list)

    def test_name_has_kana_and_kanji(self):
        name = jp.random_jp_name()
        for key in ("kana_first", "kana_last", "kanji_first", "kanji_last"):
            self.assertIn(key, name)
            self.assertTrue(name[key])

    def test_random_email_format(self):
        email = jp.random_email()
        self.assertTrue(email.endswith("@gmail.com"))
        self.assertEqual(len(email.split("@")[0]), 16)

    def test_random_password_strength(self):
        pwd = jp.random_password()
        self.assertGreaterEqual(len(pwd), 14)

    def test_random_birthdate_format(self):
        bd = jp.random_birthdate()
        parts = bd.split("/")
        self.assertEqual(len(parts), 3)
        self.assertEqual(len(parts[0]), 4)


class _FakeOption:
    def __init__(self, value, text):
        self._value = value
        self._text = text

    def get_attribute(self, name):
        return self._value if name == "value" else ""

    def inner_text(self):
        return self._text


class _FakeSelect:
    def __init__(self, options):
        self._options = options
        self.selected = None

    def query_selector_all(self, _sel):
        return self._options

    def select_option(self, value=None):
        self.selected = value


class _FakePage:
    def __init__(self, selects=None):
        self._selects = selects or {}

    def query_selector(self, sel):
        key = sel.lstrip("#")
        return self._selects.get(key)


class SelectOptionTests(unittest.TestCase):
    def _engine(self):
        return PayPalSubscribeEngine(
            long_link="https://pay.openai.com/c/pay/cs_1",
            card_number="4716496584287236",
            card_expiry="03 / 28",
            card_cvv="800",
            region="JP",
        )

    def test_exact_value_match_preferred(self):
        select = _FakeSelect([
            _FakeOption("TOKYO-TO", "東京都"),
            _FakeOption("OSAKA-FU", "大阪府"),
        ])
        page = _FakePage({"billingState": select})
        ok = self._engine()._select_option_by_values(page, "billingState", ["TOKYO-TO", "Tokyo", "東京都"])
        self.assertTrue(ok)
        self.assertEqual(select.selected, "TOKYO-TO")

    def test_contains_match_fallback(self):
        select = _FakeSelect([
            _FakeOption("JP-13", "Tokyo Metropolis"),
        ])
        page = _FakePage({"billingState": select})
        ok = self._engine()._select_option_by_values(page, "billingState", ["Tokyo"])
        self.assertTrue(ok)
        self.assertEqual(select.selected, "JP-13")

    def test_no_match_returns_false(self):
        select = _FakeSelect([_FakeOption("US-CA", "California")])
        page = _FakePage({"billingState": select})
        ok = self._engine()._select_option_by_values(page, "billingState", ["Tokyo", "東京都"])
        self.assertFalse(ok)

    def test_missing_select_returns_false(self):
        page = _FakePage({})
        ok = self._engine()._select_option_by_values(page, "billingState", ["Tokyo"])
        self.assertFalse(ok)


class RunGuardTests(unittest.TestCase):
    def test_missing_long_link(self):
        engine = PayPalSubscribeEngine(
            long_link="", card_number="4", card_expiry="03/28", card_cvv="800"
        )
        result = engine.run()
        self.assertFalse(result.success)
        self.assertIn("长链", result.error_message)

    def test_missing_card(self):
        engine = PayPalSubscribeEngine(
            long_link="https://pay.openai.com/c", card_number="", card_expiry="", card_cvv=""
        )
        result = engine.run()
        self.assertFalse(result.success)
        self.assertIn("卡信息", result.error_message)

    def test_non_jp_region_rejected(self):
        engine = PayPalSubscribeEngine(
            long_link="https://pay.openai.com/c",
            card_number="4716496584287236",
            card_expiry="03 / 28",
            card_cvv="800",
            region="US",
        )
        result = engine.run()
        self.assertFalse(result.success)
        self.assertIn("JP", result.error_message)


if __name__ == "__main__":
    unittest.main()
