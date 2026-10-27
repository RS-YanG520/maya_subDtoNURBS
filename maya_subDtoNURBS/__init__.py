# -*- coding: utf-8 -*-
"""Maya SubD / Smooth Mesh -> NURBS -> STEP exporter."""

from __future__ import absolute_import

__version__ = "0.1.1"
__author__ = "RS-Sherry"

PLUGIN_NAME = "maya_subDtoNURBS"

try:
    from .utils.text_encoding import fix_maya_default_encoding

    fix_maya_default_encoding()
except Exception:
    pass
