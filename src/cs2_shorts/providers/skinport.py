from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import requests
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

log = logging.getLogger(__name__)


def _retryable(exc: BaseException) -> bool:
    if isinstance(exc, (requests.Timeout, requests.ConnectionError)):
        return True
    response = getattr(exc, "response", None)
    return isinstance(exc, requests.HTTPError) and response is not None and response.status_code in {429, 500, 502, 503, 504}


@dataclass
class SkinportProvider:
    currency: str = "EUR"
    app_id: int = 730
    session: requests.Session | None = None

    def __post_init__(self) -> None:
        if self.session is None:
            self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "CS2-Market-Shorts/1.0 (+https://github.com/)",
            "Accept": "application/json",
            "Accept-Encoding": "br, gzip",
        })

    @retry(retry=retry_if_exception(_retryable),
           stop=stop_after_attempt(4), wait=wait_exponential(multiplier=1, min=2, max=20), reraise=True)
    def _get(self, endpoint: str) -> list[dict[str, Any]]:
        assert self.session is not None
        response = self.session.get(
            f"https://api.skinport.com/v1/{endpoint}",
            params={"app_id": self.app_id, "currency": self.currency},
            timeout=(8, 45),
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list):
            raise ValueError(f"Unexpected Skinport response from /{endpoint}")
        return payload

    def get_market_data(self) -> list[dict[str, Any]]:
        """Fetch the documented public item and aggregated sales-history feeds.

        Each endpoint is one request for the full CS2 catalog; Skinport documents
        8 requests / 5 minutes and a 5-minute cache for both endpoints.
        """
        items = self._get("items")
        history = self._get("sales/history")
        history_by_name = {str(row.get("market_hash_name")): row for row in history}
        result: list[dict[str, Any]] = []
        for item in items:
            name = str(item.get("market_hash_name") or "").strip()
            if not name:
                continue
            sales = history_by_name.get(name, {})
            day = sales.get("last_24_hours") or {}
            week = sales.get("last_7_days") or {}
            price = _num(item.get("min_price"))
            if price is None:
                price = _num(item.get("suggested_price"))
            if price is None or price <= 0:
                continue
            result.append({
                "market_hash_name": name,
                "price": price,
                "suggested_price": _num(item.get("suggested_price")),
                "quantity": _int(item.get("quantity")),
                "volume_24h": _int(day.get("volume")),
                "avg_sale_24h": _num(day.get("avg")),
                "avg_sale_7d": _num(week.get("avg")),
                "min_sale_24h": _num(day.get("min")),
                "max_sale_24h": _num(day.get("max")),
                "volume_7d": _int(week.get("volume")),
                "item_page": item.get("item_page"),
                "market_page": item.get("market_page"),
                "currency": self.currency,
                "source": "Skinport",
            })
        if not result:
            raise RuntimeError("Skinport returned no usable prices; refusing to generate stale or invented data")
        log.info("Fetched %d Skinport items", len(result))
        return result


def _num(value: Any) -> float | None:
    try:
        n = float(value)
        return n if n > 0 else None
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0
