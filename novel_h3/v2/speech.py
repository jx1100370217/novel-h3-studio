"""Strict ASR-text comparison with a tone-sensitive Mandarin spelling fallback.

This compares the dictionary readings of recognized text, not acoustic tones
or visible articulation. It never changes a script, subtitles, or approval.
"""
from importlib.metadata import version
import re

from ..speech_qc import compare


# Project-authorized readings of these proper names, not sentence exceptions.
# No heteronym search is allowed to choose whichever reading makes a test pass.
PROPER_NAME_READINGS = {'长山': ('chang2', 'shan1'), '宋焘': ('song4', 'tao1'),
                        '焘儿': ('tao1', 'er2')}


def _written_tokens(text):
    return ''.join(character for character in text if character.isalnum()).lower()


def _normalized(text):
    # Keep uncommon Han/other letters as literal tokens instead of silently
    # deleting them with the older comparator's Basic-CJK-only regular expression.
    parts = re.findall(r'[\u4e00-\u9fffA-Za-z0-9]+|[^\u4e00-\u9fffA-Za-z0-9]+', _written_tokens(text))
    return ''.join(compare(part, '')['expected_normalized'] or part for part in parts)


def _distance(left, right):
    previous = list(range(len(right) + 1))
    for index, value in enumerate(left, 1):
        current = [index]
        for other_index, other in enumerate(right, 1):
            current.append(min(current[-1] + 1, previous[other_index] + 1,
                               previous[other_index - 1] + (value != other)))
        previous = current
    return previous[-1]


def _syllables(text):
    from pypinyin import lazy_pinyin, Style
    result, readings = [], []
    pattern = '(' + '|'.join(map(re.escape, PROPER_NAME_READINGS)) + ')'
    for part in re.split(pattern, text):
        if part in PROPER_NAME_READINGS:
            syllables = list(PROPER_NAME_READINGS[part])
            result.extend(syllables)
            readings.append({'term': part, 'syllables': syllables})
        elif part:
            result.extend(lazy_pinyin(part, style=Style.TONE3, neutral_tone_with_five=True,
                                      strict=True, errors=lambda chars: ['literal:' + char for char in chars]))
    return result, readings


def compare_spoken(expected, heard):
    legacy = compare(expected, heard)
    # Calling the existing cleanup with an empty RHS retains the project's
    # character normalization without triggering its old whole-sentence alias.
    target, actual = _normalized(expected), _normalized(heard)
    character_distance = _distance(target, actual)
    expected_syllables, expected_readings = _syllables(target)
    heard_syllables, heard_readings = _syllables(actual)
    phonetic_distance = _distance(expected_syllables, heard_syllables)
    equal_lengths = (len(target) == len(actual)
                     and len(expected_syllables) == len(heard_syllables)
                     and len(expected_syllables) == len(target))
    orthographic_passed = character_distance == 0
    phonetic_match = equal_lengths and phonetic_distance == 0
    phonetic_equivalent = not orthographic_passed and phonetic_match
    return {
        'comparison_schema': 'mandarin_spoken_compare_v1',
        'passed': orthographic_passed or phonetic_equivalent,
        'match_type': ('orthographic_normalized' if orthographic_passed else
                       'phonetic_equivalent' if phonetic_equivalent else 'mismatch'),
        'phonetic_equivalent': phonetic_equivalent,
        'expected': expected, 'transcript': heard,
        'expected_normalized': target, 'transcript_normalized': actual,
        'edit_distance': character_distance, 'allowed_distance': 0,
        'raw_character_edit_distance': _distance(_written_tokens(expected), _written_tokens(heard)),
        'orthographic_passed': orthographic_passed,
        'legacy_orthographic_comparison': legacy,
        'ignored_legacy_sentence_aliases': legacy.get('normalization_aliases', []),
        'phonetic_comparison': {
            'engine': 'pypinyin', 'version': version('pypinyin'),
            'unit': 'Mandarin syllable spelling with numbered lexical tone; neutral tone=5',
            'expected_syllables': expected_syllables, 'transcript_syllables': heard_syllables,
            'edit_distance': phonetic_distance, 'allowed_distance': 0,
            'equal_character_and_syllable_counts': equal_lengths, 'tone_sensitive': True,
            'heteronym_matching': False, 'expected_proper_name_readings': expected_readings,
            'transcript_proper_name_readings': heard_readings,
        },
        'scope': '仅核对 ASR 正字或零差异带声调读音序列；同音书写等价不是实际发音、表演、音色或口型的人工验收。',
        'source_text_modified': False, 'human_listened': False, 'release_approved': False,
    }
