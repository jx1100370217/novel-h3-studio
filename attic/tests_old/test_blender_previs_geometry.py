import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from novel_h3.blender_previs import RENDER_SCRIPT, binary_path


class BlenderGeometryTests(unittest.TestCase):
    def test_real_earth_mound_extents_and_ground_contact(self):
        try:
            binary = binary_path({})
        except ValueError:
            self.skipTest("Blender is not installed")
        script = '''
import importlib.util
import bpy
from mathutils import Vector
loader = importlib.util.spec_from_file_location("previs", RENDER_PATH)
p = importlib.util.module_from_spec(loader)
loader.loader.exec_module(p)
bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete(use_global=False)
mat = p.material("earth", (.4, .35, .3))
roots = p.prop_proxy("grave", {"kind": "earth_mound", "position": {"x": 0, "y": 1, "z": .3},
                     "dimensions": {"x": 2, "y": 2.6, "z": .6}}, mat, 2, {})
bpy.context.scene.frame_set(1)
bpy.context.view_layer.update()
assert len(roots) == 1 and len(roots[0].children) == 1
obj = roots[0].children[0]
points = [obj.matrix_world @ vertex.co for vertex in obj.data.vertices]
for axis, expected in enumerate((2, 2.6, .6)):
    assert abs(max(v[axis] for v in points) - min(v[axis] for v in points) - expected) < 1e-5
assert abs(min(v.z for v in points)) < 1e-5
assert (roots[0].matrix_world.translation - Vector((0, 1, .3))).length < 1e-5
assert len(obj.data.vertices) > 8
assert not any(o.get("projection_anchor") for o in bpy.data.objects)
print("EARTH_MOUND_ASSERTIONS_PASSED")
'''.replace("RENDER_PATH", json.dumps(str(RENDER_SCRIPT)))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "check_mound.py"
            path.write_text(script)
            result = subprocess.run([binary, "--background", "--factory-startup", "--threads", "2",
                                     "--python-exit-code", "1", "--python", str(path)],
                                    text=True, capture_output=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout[-5000:] + result.stderr[-5000:])
        self.assertIn("EARTH_MOUND_ASSERTIONS_PASSED", result.stdout)

    def test_real_pose_camera_and_group_geometry(self):
        try:
            binary = binary_path({})
        except ValueError:
            self.skipTest("Blender is not installed")
        script = '''
import importlib.util
import math
import bpy
from mathutils import Vector

loader = importlib.util.spec_from_file_location("previs", RENDER_PATH)
p = importlib.util.module_from_spec(loader)
loader.loader.exec_module(p)
scene = bpy.context.scene
scene.render.resolution_x = 512
scene.render.resolution_y = 288
mat = p.material("test", (.8, .8, .8))

def clear():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)

def head(root, member=1):
    return next(o for o in root.children_recursive if o.get("projection_anchor") == "head"
                and o.get("member_prefix", "").endswith(f"member {member}"))

def world(obj, frame):
    scene.frame_set(frame)
    return obj.evaluated_get(bpy.context.evaluated_depsgraph_get()).matrix_world.translation

def actor(pose, **fields):
    return {"id": pose, "x": 0, "y": 0, "z": 0, "pose": pose,
            "path": [{"frame": 0, "x": 0, "y": 0, "z": 0},
                     {"frame": 39, "x": 0, "y": 0, "z": 0}], **fields}

clear()
heights = {}
for index, pose in enumerate(("standing", "seated", "kneeling", "reclining", "propped", "mounted")):
    _, root = p.character_proxy(f"pose {pose}", actor(pose, x=index * 4,
                         path=[{"frame": 0, "x": index * 4, "y": 0, "z": 0},
                               {"frame": 39, "x": index * 4, "y": 0, "z": 0}]), mat, mat, 40)
    heights[pose] = world(head(root), 40).z
assert heights["reclining"] < 1.1 < heights["kneeling"] < heights["standing"]
assert heights["seated"] < heights["standing"] - .35
assert heights["reclining"] < heights["propped"] < heights["standing"]
assert heights["mounted"] < heights["standing"]
assert not any("cloud proxy" in o.name for o in bpy.data.objects)
_, flying = p.character_proxy("flying", actor("flying"), mat, mat, 40)
assert len([o for o in flying.children if "cloud proxy" in o.name]) == 3
_, turned = p.character_proxy("turned reclining", actor("reclining", heading=math.pi / 2), mat, mat, 40)
assert world(head(turned), 40).x > .65

clear()
moving = actor("standing", pose_out="seated", pose_transition={"start_frame": 10, "end_frame": 20},
               path=[{"frame": 0, "x": 0, "y": -2, "z": 0},
                     {"frame": 9, "x": 0, "y": 0, "z": 0},
                     {"frame": 39, "x": 0, "y": 0, "z": 0}], y=-2)
_, root = p.character_proxy("transition", moving, mat, mat, 40)
assert world(head(root), 1).z > 2
assert world(head(root), 40).z < 1.9
assert abs(world(head(root), 21).y - world(head(root), 40).y) < 1e-5
try:
    p.character_proxy("untimed", actor("standing", pose_out="seated"), mat, mat, 40)
except ValueError as error:
    assert "requires authored" in str(error)
else:
    raise AssertionError("A pose transition without timing silently passed")

keys = [{"frame": 0, "pose": "reclining"}, {"frame": 9, "pose": "reclining"},
        {"frame": 15, "pose": "seated"}, {"frame": 20, "pose": "standing"},
        {"frame": 30, "pose": "standing"}, {"frame": 39, "pose": "seated"}]
_, multi = p.character_proxy("rise walk sit", actor("reclining", pose_out="seated", pose_keyframes=keys,
               path=[{"frame": 0, "x": 0, "y": 0, "z": 0},
                     {"frame": 20, "x": 0, "y": 0, "z": 0},
                     {"frame": 30, "x": 0, "y": 2, "z": 0},
                     {"frame": 39, "x": 0, "y": 2, "z": 0}]), mat, mat, 40)
assert abs(world(head(multi), 1).z - world(head(multi), 10).z) < 1e-5
assert world(head(multi), 16).z < 1.9
assert world(head(multi), 21).z > 2
assert world(head(multi), 31).z > 2
assert world(head(multi), 40).z < 1.9
assert (world(multi, 31) - world(multi, 40)).length < 1e-5
for invalid in ([{"frame": 1, "pose": "reclining"}, keys[-1]],
                [keys[0], {"frame": 9, "pose": "standing"}, {"frame": 8, "pose": "seated"}, keys[-1]],
                [keys[0], {"frame": 39, "pose": "standing"}]):
    try:
        p.character_proxy("invalid sequence", actor("reclining", pose_out="seated", pose_keyframes=invalid), mat, mat, 40)
    except ValueError:
        pass
    else:
        raise AssertionError("An invalid pose sequence silently passed")

_, turn = p.character_proxy("stand turn walk", actor("standing", heading=math.pi,
                heading_keyframes=[{"frame": 0, "heading": math.pi}, {"frame": 9, "heading": math.pi},
                                   {"frame": 19, "heading": 0}, {"frame": 39, "heading": 0}],
                path=[{"frame": 0, "x": 0, "y": 0, "z": 0},
                      {"frame": 19, "x": 0, "y": 0, "z": 0},
                      {"frame": 39, "x": 0, "y": -3, "z": 0}]), mat, mat, 40)
pivot = next(o for o in turn.children if o.get("heading_root"))
scene.frame_set(1)
first_heading = pivot.rotation_euler.z
scene.frame_set(10)
assert abs(pivot.rotation_euler.z - first_heading) < 1e-5
for frame in (20, 30, 40):
    scene.frame_set(frame)
    forward = pivot.evaluated_get(bpy.context.evaluated_depsgraph_get()).matrix_world.to_quaternion() @ Vector((0, -1, 0))
    assert forward.y < -.99
assert world(turn, 20).y == 0
assert abs(world(turn, 40).y + 3) < 1e-5
_, short_arc = p.character_proxy("short arc", actor("standing", heading_keyframes=[
                  {"frame": 0, "heading": math.radians(179)},
                  {"frame": 39, "heading": math.radians(-179)}]), mat, mat, 40)
pivot = next(o for o in short_arc.children if o.get("heading_root"))
scene.frame_set(20)
assert abs(abs(pivot.rotation_euler.z) - math.pi) < .002
for invalid in ([{"frame": 1, "heading": 0}, {"frame": 39, "heading": math.pi}],
                [{"frame": 0, "heading": 0}, {"frame": 9, "heading": 0}, {"frame": 8, "heading": 1}, {"frame": 39, "heading": 1}],
                [{"frame": 0, "heading": 0}, {"frame": 39, "heading": float("nan")}],
                [{"frame": 0, "heading": 0}, {"frame": 39, "heading": float("inf")}]):
    try:
        p.character_proxy("invalid heading", actor("standing", heading_keyframes=invalid), mat, mat, 40)
    except ValueError:
        pass
    else:
        raise AssertionError("An invalid heading sequence silently passed")

clear()
bpy.ops.object.camera_add()
camera = bpy.context.object
scene.camera = camera
position = {"x": -4, "y": -8, "z": 3}
target = {"x": 0, "y": 0, "z": 1}
spec = {"frames": 10, "cast": [], "scene_kind": "hall",
        "camera": {"lens_mm": 35, "movement": "locked tripod", "position": position,
                   "look_at": target, "path": [{"frame": 0, "position": position},
                                                 {"frame": 9, "position": position}]}}
p.camera_path(scene, camera, spec, [])
for frame in (1, 5, 10):
    assert (world(camera, frame) - Vector((-4, -8, 3))).length < 1e-5
spec["camera"]["path"][-1]["position"] = {"x": -2, "y": -6, "z": 3}
p.camera_path(scene, camera, spec, [])
assert (world(camera, 10) - Vector((-2, -6, 3))).length < 1e-5

clear()
layout = [{"offset": {"x": (i - 4) * 1.1, "y": 0, "z": 0}, "pose": "seated"} for i in range(9)]
center, root = p.character_proxy("nine officials", actor("seated", instances=9, instance_layout=layout), mat, mat, 40)
assert len([o for o in root.children if o.get("projection_anchor") == "head"]) == 9
for index, entry in enumerate(layout, 1):
    assert abs(world(head(root, index), 40).x - entry["offset"]["x"]) < 1e-5
    assert world(head(root, index), 40).z < 1.9
bpy.ops.object.camera_add(location=(0, -16, 4))
camera = bpy.context.object
camera.data.lens = 28
camera.rotation_euler = (Vector((0, 0, 1)) - camera.location).to_track_quat("-Z", "Y").to_euler()
scene.camera = camera
p.validate_cast_projection(scene, camera, [root], [center], 2)
head(root, 9).location.x = 30
head(root, 9).animation_data_clear()
try:
    p.validate_cast_projection(scene, camera, [root], [center], 2)
except RuntimeError as error:
    assert "member 9" in str(error)
else:
    raise AssertionError("The ninth offscreen member was not checked")

clear()
def prop(kind, position, dimensions, **extra):
    return {"kind": kind, "position": dict(zip(("x", "y", "z"), position)),
            "dimensions": dict(zip(("x", "y", "z"), dimensions)), **extra}

_, owner = p.character_proxy("holder", actor("standing", path=[
               {"frame": 0, "x": 0, "y": 0, "z": 0},
               {"frame": 39, "x": 3, "y": 0, "z": 0}]), mat, mat, 40)
paper = prop("paper", (.3, 0, 1.1), (.28, .19, .006), held_by="holder",
             path=[{"frame": 0, "position": {"x": .3, "y": 0, "z": 1.1}},
                   {"frame": 39, "position": {"x": 1, "y": 0, "z": 1.1}}])
paper_root = p.prop_proxy("world paper", paper, mat, 40, {"holder": owner})[0]
assert (world(paper_root, 40) - Vector((1, 0, 1.1))).length < 1e-5
carried = p.prop_proxy("attached paper", prop("paper", (.3, 0, 1.1), (.28, .19, .006),
                       held_by="holder"), mat, 40, {"holder": owner})[0]
assert abs(world(carried, 40).x - 3.3) < 1e-5
lid = p.prop_proxy("sliding lid", prop("coffin_lid", (-1.5, 1.15, .98), (.96, 2.25, .12),
               path=[{"frame": 0, "position": {"x": -1.5, "y": 1.15, "z": .98}},
                     {"frame": 39, "position": {"x": -1.5, "y": 2.3, "z": .14}}]), mat, 40, {})[0]
assert (world(lid, 40) - Vector((-1.5, 2.3, .14))).length < 1e-5
horse = p.prop_proxy("grounded horse", prop("horse", (0, 0, 0), (2.35, .72, 1.75)), mat, 40, {})[0]
assert len([o for o in horse.children if "equine leg" in o.name]) == 4
assert len([o for o in horse.children if "equine hoof" in o.name]) == 4
assert len([o for o in horse.children if "equine head" in o.name]) == 1

clear()
coffin = prop("coffin", (-1.5, 0, .45), (.96, 2.15, 1.04), components=[
    prop("coffin_body", (-1.5, 0, .45), (.88, 2.15, .9), component_id="body", wall_thickness=.055),
    prop("coffin_lid", (-1.5, 1.15, .98), (.96, 2.25, .12), component_id="lid")])
roots = p.prop_proxy("open coffin", coffin, mat, 2, {})
assert len(roots) == 2
assert (world(roots[0], 1) - Vector((-1.5, 0, .45))).length < 1e-5
center, root = p.character_proxy("reclining in coffin", actor("reclining", x=-1.5,
                path=[{"frame": 0, "x": -1.5, "y": 0, "z": 0},
                      {"frame": 1, "x": -1.5, "y": 0, "z": 0}]), mat, mat, 2)
bpy.ops.object.camera_add(location=(-6, -7.5, 1.65))
camera = bpy.context.object
camera.data.lens = 40
camera.rotation_euler = (Vector((-.95, .5, 1.3)) - camera.location).to_track_quat("-Z", "Y").to_euler()
scene.camera = camera
p.validate_cast_projection(scene, camera, [root], [center], 2)

clear()
positions = [(0, 7), (-3, 6), (3, 6)] + [(i * .9, 9.25) for i in range(-4, 5)]
chairs = [prop("chair", (x, y, 0), (1, .85, 1.6), position_anchor="ground_root", seat_height=.5)
          for x, y in positions]
p.create_hall(mat, mat, mat, {"set_support_geometry": chairs})
assert not any(o.name.startswith("one elevated jade throne") or o.name.startswith("registered council seat")
               for o in bpy.data.objects)
chair_roots = [p.prop_proxy(f"fixed chair {i}", item, mat, 2, {})[0] for i, item in enumerate(chairs)]
assert len(chair_roots) == 12
def bounds(obj, frame):
    scene.frame_set(frame)
    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    return [evaluated.matrix_world @ Vector(corner) for corner in evaluated.bound_box]
seat = next(o for o in chair_roots[1].children if o.name.endswith(" seat"))
seat_top = max(v.z for v in bounds(seat, 1))
assert abs(seat_top - .5) < 1e-5
assert abs(min(v.z for root in chair_roots for obj in root.children for v in bounds(obj, 1))) < 1e-5
_, seated = p.character_proxy("seated contact", actor("seated", x=-3, y=6,
                path=[{"frame": 0, "x": -3, "y": 6, "z": 0},
                      {"frame": 1, "x": -3, "y": 6, "z": 0}]), mat, mat, 2)
torso = next(o for o in seated.children if o.get("projection_anchor") == "torso")
assert abs(min(v.z for v in bounds(torso, 1)) - seat_top) < .05
turned_chair = p.prop_proxy("turned chair", prop("chair", (0, 0, 0), (1, .85, 1.6),
                position_anchor="ground_root", seat_height=.5, rotation={"z": math.pi / 2}), mat, 2, {})[0]
back = next(o for o in turned_chair.children if o.name.endswith(" back"))
assert world(back, 1).x < -.3
clear()
p.create_hall(mat, mat, mat)
legacy_seats = [o for o in bpy.data.objects if o.name.endswith(" seat")]
assert len(legacy_seats) == 9
print("BLENDER_GEOMETRY_ASSERTIONS_PASSED")
'''.replace("RENDER_PATH", json.dumps(str(RENDER_SCRIPT)))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "check_geometry.py"
            path.write_text(script)
            result = subprocess.run([binary, "--background", "--factory-startup", "--threads", "2",
                                     "--python-exit-code", "1", "--python", str(path)],
                                    text=True, capture_output=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout[-5000:] + result.stderr[-5000:])
        self.assertIn("BLENDER_GEOMETRY_ASSERTIONS_PASSED", result.stdout)


if __name__ == "__main__":
    unittest.main()
