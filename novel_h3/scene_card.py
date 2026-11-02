"""Act / time title cards for scene transitions.

The cards are silent clips inserted at chapter or time-jump boundaries. They
give the audience an explicit place/time beat and a dip-to-black transition,
without asking H3 to paint text into a take.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SERIF = "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc"
SERIF_INDEX = 2
BG = (8, 8, 9)
GOLD = (214, 176, 112)
TITLE = (240, 232, 214)
MUTED = (168, 164, 156)


def _font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(SERIF, size, index=SERIF_INDEX)


def render_scene_card_image(output: Path, *, act: str, title: str, place: str = "",
                            time: str = "", width: int = 1344, height: int = 768) -> Path:
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(image)
    centre = width // 2
    draw.text((centre, int(height * 0.36)), act, font=_font(28), fill=GOLD, anchor="mm")
    draw.text((centre, int(height * 0.46)), title, font=_font(58), fill=TITLE, anchor="mm")
    draw.rectangle([int(width * 0.42), int(height * 0.53), int(width * 0.58), int(height * 0.535)], fill=GOLD)
    place_time = " · ".join(item for item in (place, time) if item)
    if place_time:
        draw.text((centre, int(height * 0.60)), place_time, font=_font(26), fill=MUTED, anchor="mm")
    image.save(output)
    return output


def build_scene_card(output: Path, *, act: str, title: str, place: str = "", time: str = "",
                     duration_seconds: float = 1.5, fade_seconds: float = 0.25,
                     width: int = 1344, height: int = 768, fps: int = 24) -> Path:
    output = Path(output)
    still = output.with_suffix(".png")
    render_scene_card_image(still, act=act, title=title, place=place, time=time,
                            width=width, height=height)
    filters = f"scale={width}:{height}:flags=lanczos,format=yuv420p"
    if fade_seconds > 0:
        filters += (f",fade=t=in:st=0:d={fade_seconds:.3f}"
                    f",fade=t=out:st={duration_seconds - fade_seconds:.3f}:d={fade_seconds:.3f}")
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", str(still),
         "-t", f"{duration_seconds:.3f}", "-r", str(fps), "-vf", filters,
         "-c:v", "libx264", "-preset", "medium", "-crf", "16",
         "-x264-params", "keyint=48:min-keyint=48:scenecut=0",
         "-video_track_timescale", "24000", str(output)],
        check=True,
    )
    return output
