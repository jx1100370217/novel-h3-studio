"""Start the official single-5090 FastVideo NVFP4 QAD service on loopback."""
import argparse
import os
from pathlib import Path
import sys
import urllib.error

from novel_h3.fastvideo import available, api
from novel_h3.project import read
from novel_h3.safety import REPO, bounded_worker, check_power_cap


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    args = parser.parse_args()
    bounded_worker()
    cfg = read(args.project / 'config.json')
    profile = cfg['fast_h3_omni']
    if not available(cfg):
        raise SystemExit('FastVideo NVFP4 QAD components or AdaLN table are incomplete')
    check_power_cap(450)
    try:
        api(cfg, '/health')
        loaded = api(cfg, '/v1/model_info')
    except urllib.error.HTTPError as exc:
        raise SystemExit('Existing FastVideo service needs recovery: ' + str(exc))
    except OSError:
        loaded = None
    if loaded is not None:
        if Path(loaded['model_path']).resolve() != Path(profile['model_dir']).resolve():
            raise SystemExit('Port 8195 is serving a different model')
        print('FastVideo NVFP4 QAD service is already running.')
        raise SystemExit(0)
    cuda = REPO / 'runtime/fastvideo-venv/lib/python3.12/site-packages/nvidia/cu13'
    if not (cuda / 'bin/nvcc').is_file():
        raise SystemExit('The isolated CUDA 13 compiler is missing')
    # NVIDIA's wheels use lib/; FlashInfer's standard toolkit layout uses lib64/.
    for path, target in ((cuda / 'lib64', 'lib'), (cuda / 'lib/libcudart.so', 'libcudart.so.13'),
                         (cuda / 'lib/libcuda.so', '/usr/lib/x86_64-linux-gnu/libcuda.so.1')):
        if not path.exists():
            path.symlink_to(target)
    os.environ['CUDA_HOME'] = str(cuda)
    os.environ['CUDACXX'] = str(cuda / 'bin/nvcc')
    os.environ['PATH'] = os.pathsep.join((str(cuda / 'bin'), str(REPO / 'runtime/fastvideo-venv/bin'), os.environ.get('PATH', '')))
    os.environ['FLASHINFER_CUDA_ARCH_LIST'] = '12.0a'
    os.environ['MAX_JOBS'] = '4'
    os.environ['PYTORCH_ALLOC_CONF'] = 'expandable_segments:True'
    os.environ['FASTVIDEO_LAYERWISE_OFFLOAD_BUFFERS'] = '1'
    os.environ['FASTVIDEO_LAYERWISE_RESIDENT_BLOCKS'] = '0'
    os.environ['FASTVIDEO_H3_FFN_CHUNK_TOKENS'] = '8192'
    os.environ['FASTVIDEO_H3_PINNED_SWAP'] = '0'
    os.environ.setdefault('TORCHINDUCTOR_CACHE_DIR', str(REPO / 'runtime/torchinductor-cache'))
    import yaml
    source = REPO / 'runtime/FastVideo/examples/serving/openai_fasth3_omniref_rtx5090.yaml'
    recipe = yaml.safe_load(source.read_text())
    recipe['generator']['model_path'] = profile['model_dir']
    recipe['generator']['engine']['offload'].update(dit_layerwise=True, vae=True, pin_cpu_memory=False)
    recipe['generator']['pipeline']['vae_tiling'] = True
    recipe['generator']['pipeline']['experimental']['h3_vae_nvfp4_decoder'] = str(
        Path(profile['model_dir']) / 'vae_decoder_nvfp4/decoder-nvfp4.safetensors')
    recipe['server'].update(host='127.0.0.1', port=8195,
        output_dir=str(REPO / 'runtime/fastvideo-output'), served_model_name='fasth3-omni-nvfp4-qad',
        media_roots=[str((REPO / 'projects').resolve()), str((REPO / 'runtime').resolve())])
    config_path = REPO / 'runtime/fastvideo-rtx5090.yaml'
    config_path.write_text(yaml.safe_dump(recipe, sort_keys=False))
    # Apply the maintained official profile without composing/downloading a second model.
    sys.path.insert(0, str(REPO / 'runtime/FastVideo/examples/inference/basic'))
    from basic_fasth3_omniref_pdd import DEVICE_PROFILES, apply_profile
    apply_profile(DEVICE_PROFILES['rtx-5090'],
                  str(Path(profile['model_dir']) / 'vae_decoder_nvfp4/decoder-nvfp4.safetensors'),
                  profile['adaln_table'])
    os.environ['HF_HUB_OFFLINE'] = '1'
    os.environ['TOKENIZERS_PARALLELISM'] = 'false'
    os.execv(str(REPO / 'runtime/fastvideo-venv/bin/fastvideo'),
             ['fastvideo', 'serve', '--config', str(config_path)])
