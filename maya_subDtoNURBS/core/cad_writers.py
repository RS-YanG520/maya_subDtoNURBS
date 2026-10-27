# -*- coding: utf-8 -*-
"""
Pure-Python IGES / STEP writers for Maya NURBS patches.

Used when Maya has no IGES/STEP translator (common on Maya 2018 zh_CN)
and OpenCascade is not installed.
"""

from __future__ import absolute_import, print_function

import datetime
import os

from ..utils.text_encoding import safe_str


def _clamped_uniform_knots(n_poles, degree):
    """Return flat knot list length = n_poles + degree + 1."""
    n_poles = int(n_poles)
    degree = int(degree)
    n_internal = n_poles - degree - 1
    knots = [0.0] * (degree + 1)
    if n_internal > 0:
        for i in range(1, n_internal + 1):
            knots.append(float(i) / float(n_internal + 1))
    knots.extend([1.0] * (degree + 1))
    return knots


def _maya_surface_data(shape_or_xform):
    """
    Read one Maya nurbsSurface -> dict or None.
    cvs is indexed [u][v]. Prefer real knot vectors from the surface.
    """
    import maya.cmds as cmds

    node = safe_str(shape_or_xform)
    shapes = cmds.listRelatives(node, shapes=True, fullPath=True, type="nurbsSurface") or []
    if shapes:
        shape = safe_str(shapes[0])
        name = safe_str(node.split("|")[-1])
    elif cmds.nodeType(node) == "nurbsSurface":
        shape = node
        name = safe_str(node.split("|")[-1])
    else:
        return None

    degree_u = int(cmds.getAttr(shape + ".degreeU"))
    degree_v = int(cmds.getAttr(shape + ".degreeV"))
    spans_u = int(cmds.getAttr(shape + ".spansU"))
    spans_v = int(cmds.getAttr(shape + ".spansV"))
    nu = spans_u + degree_u
    nv = spans_v + degree_v

    # cvs[u][v]
    cvs = []
    for i in range(nu):
        row = []
        for j in range(nv):
            pt = cmds.pointPosition("{0}.cv[{1}][{2}]".format(shape, i, j), world=True)
            row.append((float(pt[0]), float(pt[1]), float(pt[2])))
        cvs.append(row)

    # Our created patches use clamped knots; synthesize to match CV/degree count.
    # (Reading Maya knot arrays via OM2 is version-fragile on 2018.)
    knots_u = _clamped_uniform_knots(nu, degree_u)
    knots_v = _clamped_uniform_knots(nv, degree_v)

    form_u = 0
    form_v = 0
    try:
        form_u = int(cmds.getAttr(shape + ".formU"))
        form_v = int(cmds.getAttr(shape + ".formV"))
    except Exception:
        pass

    # Min/max param from knot domain
    u0, u1 = float(knots_u[degree_u]), float(knots_u[nu])
    v0, v1 = float(knots_v[degree_v]), float(knots_v[nv])

    return {
        "name": name,
        "degree_u": degree_u,
        "degree_v": degree_v,
        "cvs": cvs,
        "knots_u": knots_u,
        "knots_v": knots_v,
        "form_u": form_u,
        "form_v": form_v,
        "u_range": (u0, u1),
        "v_range": (v0, v1),
    }


def collect_surfaces(nurbs_nodes):
    out = []
    for n in nurbs_nodes:
        data = _maya_surface_data(n)
        if data and data["cvs"]:
            out.append(data)
    return out


def _fmt_num(v):
    if isinstance(v, int):
        return str(int(v))
    s = "{0:.10G}".format(float(v))
    if s.startswith("."):
        s = "0" + s
    elif s.startswith("-."):
        s = "-0" + s[1:]
    return s


def _iges_hline(content, section, index):
    data = content[:72]
    data = data + (" " * (72 - len(data)))
    return "{0}{1}{2:7d}\n".format(data, section, index)


def _iges_params_to_lines(params, de_pointer, start_index=1):
    blob = ",".join(params) + ";"
    lines = []
    idx = start_index
    while blob:
        chunk = blob[:64]
        blob = blob[64:]
        pad = chunk + (" " * (64 - len(chunk)))
        de_field = "{0:8d}".format(de_pointer)
        lines.append(pad + de_field + "P{0:7d}\n".format(idx))
        idx += 1
    return lines, idx


