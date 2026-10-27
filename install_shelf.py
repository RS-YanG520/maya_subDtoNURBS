# -*- coding: utf-8 -*-
"""
在当前 Maya Shelf 上添加一键打开工具的按钮。

用法（Maya Script Editor）:
  execfile(r'd:/My Documents/maya/2018/zh_CN/scripts/maya_subDtoNURBS/install_shelf.py')
"""

from __future__ import absolute_import, print_function

import os
import sys

import maya.cmds as cmds
import maya.mel as mel

# 不要用 __file__（Maya execfile 不提供）
ROOT = r"d:\My Documents\maya\2018\zh_CN\scripts\maya_subDtoNURBS"
PLUGIN = os.path.join(ROOT, "plug-ins", "maya_subDtoNURBS_plugin.py")

if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def install():
    plug_dir = os.path.join(ROOT, "plug-ins")
    current = os.environ.get("MAYA_PLUG_IN_PATH", "")
    if plug_dir not in current.split(os.pathsep):
        os.environ["MAYA_PLUG_IN_PATH"] = plug_dir + os.pathsep + current

    if not cmds.pluginInfo(PLUGIN, query=True, loaded=True):
        try:
            cmds.loadPlugin(PLUGIN)
        except RuntimeError as exc:
            cmds.warning(str(exc))

    g_shelf = mel.eval("$tmp=$gShelfTopLevel")
    shelf = cmds.tabLayout(g_shelf, query=True, selectTab=True)

    buttons = cmds.shelfLayout(shelf, query=True, childArray=True) or []
    for b in buttons:
        if cmds.shelfButton(b, exists=True):
            label = cmds.shelfButton(b, query=True, label=True) or ""
            if label == "subDtoNURBS":
                cmds.deleteUI(b)

    cmd = (
        "import sys\n"
        "root = r'{0}'\n"
        "if root not in sys.path: sys.path.insert(0, root)\n"
        "for _n in sorted(list(sys.modules.keys()), reverse=True):\n"
        "    if _n == 'maya_subDtoNURBS' or _n.startswith('maya_subDtoNURBS.'):\n"
        "        sys.modules.pop(_n, None)\n"
        "from maya_subDtoNURBS.utils.text_encoding import fix_maya_default_encoding\n"
        "fix_maya_default_encoding()\n"
        "from maya_subDtoNURBS.ui import show_ui\n"
        "show_ui()\n"
    ).format(ROOT.replace("\\", "\\\\"))

    cmds.shelfButton(
        parent=shelf,
        label="subDtoNURBS",
        annotation="Smooth/SubD mesh -> NURBS -> STEP",
        image1="polySmooth.png",
        command=cmd,
        sourceType="python",
    )

    try:
        from maya_subDtoNURBS.utils.text_encoding import ui_text as _L
    except Exception:
        def _L(s):
            return s

    cmds.confirmDialog(
        title="maya_subDtoNURBS",
        message=_L(u"已在当前 Shelf 添加按钮: subDtoNURBS"),
        button=["OK"],
    )


install()
