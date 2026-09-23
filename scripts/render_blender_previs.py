import argparse
import json
import math
import os
from pathlib import Path
import sys

import bpy
from mathutils import Vector
from bpy_extras.object_utils import world_to_camera_view


def arguments():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", required=True)
    return parser.parse_args(argv)


def material(name, color, roughness=0.85):
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = (*color, 1.0)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (*color, 1.0)
    bsdf.inputs["Roughness"].default_value = roughness
    return mat


def cube(name, location, scale, mat, bevel=0.0):
    bpy.ops.mesh.primitive_cube_add(size=1, location=location)
    obj = bpy.context.object
    obj.name = name
    obj.dimensions = scale
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    obj.data.materials.append(mat)
    if bevel:
        mod = obj.modifiers.new("soft blockout edges", "BEVEL")
        mod.width = bevel
        mod.segments = 2
    return obj


def cylinder(name, location, radius, depth, mat, vertices=12):
    bpy.ops.mesh.primitive_cylinder_add(vertices=vertices, radius=radius, depth=depth, location=location)
    obj = bpy.context.object
    obj.name = name
    obj.data.materials.append(mat)
    return obj


def sphere(name, location, scale, mat, segments=12, rings=8):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=segments, ring_count=rings, radius=1, location=location)
    obj = bpy.context.object
    obj.name = name
    obj.scale = scale
    obj.data.materials.append(mat)
    return obj


def beam(name, start, end, radius, mat):
    a, b = Vector(start), Vector(end)
    delta = b - a
    obj = cylinder(name, (a + b) * 0.5, radius, delta.length, mat)
    obj.rotation_euler = delta.to_track_quat("Z", "Y").to_euler()
    return obj


def chair(prefix, x, y, z, mat):
    cube(prefix + " seat", (x, y, z + 0.82), (1.35, 1.15, 0.28), mat, 0.08)
    cube(prefix + " back", (x, y + 0.42, z + 1.48), (1.35, 0.25, 1.15), mat, 0.08)
    for dx in (-0.55, 0.55):
        for dy in (-0.42, 0.38):
            cube(prefix + " leg", (x + dx, y + dy, z + 0.4), (0.16, 0.16, 0.8), mat, 0.025)
    for dx in (-0.72, 0.72):
        cube(prefix + " arm", (x + dx, y, z + 1.08), (0.18, 0.9, 0.18), mat, 0.04)


def create_hall(floor, architectural, accent):
    cube("single uninterrupted hall floor", (0, 0, -0.2), (26, 42, 0.4), floor)
    cube("rear hall wall", (0, 18.5, 7), (26, 0.6, 14), architectural)
    for side in (-1, 1):
        cube("side wall", (side * 13, 0, 6), (0.5, 37, 12), architectural)
        for y in range(-15, 19, 4):
            cylinder("vermilion-column proxy", (side * 9.5, y, 6), 0.42, 12, accent, 16)
            cube("column capital proxy", (side * 9.5, y, 12.1), (1.6, 1.6, 0.45), architectural, 0.06)
            cube("side bay lintel", (side * 11.2, y, 8), (3, 0.25, 0.35), accent, 0.04)
    for y, width, height in ((13, 18, 0.55), (14.1, 13, 0.48), (15.0, 8, 0.38)):
        cube("central raised dais", (0, y, height * 0.5), (width, 3, height), accent, 0.08)
    chair("one elevated jade throne", 0, 14.2, 1.4, accent)
    for side in (-1, 1):
        for index, y in enumerate((-8, -3.5, 1, 5.5), 1):
            chair(f"registered council seat {side} {index}", side * 5.2, y, 0, architectural)
    # Circular relief and roof ribs establish the same rear-wall and ceiling anchors in every view.
    bpy.ops.mesh.primitive_torus_add(major_radius=3.0, minor_radius=0.12, major_segments=32,
                                     minor_segments=8, location=(0, 18.05, 9.2), rotation=(math.pi / 2, 0, 0))
    bpy.context.object.name = "single circular rear relief proxy"
    bpy.context.object.data.materials.append(accent)
    for x in (-8, -4, 0, 4, 8):
        beam("roof rib", (x, -17, 12.4), (x, 17, 12.4), 0.14, accent)


def create_celestial_exterior(floor, architectural, accent):
    cube("continuous cloud-road platform", (0, 0, 0), (28, 30, 0.7), floor, 0.18)
    cube("palace silhouette rear mass", (0, 13, 5.5), (18, 4, 11), architectural, 0.12)
    cube("palace front terrace", (0, 6, 1), (22, 5, 1.2), accent, 0.12)
    for side in (-1, 1):
        for y in (1, 7, 12):
            cylinder("outer palace pillar", (side * 8, y, 4.5), 0.35, 9, accent, 12)
            # Keep decorative cloud masses beside the marked travel lane. The
            # former center-lane clouds occluded actors and read as oversized
            # foreground blobs in the spatial guide.
            sphere("side cloud bank marker", (side * 11.0, -3 + y * 0.15, 1.0), (1.3, 0.7, 0.25), architectural)
    for y in (-8, -3, 2, 7):
        cube("cloud path guide", (0, y, 0.42), (5.0, 0.3, 0.08), accent)


