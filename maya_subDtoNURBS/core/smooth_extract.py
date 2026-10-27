# -*- coding: utf-8 -*-
"""
Extract geometry equivalent to Maya smooth-mesh preview (keyboard 1/2/3).

Maya's displaySmoothness only changes viewport display. For export we must
bake a real subdivided mesh (Catmull-Clark via polySmooth / OpenMaya).
"""

from __future__ import absolute_import, print_function

import maya.cmds as cmds

from ..constants import DEFAULT_SMOOTH_LEVEL
from ..utils.maya_helpers import unique_name
from ..utils.text_encoding import safe_str


def get_display_smooth_level(mesh_transform):
    """
    Read current smoothMesh / displaySmoothness hint if available.
    Returns 0, 1, or 2 (Maya preview divisions).
    """
    shapes = cmds.listRelatives(mesh_transform, shapes=True, fullPath=True, type="mesh") or []
    if not shapes:
        return DEFAULT_SMOOTH_LEVEL
    shape = shapes[0]
    # Prefer explicit smooth level attribute when present
    for attr in ("smoothLevel", "displaySmoothMesh"):
        plug = "{0}.{1}".format(shape, attr)
        if cmds.objExists(plug):
            try:
                val = cmds.getAttr(plug)
                if isinstance(val, bool):
                    return DEFAULT_SMOOTH_LEVEL if val else 0
                return int(val)
            except Exception:
                pass
    return DEFAULT_SMOOTH_LEVEL


def duplicate_mesh(mesh_transform, suffix="_smoothExtract"):
    """Duplicate transform+mesh for non-destructive processing."""
    mesh_transform = safe_str(mesh_transform)
    short = safe_str(mesh_transform.split("|")[-1])
    name = unique_name(short + suffix)
    dup = cmds.duplicate(mesh_transform, name=name, returnRootsOnly=True)[0]
    return safe_str(dup)


def extract_smoothed_mesh(mesh_transform, divisions=None, keep_history=False):
    """
    Bake a smoothed mesh matching preview level (default = key '3').

    Args:
        mesh_transform: polygon transform DAG path / name
        divisions: Catmull-Clark iterations (None -> DEFAULT_SMOOTH_LEVEL)
        keep_history: if False, delete construction history after smooth

    Returns:
        str: new transform name of the baked smooth mesh
    """
    if divisions is None:
        divisions = get_display_smooth_level(mesh_transform)
    divisions = max(0, int(divisions))

    dup = duplicate_mesh(mesh_transform, suffix="_subDBake")

    if divisions > 0:
        # Maya polySmooth: divisions == displaySmoothness style iterations
        cmds.polySmooth(
            dup,
            divisions=divisions,
            continuity=1.0,
            keepBorder=True,
            keepHardEdge=False,
            keepSelectionBorder=True,
            keepTessellation=True,
            propagateEdgeHardness=False,
            constructionHistory=keep_history,
        )
        if not keep_history:
            cmds.delete(dup, constructionHistory=True)

    # Triangulate is NOT done here — NURBS patch fitting prefers quads
    return dup


def ensure_quads_hint(mesh_transform):
    """
    Lightweight check: warn if mesh has many non-quad faces.
    Returns (quad_count, non_quad_count).
    """
    shapes = cmds.listRelatives(mesh_transform, shapes=True, fullPath=True, type="mesh") or []
    if not shapes:
        return 0, 0
    shape = shapes[0]
    face_count = cmds.polyEvaluate(shape, face=True)
    # Sample via polyInfo for small meshes; for large meshes use estimate
    non_quad = 0
    quad = 0
    # polyInfo -faceToVertex returns "FACE 0: 0 1 2 3" lines
    info = cmds.polyInfo(shape, faceToVertex=True) or []
    for line in info:
        parts = line.strip().split()
        # FACE <id>: v0 v1 ...
        try:
            colon = parts.index(":")
            nverts = len(parts) - colon - 1
        except ValueError:
            continue
        if nverts == 4:
            quad += 1
        else:
            non_quad += 1
    if face_count and (quad + non_quad) == 0:
        # Fallback when polyInfo empty
        return int(face_count), 0
    return quad, non_quad
