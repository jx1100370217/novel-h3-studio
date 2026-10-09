"""Rasterize exact source text with registered local fonts, never model lettering."""
from pathlib import Path

from ..project import file_hash


def rasterize(cues, width, height, folder, frames):
    from PIL import Image, ImageColor, ImageDraw, ImageFont
    folder.mkdir(exist_ok=True)
    results = []
    for index, cue in enumerate(cues):
        start, end = cue['start_frame'], cue['end_frame']
        if type(start) is not int or type(end) is not int or not 0 <= start < end <= frames:
            raise ValueError('Typography timing is outside the edit')
        x, y, w, h = cue['box_xywh']
        if not 0 <= x < x + w <= 1 or not 0 <= y < y + h <= 1:
            raise ValueError('Typography box is outside the picture')
        font_file = Path(cue['font_file']).resolve(strict=True)
        size = max(8, round(cue['font_size_fraction_of_frame_height'] * height))
        text = '\n'.join(cue['lines'])
        if not text.strip():
            raise ValueError('Visible source text must be nonempty')
        image = Image.new('RGBA', (width, height))
        draw = ImageDraw.Draw(image)
        for size in range(size, 7, -1):
            font = ImageFont.truetype(str(font_file), size)
            box = draw.multiline_textbbox((0, 0), text, font=font, spacing=round(size * .35))
            if box[2] - box[0] <= w * width and box[3] - box[1] <= h * height:
                break
        else:
            raise ValueError('Visible source text does not fit its authored box')
        alignment = cue.get('horizontal_alignment', 'center')
        left = x * width + ((w * width - (box[2] - box[0])) / 2 if alignment == 'center' else 0) - box[0]
        top = y * height + (h * height - (box[3] - box[1])) / 2 - box[1]
        background = cue.get('background')
        if background:
            padding = background.get('padding_fraction_of_frame_height', 0) * height
            draw.rectangle((x * width - padding, y * height - padding,
                            (x + w) * width + padding, (y + h) * height + padding),
                fill=(*ImageColor.getrgb(background['color']), round(background['opacity'] * 255)))
        draw.multiline_text((left, top), text, font=font, spacing=round(size * .35),
                            align=alignment, fill=cue['color'])
        path = folder / f'cue_{index:02d}.png'
        image.save(path)
        results.append({'id': cue['id'], 'path': path, 'sha256': file_hash(path),
                        'font_sha256': file_hash(font_file), 'text': cue['text'],
                        'start_frame': start, 'end_frame': end, 'actual_font_size': size})
    return results
