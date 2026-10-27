# -*- coding: utf-8 -*-
"""End-to-end: SubD cage → CC limit patches → NURBS → STEP."""

from __future__ import absolute_import, print_function

import maya.cmds as cmds

from ..constants import (
    DEFAULT_DEGREE_U,
    DEFAULT_DEGREE_V,
    DEFAULT_EXPORT_FORMAT,
    DEFAULT_SMOOTH_LEVEL,
)
from ..utils.maya_helpers import get_selected_meshes, unique_name, with_undo_chunk
from ..utils.text_encoding import safe_str, ui_text
from .mesh_to_nurbs import mesh_to_nurbs_group
from .smooth_extract import ensure_quads_hint, extract_smoothed_mesh
from .step_export import export_cad, occ_available
from .subd_to_nurbs import DEFAULT_CC_LEVELS, cage_to_nurbs_group


def run_conversion(
    mesh_transform=None,
    smooth_divisions=DEFAULT_SMOOTH_LEVEL,
    degree_u=DEFAULT_DEGREE_U,
    degree_v=DEFAULT_DEGREE_V,
    delete_temp_mesh=True,
    skip_non_quad=True,
    mode="cage",
    cc_levels=DEFAULT_CC_LEVELS,
):
    """
    mode:
      'cage'   — CC limit sampling → 1 smooth NURBS per cage quad (default)
      'legacy' — old densify path
    """
    if mesh_transform is None:
        meshes = get_selected_meshes()
        if not meshes:
            raise RuntimeError("Please select a polygon mesh first.")
        mesh_transform = meshes[0]

    mesh_transform = safe_str(mesh_transform)
    src_short = safe_str(mesh_transform.split("|")[-1])

    quad, non_quad = ensure_quads_hint(mesh_transform)
    if non_quad and skip_non_quad:
        cmds.warning(
            ui_text(
                "[maya_subDtoNURBS] non-quad faces={0}, quads={1}".format(non_quad, quad)
            )
        )

    with with_undo_chunk("subDtoNURBS_convert"):
        if mode == "legacy":
            baked = extract_smoothed_mesh(mesh_transform, divisions=smooth_divisions)
            baked = safe_str(baked)
            result = mesh_to_nurbs_group(
                baked,
                degree_u=degree_u,
                degree_v=degree_v,
                skip_non_quad=skip_non_quad,
            )
            if delete_temp_mesh and cmds.objExists(baked):
                cmds.delete(baked)
        else:
            result = cage_to_nurbs_group(
                mesh_transform,
                cc_levels=cc_levels,
                patch_degree=3,
            )

        try:
            nice = unique_name(src_short + "_NURBS")
            if result.get("group") and cmds.objExists(result["group"]):
                result["group"] = cmds.rename(result["group"], nice)
        except Exception:
            pass

    result["source"] = mesh_transform
    result["smooth_divisions"] = smooth_divisions
    result["convert_mode"] = mode
    return result


def convert_and_export(
    filepath,
    mesh_transform=None,
    smooth_divisions=DEFAULT_SMOOTH_LEVEL,
    degree_u=DEFAULT_DEGREE_U,
    degree_v=DEFAULT_DEGREE_V,
    export_format=DEFAULT_EXPORT_FORMAT,
    delete_temp_mesh=True,
    keep_nurbs_in_scene=True,
    mode="cage",
    cc_levels=DEFAULT_CC_LEVELS,
):
    filepath = safe_str(filepath)
    conv = run_conversion(
        mesh_transform=mesh_transform,
        smooth_divisions=smooth_divisions,
        degree_u=degree_u,
        degree_v=degree_v,
        delete_temp_mesh=delete_temp_mesh,
        mode=mode,
        cc_levels=cc_levels,
    )

    export_result = export_cad(conv["group"], filepath, fmt=export_format)

    if not keep_nurbs_in_scene and conv.get("group") and cmds.objExists(conv["group"]):
        cmds.delete(conv["group"])

    return {
        "conversion": conv,
        "export": export_result,
        "occ_available": occ_available(),
    }
