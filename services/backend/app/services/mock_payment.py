from __future__ import annotations

import uuid


class MockPaymentProvider:
    name = "mock"
    is_simulated = True

    def new_reference(self) -> str:
        return f"MOCK-{uuid.uuid4().hex[:16]}"

    def charge(self, reference: str, amount: float, currency: str) -> dict:
        return {"status": "succeeded", "transaction_id": f"MOCKTXN-{reference}",
                "amount": amount, "currency": currency}
