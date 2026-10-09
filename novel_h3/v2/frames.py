"""Timestamped whole-duration sampling; never claim a contact sheet is full semantic QA."""
from pathlib import Path

from ..project import write


def sample_indices(frame_count, count=24):
    if frame_count < 1 or count < 2:
        raise ValueError('Need a nonempty clip and at least two sampling points')
    return sorted({round(i * (frame_count - 1) / (count - 1)) for i in range(count)})


def make_contact(take_dir):
    import cv2
    import numpy as np

    folder = Path(take_dir)
    cap = cv2.VideoCapture(str(folder / 'native.mp4'))
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    frames = sample_indices(frame_count)
    rows = (len(frames) + 3) // 4
    canvas = np.zeros((rows * 202, 1280, 3), dtype=np.uint8)
    for i, frame_id in enumerate(frames):
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_id)
        ok, frame = cap.read()
        if not ok:
            cap.release()
            raise ValueError(f'Cannot decode requested sample frame {frame_id}')
        y, x = (i // 4) * 202, (i % 4) * 320
        canvas[y+22:y+202, x:x+320] = cv2.resize(frame, (320, 180), interpolation=cv2.INTER_AREA)
        cv2.putText(canvas, f'f{frame_id:03d}  {frame_id/24:.3f}s', (x+4, y+16),
                    cv2.FONT_HERSHEY_SIMPLEX, .45, (240, 240, 240), 1)
    cap.release()
    out = folder / 'analysis'
    out.mkdir(exist_ok=True)
    if not cv2.imwrite(str(out / 'contact.jpg'), canvas):
        raise OSError('Could not save frame contact sheet')
    evidence = {'frame_count': frame_count, 'sampled_frame_indices': frames,
                'sampled_seconds': [f / 24 for f in frames],
                'scope': 'Even samples including both endpoints, not every-frame semantic inspection'}
    write(out / 'frame_samples.json', evidence)
    return evidence
