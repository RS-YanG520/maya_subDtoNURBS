# -*- coding: utf-8 -*-
"""
Debug convert on current Maya selection and write debug_last_run.log
so the agent can read results after the user runs it.
"""

from __future__ import absolute_import, print_function

import datetime
import os
import traceback

import maya.cmds as cmds

from ..utils.maya_helpers import get_selected_meshes
from ..utils.text_encoding import safe_str
from .pipeline import run_conversion

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOG_PATH = os.path.join(_ROOT, "debug_last_run.log")


def _log(lines, msg):
    lines.append(msg)
    print("[maya_subDtoNURBS:debug] " + safe_str(msg))


def run_debug_on_selection(mode="cage"):
    """Convert selection with diagnostics; write debug_last_run.log."""
    lines = []
    _log(lines, "=== debug_run {0} ===".format(datetime.datetime.now().isoformat()))
    meshes = get_selected_meshes()
    _log(lines, "selection meshes: {0}".format(meshes))
    if not meshes:
        _log(lines, "ERROR: no polygon mesh selected")
        _write(lines)
        cmds.warning("debug: please select a polygon cage first")
        return None

    mesh = meshes[0]
    shapes = cmds.listRelatives(mesh, shapes=True, type="mesh") or []
    _log(lines, "mesh={0} shapes={1}".format(mesh, shapes))
    if shapes:
        _log(
            lines,
            "faces={0} verts={1} edges={2}".format(
                cmds.polyEvaluate(shapes[0], face=True),
                cmds.polyEvaluate(shapes[0], vertex=True),
                cmds.polyEvaluate(shapes[0], edge=True),
            ),
        )
        bb = cmds.exactWorldBoundingBox(mesh)
        _log(lines, "bbox={0}".format(bb))

    # Clean previous auto groups for this short name? don't — just report overlaps
    existing = cmds.ls("*_NURBS*") or []
    _log(lines, "existing *_NURBS* before: {0}".format(existing[:20]))

    try:
        result = run_conversion(mesh_transform=mesh, mode=mode)
    except Exception:
        _log(lines, "EXCEPTION:\n" + traceback.format_exc())
        _write(lines)
        raise

    _log(lines, "result keys={0}".format(sorted(result.keys())))
    for k in (
        "group",
        "quad_count",
        "face_total",
        "child_count",
        "regular_count",
        "approx_count",
        "rejected_nbh",
        "error_sample",
        "convert_mode",
        "mode",
        "cc_levels",
        "grid_size",
        "stitched_edges",
        "pre_stitch_gap",
        "g1_stitched_edges",
        "g1_sin_before",
        "g1_passes",
    ):
        if k in result:
            _log(lines, "  {0}={1}".format(k, result.get(k)))
    skipped = result.get("skipped_faces") or []
    _log(lines, "skipped count={0} sample={1}".format(len(skipped), skipped[:5]))

    group = result.get("group")
    if group and cmds.objExists(group):
        bb_g = cmds.exactWorldBoundingBox(group)
        bb_m = cmds.exactWorldBoundingBox(mesh)
        size_g = max(bb_g[3] - bb_g[0], bb_g[4] - bb_g[1], bb_g[5] - bb_g[2])
        size_m = max(bb_m[3] - bb_m[0], bb_m[4] - bb_m[1], bb_m[5] - bb_m[2])
        ratio = size_g / max(size_m, 1e-8)
        _log(lines, "bbox_ratio group/source={0:.4f}".format(ratio))
        if ratio > 3.0:
            _log(lines, "WARNING: bbox exploded — likely bad CVs / leftover junk")
        kids = cmds.listRelatives(group, children=True, type="transform") or []
        _log(lines, "children sample: {0}".format(kids[:10]))
        cmds.select(group, replace=True)

    _write(lines)
    cmds.confirmDialog(
        title="maya_subDtoNURBS debug",
        message="Wrote log:\n{0}".format(LOG_PATH),
        button=["OK"],
    )
    return result


def _write(lines):
    path = LOG_PATH
    try:
        with open(path, "w") as fh:
            fh.write("\n".join([safe_str(x) for x in lines]))
            fh.write("\n")
    except Exception as exc:
        print("failed to write log: {0}".format(exc))
