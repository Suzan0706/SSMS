"""Tanzanian phone numbers: accept 0754 123 456, +255 754 123 456, 255754123456 or 754123456."""

import re

_DIGITS = re.compile(r"\D")
_VALID = re.compile(r"^255[2-9][0-9]{8}$")


def normalise_phone(raw: str) -> str:
    digits = _DIGITS.sub("", raw or "")
    if len(digits) == 10 and digits.startswith("0"):
        digits = "255" + digits[1:]
    elif len(digits) == 9:
        digits = "255" + digits
    if not _VALID.match(digits):
        raise ValueError("invalid Tanzanian phone number")
    return digits


def mask_phone(last4: str | None) -> str | None:
    return f"****{last4}" if last4 else None
