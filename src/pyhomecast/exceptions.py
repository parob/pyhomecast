"""Exceptions for the Homecast client."""


class HomecastError(Exception):
    """Base exception for Homecast API errors."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class HomecastAuthError(HomecastError):
    """Raised when authentication fails (401/403)."""


class HomecastConnectionError(HomecastError):
    """Raised when the API is unreachable or returns a server error."""