def write_iges(surfaces, filepath):
    """Write IGES 5.3 with Entity 128 (Rational B-Spline Surface)."""
    filepath = os.path.abspath(safe_str(filepath))
    if not filepath.lower().endswith((".igs", ".iges")):
        filepath += ".igs"
    if not surfaces:
        raise RuntimeError("No NURBS surfaces to write.")

    start_lines = [_iges_hline("maya_subDtoNURBS IGES export", "S", 1)]
    now = datetime.datetime.now().strftime("%Y%m%d.%H%M%S")
    g_params = [
        "1H,",
        "1H,",
        "22Hmaya_subDtoNURBS_export",
        "12Hmaya_subDtoNURBS",
        "32HMaya SubD to NURBS",
        "12Hmaya_subDtoNURBS",
        "32",
        "38",
        "6",
        "38",
        "15",
        "22Hmaya_subDtoNURBS_export",
        "1.0",
        "1",
        "4HSING",
        "960",
        "0.0",
        "0.0",
        "13H{0}".format(now),
        "1.0E-6",
        "1.0",
        "8HRSSherry",
        "8HRSSherry",
        "10",
        "0",
        "13H{0}".format(now),
    ]
    g_blob = ",".join(g_params) + ";"
    g_lines = []
    gi = 1
    while g_blob:
        chunk = g_blob[:72]
        g_blob = g_blob[72:]
        g_lines.append(_iges_hline(chunk, "G", gi))
        gi += 1

    d_lines = []
    p_lines = []
    p_index = 1
    de_index = 1

    for surf in surfaces:
        degree_u = surf["degree_u"]
        degree_v = surf["degree_v"]
        cvs = surf["cvs"]
        nu = len(cvs)
        nv = len(cvs[0])
        k1 = nu - 1
        k2 = nv - 1
        m1 = degree_u
        m2 = degree_v
        prop1 = 1 if surf.get("form_u") else 0
        prop2 = 1 if surf.get("form_v") else 0

        params = [
            _fmt_num(k1),
            _fmt_num(k2),
            _fmt_num(m1),
            _fmt_num(m2),
            _fmt_num(prop1),
            _fmt_num(prop2),
            _fmt_num(1),  # polynomial
            _fmt_num(0),
            _fmt_num(0),
        ]
        for ku in surf["knots_u"]:
            params.append(_fmt_num(ku))
        for kv in surf["knots_v"]:
            params.append(_fmt_num(kv))
        # IGES: first subscript (u) varies most rapidly -> v outer, u inner
        for j in range(nv):
            for i in range(nu):
                params.append(_fmt_num(1.0))
        for j in range(nv):
            for i in range(nu):
                x, y, z = cvs[i][j]
                params.extend([_fmt_num(x), _fmt_num(y), _fmt_num(z)])
        ur = surf.get("u_range") or (0.0, 1.0)
        vr = surf.get("v_range") or (0.0, 1.0)
        params.extend(
            [_fmt_num(ur[0]), _fmt_num(ur[1]), _fmt_num(vr[0]), _fmt_num(vr[1])]
        )

        de_ptr = de_index
        plines, p_index = _iges_params_to_lines(params, de_ptr, p_index)
        p_start = p_index - len(plines)
        p_count = len(plines)

        def de_fields(vals):
            chunks = []
            for v in vals:
                if isinstance(v, int):
                    chunks.append("{0:8d}".format(v))
                else:
                    chunks.append(str(v).rjust(8)[:8])
            return "".join(chunks)

        status = "00000000"
        d1 = de_fields([128, p_start, 0, 0, 0, 0, 0, 0]) + status + "D{0:7d}\n".format(de_index)
        label = (surf.get("name") or "SURF")[:8].ljust(8)
        d2 = de_fields([128, 0, 0, p_count, 0, 0, 0, 0]) + label + "D{0:7d}\n".format(de_index + 1)
        d_lines.append(d1)
        d_lines.append(d2)
        p_lines.extend(plines)
        de_index += 2

    t_line = "S{0:7d}G{1:7d}D{2:7d}P{3:7d}{4}T{5:7d}\n".format(
        len(start_lines),
        len(g_lines),
        len(d_lines),
        len(p_lines),
        " " * 40,
        1,
    )

    with open(filepath, "w") as fh:
        for line in start_lines:
            fh.write(line)
        for line in g_lines:
            fh.write(line)
        for line in d_lines:
            fh.write(line)
        for line in p_lines:
            fh.write(line)
        fh.write(t_line)

    return filepath


def _step_knots_unique(knots):
    if not knots:
        return [], []
    vals = [float(knots[0])]
    mults = [1]
    for k in knots[1:]:
        k = float(k)
        if abs(k - vals[-1]) < 1e-12:
            mults[-1] += 1
        else:
            vals.append(k)
            mults.append(1)
    return vals, mults


