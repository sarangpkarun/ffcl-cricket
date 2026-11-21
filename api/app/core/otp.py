"""OTP delivery behind an interface. The console provider logs the code (dev only)."""

import logging
from typing import Protocol

log = logging.getLogger("ffcl.otp")


class OtpProvider(Protocol):
    def send(self, phone: str, code: str) -> None: ...


class ConsoleOtpProvider:
    def send(self, phone: str, code: str) -> None:
        log.warning("OTP for %s: %s", phone, code)


def get_provider() -> OtpProvider:
    return ConsoleOtpProvider()
