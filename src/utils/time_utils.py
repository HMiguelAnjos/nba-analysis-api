import re

GAME_STATUS_MAP = {1: "not_started", 2: "in_progress", 3: "final"}


def parse_minutes_to_float(value: str) -> float:
    """Convert NBA minutes string to float.

    Handles:
      - ISO 8601 duration: 'PT24M30.00S' -> 24.5
      - Clock format:      '24:30'        -> 24.5
      - Plain number:      '24'           -> 24.0
    """
    s = str(value).strip()

    # ISO 8601 duration (live endpoints)
    match = re.match(r"PT(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?", s)
    if match and (match.group(1) or match.group(2)):
        minutes = int(match.group(1) or 0)
        seconds = float(match.group(2) or 0)
        return minutes + seconds / 60

    # MM:SS
    if ":" in s:
        parts = s.split(":")
        try:
            return int(parts[0]) + int(parts[1]) / 60
        except (ValueError, IndexError):
            return 0.0

    try:
        return float(s)
    except (ValueError, TypeError):
        return 0.0


def format_game_clock(game_clock: str) -> str:
    """Convert 'PT08M41.00S' to '08:41'. Returns '' on empty/unknown input."""
    s = str(game_clock).strip()
    if not s:
        return ""
    match = re.match(r"PT(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?", s)
    if match:
        mins = int(match.group(1) or 0)
        secs = int(float(match.group(2) or 0))
        return f"{mins:02d}:{secs:02d}"
    return s


def map_game_status(status_code: int) -> str:
    return GAME_STATUS_MAP.get(int(status_code), "unknown")
