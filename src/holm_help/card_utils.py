"""Payment-card detection and masking. Runs before model/checkpoint input."""

from __future__ import annotations

import re

# Sequences of 13–19 digits with optional spaces/dashes (card-like).
_CARD_PATTERN = re.compile(r"(?<!\d)(?:\d[ -]*?){13,19}(?!\d)")


def _digits_only(value: str) -> str:
    return re.sub(r"\D", "", value)


def _luhn_ok(digits: str) -> bool:
    if not digits.isdigit() or not (13 <= len(digits) <= 19):
        return False
    total = 0
    reverse = digits[::-1]
    for i, ch in enumerate(reverse):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def find_card_number(text: str) -> str | None:
    """Return the first Luhn-valid card-like digit sequence, or None."""
    for match in _CARD_PATTERN.finditer(text):
        digits = _digits_only(match.group(0))
        if _luhn_ok(digits):
            return digits
    return None


def mask_card(digits: str) -> str:
    """Mask a card number as **** **** **** last4."""
    last4 = digits[-4:] if len(digits) >= 4 else digits
    return f"**** **** **** {last4}"


def sanitize_message(text: str) -> tuple[str, str | None]:
    """
    Replace any full card-like number with a mask before graph/model use.

    Returns (sanitized_text, mask_or_none).
    """
    digits = find_card_number(text)
    if not digits:
        return text, None

    mask = mask_card(digits)

    def _repl(match: re.Match[str]) -> str:
        candidate = _digits_only(match.group(0))
        if candidate == digits:
            return mask
        return match.group(0)

    sanitized = _CARD_PATTERN.sub(_repl, text)
    return sanitized, mask
