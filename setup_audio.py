#!/usr/bin/env python3
"""Create an isolated audio environment reusing the installed ComfyUI runtime."""
from pathlib import Path
import subprocess

repo = Path(__file__).resolve().parent
base = Path('/home/jx/codes/comfyui-minimax-h3/.venv/bin/python')
target = repo / '.venv-audio'
if not base.is_file():
    raise SystemExit(f'未找到现有模型运行环境：{base}')
if not (target / 'bin/python').is_file():
    subprocess.run([str(base), '-m', 'venv', str(target)], check=True)
site = subprocess.check_output([str(base), '-c', 'import sysconfig;print(sysconfig.get_path("purelib"))'], text=True).strip()
own_site = subprocess.check_output([str(target / 'bin/python'), '-c', 'import sysconfig;print(sysconfig.get_path("purelib"))'], text=True).strip()
Path(own_site, 'comfy_runtime_readonly.pth').write_text(site + '\n')
subprocess.run([str(target / 'bin/python'), '-m', 'pip', 'install', '-r', str(repo / 'requirements-audio.txt')], check=True)
subprocess.run([str(target / 'bin/python'), '-c',
    'import torch,librosa;from silero_vad import load_silero_vad;from transformers import WhisperForConditionalGeneration,ASTForAudioClassification,Qwen2_5OmniThinkerForConditionalGeneration;load_silero_vad();print("本地音频运行环境已就绪",torch.__version__,librosa.__version__,"silero-vad")'], check=True)
