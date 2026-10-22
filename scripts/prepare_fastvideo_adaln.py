"""Precompute the official fixed PDD AdaLN tables one layer at a time on a 5090."""
import argparse
import json
from pathlib import Path

import torch
import torch.nn.functional as F
from safetensors import safe_open

from fastvideo.layers.pdd import PDDModalitySchedule, build_pdd_sampling_plan
from fastvideo.layers.visual_embedding import Timesteps


def prepare(model):
    model = Path(model)
    folder = model / 'transformer_ref'
    cfg = json.loads((folder / 'config.json').read_text())
    contract = json.loads((model / 'fastvideo_inference.json').read_text())
    weights = json.loads((folder / 'diffusion_pytorch_model.safetensors.index.json').read_text())['weight_map']

    def tensor(name, dtype):
        with safe_open(folder / weights[name], framework='pt', device='cpu') as source:
            return source.get_tensor(name).to(device='cuda', dtype=dtype)

    plan = build_pdd_sampling_plan(contract['pdd_step_indices'],
        {'video': PDDModalitySchedule(shift=contract['video_scheduler_shift']),
         'audio': PDDModalitySchedule(shift=contract['audio_scheduler_shift'])}, device='cuda')
    video = 1.0 - plan.node_sigmas['video'].to(torch.float32)[:-1]
    audio = 1.0 - plan.node_sigmas['audio'].to(torch.float32)[:-1]
    time_proj = Timesteps(cfg['freq_dim'], flip_sin_to_cos=True, downscale_freq_shift=0).cuda()
    w1, b1 = tensor('time_embedder.linear_1.weight', torch.float32), tensor('time_embedder.linear_1.bias', torch.float32)
    w2, b2 = tensor('time_embedder.linear_2.weight', torch.float32), tensor('time_embedder.linear_2.bias', torch.float32)
    inputs = {}
    for vt, at in zip(video, audio):
        # Cover image-only, image+voice and video references with the same fixed scheduler.
        for visual_condition in (False, True):
            for audio_condition in (False, True):
                values = [vt.item(), at.item()]
                if visual_condition:
                    values.append(max(vt.item(), .999))
                if audio_condition:
                    values.append(1.0)
                timestep = torch.unique(torch.tensor(values, device='cuda', dtype=torch.float32), sorted=True)
                temb = F.linear(F.silu(F.linear(time_proj(timestep), w1, b1)), w2, b2)
                key = (tuple(timestep.tolist()), tuple(temb.shape), str(temb.dtype))
                inputs[key] = F.silu(temb)
    tables = {}
    for index in range(cfg['num_layers']):
        prefix = f'transformer_blocks.{index}.adaln_proj.linear.'
        weight, bias = tensor(prefix + 'weight', torch.bfloat16), tensor(prefix + 'bias', torch.bfloat16)
        tables[index] = {repr(k): F.linear(x.to(weight.dtype), weight, bias).cpu() for k, x in inputs.items()}
        del weight, bias
        print('ADALN_LAYER', index + 1, '/', cfg['num_layers'], flush=True)
    destination = model / 'adaln_table.pt'
    torch.save(tables, destination)
    torch.save({repr(k): v.cpu() for k, v in inputs.items()}, str(destination) + '.inputs')
    print('ADALN_READY', destination, 'keys', len(inputs), flush=True)
    return destination


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('model', type=Path)
    with torch.inference_mode():
        prepare(parser.parse_args().model)
