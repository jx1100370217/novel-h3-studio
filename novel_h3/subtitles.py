"""Dialogue subtitles for the delivered cut.

H3 sometimes paints the spoken line into the take and sometimes does not, so
the cut would otherwise mix subtitled and unsubtitled shots. The compose stage
burns one consistent dialogue subtitle per shot from the authored dialogue,
using the same timing rule as the Ref2VA builder.
"""
from __future__ import annotations

import re
from pathlib import Path

LINE_RE = re.compile(r'^([\u4e00-\u9fff]{1,6})(?:（[^）]*）)?：(.+)$')

STYLE = {
    'font': 'Noto Sans CJK SC',
    'size': 72,
    'primary': '&H00FFFFFF',
    'outline_colour': '&H00000000',
    'outline': 2.5,
    'shadow': 0,
    'margin_v': 45,
}


def shot_cues(shot: dict, timing: list | None = None) -> list[dict]:
    """Timed dialogue cues for one shot, in shot-local seconds."""
    duration = float(shot.get('frames') or 0) / 24 or float(shot.get('duration_seconds') or 0)
    parsed = []
    for raw in (shot.get('dialogue') or '').splitlines():
        match = LINE_RE.match(raw.strip())
        if match:
            parsed.append(match.group(2).strip())
    count = len(parsed)
    cues = []
    for index, text in enumerate(parsed):
        if timing and index < len(timing):
            start, end = timing[index]
            cues.append({'start': round(float(start), 3), 'end': round(float(end), 3), 'text': text})
            continue
        if count == 1:
            start = 1.5
        else:
            start = 1.2 + index * max(2.0, (duration - 3.5) / (count - 1))
        start = min(start, max(0.8, duration - 2.0))
        end = start + 3.4
        if index + 1 < count:
            end = min(end, start + max(2.0, (duration - 3.5) / (count - 1)) - 0.15)
        end = min(end, duration - 0.15)
        cues.append({'start': round(start, 3), 'end': round(end, 3), 'text': text})
    return cues


def _ass_time(seconds: float) -> str:
    centis = int(round(max(0.0, seconds) * 100))
    hours, rest = divmod(centis, 360000)
    minutes, rest = divmod(rest, 6000)
    secs, cs = divmod(rest, 100)
    return f'{hours}:{minutes:02d}:{secs:02d}.{cs:02d}'


def _ass_text(text: str) -> str:
    return text.replace('\\', '＼').replace('{', '（').replace('}', '）').replace('\n', ' ')


def write_ass(cues: list[dict], path: Path, *, width: int, height: int,
              style: dict | None = None) -> Path:
    """Write a shot-local ASS file whose times start at 0."""
    style = {**STYLE, **(style or {})}
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Dialogue,{style['font']},{style['size']},{style['primary']},&H000000FF,{style['outline_colour']},&H64000000,1,0,0,0,100,100,0,0,1,{style['outline']},{style['shadow']},2,60,60,{style['margin_v']},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]
    for cue in cues:
        lines.append(
            f"Dialogue: 0,{_ass_time(cue['start'])},{_ass_time(cue['end'])},Dialogue,,0,0,0,,{_ass_text(cue['text'])}\n")
    path.write_text(''.join(lines), encoding='utf-8')
    return path


def build_shot_ass(shot: dict, path: Path, *, width: int = 1344, height: int = 768,
                   style: dict | None = None, timing: list | None = None) -> Path | None:
    cues = shot_cues(shot, timing=timing)
    if not cues:
        return None
    return write_ass(cues, path, width=width, height=height, style=style)
