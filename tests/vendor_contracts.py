"""Run with the ComfyUI venv; reads the actual pinned vendor contracts."""
import importlib.util
from pathlib import Path
import sys
import types

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from novel_h3.project import read

# Do not bootstrap ArcReel's full service (database, provider clients, etc.).
# These are the unchanged upstream model and schema modules, not mocks.
package = types.ModuleType("lib")
package.__path__ = [str(REPO / "vendor/ArcReel/lib")]
sys.modules["lib"] = package
from lib.script_models import DramaNormalizedScript, DramaEpisodeScript
from lib.script_skeleton import STORYBOARD_ITEM_ID_PATTERN

project = REPO / "projects/rendao-wuji"
plan = read(project / "content_plans/proof_tongtian.json")
content = DramaNormalizedScript.model_validate(plan["script"])
export = DramaEpisodeScript.model_validate(read(project / "arcreel_export/proof_tongtian/script.json"))
assert all(STORYBOARD_ITEM_ID_PATTERN.fullmatch(scene.scene_id) for scene in export.scenes)
assert len(content.scenes) == len(export.scenes) == 2
print("ArcReel original content/export schemas and scene ID pattern: passed")

sys.path.insert(0, read(project / "config.json")["comfy_root"])
spec = importlib.util.spec_from_file_location("motion_layout_contract", REPO / "vendor/ComfyUI-H3-Motion-Context/layout_contract.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.ensure("novel-h3-studio contract verification")
assert module.is_checked()
print("Motion Context against actual installed ComfyUI PackedLayout: passed")
