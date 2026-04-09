"""Duration parsing utilities.

Provides functions to parse duration strings like '30s', '10m', '1h' 
and ISO 8601 durations like 'PT1H2M3S' into seconds.
"""

from __future__ import annotations

import re


def parse_duration(duration: str | int | float | None) -> int | None:
    """Parse a duration string into seconds.
    
    Accepts:
    - Integer/float: treated as seconds
    - String with suffix: 's' (seconds), 'm' (minutes), 'h' (hours)
    - Plain number string: treated as seconds
    - None: returns None
    
    Examples:
        >>> parse_duration('30s')
        30
        >>> parse_duration('10m')
        600
        >>> parse_duration('1h')
        3600
        >>> parse_duration('2.5h')
        9000
        >>> parse_duration(60)
        60
        >>> parse_duration('300')
        300
    """
    if duration is None:
        return None
    
    if isinstance(duration, (int, float)):
        return int(duration)
    
    duration_str = str(duration).strip().lower()
    
    if not duration_str:
        return None
    
    # Match number with optional suffix (s, m, h)
    match = re.match(r'^(\d+(?:\.\d+)?)\s*(s|m|h)?$', duration_str)
    if not match:
        # Fallback: try to parse as plain number
        try:
            return int(float(duration_str))
        except ValueError:
            return None
    
    value = float(match.group(1))
    suffix = match.group(2) or 's'  # Default to seconds if no suffix
    
    if suffix == 's':
        return int(value)
    elif suffix == 'm':
        return int(value * 60)
    elif suffix == 'h':
        return int(value * 3600)
    
    return int(value)


def parse_iso_duration(iso_duration: str | int | float | None) -> int | None:
    """Parse an ISO 8601 duration string into seconds.
    
    Accepts ISO 8601 duration format: PT[n]H[n]M[n]S
    Examples: 'PT1H2M3S', 'PT30S', 'PT10M', 'PT1H30M'
    
    Also accepts plain integers/floats (treated as seconds).
    
    Examples:
        >>> parse_iso_duration('PT1H2M3S')
        3723
        >>> parse_iso_duration('PT30S')
        30
        >>> parse_iso_duration('PT10M')
        600
        >>> parse_iso_duration(300)
        300
    """
    if iso_duration is None:
        return None
    
    if isinstance(iso_duration, (int, float)):
        return int(iso_duration)
    
    duration_str = str(iso_duration).strip()
    
    if not duration_str:
        return None
    
    # Try ISO 8601 format first
    match = re.match(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$', duration_str)
    if match:
        h, m, s = (int(x or 0) for x in match.groups())
        return h * 3600 + m * 60 + s
    
    # Fallback: try plain number or duration string
    return parse_duration(duration_str)
