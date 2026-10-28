from __future__ import annotations

import hmac
from typing import Optional

from fastapi import Depends, Header, HTTPException

from app.api.dependencies import get_settings
from app.core.config import Settings


def _matches(expected: str, supplied: Optional[str]) -> bool:
    return hmac.compare_digest((supplied or "").encode(), expected.encode())


def require_service_token(
    x_service_token: Optional[str] = Header(None),
    settings: Settings = Depends(get_settings),
) -> None:
    if settings.service_token and not _matches(settings.service_token, x_service_token):
        raise HTTPException(status_code=401, detail="invalid or missing X-Service-Token")


def require_admin_token(
    x_admin_token: Optional[str] = Header(None),
    settings: Settings = Depends(get_settings),
) -> None:
    if not settings.admin_token:
        raise HTTPException(status_code=503, detail="operator endpoints disabled: PARKING_ADMIN_TOKEN not set")
    if not _matches(settings.admin_token, x_admin_token):
        raise HTTPException(status_code=401, detail="invalid or missing X-Admin-Token")
