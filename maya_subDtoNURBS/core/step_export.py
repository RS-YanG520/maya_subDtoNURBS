# -*- coding: utf-8 -*-
"""
Export NURBS to industrial CAD formats.

IMPORTANT (Maya 2018):
  ATF / DirectConnect IGES|STEP exporters are known to hard-crash Maya
  (not a catchable Python exception). Default path therefore uses the
  pure-Python writers only. Set env MAYA_SUBD_USE_ATF=1 to opt into Maya ATF.
"""

from __future__ import absolute_import, print_function

import os
import sys

import maya.cmds as cmds

from ..constants import OCC_STEP_AVAILABLE_HINT
from ..utils.maya_helpers import ensure_plugin
from ..utils.text_encoding import safe_str
from .cad_writers import collect_surfaces, write_iges, write_step


def _use_maya_atf():
    return os.environ.get("MAYA_SUBD_USE_ATF", "").strip() in ("1", "true", "True", "YES", "yes")


def _try_import_occ():
    for label, mod_name in (("OCP", "OCP"), ("OCC.Core", "OCC.Core"), ("OCC", "OCC")):
        try:
            mod = __import__(mod_name, fromlist=["*"])
            return {"backend": label, "module": mod}
        except ImportError:
            continue
    return None


def occ_available():
    return _try_import_occ() is not None


def _load_cad_plugins():
    for name in (
        "AtfPlugin",
        "ATFPlugin",
        "atfPlugin",
        "DirectConnect",
        "iges",
        "IGESexport",
    ):
        ensure_plugin(name)


def list_file_types():
    try:
        types = cmds.translator(query=True, list=True) or []
    except Exception:
        types = []
    return [safe_str(t) for t in types]


def _find_translator(keywords):
    types = list_file_types()
    keys = [k.lower() for k in keywords]
    scored = []
    for t in types:
        low = t.lower()
        if not any(k in low for k in keys):
            continue
        score = 0
        if "export" in low:
            score += 10
        if "atf" in low:
            score += 5
        if "import" in low and "export" not in low:
            score -= 5
        scored.append((score, t))
    if not scored:
        return None
    scored.sort(key=lambda x: (-x[0], x[1]))
    return scored[0][1]


def _maya_export_selected(nurbs_nodes, filepath, type_name):
    filepath = safe_str(filepath)
    cmds.select(nurbs_nodes, replace=True)
    cmds.file(
        filepath,
        force=True,
        options="",
        type=type_name,
        exportSelected=True,
        preserveReferences=True,
    )
    if not os.path.isfile(filepath):
        raise RuntimeError("Maya export produced no file: {0}".format(filepath))
    return filepath


def export_iges_maya(nurbs_nodes, filepath):
    """Maya ATF IGES — OPT-IN only (can hard-crash Maya 2018)."""
    if not _use_maya_atf():
        raise RuntimeError("Maya ATF IGES disabled (set MAYA_SUBD_USE_ATF=1 to enable).")

    filepath = os.path.abspath(safe_str(filepath))
    if not filepath.lower().endswith((".igs", ".iges")):
        filepath += ".igs"

    _load_cad_plugins()
    candidates = [
        _find_translator(("iges_atf",)),
        "IGES_ATF Export",
    ]
    errors = []
    for type_name in candidates:
        if not type_name:
            continue
        try:
            return _maya_export_selected(nurbs_nodes, filepath, type_name)
        except Exception as exc:
            errors.append("{0}: {1}".format(type_name, safe_str(exc)))
    raise RuntimeError("Maya IGES export failed: {0}".format(" | ".join(errors)))


def export_iges(nurbs_nodes, filepath):
    """IGES via pure-Python writer (safe). Optional ATF if env enabled."""
    filepath = os.path.abspath(safe_str(filepath))
    if not filepath.lower().endswith((".igs", ".iges")):
        filepath += ".igs"

    if _use_maya_atf():
        try:
            return export_iges_maya(nurbs_nodes, filepath)
        except Exception as maya_exc:
            sys.stdout.write(
                "[maya_subDtoNURBS] Maya ATF IGES skipped/failed ({0}); using Python writer\n".format(
                    safe_str(maya_exc)
                )
            )

    surfaces = collect_surfaces(nurbs_nodes)
    return write_iges(surfaces, filepath)


