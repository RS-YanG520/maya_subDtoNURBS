# -*- coding: utf-8 -*-
"""Maya GUI — SubD cage → CC limit NURBS → STEP."""

from __future__ import absolute_import, print_function

import os
import sys

import maya.cmds as cmds

from ..constants import WINDOW_NAME, WINDOW_TITLE
from ..core.pipeline import convert_and_export, run_conversion
from ..core.step_export import occ_available
from ..core.subd_to_nurbs import DEFAULT_CC_LEVELS
from ..utils.maya_helpers import get_selected_meshes
from ..utils.text_encoding import (
    fix_maya_default_encoding,
    safe_str,
    to_unicode,
    ui_text,
)

fix_maya_default_encoding()


def _L(text):
    return ui_text(text)


def _close_if_exists():
    if cmds.window(WINDOW_NAME, exists=True):
        cmds.deleteUI(WINDOW_NAME, window=True)


def show_ui():
    _close_if_exists()

    win = cmds.window(
        WINDOW_NAME,
        title=_L(WINDOW_TITLE),
        widthHeight=(460, 380),
        sizeable=True,
    )
    cmds.columnLayout(adjustableColumn=True, rowSpacing=6, columnAttach=("both", 10))

    cmds.separator(height=8, style="none")
    cmds.text(
        label=_L(
            u"重写算法：Catmull-Clark 极限采样 → 每笼子四边面一张光滑 NURBS → STP"
        ),
        align="left",
        wordWrap=True,
    )
    cmds.separator(height=6, style="in")

    cmds.text(label=_L(u"转换模式"), align="left")
    cmds.optionMenu("subDtoNurbs_mode", label="")
    cmds.menuItem(label=_L(u"cage — CC极限补丁（推荐，接近 Plasticity）"))
    cmds.menuItem(label=_L(u"legacy — 旧聚密算法"))

    cmds.intSliderGrp(
        "subDtoNurbs_ccLevels",
        label=_L(u"CC级数"),
        field=True,
        minValue=1,
        maxValue=3,
        value=DEFAULT_CC_LEVELS,
        annotation=_L(u"CC采样级数（最终导出为4x4双三次Bezier）"),
        columnWidth=[(1, 70), (2, 40)],
    )

    cmds.checkBox(
        "subDtoNurbs_keepNurbs",
        label=_L(u"导出走后保留场景中的 NURBS"),
        value=True,
    )

    cmds.text(label=_L(u"导出格式"), align="left")
    cmds.optionMenu("subDtoNurbs_format", label="")
    cmds.menuItem(label="stp (STEP)")
    cmds.menuItem(label="iges")
    cmds.menuItem(label="both")

    occ = occ_available()
    cmds.text(
        label=_L(
            u"STEP: OpenCascade 可用" if occ else u"STEP: 内置写入器（安全）"
        ),
        align="left",
    )

    cmds.separator(height=8, style="in")
    cmds.button(
        label=_L(u"仅转换为 NURBS（不导出）"),
        height=32,
        command=_on_convert_only,
    )
    cmds.button(
        label=_L(u"转换并导出…"),
        height=36,
        backgroundColor=(0.35, 0.55, 0.40),
        command=_on_convert_export,
    )
    cmds.button(
        label=_L(u"Debug 转换并写日志…"),
        height=28,
        backgroundColor=(0.45, 0.35, 0.25),
        command=_on_debug,
    )

    cmds.separator(height=6, style="none")
    cmds.textField(
        "subDtoNurbs_status",
        text=_L(u"就绪：选中控制笼后转换"),
        editable=False,
    )

    cmds.setParent("..")
    cmds.showWindow(win)
    return win


def _read_mode():
    idx = int(cmds.optionMenu("subDtoNurbs_mode", query=True, select=True))
    return "cage" if idx == 1 else "legacy"


def _read_cc_levels():
    return int(cmds.intSliderGrp("subDtoNurbs_ccLevels", query=True, value=True))


def _read_format():
    idx = cmds.optionMenu("subDtoNurbs_format", query=True, select=True)
    return {1: "stp", 2: "iges", 3: "both"}.get(int(idx), "stp")


