"""Change the Windows master volume by a fixed step."""

from __future__ import annotations

import logging

log = logging.getLogger("jarvisai.volume")


def next_level(current: float, step: int = 10) -> float | None:
    if current >= 99.5:
        return None
    return min(100.0, current + step)


def raise_volume(step: int = 10) -> float | None:
    """Raise the speaker volume. Returns the new percent, or None at maximum."""
    from pycaw.pycaw import AudioUtilities

    speakers = AudioUtilities.GetSpeakers()
    try:
        speakers.EndpointVolume.SetMute(0, None)
    except Exception:
        log.debug("Speakers were already unmuted", exc_info=True)
    updated = next_level(float(speakers.volume_percent), step)
    if updated is None:
        return None
    speakers.volume_percent = updated
    return updated
