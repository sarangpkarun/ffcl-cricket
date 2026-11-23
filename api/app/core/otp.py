"""OTP delivery behind an interface.

- "console" logs the code: development and tests only, never in production.
- "disabled" sends nothing and generates nothing: people ask an organiser to verify their number instead.
  This is the production default until a real SMS provider is added behind `OtpProvider`.
"""

import logging
from typing import Protocol

from app.core.config import settings

log = logging.getLogger("ffcl.otp")
PROVIDERS = ("console", "disabled")
DISABLED_MESSAGE = "Phone codes are not available. Ask an organiser to verify your number."


class OtpProvider(Protocol):
    def send(self, phone: str, code: str) -> None: ...


class ConsoleOtpProvider:
    def send(self, phone: str, code: str) -> None:
        log.warning("OTP for %s: %s", phone, code)


def provider_name() -> str:
    """The provider in use: what OTP_PROVIDER says, or console in development and disabled in production."""
    return settings.otp_provider or ("disabled" if settings.environment == "production" else "console")


def enabled() -> bool:
    return provider_name() != "disabled"


def get_provider() -> OtpProvider:
    name = provider_name()
    if name == "console":
        if settings.environment == "production":
            raise RuntimeError("The console OTP provider writes codes to the log and cannot run in production")
        return ConsoleOtpProvider()
    raise RuntimeError(f"OTP provider {name!r} is not available")
