#!/usr/bin/env python3
"""novel-h3-studio monorepo entry point.

The monorepo keeps the model backends in ``novel_h3/`` and hosts the
OpenMontage production workflow in ``openmontage/``. This launcher puts the
OpenMontage code on ``sys.path`` and points its project root at the host
repository's ``projects/`` directory.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OPENMONTAGE = ROOT / 'openmontage'
os.environ.setdefault('OPENMONTAGE_PROJECTS_DIR', str(ROOT / 'projects'))
sys.path.insert(0, str(OPENMONTAGE))


def _backlot():
    from backlot.__main__ import main
    return main


def _registry():
    from tools.tool_registry import registry
    registry.discover()
    return registry


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog='studio', description=__doc__)
    sub = parser.add_subparsers(dest='command')

    board = sub.add_parser('board', help='open the Backlot production board')
    board.add_argument('project_id', nargs='?', default=None)

    serve = sub.add_parser('serve', help='run the Backlot server in the foreground')
    serve.add_argument('--port', type=int, default=4750)

    init = sub.add_parser('init', help='initialize an OpenMontage project workspace')
    init.add_argument('project_id')
    init.add_argument('--title', required=True)
    init.add_argument('--pipeline', default='novel-cinematic')

    sub.add_parser('doctor', help='print the capability menu')

    tool = sub.add_parser('tool', help='execute a registered OpenMontage tool')
    tool.add_argument('name')
    tool.add_argument('payload', help='JSON payload or @path/to/payload.json')

    args = parser.parse_args(argv)
    if args.command == 'board':
        return _backlot()(['open'] + ([args.project_id] if args.project_id else []))
    if args.command == 'serve':
        return _backlot()(['serve', '--port', str(args.port)])
    if args.command == 'init':
        from lib.checkpoint import init_project
        init_project(args.project_id, title=args.title, pipeline_type=args.pipeline)
        print(f'initialized {args.project_id} ({args.pipeline})')
        return 0
    if args.command == 'doctor':
        registry = _registry()
        print(json.dumps(registry.provider_menu_summary(), indent=2, ensure_ascii=False))
        return 0
    if args.command == 'tool':
        payload = args.payload
        if payload.startswith('@'):
            payload = Path(payload[1:]).read_text(encoding='utf-8')
        registry = _registry()
        tool_obj = registry._tools.get(args.name)
        if tool_obj is None:
            parser.error(f'unknown tool: {args.name}')
        result = tool_obj.execute(json.loads(payload))
        print(json.dumps({'success': result.success, 'data': result.data, 'error': result.error},
                         indent=2, ensure_ascii=False, default=str))
        return 0 if result.success else 1
    parser.print_help()
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
