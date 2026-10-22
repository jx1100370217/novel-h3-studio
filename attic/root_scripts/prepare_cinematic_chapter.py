"""Prepare, accept or validate the filmable handoff before chapter generation."""
import argparse
from pathlib import Path

from novel_h3.project import read
from novel_h3.v2.cinematization import accept, prepare, require

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('prepare', 'accept', 'validate'))
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--source-plan', type=Path)
    parser.add_argument('--response', type=Path)
    args = parser.parse_args()
    if args.stage == 'prepare':
        if args.source_plan is None:
            parser.error('prepare requires --source-plan')
        print(prepare(args.project, args.source_plan, args.directory))
    elif args.stage == 'accept':
        if args.response is None:
            parser.error('accept requires --response')
        print(accept(args.project, args.directory, read(args.response)))
    else:
        print(require(args.project, read(args.directory / 'chapter_plan.json')))
