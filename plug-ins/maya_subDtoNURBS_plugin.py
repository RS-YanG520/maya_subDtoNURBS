# -*- coding: utf-8 -*-
"""
Maya plug-in entry for maya_subDtoNURBS.

Load via:
  Window > Settings/Preferences > Plug-in Manager
  or: cmds.loadPlugin('maya_subDtoNURBS_plugin.py')

Commands:
  subDtoNURBS          — open UI
  subDtoNURBSConvert   — convert selection (flags for export path)
"""

from __future__ import absolute_import, print_function

import os
import sys

import maya.api.OpenMaya as om
import maya.cmds as cmds

# Ensure package root (parent of plug-ins/) is on sys.path
_PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_PLUGIN_DIR)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def maya_useNewAPI():
    """Use Maya Python API 2.0."""
    pass


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

class SubDtoNURBSCmd(om.MPxCommand):
    CMD_NAME = "subDtoNURBS"

    def doIt(self, args):
        from maya_subDtoNURBS.ui import show_ui
        show_ui()


def _cmd_creator():
    return SubDtoNURBSCmd()


class SubDtoNURBSConvertCmd(om.MPxCommand):
    CMD_NAME = "subDtoNURBSConvert"

    def __init__(self):
        super(SubDtoNURBSConvertCmd, self).__init__()
        self._filepath = ""
        self._level = 2
        self._fmt = "stp"

    def doIt(self, args):
        arg_db = om.MArgDatabase(self.syntax(), args)
        if arg_db.isFlagSet("-f"):
            self._filepath = arg_db.flagArgumentString("-f", 0)
        if arg_db.isFlagSet("-l"):
            self._level = arg_db.flagArgumentInt("-l", 0)
        if arg_db.isFlagSet("-t"):
            self._fmt = arg_db.flagArgumentString("-t", 0)

        if self._filepath:
            from maya_subDtoNURBS.core import convert_and_export
            result = convert_and_export(
                filepath=self._filepath,
                smooth_divisions=self._level,
                export_format=self._fmt,
            )
            self.clearResult()
            group = result["conversion"].get("group") or ""
            self.setResult(group)
        else:
            from maya_subDtoNURBS.core import run_conversion
            result = run_conversion(smooth_divisions=self._level)
            self.clearResult()
            self.setResult(result.get("group") or "")


def _convert_creator():
    return SubDtoNURBSConvertCmd()


def _convert_syntax():
    syn = om.MSyntax()
    syn.addFlag("-f", "-filepath", om.MSyntax.kString)
    syn.addFlag("-l", "-level", om.MSyntax.kLong)
    syn.addFlag("-t", "-type", om.MSyntax.kString)
    return syn


# ---------------------------------------------------------------------------
# Plugin init
# ---------------------------------------------------------------------------

def initializePlugin(plugin):
    plugin_fn = om.MFnPlugin(plugin, "RS-Sherry", "0.1.0", "Any")
    try:
        plugin_fn.registerCommand(SubDtoNURBSCmd.CMD_NAME, _cmd_creator)
        plugin_fn.registerCommand(
            SubDtoNURBSConvertCmd.CMD_NAME,
            _convert_creator,
            _convert_syntax,
        )
    except Exception as exc:
        om.MGlobal.displayError("maya_subDtoNURBS register failed: {0}".format(exc))
        raise
    om.MGlobal.displayInfo("maya_subDtoNURBS loaded.  Run: subDtoNURBS")


def uninitializePlugin(plugin):
    plugin_fn = om.MFnPlugin(plugin)
    for name in (SubDtoNURBSCmd.CMD_NAME, SubDtoNURBSConvertCmd.CMD_NAME):
        try:
            plugin_fn.deregisterCommand(name)
        except Exception:
            pass
