# -*- coding: utf-8 -*-
"""Shared defaults and labels."""

from __future__ import absolute_import, print_function

# Smooth preview levels mirror Maya's 1 / 2 / 3 keys
SMOOTH_LEVEL_DISPLAY = {
    0: "1 (cage)",
    1: "2 (preview)",
    2: "3 (smooth)",
}

DEFAULT_SMOOTH_LEVEL = 2  # same as pressing "3"
DEFAULT_POLY_SMOOTH_DIVISIONS = 2
# 1 = bilinear per face (recommended for CAD). 3 = bicubic Bezier-style.
DEFAULT_DEGREE_U = 1
DEFAULT_DEGREE_V = 1
DEFAULT_EXPORT_FORMAT = "stp"  # stp | iges | both

WINDOW_TITLE = "SubD / Smooth -> NURBS -> STEP"
WINDOW_NAME = "mayaSubDtoNURBSWin"

# Maya file translators (native)
MAYA_IGES_TRANSLATOR = "IGES"
MAYA_OBJ_TRANSLATOR = "OBJexport"

# Optional external STEP writer
OCC_STEP_AVAILABLE_HINT = (
    "pythonocc-core / OCP not found. "
    "Install OpenCascade Python bindings for native .stp export, "
    "or export IGES and convert in CAD."
)
