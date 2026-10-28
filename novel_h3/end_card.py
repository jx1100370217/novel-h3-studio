"""End-card renderer for delivered cuts.

Every delivered film ends on one card: title, source, production credits and
the project signature. The signature is this repository, not the workflow
tool, so a viewer can find the project that made the film.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

PROJECT_CREDIT = 'https://github.com/jx1100370217/novel-h3-studio'
SERIF = '/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc'
SERIF_BOLD = '/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc'
SERIF_INDEX = 2  # Simplified Chinese face inside the CJK collection
BACKGROUND = (9, 9, 10)
TITLE_INK = (240, 232, 214)
RULE_INK = (214, 176, 112)
BODY_INK = (214, 210, 202)
MUTED_INK = (168, 164, 156)


def _font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size, index=SERIF_INDEX)


def _fit(draw: ImageDraw.ImageDraw, text: str, path: str, size: int, limit: int) -> ImageFont.FreeTypeFont:
    font = _font(path, size)
    while size > 18 and draw.textlength(text, font=font) > limit:
        size -= 2
        font = _font(path, size)
    return font


def render_card_image(output: Path, *, title: str, source: str = '', credits: tuple[str, ...] = (),
                      credit: str = PROJECT_CREDIT, end_mark: str = '全片完',
                      width: int = 1344, height: int = 768) -> Path:
    """Draw the end card as a PNG so the layout is deterministic."""
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new('RGB', (width, height), BACKGROUND)
    draw = ImageDraw.Draw(image)
    limit = width - 200

    title_font = _fit(draw, title, SERIF_BOLD, 76, limit)
    draw.text((width // 2, 168), title, font=title_font, fill=TITLE_INK, anchor='mm')
    rule_width = 320
    draw.line([(width // 2 - rule_width // 2, 232), (width // 2 + rule_width // 2, 232)],
              fill=RULE_INK, width=2)
    if source:
        source_font = _fit(draw, source, SERIF, 32, limit)
        draw.text((width // 2, 282), source, font=source_font, fill=MUTED_INK, anchor='mm')

    lines = (f'改编 / 制作 {credit}', *credits)
    y = 372
    for line in lines:
        font = _fit(draw, line, SERIF, 30, limit)
        draw.text((width // 2, y), line, font=font, fill=BODY_INK, anchor='mm')
        y += 50
    if end_mark:
        mark_font = _fit(draw, end_mark, SERIF, 26, limit)
        draw.text((width // 2, height - 62), end_mark, font=mark_font, fill=MUTED_INK, anchor='mm')
    image.save(output, quality=95)
    return output


def build_end_card(output: Path, *, title: str, source: str = '', credits: tuple[str, ...] = (),
                   credit: str = PROJECT_CREDIT, end_mark: str = '全片完',
                   duration_seconds: float = 3.0, fade_in_seconds: float = 0.0,
                   frames: int | None = None,
                   width: int = 1344, height: int = 768, fps: int = 24) -> Path:
    """Render the card still and turn it into a silent clip for the cut."""
    output = Path(output)
    still = output.with_suffix('.png')
    render_card_image(still, title=title, source=source, credits=credits, credit=credit,
                      end_mark=end_mark, width=width, height=height)
    output.parent.mkdir(parents=True, exist_ok=True)
    filters = f'scale={width}:{height}:flags=lanczos,format=yuv420p'
    if fade_in_seconds > 0:
        filters += f',fade=t=in:st=0:d={fade_in_seconds:.3f}'
    length = ['-frames:v', str(frames)] if frames else ['-t', f'{duration_seconds:.3f}']
    subprocess.run(
        ['ffmpeg', '-y', '-loglevel', 'error', '-loop', '1', '-i', str(still),
         *length, '-r', str(fps),
         '-vf', filters,
         '-c:v', 'libx264', '-preset', 'medium', '-crf', '16',
         '-x264-params', 'keyint=48:min-keyint=48:scenecut=0',
         '-video_track_timescale', '24000', str(output)],
        check=True,
    )
    return output
