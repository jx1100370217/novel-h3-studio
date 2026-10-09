"""Run the authorized complete-chapter production on the existing local H3 service."""
import argparse
from pathlib import Path

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('project', type=Path)
    parser.add_argument('plan', type=Path)
    parser.add_argument('--seed', type=int, default=202610080901)
    args = parser.parse_args()
    from novel_h3.safety import bounded_worker
    bounded_worker()
    from novel_h3.v2.production import produce
    print(produce(args.project, args.plan, args.seed), flush=True)
