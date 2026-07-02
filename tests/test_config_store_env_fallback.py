import tempfile
import unittest
from pathlib import Path

from core.config_store import (
    _canonical_config_key,
    _get_env_fallback_value,
    _load_env_file,
    _merge_env_fallback,
    _normalize_config_value,
)


class ConfigStoreEnvFallbackTests(unittest.TestCase):
    def test_normalize_config_value_strips_matching_quotes(self):
        self.assertEqual(_normalize_config_value('"quoted"'), "quoted")
        self.assertEqual(_normalize_config_value("'quoted'"), "quoted")
        self.assertEqual(_normalize_config_value("plain"), "plain")

    def test_load_env_file_supports_export_and_quotes(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            env_path = Path(tmp_dir) / ".env"
            env_path.write_text(
                "\n".join(
                    [
                        "# comment",
                        "export SMSTOME_COOKIE='cf_clearance=demo'",
                        'cfworker_custom_auth="secret-pass"',
                    ]
                ),
                encoding="utf-8",
            )

            values = _load_env_file(env_path)

        self.assertEqual(values["SMSTOME_COOKIE"], "cf_clearance=demo")
        self.assertEqual(values["cfworker_custom_auth"], "secret-pass")

    def test_get_env_fallback_value_matches_uppercase_env_names(self):
        env_values = {
            "SMSTOME_COOKIE": "cf_clearance=demo",
            "CFWORKER_CUSTOM_AUTH": "secret-pass",
            "CHATGPT_PHONE_PROVIDER": "hero_sms",
            "HERO_SMS_API_KEY": "hero-key",
        }

        self.assertEqual(
            _get_env_fallback_value("smstome_cookie", env_values=env_values),
            "cf_clearance=demo",
        )
        self.assertEqual(
            _get_env_fallback_value("cfworker_custom_auth", env_values=env_values),
            "secret-pass",
        )
        self.assertEqual(
            _get_env_fallback_value("chatgpt_phone_provider", env_values=env_values),
            "hero_sms",
        )
        self.assertEqual(
            _get_env_fallback_value("hero_sms_api_key", env_values=env_values),
            "hero-key",
        )

    def test_merge_env_fallback_uses_canonical_key_without_overriding_db(self):
        merged = _merge_env_fallback(
            {
                "smstome_cookie": "",
                "cfworker_custom_auth": "db-value",
                "chatgpt_phone_provider": "",
                "hero_sms_api_key": "",
            },
            env_values={
                "SMSTOME_COOKIE": "cf_clearance=demo",
                "CFWORKER_CUSTOM_AUTH": "env-value",
                "CHATGPT_PHONE_PROVIDER": "hero_sms",
                "HERO_SMS_API_KEY": "hero-key",
            },
        )

        self.assertEqual(_canonical_config_key("SMSTOME_COOKIE"), "smstome_cookie")
        self.assertEqual(_canonical_config_key("HERO_SMS_API_KEY"), "hero_sms_api_key")
        self.assertEqual(merged["smstome_cookie"], "cf_clearance=demo")
        self.assertEqual(merged["cfworker_custom_auth"], "db-value")
        self.assertEqual(merged["chatgpt_phone_provider"], "hero_sms")
        self.assertEqual(merged["hero_sms_api_key"], "hero-key")


if __name__ == "__main__":
    unittest.main()
