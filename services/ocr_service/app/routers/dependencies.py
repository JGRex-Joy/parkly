from __future__ import annotations

import threading

from fastapi import Request

from app.config import get_settings
from app.services.container import ServiceContainer

_lock = threading.Lock()


def get_container(request: Request) -> ServiceContainer:
    app = request.app
    container = getattr(app.state, "container", None)
    if container is None:
        with _lock:
            container = getattr(app.state, "container", None)
            if container is None:
                container = ServiceContainer.build(get_settings())
                app.state.container = container
    return container
