from __future__ import annotations

import json
from typing import Any, Optional

import requests


DEFAULT_HERO_SMS_BASE_URL = "https://hero-sms.com/stubs/handler_api.php"
DEFAULT_HERO_SMS_SERVICE = "dr"
DEFAULT_HERO_SMS_COUNTRY_ID = 187
DEFAULT_HERO_SMS_COUNTRY_LABEL = "United States"


class HeroSMSClient:
    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = DEFAULT_HERO_SMS_BASE_URL,
        timeout: int = 20,
    ):
        self.api_key = str(api_key or "").strip()
        self.base_url = str(base_url or DEFAULT_HERO_SMS_BASE_URL).strip() or DEFAULT_HERO_SMS_BASE_URL
        self.timeout = timeout if timeout > 0 else 20

    def _get(self, params: dict[str, Any]) -> requests.Response:
        query = dict(params)
        if self.api_key:
            query["api_key"] = self.api_key
        response = requests.get(self.base_url, params=query, timeout=self.timeout)
        response.raise_for_status()
        return response

    @staticmethod
    def _parse_status_text(text: str) -> dict[str, Any]:
        text = str(text or "").strip()
        if text == "STATUS_WAIT_CODE":
            return {"status": "wait_code", "raw": text}
        if text.startswith("STATUS_WAIT_RETRY"):
            return {"status": "wait_retry", "raw": text}
        if text == "STATUS_WAIT_RESEND":
            return {"status": "wait_resend", "raw": text}
        if text.startswith("STATUS_OK:"):
            return {"status": "ok", "code": text.split(":", 1)[1].strip(), "raw": text}
        if text == "STATUS_CANCEL":
            return {"status": "cancel", "raw": text}
        return {"status": "unknown", "raw": text}

    @staticmethod
    def _parse_json_payload(text: str) -> Optional[Any]:
        try:
            return json.loads(text)
        except Exception:
            return None

    @staticmethod
    def _valid_code(value: Any) -> str:
        code = str(value or "").strip()
        if not code or code in {"null", "None"}:
            return ""
        return code

    @classmethod
    def _normalize_country_item(cls, raw, fallback_id=None) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise ValueError(f"Unexpected country item: {raw!r}")
        country_id = raw.get("id", fallback_id)
        try:
            country_id = int(country_id)
        except Exception:
            pass
        return {
            **raw,
            "id": country_id,
            "rus": str(raw.get("rus") or ""),
            "eng": str(raw.get("eng") or raw.get("name") or country_id),
            "chn": str(raw.get("chn") or raw.get("eng") or raw.get("name") or country_id),
        }

    @classmethod
    def _normalize_countries_response(cls, data) -> list[dict[str, Any]]:
        if isinstance(data, list):
            return [cls._normalize_country_item(item) for item in data]
        if isinstance(data, dict):
            return [cls._normalize_country_item(item, fallback_id=key) for key, item in data.items()]
        raise ValueError(f"Unexpected countries response type: {type(data).__name__}")

    @classmethod
    def _normalize_services_response(cls, data) -> list[dict[str, str]]:
        if isinstance(data, dict):
            status = data.get("status")
            if status == "success":
                services = data.get("services", [])
            elif status is not None:
                raise ValueError(f"Unexpected services response status: {data!r}")
            else:
                services = data
        else:
            services = data
        if isinstance(services, dict):
            services = [{"code": str(code), "name": str(name)} for code, name in services.items()]
        if not isinstance(services, list):
            raise ValueError(f"Unexpected services response type: {type(data).__name__}")
        normalized = []
        for item in services:
            if not isinstance(item, dict):
                raise ValueError(f"Unexpected service item: {item!r}")
            code = str(item.get("code") or "").strip()
            name = str(item.get("name") or code).strip()
            if code:
                normalized.append({"code": code, "name": name})
        return normalized

    def get_balance(self) -> float:
        response = self._get({"action": "getBalance"})
        text = response.text.strip()
        if text.startswith("ACCESS_BALANCE:"):
            return float(text.split(":", 1)[1])
        data = self._parse_json_payload(text)
        if isinstance(data, dict):
            value = data.get("balance") or data.get("money") or data.get("amount")
            if value is not None:
                return float(value)
        raise ValueError(f"Unexpected balance response: {text}")

    def get_services(self, country=None, lang: str = "cn") -> list[dict[str, str]]:
        params: dict[str, Any] = {"action": "getServicesList", "lang": lang}
        if country is not None and str(country).strip():
            params["country"] = country
        response = self._get(params)
        data = response.json()
        return self._normalize_services_response(data)

    def get_countries(self) -> list[dict[str, Any]]:
        response = self._get({"action": "getCountries"})
        data = response.json()
        return self._normalize_countries_response(data)

    def get_prices(self, service=None, country=None) -> dict[str, Any]:
        params: dict[str, Any] = {"action": "getPrices"}
        if service is not None and str(service).strip():
            params["service"] = service
        if country is not None and str(country).strip():
            params["country"] = country
        response = self._get(params)
        return response.json()

    def request_number(self, service: str, country: int, max_price: Optional[float] = None) -> dict[str, Any]:
        params_common: dict[str, Any] = {
            "service": str(service or DEFAULT_HERO_SMS_SERVICE).strip() or DEFAULT_HERO_SMS_SERVICE,
            "country": int(country or DEFAULT_HERO_SMS_COUNTRY_ID),
        }
        if max_price and max_price > 0:
            params_common["maxPrice"] = max_price

        v2_error = ""
        try:
            response = self._get({"action": "getNumberV2", **params_common})
            text = response.text.strip()
            data = self._parse_json_payload(text)
            if isinstance(data, dict) and data.get("activationId") and data.get("phoneNumber"):
                return data
            v2_error = text[:200]
        except Exception as exc:
            v2_error = str(exc)

        try:
            response = self._get({"action": "getNumber", **params_common})
            text = response.text.strip()
            if text.startswith("ACCESS_NUMBER:"):
                parts = text.split(":", 2)
                if len(parts) == 3:
                    return {
                        "activationId": parts[1],
                        "phoneNumber": parts[2],
                        "countryPhoneCode": "",
                        "activationCost": None,
                        "raw": text,
                    }
            raise ValueError(text[:200])
        except Exception as exc:
            raise ValueError(f"HeroSMS 获取号码失败 — V2: {v2_error}; V1: {exc}") from exc

    def get_status(self, activation_id: str) -> dict[str, Any]:
        response = self._get({"action": "getStatus", "id": activation_id})
        return self._parse_status_text(response.text)

    def get_status_v2(self, activation_id: str) -> dict[str, Any]:
        response = self._get({"action": "getStatusV2", "id": activation_id})
        text = response.text.strip()
        data = self._parse_json_payload(text)
        if isinstance(data, str):
            return self._parse_status_text(data)
        if not isinstance(data, dict):
            return self._parse_status_text(text)

        raw_status = data.get("status")
        if isinstance(raw_status, str):
            parsed = self._parse_status_text(raw_status)
            if parsed.get("status") != "unknown":
                return parsed

        for channel in ("sms", "call"):
            payload = data.get(channel)
            if isinstance(payload, dict):
                code = self._valid_code(payload.get("code"))
                if code:
                    return {"status": "ok", "code": code, "channel": channel, "raw": data}

        return {"status": "wait_code", "raw": data}

    def set_status(self, activation_id: str, status: int) -> str:
        response = self._get({"action": "setStatus", "id": activation_id, "status": int(status)})
        return response.text.strip()

    def request_additional_sms(self, activation_id: str) -> str:
        return self.set_status(activation_id, 3)

    def finish_activation(self, activation_id: str) -> bool:
        try:
            result = self.set_status(activation_id, 6)
            return "ACCESS" in result or "OK" in result.upper()
        except Exception:
            return False

    def cancel_activation(self, activation_id: str) -> bool:
        try:
            result = self.set_status(activation_id, 8)
            return "ACCESS" in result or "CANCEL" in result.upper()
        except Exception:
            return False