def _set_status(msg):
    text = _L(msg)
    if cmds.textField("subDtoNurbs_status", exists=True):
        cmds.textField("subDtoNurbs_status", edit=True, text=text)
    try:
        sys.stdout.write("[maya_subDtoNURBS] %s\n" % safe_str(msg))
    except Exception:
        pass


def _cleanup_old(short):
    junk = cmds.ls(short + "_NURBS*", short + "_f*") or []
    junk += [n for n in (cmds.ls("*_NURBS*") or []) if n not in junk]
    if junk:
        try:
            cmds.delete(junk)
        except Exception:
            pass
    return len(junk)


def _on_debug(*_args):
    try:
        from ..core.debug_run import LOG_PATH, run_debug_on_selection

        run_debug_on_selection(mode=_read_mode())
        _set_status(u"Debug 日志: {0}".format(to_unicode(LOG_PATH)))
    except Exception as exc:
        cmds.warning(_L(safe_str(exc)))
        _set_status(u"Debug 失败: {0}".format(to_unicode(exc)))


def _on_convert_only(*_args):
    meshes = get_selected_meshes()
    if not meshes:
        cmds.warning(_L(u"请先选择多边形物体（控制笼）"))
        _set_status(u"未选择网格")
        return
    try:
        short = safe_str(meshes[0].split("|")[-1])
        njunk = _cleanup_old(short)
        result = run_conversion(
            mesh_transform=meshes[0],
            mode=_read_mode(),
            cc_levels=_read_cc_levels(),
        )
        qc = result.get("quad_count", 0)
        ft = result.get("face_total", 0)
        cc = result.get("child_count", 0)
        gs = result.get("grid_size", "?")
        msg = u"完成: {0}/{1} 面片 组内{2} grid={3}x{3} 清理{4} → {5}".format(
            qc, ft, cc, gs, njunk, to_unicode(result.get("group"))
        )
        if result.get("error_sample") and qc == 0:
            cmds.warning(
                _L(u"未生成 NURBS: {0}".format(to_unicode(result["error_sample"])))
            )
        skipped = result.get("skipped_faces") or []
        if skipped:
            msg += u" skip={0}:{1}".format(len(skipped), to_unicode(skipped[0][1]))
        _set_status(msg)
        if result.get("group") and cmds.objExists(result["group"]):
            cmds.select(result["group"], replace=True)
    except Exception as exc:
        cmds.warning(_L(safe_str(exc)))
        _set_status(u"失败: {0}".format(to_unicode(exc)))


def _on_convert_export(*_args):
    meshes = get_selected_meshes()
    if not meshes:
        cmds.warning(_L(u"请先选择多边形物体（控制笼）"))
        _set_status(u"未选择网格")
        return

    start_dir = cmds.workspace(query=True, rootDirectory=True) or os.path.expanduser("~")
    path = cmds.fileDialog2(
        fileMode=0,
        caption=_L(u"导出 STEP / IGES"),
        startingDirectory=safe_str(start_dir),
        fileFilter="STEP (*.stp);;IGES (*.igs);;All (*.*)",
    )
    if not path:
        _set_status(u"已取消导出")
        return

    try:
        short = safe_str(meshes[0].split("|")[-1])
        _cleanup_old(short)
        out = convert_and_export(
            filepath=safe_str(path[0]),
            mesh_transform=meshes[0],
            export_format=_read_format(),
            keep_nurbs_in_scene=cmds.checkBox(
                "subDtoNurbs_keepNurbs", query=True, value=True
            ),
            mode=_read_mode(),
            cc_levels=_read_cc_levels(),
        )
        exp = out.get("export") or {}
        parts = []
        if exp.get("stp"):
            parts.append(
                u"STP[{0}]: {1}".format(
                    to_unicode(exp.get("stp_backend") or ""),
                    to_unicode(exp["stp"]),
                )
            )
        if exp.get("iges"):
            parts.append(u"IGES: {0}".format(to_unicode(exp["iges"])))
        msg = u" | ".join(parts) if parts else u"未写出文件"
        errs = exp.get("errors") or []
        if errs:
            msg += u" || " + u"; ".join([to_unicode(e) for e in errs])
        _set_status(msg)
        group = out["conversion"].get("group")
        if group and cmds.objExists(group):
            cmds.select(group, replace=True)
    except Exception as exc:
        cmds.warning(_L(safe_str(exc)))
        _set_status(u"失败: {0}".format(to_unicode(exc)))
