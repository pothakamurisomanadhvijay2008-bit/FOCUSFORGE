"""Transparent, category-based rewards for completed manual sessions."""

COINS_PER_15_MINUTES = {
    "coding": 15,
    "assignment": 15,
    "creative": 12,
    "research": 10,
    "learning": 10,
    "video": 3,
}


def reward_coins(session_type: str, elapsed_seconds: int) -> int:
    """Award whole coins for completed tracked time; breaks/private work earn none."""
    rate = COINS_PER_15_MINUTES.get(session_type, 0)
    return max(0, int(max(0, elapsed_seconds) * rate // 900))