def create_water_landscape(floor, architectural, accent, disaster=False):
    cube("ground plane", (0, 0, -0.5), (60, 60, 1), floor)
    if disaster:
        cube("damaged settlement mass", (-7, 7, 2), (8, 9, 4), architectural, 0.2)
        cube("broken roof plane", (-7, 7, 4.4), (9, 9, 0.35), accent, 0.1)
        for x, y, h in ((2, 5, 5), (8, 11, 3), (-1, 14, 7)):
            cube("fractured cliff mass", (x, y, h * 0.5), (5, 7, h), architectural, 0.3)
        for x in (-20, -12, -4, 4, 12, 20):
            cube("floodwater band", (x, -6, 0.08), (6, 18, 0.15), accent)
    else:
        for x in range(-24, 25, 4):
            cube("parallel water plane band", (x, 2, 0.02), (3.6, 34, 0.08), accent)
        for x, y, h in ((-16, 13, 11), (-8, 17, 8), (8, 16, 10), (17, 12, 7)):
            sphere("distant coast or mountain mass", (x, y, h * 0.45), (5, 4, h), architectural)


def animate_environment_motion(spec, architecture, accent, scene, camera):
    """Make authored non-human action beats visible in the silent previs."""
    frame_limit = int(spec["frames"])

    def span(cue):
        start = max(1, min(frame_limit, int(cue["start_frame"]) + 1))
        end = max(start + 1, min(frame_limit, int(cue["end_frame"]) + 1))
        return start, end

    def key_location(obj, frame, location):
        obj.location = location
        obj.keyframe_insert(data_path="location", frame=frame)

    fissure = None
    for cue in spec.get("environment_motion", []):
        kind = cue["kind"]
        start, end = span(cue)
        duration = max(2, end - start)
        if kind == "lightning_flash":
            bpy.ops.object.light_add(type="AREA", location=(0, 0, 18))
            flash = bpy.context.object
            flash.name = "one authored lightning flash"
            flash.data.shape = "DISK"
            flash.data.size = 18
            flash.data.energy = 0
            flash.data.keyframe_insert(data_path="energy", frame=max(1, start - 1))
            flash.data.energy = 2600
            flash.data.keyframe_insert(data_path="energy", frame=start)
            flash.data.energy = 0
            flash.data.keyframe_insert(data_path="energy", frame=min(end, start + 4))
        elif kind == "ground_tremor":
            pulse_end = min(end, start + 4)
            frames = list(range(start, pulse_end + 1))
            if pulse_end < frame_limit:
                frames.append(pulse_end + 1)
            base_locations = {}
            for frame in frames:
                scene.frame_set(frame)
                base_locations[frame] = camera.location.copy()
            for index, frame in enumerate(frames):
                camera.location = base_locations[frame]
                if frame <= pulse_end:
                    camera.location.x += (0.08, -0.08, 0.05, -0.04, 0.0)[index]
                camera.keyframe_insert(data_path="location", frame=frame)
        elif kind == "roof_tile_fall":
            for index, (x, y) in enumerate(((-9.0, 4.4), (-7.0, 4.1), (-5.2, 5.2))):
                tile = cube(f"falling roof tile proxy {index + 1}", (x, y, 4.66),
                            (0.95, 1.05, 0.16), accent, 0.025)
                tile.rotation_euler[1] = (index - 1) * 0.04
                tile.keyframe_insert(data_path="location", frame=start)
                tile.keyframe_insert(data_path="rotation_euler", frame=start)
                fall = min(end, start + max(2, round(duration * (0.35 + index * 0.08))))
                tile.location = (x + 0.15 * (index - 1), y - 0.5, 3.9)
                tile.rotation_euler[1] += 0.6
                tile.keyframe_insert(data_path="location", frame=fall)
                tile.keyframe_insert(data_path="rotation_euler", frame=fall)
                tile.location = (x + 0.25 * (index - 1), y - 1.4, 0.28)
                tile.rotation_euler[1] += 0.8
                tile.keyframe_insert(data_path="location", frame=end)
                tile.keyframe_insert(data_path="rotation_euler", frame=end)
        elif kind == "dust_plume":
            for index, (dx, dy, height) in enumerate(((-0.6, 0, 0.55), (0, 0.3, 0.8), (0.7, 0, 0.62))):
                plume = sphere(f"settling dust proxy {index + 1}", (-7 + dx, 2 + dy, height),
                               (0.08, 0.08, 0.08), accent)
                plume.keyframe_insert(data_path="scale", frame=start)
                plume.scale = (0.8 + 0.15 * index, 0.55, 0.4 + 0.1 * index)
                plume.location.z += height
                plume.keyframe_insert(data_path="scale", frame=min(end, start + max(2, duration // 2)))
                plume.keyframe_insert(data_path="location", frame=min(end, start + max(2, duration // 2)))
                plume.scale = (0.34, 0.25, 0.18)
                plume.keyframe_insert(data_path="scale", frame=end)
        elif kind == "water_surge":
            # A broad, low-poly wave front travels toward the shore in one direction.
            for index, (y, height) in enumerate(((15.0, 5.0), (18.5, 3.4))):
                wave = cube(f"advancing water front proxy {index + 1}", (0, y, height / 2),
                            (34, 0.75, height), architecture, 0.18)
                key_location(wave, start, (0, y, height / 2))
                key_location(wave, end, (0, -3.5 + index * 2.0, height / 2))
        elif kind == "mountain_fracture":
            fissure = cube("single visible mountain fissure proxy", (3.8, 7.2, 5.5),
                           (0.16, 8.0, 0.12), accent)
            fissure.rotation_euler[1] = -0.35
            fissure.scale.z = 0.05
            fissure.keyframe_insert(data_path="scale", frame=start)
            fissure.scale.z = 1.0
            fissure.keyframe_insert(data_path="scale", frame=end)
        elif kind == "rock_slab_slide":
            if fissure is None:
                fissure = cube("single visible mountain fissure proxy", (3.8, 7.2, 5.5),
                               (0.16, 8.0, 0.12), accent)
            slab = cube("one sliding rock slab proxy", (4.0, 7.2, 5.5),
                        (4.0, 5.0, 0.55), architecture, 0.12)
            slab.rotation_euler[1] = -0.15
            slab.keyframe_insert(data_path="location", frame=start)
            slab.keyframe_insert(data_path="rotation_euler", frame=start)
            slab.location = (6.2, 6.0, 2.6)
            slab.rotation_euler[1] = 0.32
            slab.keyframe_insert(data_path="location", frame=end)
            slab.keyframe_insert(data_path="rotation_euler", frame=end)
        elif kind == "descending_light_trails":
            for index, x in enumerate((-8.0, 8.0)):
                trail = cylinder(f"descending light trail proxy {index + 1}",
                                 (x, 12, 0), 0.22, 8.0, accent, 10)
                key_location(trail, start, (x, 12, 18))
                key_location(trail, end, (x * 0.7, 12, 4.5))


def create_interior(floor, architectural):
    cube("single room floor", (0, 0, -0.2), (24, 28, 0.4), floor)
    cube("back wall", (0, 13.8, 5), (24, 0.4, 10), architectural)
    for side in (-1, 1):
        cube("side wall", (side * 11.8, 0, 4), (0.4, 28, 8), architectural)


def character_proxy(prefix, actor, floor_mat, accent_mat, end_frame):
    x, y = actor["x"], actor["y"]
    z = float(actor.get("z", 0.0))
    seated = actor.get("pose") == "seated"
    created = set(bpy.data.objects)
    if seated:
        pelvis_z, shoulder_z, head_z = z + 1.13, z + 1.72, z + 2.28
        sphere(prefix + " torso proxy", (x, y, shoulder_z), (0.48, 0.31, 0.68), floor_mat)
        # Keep the human silhouette brighter than the throne/backdrop so a
        # seated speaker cannot visually disappear into the set blockout.
        sphere(prefix + " head proxy", (x, y - 0.03, head_z), (0.27, 0.27, 0.34), floor_mat)
        beam(prefix + " left arm proxy", (x - 0.35, y - 0.04, z + 2.05), (x - 0.5, y - 0.48, z + 1.42), 0.14, floor_mat)
        beam(prefix + " right arm proxy", (x + 0.35, y - 0.04, z + 2.05), (x + 0.5, y - 0.48, z + 1.42), 0.14, floor_mat)
        beam(prefix + " bent leg proxy", (x - 0.2, y - 0.1, pelvis_z), (x - 0.2, y - 0.65, z + 0.55), 0.16, floor_mat)
        beam(prefix + " bent leg proxy", (x + 0.2, y - 0.1, pelvis_z), (x + 0.2, y - 0.65, z + 0.55), 0.16, floor_mat)
    else:
        sphere(prefix + " torso proxy", (x, y, z + 1.28), (0.5, 0.32, 0.78), floor_mat)
        sphere(prefix + " head proxy", (x, y, z + 2.2), (0.29, 0.29, 0.36), floor_mat)
        for side in (-1, 1):
            beam(prefix + " arm proxy", (x + side * 0.34, y, z + 1.75), (x + side * 0.42, y - 0.03, z + 0.9), 0.14, floor_mat)
            beam(prefix + " leg proxy", (x + side * 0.2, y, z + 0.85), (x + side * 0.23, y - 0.03, z + 0.12), 0.17, floor_mat)
    if actor.get("pose") == "flying" or actor.get("path"):
        for idx, (dx, dy, sx) in enumerate(((-0.62, 0.18, 0.68), (0, 0.36, 0.88), (0.62, 0.18, 0.68))):
            sphere(prefix + f" cloud proxy {idx + 1}", (x + dx, y + dy, z + 0.22),
                   (sx, 0.42, 0.2), accent_mat)
    obj = bpy.data.objects.get(prefix + " torso proxy")
    if obj:
        # The proxy faces the center aisle in the council hall; elsewhere it faces the camera.
        if x < -1:
            obj.rotation_euler[2] = math.pi / 2
        elif x > 1:
            obj.rotation_euler[2] = -math.pi / 2
    created = [obj for obj in bpy.data.objects if obj not in created]
    root = bpy.data.objects.new(prefix + " blocking root", None)
    bpy.context.collection.objects.link(root)
    for obj in created:
        obj.parent = root
        obj.matrix_parent_inverse = root.matrix_world.inverted()
    start = Vector((x, y, z))
    root.location = (0, 0, 0)
    root.keyframe_insert(data_path="location", frame=1)
    for point in actor.get("path", []):
        destination = Vector((point["x"], point["y"], point["z"]))
        root.location = destination - start
        root.keyframe_insert(data_path="location", frame=max(1, int(point["frame"])))
    if actor.get("path"):
        root.location = Vector((actor["path"][-1]["x"], actor["path"][-1]["y"], actor["path"][-1]["z"])) - start
        root.keyframe_insert(data_path="location", frame=end_frame)
    instances = max(1, int(actor.get("instances", 1)))
    if instances > 1:
        # The group remains one bound asset; its silhouettes are a compact proxy cluster.
        for idx, offset in enumerate(range(1, instances)):
            group = bpy.data.objects.new(prefix + f" group member {idx + 2}", None)
            bpy.context.collection.objects.link(group)
            group.location = (0, 0, 0)
            group.parent = root
            group.location = ((idx - (instances - 2) / 2) * 0.9, 0.25, 0)
            # Keep a readable group outline with lightweight torso/head stand-ins.
            sphere(prefix + f" group torso {idx + 2}", (x + (idx - (instances - 2) / 2) * 0.9, y + 0.25, z + 1.25),
                   (0.36, 0.27, 0.64), floor_mat).parent = root
            sphere(prefix + f" group head {idx + 2}", (x + (idx - (instances - 2) / 2) * 0.9, y + 0.25, z + 2.15),
                   (0.23, 0.23, 0.3), floor_mat).parent = root
    return (x, y, z + 1.55), root


def camera_path(scene, camera, spec, actor_centers):
    shot_camera = spec.get("camera", {})
    lens = max(24.0, min(100.0, float(shot_camera.get("lens_mm", 50))))
    camera.data.lens = lens
    cast = spec.get("cast", [])
    by_id = {actor["id"]: actor_centers[i] for i, actor in enumerate(cast)}
    dialogue = sorted(spec.get("dialogue_events", []), key=lambda x: x.get("start_frame", 0))
    dialogue_actor_by_frame = {int(item.get("start_frame", 0)) + 1: next(
        (actor for actor in cast if actor["id"] == item["asset_id"]), None
    ) for item in dialogue}
    # Aim dialogue coverage at a face/eye-height target, not the torso proxy
    # center.  At a seated throne this distinction is enough to crop the
    # speaker's head with a 65 mm lens while the old center-only gate passed.
    focus_events = [(int(item.get("start_frame", 0)) + 1,
                     (by_id[item["asset_id"]][0], by_id[item["asset_id"]][1],
                      by_id[item["asset_id"]][2] + 0.65))
                    for item in dialogue if item.get("asset_id") in by_id]
    if focus_events:
        targets = focus_events
    elif len(cast) == 1:
        targets = [(1, actor_centers[0])]
    elif cast and spec.get("scene_kind") == "hall":
        targets = [(1, (0, 4, 3.2))]
    elif cast:
        moving_cast = [actor for actor in cast if actor.get("path")]
        if moving_cast:
            route_frames = sorted({1, int(spec["frames"]), *[
                max(1, min(int(spec["frames"]), int(point["frame"])))
                for actor in moving_cast for point in actor["path"]
            ]})

            def actor_position(point):
                position = point.get("position", point)
                return (position["x"], position["y"], position.get("z", 0.0))

            def position_at(actor, frame):
                start = {"frame": 1, "x": actor["x"], "y": actor["y"], "z": actor.get("z", 0.0)}
                points = [start, *actor.get("path", [])]
                if points[-1]["frame"] < int(spec["frames"]):
                    points.append({"frame": int(spec["frames"]), **dict(zip(("x", "y", "z"), actor_position(points[-1])))})
                for left, right in zip(points, points[1:]):
                    left_frame = int(left["frame"])
                    right_frame = int(right["frame"])
                    if frame <= right_frame:
                        left_pos = actor_position(left)
                        right_pos = actor_position(right)
                        ratio = (frame - left_frame) / max(1, right_frame - left_frame)
                        return tuple(a + (b - a) * ratio for a, b in zip(left_pos, right_pos))
                final = points[-1]
                return actor_position(final)

            targets = []
            for route_frame in route_frames:
                positions = [position_at(actor, route_frame) for actor in cast]
                targets.append((route_frame, tuple(sum(p[axis] for p in positions) / len(positions)
                                                   + (1.55 if axis == 2 else 0.0)
                                                   for axis in range(3))))
        else:
            x = sum(p[0] for p in actor_centers) / len(actor_centers)
            y = sum(p[1] for p in actor_centers) / len(actor_centers)
            targets = [(1, (x, y, 2.0))]
    else:
        cue_kinds = {cue.get("kind") for cue in spec.get("environment_motion", [])}
        if "roof_tile_fall" in cue_kinds:
            targets = [(1, (-7.0, 5.5, 3.7))]
        elif "mountain_fracture" in cue_kinds or "rock_slab_slide" in cue_kinds:
            targets = [(1, (2.0, 8.0, 5.0))]
        elif "water_surge" in cue_kinds:
            targets = [(1, (0.0, 8.0, 2.5))]
        elif "descending_light_trails" in cue_kinds:
            targets = [(1, (0.0, 12.0, 8.0))]
        else:
            targets = [(1, (0, 0, 2.0))]
    start_frame, end_frame = 1, int(spec["frames"])
    move = str(shot_camera.get("movement", "")).lower()
    size = str(shot_camera.get("size", "")).lower()
    if not cast and ("tilt" in move or "俯仰" in move) and "descending_light_trails" in {
            cue.get("kind") for cue in spec.get("environment_motion", [])}:
        targets = [(start_frame, (0.0, 12.0, 15.0)), (end_frame, (0.0, 12.0, 2.5))]
    if (spec["scene_kind"] == "hall" and len(cast) == 1 and not dialogue
            and ("wide" in size or "全景" in size)):
        # A hall-establishing shot should show the room plan and the throne,
        # not crop to a tiny fragment of the rear wall behind the emperor.
        targets = [(1, (0, 4, 3.2))]
    if not focus_events and len(targets) == 1:
        targets.append((end_frame, targets[0][1]))
    if (spec["scene_kind"] == "hall" and len(cast) > 1
            and ("wide" in size or "全景" in size)):
        # A multi-row council master must start outside the near seating row.
        # The ordinary 17 m wide-shot default crops the nearest row even with
        # a wide lens, which either hides actors or encourages empty-room cuts.
        distance = 29.0
    elif "medium" in size or "中景" in size:
        distance = 6.8 if "close" in size else 9.0
    elif "close" in size or "特写" in size:
        # A portrait close-up must retain the head and enough shoulder line to
        # read the performance. A fixed 3.8 m default with an 85 mm lens made
        # seated speakers too tight and forced a low-angle crop.
        distance = max(3.8, lens * 0.08)
    elif "wide" in size or "全景" in size:
        distance = 17.0
    else:
        distance = 10.0
    cue_kinds = {cue.get("kind") for cue in spec.get("environment_motion", [])}
    if "roof_tile_fall" in cue_kinds:
        distance = min(distance, 14.0)
    elif "mountain_fracture" in cue_kinds or "rock_slab_slide" in cue_kinds:
        distance = max(distance, 25.0)
    elif "water_surge" in cue_kinds or "descending_light_trails" in cue_kinds:
        distance = max(distance, 24.0)
    if cast and not focus_events and len(cast) > 1:
        # Ensemble masters must be framed from the authored group bounds, not
        # from the generic single-subject shot-size default.  Otherwise a
        # medium-wide tracking shot can crop the outer speakers/visitors even
        # though the camera follows the group's centroid.
        route_frames = {1, end_frame, *[
            max(1, min(end_frame, int(point["frame"])))
            for actor in cast for point in actor.get("path", [])
        ]}

        def actor_x_at(actor, frame):
            points = [{"frame": 1, "x": actor["x"]}, *actor.get("path", [])]
            points.sort(key=lambda point: int(point["frame"]))
            for left, right in zip(points, points[1:]):
                lf, rf = int(left["frame"]), int(right["frame"])
                if frame <= rf:
                    ratio = (frame - lf) / max(1, rf - lf)
                    return float(left["x"]) + (float(right["x"]) - float(left["x"])) * ratio
            return float(points[-1]["x"])

        half_span = 0.0
        for route_frame in route_frames:
            xs = [actor_x_at(actor, route_frame) for actor in cast]
            centroid = sum(xs) / len(xs)
            half_span = max(half_span, *(abs(x - centroid) for x in xs))
        # Blender's default horizontal sensor is 36 mm. Keep the full group
        # inside roughly 72% of frame width, with extra room for bodies and
        # the small lateral tracking arc. This remains a conservative lower
        # bound; the per-frame projection gate below is still authoritative.
        half_fov = math.atan(36.0 / (2.0 * lens))
        lateral_arc = 0.8 if any(x in move for x in ("track", "跟拍", "tracking")) else 0.0
        distance = max(distance, (half_span + 0.65 + lateral_arc) / (math.tan(half_fov) * 0.72))
    for index, (frame, target_value) in enumerate(targets):
        target = Vector(target_value)
        phase = index / max(1, len(targets) - 1)
        focus_actor = dialogue_actor_by_frame.get(int(frame))
        if focus_actor and spec["scene_kind"] == "hall":
            actor = focus_actor
            sign = 1 if actor["x"] < -0.1 else -1
            d = distance
            if "push" in move or "dolly in" in move or "推进" in move:
                d = distance + 1.8 - phase * 1.8
            elif "pull" in move or "dolly out" in move or "拉远" in move:
                d = distance - 1.0 + phase * 2.2
            lateral = (phase - 0.5) * 0.4 if any(x in move for x in ("track", "跟拍", "tracking")) else 0.0
            if "close" in size and abs(actor["x"]) < 0.1 and not lateral:
                lateral = 0.9  # a subtle three-quarter view separates the speaker from the throne back
            target = Vector(target_value)
            eye_height = float(actor.get("z", 0.0)) + 2.05
            if abs(actor["x"]) < 0.1:
                location = Vector((actor["x"] + lateral, actor["y"] - d, eye_height))
            else:
                location = Vector((actor["x"] + sign * d, actor["y"] - 1.6 + lateral, eye_height))
        elif (spec["scene_kind"] == "hall" and len(cast) == 1 and not dialogue
                and ("wide" in size or "全景" in size)):
            target = Vector(target_value)
            d = 29.0
            if "push" in move or "dolly in" in move or "推进" in move:
                d = 31.0 - phase * 2.0
            elif "pull" in move or "dolly out" in move or "拉远" in move:
                d = 27.0 + phase * 2.0
            location = target + Vector((0, -d, max(8.0, d * 0.32)))
        elif spec["scene_kind"] == "hall" and len(cast) == 1:
            actor = cast[0]
            # Hold the camera on the aisle side at seated eye level. The old
            # 3.7 m offset with a 65 mm lens cropped the proxy head and most of
            # the room, accidentally reproducing an empty-looking close crop.
            sign = 1 if actor["x"] < 0 else -1
            d = distance
            if "push" in move or "dolly in" in move or "推进" in move:
                d = distance + 1.8 - phase * 1.8
            elif "pull" in move or "dolly out" in move or "拉远" in move:
                d = distance - 1.0 + phase * 2.2
            lateral = (phase - 0.5) * 0.55 if any(x in move for x in ("track", "跟拍", "tracking")) else 0.0
            if "close" in size and abs(actor["x"]) < 0.1 and not lateral:
                lateral = 0.9  # preserve a readable face silhouette against the central throne
            target = Vector((actor["x"], actor["y"], 1.72 if actor.get("pose") == "seated" else 1.55))
            eye_height = float(actor.get("z", 0.0)) + 2.05
            if abs(actor["x"]) < 0.1:
                # A centered throne subject must be filmed from the central
                # aisle. A lateral offset crosses the opaque side wall and
                # leaves an apparently empty room despite correct actor refs.
                location = Vector((actor["x"] + lateral, actor["y"] - d, eye_height))
            else:
                location = Vector((actor["x"] + sign * d, actor["y"] - 1.6 + lateral, eye_height))
        elif not cast and ("tilt" in move or "俯仰" in move) and "descending_light_trails" in cue_kinds:
            location = Vector((0.0, -22.0, 17.0))
        elif not cast and "roof_tile_fall" in cue_kinds:
            location = Vector((target.x, target.y - distance, target.z + 4.8))
        elif not cast and ("mountain_fracture" in cue_kinds or "rock_slab_slide" in cue_kinds):
            location = Vector((target.x, target.y - distance, target.z + 9.0))
        elif not cast and "water_surge" in cue_kinds:
            location = Vector((target.x, target.y - distance, target.z + 10.0))
        elif "push" in move or "dolly in" in move or "推进" in move:
            start_distance = distance + 2.0
            d = start_distance if index == 0 else max(3.5, distance - 0.7)
            location = target + Vector((0, -d, max(2.2, d * 0.34)))
        elif "pull" in move or "dolly out" in move or "拉远" in move:
            d = distance if index == 0 else distance + 2.5
            location = target + Vector((0, -d, max(2.2, d * 0.34)))
        elif "track" in move or "follow" in move or "跟拍" in move or "tracking" in move:
            d = distance
            side = (phase - 0.5) * 1.3
            location = target + Vector((side, -d, max(2.5, d * 0.25)))
        elif "pan" in move or "摇" in move:
            d = distance
            side = (phase - 0.5) * 2.2
            location = target + Vector((side, -d, max(2.3, d * 0.28)))
        else:
            d = distance
            location = target + Vector((0, -d, max(2.2, d * 0.3)))
        frame = min(end_frame, max(start_frame, frame))
        camera.location = location
        camera.rotation_euler = (target - location).to_track_quat("-Z", "Y").to_euler()
        camera.keyframe_insert(data_path="location", frame=frame)
        camera.keyframe_insert(data_path="rotation_euler", frame=frame)
    if focus_events:
        if targets[0][0] > start_frame:
            camera.keyframe_insert(data_path="location", frame=start_frame)
            camera.keyframe_insert(data_path="rotation_euler", frame=start_frame)
        camera.keyframe_insert(data_path="location", frame=end_frame)
        camera.keyframe_insert(data_path="rotation_euler", frame=end_frame)
    # Blender 5.2 stores keyframes in layered action channel bags instead of
    # exposing Action.fcurves. Default keyframe handles already use smooth
    # Bezier interpolation, so avoid depending on the removed legacy API.


def setup_lights():
    world = bpy.data.worlds.new("neutral gray previs world")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.24, 0.24, 0.24, 1)
    world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.55
    bpy.context.scene.world = world
    for name, position, energy, size in (("broad key", (1, -7, 13), 700, 10),
                                         ("soft fill", (-9, 3, 10), 300, 8)):
        bpy.ops.object.light_add(type="AREA", location=position)
        light = bpy.context.object
        light.name = name
        light.data.energy = energy
        light.data.shape = "DISK"
        light.data.size = size
        light.rotation_euler = (Vector((0, 0, 3)) - light.location).to_track_quat("-Z", "Y").to_euler()


def validate_cast_projection(scene, camera, actor_roots, centers, frames):
    if not actor_roots:
        return
    for frame in range(1, int(frames) + 1):
        scene.frame_set(frame)
        depsgraph = bpy.context.evaluated_depsgraph_get()
        evaluated_camera = camera.evaluated_get(depsgraph)
        camera_origin = evaluated_camera.matrix_world.translation
        for index, root in enumerate(actor_roots):
            evaluated = root.evaluated_get(depsgraph)
            delta = evaluated.matrix_world.translation
            center = Vector(centers[index]) + delta
            head_world = center + Vector((0, 0, 0.7))
            projected = world_to_camera_view(scene, camera, center)
            head = world_to_camera_view(scene, camera, head_world)
            if (projected.z <= 0 or head.z <= 0
                    or not (0.015 <= projected.x <= 0.985 and 0.015 <= projected.y <= 0.985)
                    or not (0.015 <= head.x <= 0.985 and 0.015 <= head.y <= 0.985)):
                raise RuntimeError(
                    f"Registered actor proxy {index + 1} or its head leaves the camera frame at frame {frame} "
                    f"(body=({projected.x:.3f},{projected.y:.3f},{projected.z:.2f}), "
                    f"head=({head.x:.3f},{head.y:.3f},{head.z:.2f}), "
                    f"camera={tuple(round(float(v), 2) for v in camera_origin)}); "
                    "revise blocking or framing before sending this guide to H3."
                )
            if abs(head.y - projected.y) < 0.012:
                raise RuntimeError(
                    f"Registered actor proxy {index + 1} is too small to read at frame {frame}; "
                    "revise camera distance or blocking."
                )
            ray = head_world - camera_origin
            distance = ray.length
            hit, _location, _normal, _face, hit_object, _matrix = scene.ray_cast(
                depsgraph, camera_origin, ray.normalized(), distance=distance + 0.05
            )
            actor_prefix = root.name.removesuffix(" blocking root")
            if not hit or not hit_object.name.startswith(actor_prefix):
                obstacle = hit_object.name if hit else "no visible registered body"
                raise RuntimeError(
                    f"Registered actor proxy {index + 1} is occluded by {obstacle} at frame {frame}; "
                    "the scene geometry or blocking hides a required person."
                )


def main():
    args = arguments()
    spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    out = Path(args.spec).resolve().parent
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for datablocks in (bpy.data.meshes, bpy.data.curves, bpy.data.cameras, bpy.data.lights, bpy.data.materials):
        for block in list(datablocks):
            if block.users == 0:
                datablocks.remove(block)

    floor = material("matte gray structure", (0.35, 0.35, 0.35))
    architecture = material("mid gray architectural mass", (0.22, 0.22, 0.22))
    accent = material("light gray staging anchors", (0.5, 0.5, 0.5))
    proxy = material("neutral gray character proxies", (0.9, 0.9, 0.9))
    if spec["scene_kind"] == "hall":
        create_hall(floor, architecture, accent)
    elif spec["scene_kind"] == "celestial_exterior":
        create_celestial_exterior(floor, architecture, accent)
    elif spec["scene_kind"] == "water":
        create_water_landscape(floor, architecture, accent)
    elif spec["scene_kind"] == "disaster":
        create_water_landscape(floor, architecture, accent, disaster=True)
    elif spec["scene_kind"] == "interior":
        create_interior(floor, architecture)
    else:
        cube("neutral landscape ground", (0, 0, -0.5), (40, 40, 1), floor)
        for x, y, h in ((-11, 9, 5), (-4, 14, 8), (6, 12, 7), (13, 8, 4)):
            sphere("distant neutral mass", (x, y, h / 2), (5, 4, h), architecture)

    cast = spec.get("cast", [])
    centers, actor_roots = [], []
    for i, actor in enumerate(cast, 1):
        center, root = character_proxy(f"registered proxy {i}", actor, proxy, accent, spec["frames"])
        centers.append(center)
        actor_roots.append(root)
    for i, _prop in enumerate(spec.get("props", []), 1):
        actor = cast[0] if cast else {"x": 0, "y": 0}
        cube(f"registered prop blockout {i}", (actor["x"] + 0.55, actor["y"] - 0.4, 1.18),
             (0.25, 0.12, 0.62), accent, 0.025)

    bpy.ops.object.camera_add(location=(0, -20, 8))
    camera = bpy.context.object
    camera.name = "single authored shot camera"
    bpy.context.scene.camera = camera
    scene = bpy.context.scene
    camera_path(scene, camera, spec, centers)
    validate_cast_projection(scene, camera, actor_roots, centers, spec["frames"])
    setup_lights()
    animate_environment_motion(spec, architecture, accent, scene, camera)

    engine_items = scene.render.bl_rna.properties["engine"].enum_items.keys()
    scene.render.engine = "BLENDER_EEVEE" if "BLENDER_EEVEE" in engine_items else "BLENDER_EEVEE_NEXT"
    scene.render.resolution_x = spec["width"]
    scene.render.resolution_y = spec["height"]
    scene.render.resolution_percentage = 100
    scene.render.fps = spec["fps"]
    scene.frame_start = 1
    scene.frame_end = spec["frames"]
    scene.render.image_settings.media_type = "VIDEO"
    scene.render.image_settings.file_format = "FFMPEG"
    scene.render.ffmpeg.format = "MPEG4"
    scene.render.ffmpeg.codec = "H264"
    scene.render.ffmpeg.constant_rate_factor = "MEDIUM"
    scene.render.ffmpeg.ffmpeg_preset = "REALTIME"
    scene.render.filepath = str(out / "guide")
    scene.render.image_settings.color_mode = "RGB"
    scene.render.film_transparent = False
    scene.view_settings.view_transform = "Standard"
    scene.render.image_settings.color_depth = "8"
    scene.render.threads_mode = "FIXED"
    scene.render.threads = spec["threads"]
    scene.render.use_file_extension = True
    scene.camera.data.dof.use_dof = False
    scene.render.resolution_percentage = 100
    bpy.ops.wm.save_as_mainfile(filepath=str(out / "scene.blend"))
    bpy.ops.render.render(animation=True)
    # Save a full-resolution contact frame for quick workbench inspection.
    scene.frame_set(1)
    scene.render.image_settings.media_type = "IMAGE"
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = str(out / "frame_0001.png")
    bpy.ops.render.render(write_still=True)
    rendered = sorted(out.glob("guide*.mp4"))
    if len(rendered) == 1 and rendered[0] != out / "guide.mp4":
        os.replace(rendered[0], out / "guide.mp4")
    if not (out / "guide.mp4").is_file():
        raise RuntimeError("Blender did not produce the expected single guide MP4")
    print("BLENDER_PREVIS_RENDERED", out / "guide.mp4")


if __name__ == "__main__":
    main()
