import json
from pathlib import Path

from novel_h3.fastvideo_runner import _build_generator_config, preflight


def test_official_fastvideo_preflight_rejects_comfy_only_directory(tmp_path: Path):
    model_root = tmp_path / "model"
    model_root.mkdir()
    (tmp_path / "config.json").write_text(json.dumps({
        "fastvideo": {"model_card": "https://huggingface.co/FastVideo/FastVideo-FastH3-8-Step-V2",
                       "official": {"runtime_repo": str(tmp_path / "runtime"),
                                    "model_root": str(model_root)}}
    }), encoding="utf-8")
    (tmp_path / "runtime").mkdir()
    result = preflight(tmp_path)
    assert result["ready"] is False
    assert "checkpoint_content.json" in result["missing_components"]


def test_official_runner_uses_single_gpu_5090_offload_profile(monkeypatch):
    runtime_repo = Path("/home/jx/codes/FastVideo")
    if runtime_repo.is_dir():
        monkeypatch.syspath_prepend(str(runtime_repo))
    class Args:
        model_root = "/tmp/fasth3-official"
        num_gpus = 1
        vsa_sparsity = 0.8
        vsa_tile_size = 64

    config = _build_generator_config(Args())
    assert config.engine.num_gpus == 1
    assert config.engine.parallelism.sp_size == 1
    assert config.engine.use_fsdp_inference is True
    assert config.engine.offload.dit is True
    assert config.engine.offload.dit_layerwise is False
    assert config.engine.offload.lazy_module_load is True
    assert config.engine.offload.pin_cpu_memory is False
