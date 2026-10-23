#!/usr/bin/env python3
"""Render a silent grayscale Blender blockout still for a v5 Ref2VA shot.

The guide is intentionally crude: it fixes only the number of bodies, their
screen positions, poses, props and camera. FastH3 must take identity, costume,
lighting and materials from the approved picture references, never from this
gray proxy.

Run with Blender:
  blender --background --factory-startup --python scripts/render_v5_previs.py -- \
      --spec projects/.../v5/previs_specs.json --shot A13 --out .../A13.png
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector


def args():
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument('--spec', required=True)
    parser.add_argument('--shot', required=True)
    parser.add_argument('--out', required=True)
    return parser.parse_args(argv)


def mat(name, value):
    m = bpy.data.materials.new(name)
    m.diffuse_color = (value, value, value, 1.0)
    m.use_nodes = False
    return m


def cube(name, loc, dims, material, bevel=0.0):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc)
    o = bpy.context.object
    o.name = name
    o.dimensions = dims
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    o.data.materials.append(material)
    if bevel:
        mod = o.modifiers.new('soft', 'BEVEL')
        mod.width = bevel
        mod.segments = 2
    return o


def cyl(name, loc, radius, depth, material, vertices=12):
    bpy.ops.mesh.primitive_cylinder_add(vertices=vertices, radius=radius, depth=depth, location=loc)
    o = bpy.context.object
    o.name = name
    o.data.materials.append(material)
    return o


def sphere(name, loc, scale, material, segments=16, rings=10):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=segments, ring_count=rings, radius=1, location=loc)
    o = bpy.context.object
    o.name = name
    o.scale = scale
    o.data.materials.append(material)
    return o


def beam(name, start, end, radius, material):
    a, b = Vector(start), Vector(end)
    delta = b - a
    o = cyl(name, (a + b) * 0.5, radius, delta.length, material)
    o.rotation_euler = delta.to_track_quat('Z', 'Y').to_euler()
    return o


def limb(name, start, end, radius, material):
    return beam(name, start, end, radius, material)


# ---------------------------------------------------------------- scenes
def build_room(floor, wall, accent):
    cube('room floor', (0, 0, -0.12), (10, 12, 0.24), floor)
    cube('back wall', (0, 5.8, 2.6), (10, 0.2, 5.2), wall)
    cube('left wall', (-4.9, 0, 2.6), (0.2, 12, 5.2), wall)
    cube('right wall', (4.9, 0, 2.6), (0.2, 12, 5.2), wall)
    # paper window on camera-right, door opening back-left
    cube('window frame', (3.6, 3.2, 2.0), (1.8, 0.08, 2.2), accent)
    cube('door frame', (-2.8, 4.6, 2.0), (1.4, 0.12, 3.2), accent)
    cube('bed platform', (0, 2.2, 0.35), (2.2, 3.4, 0.7), accent, 0.04)
    cube('bed mattress', (0, 2.2, 0.78), (2.0, 3.1, 0.25), floor, 0.03)
    cube('bed headboard', (0, 3.95, 1.0), (2.2, 0.12, 1.4), accent, 0.03)
    cube('bedside table', (1.7, 2.4, 0.5), (0.6, 0.6, 1.0), accent, 0.02)
    cyl('oil lamp base', (1.7, 2.4, 1.08), 0.09, 0.18, accent)
    sphere('oil lamp glow proxy', (1.7, 2.4, 1.22), (0.12, 0.12, 0.16), floor)


def build_hall(floor, wall, accent):
    cube('hall floor', (0, 0, -0.12), (22, 28, 0.24), floor)
    cube('rear wall', (0, 13.5, 4.5), (22, 0.3, 9), wall)
    for side in (-1, 1):
        cube('side wall', (side * 10.8, 0, 4.5), (0.3, 27, 9), wall)
        for y in (-8, -3, 2, 7, 12):
            cyl('red column proxy', (side * 6.2, y, 4.5), 0.32, 9, accent, 16)
    # raised dais and judge's desk at the rear
    cube('dais lower', (0, 9.0, 0.25), (8, 5.0, 0.5), accent, 0.05)
    cube('dais upper', (0, 9.0, 0.65), (6, 3.6, 0.3), accent, 0.04)
    cube('judge desk', (0, 8.0, 1.05), (3.6, 1.1, 0.9), accent, 0.05)
    cube('desk top', (0, 8.0, 1.55), (3.9, 1.25, 0.12), floor, 0.02)
    # two candidate desks near the front
    for x in (-3.2, 3.2):
        cube('exam desk', (x, 1.0, 0.85), (2.4, 1.0, 0.12), accent)
        for dx in (-1.0, 1.0):
            for dy in (-0.35, 0.35):
                cube('desk leg', (x + dx, 1.0 + dy, 0.4), (0.1, 0.1, 0.8), accent)
    # incense burner
    cyl('incense burner', (0, 5.0, 0.55), 0.35, 0.5, accent, 16)


def build_temple(floor, wall, accent):
    build_hall(floor, wall, accent)
    cube('gold screen', (0, 12.8, 4.0), (7.5, 0.2, 5.5), accent)
    for x in (-2.5, 2.5):
        cyl('lantern', (x, 6.5, 3.6), 0.16, 0.5, accent, 12)


def build_courtyard(floor, wall, accent):
    cube('courtyard floor', (0, 0, -0.12), (12, 14, 0.24), floor)
    cube('back house', (0, 6.0, 2.4), (12, 0.4, 4.8), wall)
    cube('left wall', (-5.9, 0, 1.8), (0.3, 14, 3.6), wall)
    cube('right wall', (5.9, 0, 1.8), (0.3, 14, 3.6), wall)
    cube('gate posts left', (-2.0, 5.0, 2.0), (0.35, 0.35, 4.0), accent)
    cube('gate posts right', (2.0, 5.0, 2.0), (0.35, 0.35, 4.0), accent)
    cube('gate lintel', (0, 5.0, 3.8), (4.3, 0.4, 0.4), accent)
    cyl('gate lantern', (1.6, 4.7, 2.7), 0.13, 0.45, accent, 12)
    cube('door step', (0, 4.6, 0.1), (4.4, 1.0, 0.2), accent)


def build_lane(floor, wall, accent):
    cube('lane ground', (0, 0, -0.12), (12, 30, 0.24), floor)
    cube('lane stone strip', (0, 0, 0.02), (3.2, 30, 0.04), accent)
    for side in (-1, 1):
        for y in (-9, -3, 3, 9, 15):
            cube('lane house mass', (side * 5.8, y, 2.2), (3.2, 3.0, 4.4), wall)
            cube('lane eave', (side * 4.5, y, 4.3), (1.0, 3.2, 0.2), accent)
    cube('lane distant gate', (0, 16, 2.0), (6, 0.4, 4), accent)


def build_road(floor, wall, accent):
    cube('road ground', (0, 0, -0.2), (40, 50, 0.4), floor)
    cube('road strip', (0, 0, 0.01), (5.0, 50, 0.04), accent)
    for side in (-1, 1):
        for y in (-12, -4, 4, 12, 20):
            cyl('bare tree trunk', (side * 7.5, y, 2.0), 0.18, 4.0, wall, 8)
            sphere('bare tree crown', (side * 7.5, y, 4.3), (1.2, 1.2, 1.4), wall, 10, 6)
    cube('distant gate left', (-3, 24, 2.0), (0.5, 0.5, 4), accent)
    cube('distant gate right', (3, 24, 2.0), (0.5, 0.5, 4), accent)
    cube('distant gate lintel', (0, 24, 3.8), (6.5, 0.5, 0.4), accent)


def build_coffin_room(floor, wall, accent):
    cube('room floor', (0, 0, -0.12), (10, 12, 0.24), floor)
    cube('back wall', (0, 5.8, 2.6), (10, 0.2, 5.2), wall)
    cube('left wall', (-4.9, 0, 2.6), (0.2, 12, 5.2), wall)
    cube('right wall', (4.9, 0, 2.6), (0.2, 12, 5.2), wall)
    cube('window frame', (3.6, 3.2, 2.0), (1.8, 0.08, 2.2), accent)
    cube('door frame', (-2.8, 4.6, 2.0), (1.4, 0.12, 3.2), accent)
    # low open coffin in the same room
    cube('coffin base', (0, 2.3, 0.25), (2.1, 3.6, 0.5), accent, 0.04)
    cube('coffin left wall', (-1.0, 2.3, 0.8), (0.15, 3.6, 0.7), accent, 0.03)
    cube('coffin right wall', (1.0, 2.3, 0.8), (0.15, 3.6, 0.7), accent, 0.03)
    cube('coffin back wall', (0, 4.0, 0.8), (2.1, 0.15, 0.7), accent, 0.03)
    cube('coffin front rim', (0, 0.6, 0.55), (2.1, 0.15, 0.3), accent, 0.03)


SCENES = {
    'room': build_room,
    'hall': build_hall,
    'temple': build_temple,
    'courtyard': build_courtyard,
    'lane': build_lane,
    'road': build_road,
    'coffin_room': build_coffin_room,
}


# ---------------------------------------------------------------- actors
POSE = {
    'standing': {'pelvis': 0.50, 'torso': 0.64, 'head': 0.88, 'arms': (0.78, 0.50), 'legs': (0.50, 0.04)},
    'seated': {'pelvis': 0.28, 'torso': 0.47, 'head': 0.73, 'arms': (0.62, 0.40), 'legs': (0.28, 0.04)},
    'kneeling': {'pelvis': 0.22, 'torso': 0.40, 'head': 0.66, 'arms': (0.55, 0.35), 'legs': (0.22, 0.04)},
    'lying': {'pelvis': 0.18, 'torso': 0.18, 'head': 0.20, 'arms': (0.18, 0.12), 'legs': (0.18, 0.12)},
    'propped': {'pelvis': 0.28, 'torso': 0.38, 'head': 0.62, 'arms': (0.50, 0.34), 'legs': (0.24, 0.10)},
    'mounted': {'pelvis': 0.82, 'torso': 0.98, 'head': 1.24, 'arms': (1.10, 0.88), 'legs': (0.82, 0.52)},
}


def mannequin(prefix, actor, body_mat):
    """A jointed gray proxy. z is the floor, except seated actors where z is
    the seat surface (chair seat or bed top)."""
    h = float(actor.get('height', 1.75))
    x, y, z = float(actor['x']), float(actor['y']), float(actor.get('z', 0.0))
    pose = actor.get('pose', 'standing')

    def seg(name, a, b, r):
        limb(prefix + ' ' + name, a, b, r, body_mat)

    def head(px, py, pz):
        sphere(prefix + ' head', (px, py, pz), (0.105 * h, 0.115 * h, 0.135 * h), body_mat)

    if pose == 'lying':
        # body along +Y, head at the far end
        pelvis = (x, y, z + 0.15 * h)
        shoulder = (x, y + 0.30 * h, z + 0.17 * h)
        head(x, y + 0.48 * h, z + 0.20 * h)
        cube(prefix + ' torso', (x, y + 0.15 * h, z + 0.16 * h), (0.42, 0.43 * h, 0.24), body_mat, 0.05)
        for side in (-1, 1):
            seg('thigh', (x + side * 0.11, y - 0.02, z + 0.13 * h),
                (x + side * 0.13, y - 0.34 * h, z + 0.11 * h), 0.07 * h)
            seg('shin', (x + side * 0.13, y - 0.34 * h, z + 0.11 * h),
                (x + side * 0.14, y - 0.62 * h, z + 0.09 * h), 0.055 * h)
            seg('arm', (x + side * 0.22, y + 0.24 * h, z + 0.16 * h),
                (x + side * 0.25, y - 0.02 * h, z + 0.13 * h), 0.05 * h)
    elif pose == 'propped':
        # reclining against a pillow, torso lifted
        cube(prefix + ' torso', (x, y - 0.02 * h, z + 0.34 * h), (0.42, 0.26, 0.42 * h), body_mat, 0.05)
        head(x, y - 0.14 * h, z + 0.62 * h)
        for side in (-1, 1):
            seg('thigh', (x + side * 0.11, y + 0.02 * h, z + 0.14 * h),
                (x + side * 0.13, y - 0.28 * h, z + 0.12 * h), 0.07 * h)
            seg('shin', (x + side * 0.13, y - 0.28 * h, z + 0.12 * h),
                (x + side * 0.14, y - 0.58 * h, z + 0.10 * h), 0.055 * h)
            seg('arm', (x + side * 0.21, y - 0.02 * h, z + 0.44 * h),
                (x + side * 0.25, y + 0.12 * h, z + 0.20 * h), 0.05 * h)
    elif pose == 'seated':
        seat = z + 0.02 * h
        cube(prefix + ' torso', (x, y, seat + 0.25 * h), (0.42, 0.26, 0.48 * h), body_mat, 0.05)
        head(x, y, seat + 0.62 * h)
        for side in (-1, 1):
            seg('thigh', (x + side * 0.11, y, seat),
                (x + side * 0.13, y + 0.34 * h, seat), 0.075 * h)
            seg('shin', (x + side * 0.13, y + 0.34 * h, seat),
                (x + side * 0.14, y + 0.34 * h, seat - 0.42 * h), 0.06 * h)
            seg('arm', (x + side * 0.21, y, seat + 0.44 * h),
                (x + side * 0.24, y + 0.18 * h, seat + 0.10 * h), 0.05 * h)
    elif pose == 'kneeling':
        pelvis = z + 0.28 * h
        cube(prefix + ' torso', (x, y, pelvis + 0.24 * h), (0.42, 0.26, 0.48 * h), body_mat, 0.05)
        head(x, y, pelvis + 0.60 * h)
        for side in (-1, 1):
            seg('thigh', (x + side * 0.11, y, pelvis),
                (x + side * 0.13, y + 0.30 * h, z + 0.12 * h), 0.075 * h)
            seg('shin', (x + side * 0.13, y + 0.30 * h, z + 0.12 * h),
                (x + side * 0.14, y + 0.58 * h, z + 0.08 * h), 0.06 * h)
            seg('arm', (x + side * 0.21, y, pelvis + 0.42 * h),
                (x + side * 0.24, y + 0.18 * h, pelvis - 0.02 * h), 0.05 * h)
    elif pose == 'mounted':
        cube(prefix + ' pelvis', (x, y, z + 0.86 * h), (0.38, 0.30, 0.24 * h), body_mat, 0.05)
        cube(prefix + ' torso', (x, y, z + 1.08 * h), (0.40, 0.26, 0.36 * h), body_mat, 0.05)
        head(x, y, z + 1.34 * h)
        for side in (-1, 1):
            seg('thigh', (x + side * 0.17, y, z + 0.82 * h),
                (x + side * 0.28, y + 0.18 * h, z + 0.58 * h), 0.075 * h)
            seg('shin', (x + side * 0.28, y + 0.18 * h, z + 0.58 * h),
                (x + side * 0.29, y + 0.06 * h, z + 0.28 * h), 0.06 * h)
            seg('arm', (x + side * 0.21, y, z + 1.20 * h),
                (x + side * 0.26, y + 0.24 * h, z + 0.92 * h), 0.05 * h)
    else:  # standing
        pelvis = z + 0.52 * h
        cube(prefix + ' torso', (x, y, z + 0.67 * h), (0.42, 0.26, 0.30 * h), body_mat, 0.05)
        head(x, y, z + 0.91 * h)
        for side in (-1, 1):
            seg('thigh', (x + side * 0.11, y, pelvis),
                (x + side * 0.12, y + 0.02, z + 0.28 * h), 0.075 * h)
            seg('shin', (x + side * 0.12, y + 0.02, z + 0.28 * h),
                (x + side * 0.13, y + 0.03, z + 0.05 * h), 0.06 * h)
            seg('arm', (x + side * 0.21, y, z + 0.82 * h),
                (x + side * 0.25, y + 0.04, z + 0.52 * h), 0.05 * h)
    # a small nose wedge makes the body's facing direction legible
    heading = float(actor.get('heading', 0.0))
    sphere(prefix + ' nose', (x + math.sin(heading) * 0.10 * h,
                              y - math.cos(heading) * 0.10 * h,
                              z + (0.86 if pose in ('standing', 'kneeling') else 0.55 if pose == 'seated' else 0.20) * h),
           (0.025 * h, 0.025 * h, 0.025 * h), body_mat)


def horse(prefix, x, y, z=0.0, material=None):
    body = sphere(prefix + ' horse body', (x, y, z + 0.85), (0.45, 0.95, 0.32), material, 16, 10)
    beam(prefix + ' horse neck', (x, y + 0.55, z + 1.0), (x, y + 0.95, z + 1.35), 0.16, material)
    sphere(prefix + ' horse head', (x, y + 1.0, z + 1.38), (0.18, 0.28, 0.16), material)
    for dx in (-0.25, 0.25):
        for dy in (-0.5, 0.5):
            limb(prefix + ' horse leg', (x + dx, y + dy, z + 0.7),
                 (x + dx, y + dy, z + 0.05), 0.07, material)
    beam(prefix + ' horse tail', (x, y - 0.85, z + 0.95), (x, y - 1.15, z + 0.55), 0.06, material)


def prop(prefix, item, material):
    kind = item['kind']
    x, y, z = (float(item.get(k, 0.0)) for k in ('x', 'y', 'z'))
    if kind == 'chair':
        cube(prefix + ' seat', (x, y, z + 0.45), (0.6, 0.55, 0.08), material)
        cube(prefix + ' back', (x, y + 0.25, z + 0.85), (0.6, 0.08, 0.9), material)
        for dx in (-0.24, 0.24):
            for dy in (-0.2, 0.2):
                cube(prefix + ' leg', (x + dx, y + dy, z + 0.22), (0.07, 0.07, 0.44), material)
    elif kind == 'desk':
        cube(prefix + ' top', (x, y, z + 0.78), (2.2, 1.0, 0.1), material)
        for dx in (-0.95, 0.95):
            for dy in (-0.4, 0.4):
                cube(prefix + ' leg', (x + dx, y + dy, z + 0.38), (0.08, 0.08, 0.76), material)
    elif kind == 'coffin':
        cube(prefix + ' coffin base', (x, y, z + 0.2), (2.1, 3.5, 0.4), material)
        cube(prefix + ' coffin left', (x - 1.0, y, z + 0.55), (0.12, 3.5, 0.7), material)
        cube(prefix + ' coffin right', (x + 1.0, y, z + 0.55), (0.12, 3.5, 0.7), material)
        cube(prefix + ' coffin back', (x, y + 1.7, z + 0.55), (2.1, 0.12, 0.7), material)
        cube(prefix + ' coffin front', (x, y - 1.7, z + 0.35), (2.1, 0.12, 0.3), material)
    elif kind == 'table':
        cube(prefix + ' table top', (x, y, z + 0.75), (1.2, 0.8, 0.08), material)
        for dx in (-0.5, 0.5):
            for dy in (-0.3, 0.3):
                cube(prefix + ' table leg', (x + dx, y + dy, z + 0.37), (0.07, 0.07, 0.74), material)
    elif kind == 'lantern':
        cyl(prefix + ' lantern post', (x, y, z + 0.8), 0.05, 1.6, material)
        sphere(prefix + ' lantern body', (x, y, z + 1.65), (0.18, 0.18, 0.25), material)
    elif kind == 'screen':
        cube(prefix + ' screen', (x, y, z + 1.2), (3.0, 0.1, 2.4), material)
    elif kind == 'bed':
        cube(prefix + ' bed base', (x, y, z + 0.3), (2.2, 3.4, 0.6), material)
        cube(prefix + ' bed mattress', (x, y, z + 0.68), (2.0, 3.1, 0.2), material)
        cube(prefix + ' bed head', (x, y + 1.55, z + 1.0), (2.2, 0.12, 1.2), material)
    elif kind == 'body_cover':
        cube(prefix + ' covered body', (x, y, z + 0.16), (0.55, 1.75, 0.28), material, 0.05)
    elif kind == 'horse':
        horse(prefix, x, y, z, material)


def setup_render(spec, out):
    scene = bpy.context.scene
    scene.render.engine = 'BLENDER_WORKBENCH'
    scene.display.shading.light = 'STUDIO'
    scene.display.shading.studio_light = 'paint.sl'
    scene.display.shading.color_type = 'MATERIAL'
    scene.display.shading.show_shadows = True
    scene.display.shading.show_cavity = False
    scene.display.shading.show_object_outline = False
    scene.display.shading.background_type = 'VIEWPORT'
    scene.display.shading.background_color = (0.16, 0.16, 0.16)
    scene.render.resolution_x = int(spec.get('width', 1344))
    scene.render.resolution_y = int(spec.get('height', 768))
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = False
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGB'
    scene.render.image_settings.color_depth = '8'
    scene.render.filepath = str(out)
    scene.view_settings.view_transform = 'Standard'
    scene.render.fps = 24


def main():
    a = args()
    data = json.loads(Path(a.spec).read_text(encoding='utf-8'))
    spec = data['shots'][a.shot]
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    for blocks in (bpy.data.meshes, bpy.data.curves, bpy.data.cameras, bpy.data.lights, bpy.data.materials):
        for block in list(blocks):
            if block.users == 0:
                blocks.remove(block)
    floor = mat('floor', 0.30)
    wall = mat('wall', 0.22)
    accent = mat('accent', 0.48)
    body = mat('body', 0.78)
    build = SCENES[spec.get('scene', 'room')]
    build(floor, wall, accent)
    for index, actor in enumerate(spec.get('cast', []), 1):
        mannequin(f'actor {index} {actor["id"]}', actor, body)
        if actor.get('horse'):
            horse(f'actor {index} horse', float(actor['x']), float(actor['y']) + 0.1, float(actor.get('z', 0.0)), accent)
    for index, extra in enumerate(spec.get('extras', []), 1):
        mannequin(f'extra {index}', extra, body)
    for index, item in enumerate(spec.get('props_list', []), 1):
        prop(f'prop {index}', item, accent)
    cam = spec['camera']
    bpy.ops.object.camera_add(location=tuple(cam['position']))
    camera = bpy.context.object
    camera.name = 'previs camera'
    camera.data.lens = float(cam.get('lens', 40))
    target = Vector(tuple(cam['look_at']))
    camera.rotation_euler = (target - camera.location).to_track_quat('-Z', 'Y').to_euler()
    bpy.context.scene.camera = camera
    setup_render(spec, a.out)
    bpy.context.scene.frame_set(1)
    bpy.ops.render.render(write_still=True)
    print('PREVIS_RENDERED', a.out, flush=True)


if __name__ == '__main__':
    main()
