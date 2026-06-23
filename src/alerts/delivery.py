from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable
from urllib import request

from pydantic import BaseModel

from alerts.rules import AlertEvent


class WebhookDelivery(BaseModel):
    url: str
    status: str
    attempt: int = 1
    request_body: dict[str, Any]
    response_status: int | None = None
    response_body: str | None = None
    error: str | None = None


@dataclass
class DeliveryResult:
    succeeded: bool
    deliveries: list[WebhookDelivery]


def build_webhook_payload(event: AlertEvent, *, dashboard_url: str | None = None, artifact_url: str | None = None) -> dict[str, Any]:
    payload = {
        "alert_id": event.id,
        "run_id": event.run_id,
        "severity": event.severity,
        "rule_id": event.rule_id,
        "type": event.type,
        "summary": event.summary,
        "status": event.status,
        "dedupe_key": event.dedupe_key,
        "payload": event.payload,
    }
    if dashboard_url:
        payload["dashboard_url"] = dashboard_url
    if artifact_url:
        payload["artifact_url"] = artifact_url
    return payload


def deliver_webhook(
    event: AlertEvent,
    url: str,
    *,
    dashboard_url: str | None = None,
    artifact_url: str | None = None,
    max_attempts: int = 1,
    sender: Callable[[str, dict[str, Any]], tuple[int, str]] | None = None,
) -> DeliveryResult:
    payload = build_webhook_payload(event, dashboard_url=dashboard_url, artifact_url=artifact_url)
    deliveries: list[WebhookDelivery] = []
    send = sender or _send_http_json
    for attempt in range(1, max_attempts + 1):
        try:
            status, body = send(url, payload)
            delivery_status = "succeeded" if 200 <= status < 300 else "failed"
            deliveries.append(WebhookDelivery(url=url, status=delivery_status, attempt=attempt, request_body=payload, response_status=status, response_body=body))
            if delivery_status == "succeeded":
                return DeliveryResult(succeeded=True, deliveries=deliveries)
        except Exception as exc:
            deliveries.append(WebhookDelivery(url=url, status="failed", attempt=attempt, request_body=payload, error=str(exc)))
    return DeliveryResult(succeeded=False, deliveries=deliveries)


def _send_http_json(url: str, payload: dict[str, Any]) -> tuple[int, str]:
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    with request.urlopen(req, timeout=10) as response:
        return int(response.status), response.read().decode("utf-8")
