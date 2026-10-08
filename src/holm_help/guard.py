"""Pre-model guard for blocked requests and payment-card input."""

from __future__ import annotations

import re

from holm_help.card_utils import sanitize_message

_BLOCKED_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?(previous\s+)?rules", re.I),
    re.compile(r"list\s+(every|all)\s+customer\s+(email|emails|data)", re.I),
    re.compile(r"customer\s+list", re.I),
    re.compile(r"internal\s+(instructions|prompt|system\s+prompt)", re.I),
    re.compile(r"full\s+payment[\s-]?card", re.I),
]


def is_blocked_request(text: str) -> str | None:
    """
    Detect the demo's blocked-request scenarios.

    This is not a universal prompt-injection defense — only the specified
    portfolio scenarios (customer lists / internal instructions / rule bypass).
    """
    for pattern in _BLOCKED_PATTERNS:
        if pattern.search(text):
            return (
                "I cannot provide customer lists, internal instructions, or bypass "
                "support rules. If you need help with an order or our return policy, "
                "please ask about a specific order ID."
            )
    return None


def guard_message(text: str) -> dict:
    """
    Run guard checks before any tool or model call.

    Returns keys: blocked, blocked_reason, sanitized_message, card_masked.
    """
    sanitized, card_mask = sanitize_message(text)
    if card_mask:
        return {
            "blocked": True,
            "blocked_reason": "payment_card",
            "sanitized_message": sanitized,
            "card_masked": card_mask,
            "reply": (
                f"For your security, please do not send payment-card details in chat. "
                f"I detected a card-like number and will only show a mask: {card_mask}. "
                f"Holm Help cannot process card numbers. If you need billing help, "
                f"ask to be handed off to a human agent without sharing card data."
            ),
        }

    blocked_msg = is_blocked_request(sanitized)
    if blocked_msg:
        return {
            "blocked": True,
            "blocked_reason": "blocked_request",
            "sanitized_message": sanitized,
            "card_masked": None,
            "reply": blocked_msg,
        }

    return {
        "blocked": False,
        "blocked_reason": None,
        "sanitized_message": sanitized,
        "card_masked": None,
        "reply": None,
    }
