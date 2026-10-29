"""Hard preflight for Ref2VA voice bindings.

H3 pairs the Nth audio reference in the request with the Nth visible subject.
A spec can pass the official six-section validator and still swap voices when
the ``voices`` list order, the ``<Audio N>`` labels and the subject definitions
disagree. This audit runs before every render and refuses the job instead of
burning GPU time on a take with the wrong voice.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

AUDIO_RE = re.compile(r'^<Audio (\d+)>$')
SUBJECT_RE = re.compile(r'^<Subject (\d+)>$')


def audit_spec(spec: dict) -> list[str]:
    """Return human-readable binding defects; an empty list means safe to render."""
    issues: list[str] = []
    voices = spec.get('voices') or []
    visuals = spec.get('visuals') or []
    subject_labels = {ref.get('subject') for ref in visuals if ref.get('subject')}
    definitions = (spec.get('sections') or {}).get('subject_definitions') or ''

    for index, voice in enumerate(voices, 1):
        audio = voice.get('audio')
        subject = voice.get('subject')
        role = voice.get('role') or voice.get('asset_id') or f'#{index}'
        expected_audio = f'<Audio {index}>'
        if audio != expected_audio:
            issues.append(
                f'voice {index} ({role}) is labelled {audio}; the API sends this file as '
                f'{expected_audio}, so the label and the audio order must match')
        if subject:
            match = SUBJECT_RE.match(subject)
            if not match:
                issues.append(f'{audio} ({role}) has malformed subject {subject!r}')
            elif subject not in subject_labels:
                issues.append(f'{audio} ({role}) names {subject}, which is not in visuals')
            elif int(match.group(1)) > index:
                issues.append(
                    f'{audio} ({role}) is paired with {subject}; H3 would bind {expected_audio} '
                    f'to <Subject {index}>, so the speaker would get the wrong voice')
            # subject_index < audio_index means an earlier visible subject is
            # silent or the voice is off-screen; that ordering is legitimate
            # and is covered by the silent-character / off-screen locks.
        line = next((item for item in definitions.splitlines() if item.startswith(f'{expected_audio} ')), '')
        if not line:
            issues.append(f'{expected_audio} has no voice-definition line')
        elif subject and subject not in line:
            issues.append(f'{expected_audio} definition does not name {subject}')

    for line in spec.get('spoken_lines') or []:
        speaker = line.get('speaker') or '?'
        subject = line.get('speaker_subject')
        if subject and subject not in subject_labels:
            issues.append(f'spoken line by {speaker} names {subject}, which is not in visuals')
        elif subject and subject not in {voice.get('subject') for voice in voices}:
            issues.append(f'spoken line by {speaker} ({subject}) has no matching voice reference')

    return issues


def audit_spec_file(path: Path) -> list[str]:
    return audit_spec(json.loads(Path(path).read_text(encoding='utf-8')))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Audit Ref2VA voice bindings before rendering.')
    parser.add_argument('--specs-dir', type=Path, required=True)
    parser.add_argument('--shots', default='', help='Comma-separated shot ids')
    args = parser.parse_args(argv)
    wanted = {item.strip() for item in args.shots.split(',') if item.strip()}
    failures = 0
    for path in sorted(Path(args.specs_dir).glob('*.json')):
        if wanted and path.stem not in wanted:
            continue
        issues = audit_spec_file(path)
        if issues:
            failures += 1
            print(f'{path.stem}: FAIL')
            for issue in issues:
                print(f'  - {issue}')
        else:
            print(f'{path.stem}: ok')
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
