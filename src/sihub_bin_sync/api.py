from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from typing import Any

from .errors import ApiError, ConfigError
from .models import ApiConfig, DefaultsConfig, RemoteRecord, SliceConfig


class GatewayCardInfoClient:
    def __init__(self, config: ApiConfig) -> None:
        self._config = config

    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {"content-type": "application/json", "accept": "application/json"}
        missing: list[str] = []
        for header_name, env_var in self._config.headers_from_env.items():
            value = os.getenv(env_var)
            if not value:
                missing.append(env_var)
                continue
            headers[header_name] = value
        if missing:
            raise ConfigError(
                "Missing required environment variables for API auth: " + ", ".join(sorted(missing))
            )
        return headers

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        url = urllib.parse.urljoin(self._config.base_url, path)
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(url=url, data=data, method=method, headers=self._headers())
        try:
            with urllib.request.urlopen(request, timeout=self._config.timeout_seconds) as response:
                body = response.read().decode("utf-8")
        except Exception as exc:  # noqa: BLE001
            raise ApiError(f"{method} {url} failed: {exc}") from exc

        if not body:
            return {}
        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise ApiError(f"{method} {url} returned non-JSON response.") from exc

    def list_gateway_records(self, gateway: str, slice_config: SliceConfig, defaults: DefaultsConfig) -> dict[str, RemoteRecord]:
        offset = 0
        limit = 100
        records: dict[str, RemoteRecord] = {}

        while True:
            payload = {
                "offset": offset,
                "limit": limit,
                "gateway": gateway,
                "validationType": slice_config.resolved_validation_type(defaults),
                "authType": slice_config.resolved_auth_type(defaults),
            }
            response = self._request("POST", self._config.list_path, payload)
            rows = response.get("rows", [])
            for row in rows:
                isin = str(row.get("isin") or "").strip()
                if not isin:
                    continue
                records[isin] = RemoteRecord(
                    id=str(row["id"]),
                    gateway=str(row.get("gateway", gateway)),
                    isin=isin,
                    disabled=bool(row.get("disabled", False)),
                    auth_type=row.get("authType"),
                    validation_type=row.get("validationType"),
                    payment_method_type=row.get("paymentMethodType"),
                    raw=row,
                )
            summary = response.get("summary", {})
            total_count = int(summary.get("totalCount", len(records)))
            offset += limit
            if offset >= total_count or not rows:
                break

        return records

    def submit_create_batch(self, slice_config: SliceConfig, defaults: DefaultsConfig, isins: list[str]) -> Any:
        query = urllib.parse.urlencode({"changeDescription": self._config.change_description})
        path = f"{self._config.batch_create_path}?{query}"
        payload = {
            "list": [
                {
                    "gateway": slice_config.gateway,
                    "authType": slice_config.resolved_auth_type(defaults),
                    "isin": isin,
                    "validationType": slice_config.resolved_validation_type(defaults),
                    "paymentMethodType": slice_config.resolved_payment_method_type(defaults),
                    "juspayBankCode": slice_config.juspay_bank_code,
                    "gatewayBankCode": slice_config.gateway_bank_code,
                }
                for isin in isins
            ]
        }
        return self._request("POST", path, payload)

    def update_disabled(self, record_id: str, disabled: bool) -> Any:
        query = urllib.parse.urlencode({"changeDescription": self._config.change_description})
        path = self._config.update_path_template.format(id=record_id)
        return self._request("PUT", f"{path}?{query}", {"disabled": disabled})
