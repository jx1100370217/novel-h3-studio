"""Safety checks for local character voice reference generation."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tools.audio import qwen3_voice_design as voice
from tools.base_tool import ToolStatus


def test_existing_reference_is_not_overwritten(tmp_path):
    output = tmp_path / "reference.wav"
    output.write_bytes(b"existing reference")
    tool = voice.Qwen3VoiceDesign()
    with patch.object(tool, "get_status", return_value=ToolStatus.AVAILABLE), patch.object(voice.subprocess, "run") as run:
        result = tool.execute({"text": "你好", "instruct": "温柔的成年女声", "output_path": str(output)})
    assert not result.success
    assert output.read_bytes() == b"existing reference"
    run.assert_not_called()


def test_generation_runs_offline_and_returns_reference(tmp_path, monkeypatch):
    snapshot = tmp_path / "snapshots" / "model"
    snapshot.mkdir(parents=True)
    (snapshot / "config.json").write_text("{}")
    output = tmp_path / "reference.wav"
    monkeypatch.setattr(voice, "SNAPSHOTS", snapshot.parent)
    tool = voice.Qwen3VoiceDesign()

    def fake_run(args, **kwargs):
        assert kwargs["env"]["HF_HUB_OFFLINE"] == "1"
        assert kwargs["env"]["TRANSFORMERS_OFFLINE"] == "1"
        output.write_bytes(b"new reference")
        return SimpleNamespace(returncode=0, stderr="")

    with patch.object(tool, "get_status", return_value=ToolStatus.AVAILABLE), patch.object(voice.subprocess, "run", fake_run):
        result = tool.execute({"text": "你好", "instruct": "温柔的成年女声", "output_path": str(output)})
    assert result.success
    assert Path(result.data["output_path"]) == output
    assert output.read_bytes() == b"new reference"
