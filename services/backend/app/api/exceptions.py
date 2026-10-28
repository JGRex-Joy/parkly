from __future__ import annotations


class ParkingError(Exception):
    status_code = 400

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class NotFoundError(ParkingError):
    status_code = 404


class ConflictError(ParkingError):
    status_code = 409


class NoFreeSpaceError(ConflictError):
    CUSTOMER = "Нет свободных платных мест"
    STAFF = "Нет свободных мест"

    def __init__(self, *, is_staff: bool) -> None:
        super().__init__(self.STAFF if is_staff else self.CUSTOMER)


class SlotOccupiedError(ConflictError):
    def __init__(self) -> None:
        super().__init__("Слот уже занят")


class ConfigurationError(ParkingError):
    status_code = 503


class ValidationFailedError(ParkingError):
    status_code = 422


class ForbiddenError(ParkingError):
    status_code = 403


class AmbiguousVehicleError(ConflictError):
    pass