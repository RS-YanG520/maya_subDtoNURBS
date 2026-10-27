# -*- coding: utf-8 -*-
"""Resolve package root even when Maya execfile() leaves __file__ undefined."""

from __future__ import absolute_import, print_function

import os
import sys


# Fallback when Script Editor uses execfile / Execute without __file__
_DEFAULT_ROOT = r"d:\My Documents\maya\2018\zh_CN\scripts\maya_subDtoNURBS"


def package_root(anchor_file=None):
    """
    Return the directory that contains the maya_subDtoNURBS package folder.

    Tries, in order:
      1. anchor_file / caller __file__
      2. already-imported maya_subDtoNURBS.__file__
      3. hardcoded _DEFAULT_ROOT (this project's install path)
    """
    candidates = []

    if anchor_file:
        candidates.append(anchor_file)

    # Caller frame __file__ (when imported as module this works)
    try:
        import inspect
        frame = inspect.currentframe()
        if frame and frame.f_back:
            caller_file = frame.f_back.f_globals.get("__file__")
            if caller_file:
                candidates.append(caller_file)
    except Exception:
        pass

    # Already on sys.modules
    mod = sys.modules.get("maya_subDtoNURBS")
    if mod is not None:
        mod_file = getattr(mod, "__file__", None)
        if mod_file:
            # .../maya_subDtoNURBS/__init__.py -> parent is ROOT
            candidates.append(os.path.join(os.path.dirname(os.path.abspath(mod_file)), os.pardir))

    candidates.append(_DEFAULT_ROOT)

    for path in candidates:
        try:
            abs_path = os.path.abspath(path)
            if os.path.isfile(abs_path):
                abs_path = os.path.dirname(abs_path)
            # If we landed inside the package dir, go up one
            if os.path.basename(abs_path) == "maya_subDtoNURBS" and os.path.isdir(
                os.path.join(os.path.dirname(abs_path), "maya_subDtoNURBS")
            ):
                abs_path = os.path.dirname(abs_path)
            pkg = os.path.join(abs_path, "maya_subDtoNURBS")
            if os.path.isdir(pkg):
                return abs_path
        except Exception:
            continue

    return os.path.abspath(_DEFAULT_ROOT)


def ensure_sys_path(root=None):
    root = root or package_root()
    if root not in sys.path:
        sys.path.insert(0, root)
    return root
