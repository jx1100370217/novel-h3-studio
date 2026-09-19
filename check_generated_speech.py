import argparse
import json
import os
from pathlib import Path
from novel_h3.safety import bounded_worker

if __name__ == '__main__':
    # Video rendering stays in the GPU workload slice, but Whisper runs in a
    # separate CPU-only transient unit.  Do not re-enter the model slice when
    # the caller explicitly launched this checker there.
    if os.environ.get('NOVEL_H3_AUDIO_QC') != '1':
        bounded_worker()
    p=argparse.ArgumentParser()
    p.add_argument('project',type=Path)
    p.add_argument('take')
    args=p.parse_args()
    from novel_h3.speech_qc import run
    result=run(args.project,args.take)
    print(json.dumps(result,ensure_ascii=False))
    raise SystemExit(0 if result['passed'] else 2)
