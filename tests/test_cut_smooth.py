import numpy as np

from novel_h3.cut_smooth import blend_pair


def test_blend_pair_keeps_subtitle_band_hard():
    previous = np.full((10, 10, 3), 0, dtype=np.uint8)
    current = np.full((10, 10, 3), 100, dtype=np.uint8)
    first, second = blend_pair(previous, current, alpha=0.25, subtitle_band=0.7)
    # Top 70% is blended; first leans to the outgoing frame, second to incoming.
    assert abs(int(first[0, 0, 0]) - 25) <= 1
    assert abs(int(second[0, 0, 0]) - 75) <= 1
    # Bottom 30% stays on the outgoing / incoming frame for a clean caption cut.
    assert int(first[9, 0, 0]) == 0
    assert int(second[9, 0, 0]) == 100


def test_blend_pair_rejects_shape_mismatch():
    a = np.zeros((10, 10, 3), dtype=np.uint8)
    b = np.zeros((9, 10, 3), dtype=np.uint8)
    try:
        blend_pair(a, b)
    except ValueError:
        pass
    else:
        raise AssertionError('shape mismatch must fail')
