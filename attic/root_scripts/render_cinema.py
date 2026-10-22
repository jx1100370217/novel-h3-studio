"""Generate selected native-H3 film candidates without touching legacy takes."""
import argparse
from pathlib import Path

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('project', type=Path)
    parser.add_argument('plan', type=Path)
    parser.add_argument('--shots', nargs='+')
    parser.add_argument('--seed', type=int, default=2026100801)
    args = parser.parse_args()
    from novel_h3.safety import bounded_worker
    bounded_worker()
    from novel_h3.v2.runner import run
    print(run(args.project, args.plan, args.shots, args.seed), flush=True)