def write_step(surfaces, filepath):
    """Write minimal STEP AP203 with B_SPLINE_SURFACE_WITH_KNOTS."""
    filepath = os.path.abspath(safe_str(filepath))
    if not filepath.lower().endswith((".stp", ".step")):
        filepath += ".stp"
    if not surfaces:
        raise RuntimeError("No NURBS surfaces to write.")

    entities = []
    eid = [1]

    def add(body):
        i = eid[0]
        eid[0] += 1
        entities.append("#{0} = {1};".format(i, body))
        return i

    now = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    fname = os.path.basename(filepath).replace("'", "")

    app = add(
        "APPLICATION_CONTEXT('configuration controlled 3d designs of mechanical parts and assemblies')"
    )
    pctx = add("PRODUCT_CONTEXT('',#{0},'mechanical')".format(app))
    pdctx = add("PRODUCT_DEFINITION_CONTEXT('part definition',#{0},'design')".format(app))
    prod = add("PRODUCT('export','export','',(#{0}))".format(pctx))
    pdf = add("PRODUCT_DEFINITION_FORMATION('',#{0},#{1})".format(prod, pdctx))
    pd = add("PRODUCT_DEFINITION('design','',#{0},#{1})".format(pdf, pdctx))
    pds = add("PRODUCT_DEFINITION_SHAPE('','',#{0})".format(pd))

    length_unit = add("(LENGTH_UNIT() NAMED_UNIT(*) SI_UNIT(.MILLI.,.METRE.))")
    angle_unit = add("(NAMED_UNIT(*) PLANE_ANGLE_UNIT() SI_UNIT($,.RADIAN.))")
    solid_angle = add("(NAMED_UNIT(*) SI_UNIT($,.STERADIAN.) SOLID_ANGLE_UNIT())")
    unc = add(
        "UNCERTAINTY_MEASURE_WITH_UNIT(LENGTH_MEASURE(1.E-6),#{0},"
        "'distance_accuracy_value','confusion accuracy')".format(length_unit)
    )
    ctx = add(
        "(GEOMETRIC_REPRESENTATION_CONTEXT(3) "
        "GLOBAL_UNCERTAINTY_ASSIGNED_CONTEXT((#{0})) "
        "GLOBAL_UNIT_ASSIGNED_CONTEXT((#{1},#{2},#{3})) "
        "REPRESENTATION_CONTEXT('Context','3D Context with UNIT and UNCERTAINTY'))".format(
            unc, length_unit, angle_unit, solid_angle
        )
    )

    surf_ids = []
    for surf in surfaces:
        degree_u = int(surf["degree_u"])
        degree_v = int(surf["degree_v"])
        cvs = surf["cvs"]
        nu = len(cvs)
        nv = len(cvs[0])

        rows = []
        for i in range(nu):
            cols = []
            for j in range(nv):
                x, y, z = cvs[i][j]
                pid = add(
                    "CARTESIAN_POINT('',({0:.10G},{1:.10G},{2:.10G}))".format(x, y, z)
                )
                cols.append("#{0}".format(pid))
            rows.append("({0})".format(",".join(cols)))
        cpl = "({0})".format(",".join(rows))

        u_vals, u_mults = _step_knots_unique(surf["knots_u"])
        v_vals, v_mults = _step_knots_unique(surf["knots_v"])

        sid = add(
            "B_SPLINE_SURFACE_WITH_KNOTS('',{0},{1},{2},"
            ".UNSPECIFIED.,.F.,.F.,.F.,"
            "({3}),({4}),({5}),({6}),.UNSPECIFIED.)".format(
                degree_u,
                degree_v,
                cpl,
                ",".join(str(int(m)) for m in u_mults),
                ",".join(str(int(m)) for m in v_mults),
                ",".join("{0:.10G}".format(v) for v in u_vals),
                ",".join("{0:.10G}".format(v) for v in v_vals),
            )
        )
        surf_ids.append(sid)

    items = ",".join("#{0}".format(i) for i in surf_ids)
    shape_rep = add("SHAPE_REPRESENTATION('',({0}),#{1})".format(items, ctx))
    add("SHAPE_DEFINITION_REPRESENTATION(#{0},#{1})".format(pds, shape_rep))

    with open(filepath, "w") as fh:
        fh.write("ISO-10303-21;\n")
        fh.write("HEADER;\n")
        fh.write("FILE_DESCRIPTION(('maya_subDtoNURBS'),'2;1');\n")
        fh.write(
            "FILE_NAME('{0}','{1}',('RS-Sherry'),(''),"
            "'maya_subDtoNURBS','maya_subDtoNURBS','');\n".format(fname, now)
        )
        fh.write("FILE_SCHEMA(('CONFIG_CONTROL_DESIGN'));\n")
        fh.write("ENDSEC;\n")
        fh.write("DATA;\n")
        for line in entities:
            fh.write(line + "\n")
        fh.write("ENDSEC;\n")
        fh.write("END-ISO-10303-21;\n")

    return filepath
