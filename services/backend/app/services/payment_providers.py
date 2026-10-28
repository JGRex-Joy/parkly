from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from dataclasses import dataclass
from typing import Optional, Protocol

from app.core.config import Settings


class PaymentVerificationError(Exception):
    pass

@dataclass(frozen=True)
class VerifiedCallback:
    reference: str
    status: str            # "succeeded" | "failed"
    amount: float
    currency: str
    transaction_id: str


class PaymentProvider(Protocol):
    name: str
    is_simulated: bool

    def new_reference(self) -> str: ...

    def verify_callback(self, raw_body: bytes, signature: Optional[str]) -> VerifiedCallback: ...


class SimulatedProvider:
    name = "simulated"
    is_simulated = True

    def new_reference(self) -> str:
        return f"SIM-{uuid.uuid4().hex[:16]}"

    def verify_callback(self, raw_body: bytes, signature: Optional[str]) -> VerifiedCallback:
        raise PaymentVerificationError("the simulated provider has no callbacks")


class WebhookProvider:
    name = "webhook"
    is_simulated = False

    def __init__(self, secret: str) -> None:
        self._secret = secret.encode()

    def new_reference(self) -> str:
        return f"PK-{uuid.uuid4().hex[:20]}"

    def sign(self, raw_body: bytes) -> str:
        return "sha256=" + hmac.new(self._secret, raw_body, hashlib.sha256).hexdigest()

    def verify_callback(self, raw_body: bytes, signature: Optional[str]) -> VerifiedCallback:
        if not self._secret:
            raise PaymentVerificationError("PARKING_PAYMENT_WEBHOOK_SECRET is not configured")
        if not signature or not hmac.compare_digest(signature.strip(), self.sign(raw_body)):
            raise PaymentVerificationError("invalid signature")
        try:
            data = json.loads(raw_body)
            return VerifiedCallback(
                reference=str(data["reference"]),
                status=str(data["status"]).lower(),
                amount=float(data["amount"]),
                currency=str(data["currency"]),
                transaction_id=str(data["transaction_id"]),
            )
        except (ValueError, KeyError, TypeError) as exc:
            raise PaymentVerificationError(f"malformed callback: {exc}") from exc


def build_provider(settings: Settings) -> PaymentProvider:
    if settings.payment_mode == "simulated":
        return SimulatedProvider()
    return WebhookProvider(settings.payment_webhook_secret)
