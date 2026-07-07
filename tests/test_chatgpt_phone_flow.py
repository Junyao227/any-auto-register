import base64
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from platforms.chatgpt.oauth_client import OAuthClient
from platforms.chatgpt.herosms_service import HeroSmsApiClient, HeroSmsPhoneEntry, HeroSmsPhoneService, reset_herosms_phone_cache
from platforms.chatgpt.phone_service import (
    SMSToMePhoneService,
    add_phone_global_lock,
    clear_phone_activation_cache,
)
from platforms.chatgpt.utils import FlowState
from smstome_tool import PhoneEntry, parse_country_slugs


class OAuthCookieDecodeTests(unittest.TestCase):
    def test_decode_signed_cookie_payload(self):
        payload = {
            "email": "demo@example.com",
            "phone_number": "+447456344799",
            "phone_verification_channel": "whatsapp",
        }
        encoded = base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode("utf-8").rstrip("=")
        cookie_value = f"{encoded}.sig-a.sig-b"

        self.assertEqual(OAuthClient._decode_cookie_json_value(cookie_value), payload)

    def test_decode_invalid_cookie_payload(self):
        self.assertIsNone(OAuthClient._decode_cookie_json_value("not-a-valid-cookie"))


class SMSToMeConfigTests(unittest.TestCase):
    def test_parse_country_slugs_accepts_csv_and_iterables(self):
        self.assertEqual(
            parse_country_slugs("united-kingdom, poland;finland"),
            ["united-kingdom", "poland", "finland"],
        )
        self.assertEqual(
            parse_country_slugs(["united-kingdom", "poland", "united_kingdom"]),
            ["united-kingdom", "poland"],
        )

    def test_phone_service_enabled_when_pool_file_exists(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            pool_path = Path(tmp_dir) / "phones.txt"
            pool_path.write_text("+447456344799\tunited-kingdom\thttps://example.com\n", encoding="utf-8")

            service = SMSToMePhoneService({"smstome_global_file": str(pool_path)})
            self.assertTrue(service.enabled)

    def test_phone_service_disabled_for_empty_pool_without_cookie(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            pool_path = Path(tmp_dir) / "phones.txt"
            pool_path.write_text("", encoding="utf-8")

            service = SMSToMePhoneService({"smstome_global_file": str(pool_path)})
            self.assertFalse(service.enabled)

    def test_wait_for_code_forwards_cookie_timeout_and_poll_interval(self):
        entry = PhoneEntry(
            country_slug="united-kingdom",
            phone="+447456344799",
            detail_url="https://example.com/phone/1",
        )
        service = SMSToMePhoneService(
            {
                "smstome_cookie": "cf_clearance=demo",
                "smstome_otp_timeout_seconds": "66",
                "smstome_poll_interval_seconds": "7",
            }
        )

        with mock.patch("platforms.chatgpt.phone_service.wait_for_otp", return_value="123456") as mocked:
            code = service.wait_for_code(entry)

        self.assertEqual(code, "123456")
        mocked.assert_called_once()
        kwargs = mocked.call_args.kwargs
        self.assertEqual(kwargs["cookie_header"], "cf_clearance=demo")
        self.assertEqual(kwargs["timeout"], 66)
        self.assertEqual(kwargs["poll_interval"], 7)
        self.assertFalse(kwargs["raise_on_timeout"])

    def test_ensure_pool_ready_syncs_with_configured_page_limit(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            pool_path = Path(tmp_dir) / "phones.txt"
            service = SMSToMePhoneService(
                {
                    "smstome_cookie": "cf_clearance=demo",
                    "smstome_country_slugs": "united-kingdom",
                    "smstome_global_file": str(pool_path),
                    "smstome_sync_max_pages_per_country": "9",
                }
            )

            with mock.patch("platforms.chatgpt.phone_service.update_global_phone_list", return_value=3) as mocked:
                service.ensure_pool_ready()

        mocked.assert_called_once()
        kwargs = mocked.call_args.kwargs
        self.assertEqual(kwargs["cookie_header"], "cf_clearance=demo")
        self.assertEqual(kwargs["countries"], ["united-kingdom"])
        self.assertEqual(kwargs["output_path"], pool_path)
        self.assertEqual(kwargs["max_pages_per_country"], 9)

    def test_acquire_phone_reuses_short_lived_cache_without_extra_request(self):
        clear_phone_activation_cache()
        with tempfile.TemporaryDirectory() as tmp_dir:
            pool_path = Path(tmp_dir) / "phones.txt"
            pool_path.write_text("+447456344799\tunited-kingdom\thttps://smstome.com/uk/phone/447456344799/sms/14642\n", encoding="utf-8")
            entry = PhoneEntry(
                country_slug="united-kingdom",
                phone="+447456344799",
                detail_url="https://smstome.com/uk/phone/447456344799/sms/14642",
            )
            service = SMSToMePhoneService({"smstome_global_file": str(pool_path)})

            with mock.patch("platforms.chatgpt.phone_service.get_unused_phone", return_value=entry) as mocked:
                first = service.acquire_phone()
                service.record_success(first, "123456")
                second = service.acquire_phone()

        self.assertEqual(first.phone, second.phone)
        mocked.assert_called_once()
        clear_phone_activation_cache()

    def test_phone_limit_invalidates_cache_and_uses_all_attempts_for_openai_used_numbers(self):
        client = OAuthClient(config={"smstome_phone_attempts": 3}, verbose=False)
        logs = []
        client._log = logs.append
        first = PhoneEntry("united-kingdom", "+447000000001", "https://smstome.com/a/sms/1")
        second = PhoneEntry("united-kingdom", "+447000000002", "https://smstome.com/a/sms/2")
        third = PhoneEntry("united-kingdom", "+447000000003", "url")
        phone_service = mock.Mock()
        phone_service.enabled = True
        phone_service.max_attempts = 3
        phone_service.acquire_phone.side_effect = [first, second, third]
        phone_service.prefix_hint.side_effect = lambda phone: phone[:7]

        with mock.patch("platforms.chatgpt.oauth_client.SMSToMePhoneService", return_value=phone_service):
            with mock.patch.object(
                client,
                "_send_phone_number",
                side_effect=[
                    (False, None, "add-phone/send 失败: Phone number already in use. Please use a different phone number."),
                    (False, None, "add-phone/send 失败: Phone number already in use. Please use a different phone number."),
                    (False, None, "add-phone/send 失败: too many verification requests"),
                ],
            ):
                state = client._handle_add_phone_verification(
                    "device-id",
                    "Mozilla/5.0",
                    None,
                    None,
                    FlowState(page_type="add_phone"),
                )

        self.assertIsNone(state)
        self.assertEqual(phone_service.acquire_phone.call_count, 3)
        self.assertEqual(phone_service.release_if_unusable.call_count, 3)
        self.assertTrue(any("OpenAI 拒绝手机号" in line for line in logs))
        self.assertIn("add_phone 阶段失败", client.last_error)

    def test_add_phone_uses_global_lock_around_sms_flow(self):
        client = OAuthClient(config={}, verbose=False)
        client._log = lambda _msg: None
        phone_service = mock.Mock()
        phone_service.enabled = True

        with add_phone_global_lock():
            with mock.patch("platforms.chatgpt.oauth_client.SMSToMePhoneService", return_value=phone_service):
                with mock.patch.object(client, "_handle_add_phone_verification_with_service", return_value=FlowState(page_type="done")) as inner:
                    state = client._handle_add_phone_verification(
                        "device-id",
                        "Mozilla/5.0",
                        None,
                        None,
                        FlowState(page_type="add_phone"),
                    )

        self.assertEqual(state.page_type, "done")
        inner.assert_called_once()

    def test_default_add_phone_retry_is_serial_not_parallel(self):
        from platforms.chatgpt.refresh_token_registration_engine import RefreshTokenRegistrationEngine

        engine = RefreshTokenRegistrationEngine(email_service=mock.Mock(), extra_config={})
        engine.password = "pass"
        oauth_client = mock.Mock()
        oauth_client.config = {}
        oauth_client.login_and_get_tokens.return_value = {"access_token": "at"}
        register_client = mock.Mock()
        register_client.ua = "ua"
        register_client.sec_ch_ua = None
        register_client.impersonate = None
        result = mock.Mock()
        result.email = "demo@example.com"

        with mock.patch.object(engine, "_build_oauth_client", return_value=oauth_client):
            tokens, returned_client = engine._serial_add_phone_retry(
                result=result,
                register_client=register_client,
                email_adapter=mock.Mock(),
                first_name="A",
                last_name="B",
                birthdate="2000-01-01",
                register_otp_wait_seconds=600,
            )

        self.assertEqual(tokens, {"access_token": "at"})
        self.assertIs(returned_client, oauth_client)
        oauth_client.login_and_get_tokens.assert_called_once()
        self.assertEqual(oauth_client.login_and_get_tokens.call_args.kwargs["login_source"], "add_phone_serial_retry")


class HeroSmsServiceTests(unittest.TestCase):
    def test_oauth_selects_herosms_when_api_key_is_configured(self):
        client = OAuthClient(config={"herosms_api_key": "hero-key"}, verbose=False)
        service = client._create_phone_service()
        self.assertIsInstance(service, HeroSmsPhoneService)
        self.assertTrue(service.enabled)

    def test_oauth_falls_back_to_smstome_without_herosms_api_key(self):
        client = OAuthClient(config={}, verbose=False)
        service = client._create_phone_service()
        self.assertIsInstance(service, SMSToMePhoneService)

    def test_parse_number_payload_accepts_json_v2_response(self):
        entry = HeroSmsApiClient.parse_number_payload(
            '{"activationId":"12345","phoneNumber":"66812345678"}',
            country_id="52",
        )
        self.assertEqual(entry.activation_id, "12345")
        self.assertEqual(entry.phone, "+66812345678")
        self.assertEqual(entry.country_id, "52")

    def test_parse_number_payload_accepts_legacy_access_number(self):
        entry = HeroSmsApiClient.parse_number_payload("ACCESS_NUMBER:12345:66812345678", country_id="52")
        self.assertEqual(entry.activation_id, "12345")
        self.assertEqual(entry.phone, "+66812345678")
        self.assertEqual(entry.country_id, "52")

    def test_wait_for_code_polls_until_status_ok(self):
        api = mock.Mock()
        api.extract_code_from_status.side_effect = HeroSmsApiClient.extract_code_from_status
        api.get_status.side_effect = ["STATUS_WAIT_CODE", "STATUS_OK:Your code is 654321"]
        api.get_active_activations.return_value = []
        service = HeroSmsPhoneService(
            {
                "herosms_api_key": "hero-key",
            },
            client=api,
        )
        entry = HeroSmsPhoneEntry(activation_id="act-1", phone="+66812345678")

        with mock.patch("platforms.chatgpt.herosms_service.time.sleep"):
            code = service.wait_for_code(entry)

        self.assertEqual(code, "654321")
        api.set_status.assert_called_once_with("act-1", 1)
        self.assertEqual(api.get_status.call_count, 2)

    def test_acquire_and_finish_and_cancel(self):
        reset_herosms_phone_cache()
        api = mock.Mock()
        api.get_number.return_value = HeroSmsPhoneEntry(activation_id="act-1", phone="+66812345678", country_id="52")
        service = HeroSmsPhoneService(
            {
                "herosms_api_key": "hero-key",
                "herosms_country": "52",
                "herosms_max_price": "0.2",
                "herosms_phone_cache_max_uses": "1",
            },
            client=api,
        )

        entry = service.acquire_phone(exclude_prefixes={"+447000"})
        self.assertEqual(entry.phone, "+66812345678")
        self.assertEqual(entry.country_slug, "herosms:52")
        api.get_number.assert_called_once_with(service="dr", country="52", max_price="0.2")

        service.record_success(entry, "123456")
        api.finish_activation.assert_called_once_with("act-1")

        with mock.patch.object(api, "get_number", return_value=HeroSmsPhoneEntry(activation_id="act-2", phone="+66812345679", country_id="52")):
            entry2 = service.acquire_phone()
        service.mark_blacklisted(entry2.phone)
        api.cancel_activation.assert_called_once_with("act-2")
        reset_herosms_phone_cache()

    def test_herosms_module_cache_reuses_number_across_instances(self):
        reset_herosms_phone_cache()
        with tempfile.TemporaryDirectory() as tmp_dir:
            cache_file = Path(tmp_dir) / ".herosms_phone_cache.json"
            api1 = mock.Mock()
            api1.get_number.return_value = HeroSmsPhoneEntry(activation_id="act-cache", phone="+66800000001", country_id="52")
            api2 = mock.Mock()
            service1 = HeroSmsPhoneService(
                {
                    "herosms_api_key": "hero-key",
                    "herosms_country": "52",
                    "herosms_phone_cache_file": str(cache_file),
                    "herosms_phone_reuse_enabled": "true",
                },
                client=api1,
            )
            service2 = HeroSmsPhoneService(
                {
                    "herosms_api_key": "hero-key",
                    "herosms_country": "52",
                    "herosms_phone_cache_file": str(cache_file),
                    "herosms_phone_reuse_enabled": "true",
                },
                client=api2,
            )

            entry1 = service1.acquire_phone()
            entry2 = service2.acquire_phone()

        self.assertEqual(entry1.phone, "+66800000001")
        self.assertEqual(entry2.phone, "+66800000001")
        api1.get_number.assert_called_once()
        api2.get_number.assert_not_called()
        reset_herosms_phone_cache()

    def test_herosms_skips_cache_when_reuse_disabled(self):
        reset_herosms_phone_cache()
        api = mock.Mock()
        api.get_number.side_effect = [
            HeroSmsPhoneEntry(activation_id="act-1", phone="+66800000011", country_id="52"),
            HeroSmsPhoneEntry(activation_id="act-2", phone="+66800000012", country_id="52"),
        ]
        service = HeroSmsPhoneService(
            {
                "herosms_api_key": "hero-key",
                "herosms_country": "52",
                "herosms_phone_reuse_enabled": "false",
            },
            client=api,
        )

        entry1 = service.acquire_phone()
        self.assertEqual(entry1.phone, "+66800000011")
        service.record_success(entry1, "111111")
        api.finish_activation.assert_called_once_with("act-1")

        entry2 = service.acquire_phone()
        self.assertEqual(entry2.phone, "+66800000012")
        self.assertEqual(api.get_number.call_count, 2)
        reset_herosms_phone_cache()

    def test_herosms_phone_reuse_defaults_to_disabled(self):
        service = HeroSmsPhoneService({"herosms_api_key": "hero-key"}, client=mock.Mock())
        self.assertFalse(service.phone_reuse_enabled)
        reset_herosms_phone_cache()

    def test_herosms_disk_cache_persists_used_codes_without_active_code_field(self):
        reset_herosms_phone_cache()
        with tempfile.TemporaryDirectory() as tmp_dir:
            cache_file = Path(tmp_dir) / ".herosms_phone_cache.json"
            api = mock.Mock()
            api.get_number.return_value = HeroSmsPhoneEntry(activation_id="act-disk", phone="+66800000002", country_id="52")
            service = HeroSmsPhoneService(
                {
                    "herosms_api_key": "hero-key",
                    "herosms_country": "52",
                    "herosms_phone_cache_file": str(cache_file),
                    "herosms_phone_reuse_enabled": "true",
                },
                client=api,
            )
            entry = service.acquire_phone()
            service.record_success(entry, "654321")
            data = json.loads(cache_file.read_text(encoding="utf-8"))

        cached = data["entries"][service.cache_key]
        self.assertEqual(cached["used_codes"], ["654321"])
        self.assertNotIn("active_code", cached)
        self.assertNotIn("code", cached)
        reset_herosms_phone_cache()

    def test_herosms_does_not_reuse_cached_phone_with_less_than_wait_window_remaining(self):
        reset_herosms_phone_cache()
        api = mock.Mock()
        old_entry = HeroSmsPhoneEntry(activation_id="act-old", phone="+66800000001", country_id="52")
        new_entry = HeroSmsPhoneEntry(activation_id="act-new", phone="+66800000002", country_id="52")
        api.get_number.return_value = new_entry
        service = HeroSmsPhoneService(
            {
                "herosms_api_key": "hero-key",
                "herosms_country": "52",
                "herosms_otp_timeout_seconds": "240",
                "herosms_phone_cache_ttl_seconds": "1200",
                "herosms_phone_reuse_enabled": "true",
            },
            client=api,
        )
        service._set_cache_locked({
            "phone_number": old_entry.phone,
            "entry": {
                "activation_id": old_entry.activation_id,
                "phone": old_entry.phone,
                "country_id": old_entry.country_id,
                "country_slug": old_entry.country_slug,
                "provider": old_entry.provider,
                "raw": old_entry.raw,
            },
            "activation_id": old_entry.activation_id,
            "acquired_at": 1000,
            "use_count": 0,
            "used_codes": [],
            "config_signature": dict(service.signature),
            "country": service.country_id,
            "service": service.service_code,
            "max_price": service.max_price,
        })

        with mock.patch("platforms.chatgpt.herosms_service.time.time", return_value=2085):
            entry = service.acquire_phone()

        self.assertEqual(entry.phone, new_entry.phone)
        api.get_number.assert_called_once()

    def test_herosms_wait_for_code_skips_used_codes_until_new_code(self):
        reset_herosms_phone_cache()
        api = mock.Mock()
        api.extract_code_from_status.side_effect = HeroSmsApiClient.extract_code_from_status
        api.get_status.side_effect = ["STATUS_OK:111111", "STATUS_OK:222222"]
        api.get_active_activations.return_value = []
        service = HeroSmsPhoneService({"herosms_api_key": "hero-key"}, client=api)
        entry = HeroSmsPhoneEntry(activation_id="act-used", phone="+66800000003")

        with mock.patch("platforms.chatgpt.herosms_service.time.sleep"):
            code = service.wait_for_code(entry, used_codes={"111111"})

        self.assertEqual(code, "222222")
        reset_herosms_phone_cache()

    def test_oauth_forwards_used_codes_and_records_success(self):
        client = OAuthClient(config={}, verbose=False)
        client._log = lambda _msg: None
        entry = PhoneEntry("herosms:52", "+66800000004", "herosms://activation/780")
        phone_service = mock.Mock()
        phone_service.enabled = True
        phone_service.max_attempts = 1
        phone_service.acquire_phone.return_value = entry
        phone_service.prefix_hint.return_value = "+668000"
        phone_service.get_used_codes.return_value = {"111111"}
        phone_service.wait_for_code.return_value = "222222"
        next_state = FlowState(page_type="phone_otp_verification", current_url="https://auth.openai.com/phone-verification")
        validated_state = FlowState(page_type="consent", current_url="https://auth.openai.com/consent")

        with mock.patch("platforms.chatgpt.oauth_client.OAuthClient._create_phone_service", return_value=phone_service):
            with mock.patch.object(client, "_send_phone_number", return_value=(True, next_state, "")):
                with mock.patch.object(client, "_validate_phone_otp", return_value=(True, validated_state, "")):
                    state = client._handle_add_phone_verification(
                        "device-id",
                        "Mozilla/5.0",
                        None,
                        None,
                        FlowState(page_type="add_phone"),
                    )

        self.assertEqual(state, validated_state)
        phone_service.wait_for_code.assert_called_once()
        kwargs = phone_service.wait_for_code.call_args.kwargs
        self.assertEqual(kwargs["used_codes"], {"111111"})
        self.assertEqual(kwargs["exclude_codes"], {"111111"})
        phone_service.record_success.assert_called_once_with(entry, "222222")

    def test_herosms_default_phone_attempts_is_five(self):
        service = HeroSmsPhoneService({"herosms_api_key": "hero-key"}, client=mock.Mock())

        self.assertEqual(service.max_attempts, 5)

    def test_herosms_default_wait_uses_configured_timeout_not_cache_ttl(self):
        reset_herosms_phone_cache()
        api = mock.Mock()
        api.extract_code_from_status.side_effect = HeroSmsApiClient.extract_code_from_status
        api.get_status.return_value = "STATUS_WAIT_CODE"
        api.get_active_activations.return_value = []
        service = HeroSmsPhoneService(
            {
                "herosms_api_key": "hero-key",
                "herosms_otp_timeout_seconds": "240",
                "herosms_poll_interval_seconds": "5",
            },
            client=api,
        )
        entry = HeroSmsPhoneEntry(activation_id="act-timeout", phone="+66800000005")

        times = [1000] * 10 + [1060] * 10 + [1121] * 10
        with mock.patch("platforms.chatgpt.herosms_service.time.time", side_effect=times), \
            mock.patch("platforms.chatgpt.herosms_service.time.sleep") as sleep_mock:
            code = service.wait_for_code(entry)

        self.assertIsNone(code)
        self.assertGreater(api.get_status.call_count, 1)
        self.assertLessEqual(api.get_status.call_count, 30)
        sleep_mock.assert_called_with(5)

    def test_oauth_changes_phone_when_wait_for_code_times_out(self):
        client = OAuthClient(config={}, verbose=False)
        client._log = lambda _msg: None
        first = PhoneEntry("herosms:31", "+27680000001", "herosms://activation/1")
        second = PhoneEntry("herosms:31", "+27680000002", "herosms://activation/2")
        phone_service = mock.Mock()
        phone_service.enabled = True
        phone_service.max_attempts = 2
        phone_service.acquire_phone.side_effect = [first, second]
        phone_service.prefix_hint.side_effect = lambda phone: phone[:7]
        phone_service.get_used_codes.return_value = set()
        phone_service.wait_for_code.side_effect = [None, "222222"]
        next_state = FlowState(page_type="phone_otp_verification", current_url="https://auth.openai.com/phone-verification")
        validated_state = FlowState(page_type="consent", current_url="https://auth.openai.com/consent")

        with mock.patch("platforms.chatgpt.oauth_client.OAuthClient._create_phone_service", return_value=phone_service):
            with mock.patch.object(client, "_send_phone_number", return_value=(True, next_state, "")):
                with mock.patch.object(client, "_validate_phone_otp", return_value=(True, validated_state, "")):
                    state = client._handle_add_phone_verification(
                        "device-id",
                        "Mozilla/5.0",
                        None,
                        None,
                        FlowState(page_type="add_phone"),
                    )

        self.assertEqual(code, "222222")
        self.assertEqual(state, validated_state)
        self.assertEqual(phone_service.acquire_phone.call_count, 2)
        phone_service.release_if_unusable.assert_called_once_with(first, reason=f"手机号 {first.phone} 4分钟内未收到验证码")
        phone_service.record_success.assert_called_once_with(second, "222222")

    def test_project_does_not_import_gpt_sms_herosms_client(self):
        import ast

        root = Path(__file__).resolve().parents[1]
        forbidden = {
            "gpt-sms",
            "gpt_sms",
            "src.core.herosms_client",
        }
        violations = []
        for path in root.rglob("*.py"):
            if any(part in {".git", "__pycache__", "gpt-sms"} for part in path.parts):
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module or ""]
                else:
                    continue
                for name in names:
                    if name in forbidden or name.startswith("gpt_sms.") or name.startswith("src.core.herosms_client"):
                        violations.append((str(path), name))
        self.assertEqual(violations, [])


class OAuthPhoneBlacklistTests(unittest.TestCase):
    def test_should_blacklist_explicit_phone_rejection(self):
        state = FlowState(
            page_type="add_phone",
            payload={"error": {"message": "phone number is invalid"}},
        )
        self.assertTrue(
            OAuthClient._should_blacklist_phone_failure(
                "add-phone/send 失败: 400 - phone number is invalid",
                state,
            )
        )

    def test_should_not_blacklist_whatsapp_or_delivery_failures(self):
        self.assertFalse(
            OAuthClient._should_blacklist_phone_failure(
                "add_phone 已切到 whatsapp 通道，当前 SMSToMe 仅支持短信接码"
            )
        )
        self.assertFalse(
            OAuthClient._should_blacklist_phone_failure("手机号 +447000000001 未收到短信验证码")
        )

    def test_handle_add_phone_blacklists_explicitly_rejected_number(self):
        client = OAuthClient(config={}, verbose=False)
        client._log = lambda _msg: None
        entry = PhoneEntry(
            country_slug="united-kingdom",
            phone="+447000000001",
            detail_url="https://example.com/phone/1",
        )
        phone_service = mock.Mock()
        phone_service.enabled = True
        phone_service.max_attempts = 1
        phone_service.acquire_phone.return_value = entry
        phone_service.prefix_hint.return_value = "+447000"

        with mock.patch("platforms.chatgpt.oauth_client.OAuthClient._create_phone_service", return_value=phone_service):
            with mock.patch.object(
                client,
                "_send_phone_number",
                return_value=(False, None, "add-phone/send 失败: 400 - phone number is invalid"),
            ):
                state = client._handle_add_phone_verification(
                    "device-id",
                    "Mozilla/5.0",
                    None,
                    None,
                    FlowState(page_type="add_phone"),
                )

        self.assertIsNone(state)
        phone_service.mark_blacklisted.assert_called_once_with(entry.phone)
        self.assertIn("add_phone 阶段失败", client.last_error)

    def test_handle_add_phone_does_not_blacklist_whatsapp_channel(self):
        client = OAuthClient(config={}, verbose=False)
        client._log = lambda _msg: None
        entry = PhoneEntry(
            country_slug="united-kingdom",
            phone="+447000000002",
            detail_url="https://example.com/phone/2",
        )
        phone_service = mock.Mock()
        phone_service.enabled = True
        phone_service.max_attempts = 1
        phone_service.acquire_phone.return_value = entry
        phone_service.prefix_hint.return_value = "+447000"

        next_state = FlowState(
            page_type="phone_otp_verification",
            continue_url="https://auth.openai.com/phone-verification",
        )

        with mock.patch("platforms.chatgpt.oauth_client.OAuthClient._create_phone_service", return_value=phone_service):
            with mock.patch.object(client, "_send_phone_number", return_value=(True, next_state, "")):
                with mock.patch.object(
                    client,
                    "_decode_oauth_session_cookie",
                    return_value={
                        "phone_verification_channel": "whatsapp",
                        "phone_number": entry.phone,
                    },
                ):
                    state = client._handle_add_phone_verification(
                        "device-id",
                        "Mozilla/5.0",
                        None,
                        None,
                        FlowState(page_type="add_phone"),
                    )

        self.assertIsNone(state)
        phone_service.mark_blacklisted.assert_not_called()
        self.assertIn("whatsapp", client.last_error)


if __name__ == "__main__":
    unittest.main()
