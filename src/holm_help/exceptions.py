"""Controlled exceptions for Holm Help."""


class OrdersServiceUnavailable(Exception):
    """Raised when ORDERS_MODE=down to simulate order-service outage."""

    def __init__(self, message: str = "Order service is temporarily unavailable.") -> None:
        super().__init__(message)
