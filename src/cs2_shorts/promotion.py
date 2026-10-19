"""Shared promotional copy used by every Shorts series."""

PROMO_MESSAGE = "10$ FREE SKIN, LINK IN DESCRIPTION"
PROMO_URL = "http://clash.gg/r/CSSKINNS"


def add_promo_link(description: str) -> str:
    """Put the referral link first so it remains visible before YouTube truncates."""
    return f"10$ FREE SKIN: {PROMO_URL}\n\n{description.lstrip()}"
