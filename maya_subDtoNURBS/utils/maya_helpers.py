# -*- coding: utf-8 -*-
"""Thin Maya helpers (cmds / OpenMaya)."""

from __future__ import absolute_import, print_function

import contextlib

import maya.cmds as cmds

from .text_encoding import safe_str


def ensure_plugin(plugin_name, quiet=True):
    """Load a Maya plug-in if it is not already loaded."""
    if cmds.pluginInfo(plugin_name, query=True, loaded=True):
        return True
    try:
        cmds.loadPlugin(plugin_name, quiet=quiet)
        return True
    except RuntimeError:
        return False


def get_selected_meshes():
    """Return transform names of selected polygon meshes (or mesh shapes)."""
    sel = cmds.ls(selection=True, long=True) or []
    meshes = []
    for node in sel:
        node = safe_str(node)
        shapes = cmds.listRelatives(node, shapes=True, fullPath=True, type="mesh") or []
        if shapes:
            meshes.append(node)
            continue
        # also accept history/dependency poly nodes selected in AE — skip
        if cmds.nodeType(node) == "mesh":
            parents = cmds.listRelatives(node, parent=True, fullPath=True) or []
            if parents:
                meshes.append(safe_str(parents[0]))
    seen = set()
    out = []
    for m in meshes:
        if m not in seen:
            seen.add(m)
            out.append(m)
    return out


def unique_name(base):
    """Return a scene-unique DAG name."""
    base = safe_str(base)
    if not cmds.objExists(base):
        return base
    i = 1
    while cmds.objExists("{0}_{1}".format(base, i)):
        i += 1
    return "{0}_{1}".format(base, i)


@contextlib.contextmanager
def with_undo_chunk(name="maya_subDtoNURBS"):
    """Group Maya operations into one undo chunk."""
    cmds.undoInfo(openChunk=True, chunkName=name)
    try:
        yield
    finally:
        cmds.undoInfo(closeChunk=True)