def export_step_via_occ(nurbs_nodes, filepath):
    occ = _try_import_occ()
    if occ is None:
        raise ImportError(OCC_STEP_AVAILABLE_HINT)

    filepath = os.path.abspath(safe_str(filepath))
    if not filepath.lower().endswith((".stp", ".step")):
        filepath += ".stp"

    backend = occ["backend"]
    from .cad_writers import _maya_surface_data

    surfaces = []
    for n in nurbs_nodes:
        data = _maya_surface_data(n)
        if data:
            surfaces.append(data)
    if not surfaces:
        raise RuntimeError("No NURBS surfaces for OCC export.")

    if backend == "OCP":
        from OCP.gp import gp_Pnt
        from OCP.TColgp import TColgp_Array2OfPnt
        from OCP.Geom import Geom_BSplineSurface
        from OCP.TColStd import TColStd_Array1OfReal, TColStd_Array1OfInteger
        from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
        from OCP.TopoDS import TopoDS_Compound
        from OCP.BRep import BRep_Builder
        from OCP.STEPControl import STEPControl_Writer, STEPControl_AsIs
        from OCP.IFSelect import IFSelect_RetDone
    else:
        try:
            from OCC.Core.gp import gp_Pnt
            from OCC.Core.TColgp import TColgp_Array2OfPnt
            from OCC.Core.Geom import Geom_BSplineSurface
            from OCC.Core.TColStd import TColStd_Array1OfReal, TColStd_Array1OfInteger
            from OCC.Core.BRepBuilderAPI import BRepBuilderAPI_MakeFace
            from OCC.Core.TopoDS import TopoDS_Compound
            from OCC.Core.BRep import BRep_Builder
            from OCC.Core.STEPControl import STEPControl_Writer, STEPControl_AsIs
            from OCC.Core.IFSelect import IFSelect_RetDone
        except ImportError:
            from OCC.gp import gp_Pnt
            from OCC.TColgp import TColgp_Array2OfPnt
            from OCC.Geom import Geom_BSplineSurface
            from OCC.TColStd import TColStd_Array1OfReal, TColStd_Array1OfInteger
            from OCC.BRepBuilderAPI import BRepBuilderAPI_MakeFace
            from OCC.TopoDS import TopoDS_Compound
            from OCC.BRep import BRep_Builder
            from OCC.STEPControl import STEPControl_Writer, STEPControl_AsIs
            from OCC.IFSelect import IFSelect_RetDone

    builder = BRep_Builder()
    compound = TopoDS_Compound()
    builder.MakeCompound(compound)

    def uniform_knots_occ(n_poles, degree):
        n_unique = n_poles - degree + 1
        knots = TColStd_Array1OfReal(1, n_unique)
        mults = TColStd_Array1OfInteger(1, n_unique)
        for k in range(1, n_unique + 1):
            knots.SetValue(k, float(k - 1) / max(n_unique - 1, 1))
            mults.SetValue(k, degree + 1 if (k == 1 or k == n_unique) else 1)
        return knots, mults

    for surf in surfaces:
        degree_u = surf["degree_u"]
        degree_v = surf["degree_v"]
        cvs = surf["cvs"]
        nu = len(cvs)
        nv = len(cvs[0])
        poles = TColgp_Array2OfPnt(1, nu, 1, nv)
        for i in range(nu):
            for j in range(nv):
                x, y, z = cvs[i][j]
                poles.SetValue(i + 1, j + 1, gp_Pnt(float(x), float(y), float(z)))
        ku, mu = uniform_knots_occ(nu, degree_u)
        kv, mv = uniform_knots_occ(nv, degree_v)
        try:
            geom = Geom_BSplineSurface(poles, ku, kv, mu, mv, degree_u, degree_v)
            face = BRepBuilderAPI_MakeFace(geom, 1e-6).Face()
            builder.Add(compound, face)
        except Exception as exc:
            sys.stderr.write("[maya_subDtoNURBS] OCC skip: {0}\n".format(safe_str(exc)))

    writer = STEPControl_Writer()
    writer.Transfer(compound, STEPControl_AsIs)
    status = writer.Write(filepath)
    if int(status) != int(IFSelect_RetDone):
        raise RuntimeError("STEP write failed with status {0}".format(status))
    return filepath


def export_step(nurbs_nodes, filepath):
    """
    STEP chain (safe by default):
      1) OpenCascade (optional)
      2) Pure-Python STEP writer
    Maya ATF is skipped unless MAYA_SUBD_USE_ATF=1 (crash risk).
    """
    filepath = os.path.abspath(safe_str(filepath))
    if not filepath.lower().endswith((".stp", ".step")):
        filepath += ".stp"

    errors = []

    try:
        return export_step_via_occ(nurbs_nodes, filepath), "occ"
    except Exception as exc:
        errors.append("OCC: {0}".format(safe_str(exc)))

    surfaces = collect_surfaces(nurbs_nodes)
    path = write_step(surfaces, filepath)
    note = "; ".join(errors) if errors else "ok"
    return path, "python({0})".format(note)


def export_cad(nurbs_group_or_nodes, filepath, fmt="stp"):
    if isinstance(nurbs_group_or_nodes, (list, tuple)):
        nodes = list(nurbs_group_or_nodes)
    else:
        children = (
            cmds.listRelatives(
                nurbs_group_or_nodes, children=True, fullPath=True, type="transform"
            )
            or []
        )
        nodes = children if children else [nurbs_group_or_nodes]
        filtered = []
        for n in nodes:
            shapes = cmds.listRelatives(n, shapes=True, type="nurbsSurface") or []
            if shapes:
                filtered.append(n)
        nodes = filtered or nodes

    nodes = [safe_str(n) for n in nodes]
    result = {"stp": None, "iges": None, "errors": [], "stp_backend": None}
    base, _ext = os.path.splitext(safe_str(filepath))
    fmt = (fmt or "stp").lower()

    if fmt in ("stp", "step", "both"):
        try:
            path, backend = export_step(nodes, base + ".stp")
            result["stp"] = path
            result["stp_backend"] = backend
        except Exception as exc:
            result["errors"].append("STEP: {0}".format(safe_str(exc)))
            if fmt in ("stp", "step"):
                try:
                    result["iges"] = export_iges(nodes, base + ".igs")
                    result["errors"].append(
                        "STEP failed; wrote IGES: {0}".format(result["iges"])
                    )
                except Exception as exc2:
                    result["errors"].append(
                        "IGES fallback failed: {0}".format(safe_str(exc2))
                    )

    if fmt in ("iges", "igs", "both"):
        try:
            result["iges"] = export_iges(nodes, base + ".igs")
        except Exception as exc:
            result["errors"].append("IGES: {0}".format(safe_str(exc)))

    return result
