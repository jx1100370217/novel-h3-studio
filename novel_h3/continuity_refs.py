"""Video-continuation references for sequential H3 rendering.

A shot inherits the previous take only when both belong to the same script
section: the silent tail of that take is a ``<Video N>`` continuation source
for the ending pose, costume, hand/prop position, light and screen direction.
A scene jump starts from cast and location references only, because the
previous take has a different place, time and light.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable, Mapping

from .ref2va_builder import VideoRef

DEFAULT_TAIL_SECONDS = 3.0


def continuation_ref(previous: Mapping[str, str] | None, previous_section: str | None,
                     section: str, takes_dir: Path, *,
                     tail_seconds: float = DEFAULT_TAIL_SECONDS) -> VideoRef | None:
    """Return the continuation reference for the shot after ``previous``.

    ``previous`` carries the ``id`` and the English ``close_state`` of the
    take that precedes this shot. The returned clip is the silent tail of that
    take, not a copy of its framing or audio.
    """
    if not previous or previous_section != section:
        return None
    source = Path(takes_dir) / previous['id'] / 'native.mp4'
    return VideoRef(
        asset_id=previous['id'],
        path=str(source.resolve()),
        definition=(f"the previous take {previous['id']}, a silent continuation source; "
                    f"its last seconds end with: {previous['close_state']}"),
        task_type='video continuation',
        tail_seconds=tail_seconds,
        cache_dir='runtime/video-refs',
    )


def missing_continuations(entries: Iterable[Mapping]) -> list[str]:
    """Return shots that continue a section but declare no video reference.

    ``entries`` are ordered shot descriptors with ``id``, ``section`` and the
    optional ``videos`` list. The first shot of a section is exempt.
    """
    issues: list[str] = []
    previous_section: str | None = None
    for entry in entries:
        if previous_section == entry['section'] and not entry.get('videos'):
            issues.append(entry['id'])
        previous_section = entry['section']
    return issues
