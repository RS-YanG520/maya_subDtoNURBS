# -*- coding: utf-8 -*-
"""
Convert polygon mesh (preferably quads) to a group of NURBS patches.

Industrial-CAD-safe approach:
  - One bilinear (deg 1, 2x2 CV) NURBS per quad — matches the face exactly
  - Consistent outward winding (avoids black flipped faces in CAD)
  - No loft/autoReverse (those caused twisted/circular artifacts)
"""

from __future__ import absolute_import, print_function

import maya.cmds as cmds
import maya.mel as mel

from ..constants import DEFAULT_DEGREE_U, DEFAULT_DEGREE_V
from ..utils.maya_helpers import unique_name
from ..utils.text_encoding import safe_str

DEFAULT_MAX_FACES = 2000


def _iter_faces(mesh_transform):
    """Yield (face_id, [(x,y,z), ...]) in world space via cmds."""
    mesh_transform = safe_str(mesh_transform)
    shapes = cmds.listRelatives(mesh_transform, shapes=True, fullPath=True, type="mesh") or []
    if not shapes:
        return
    shape = safe_str(shapes[0])
    nfaces = int(cmds.polyEvaluate(shape, face=True) or 0)

    for i in range(nfaces):
        face = "{0}.f[{1}]".format(shape, i)
        try:
            vtx_comps = cmds.polyListComponentConversion(
                face, fromFace=True, toVertex=True
            )
            vtx_comps = cmds.ls(vtx_comps, flatten=True) or []
        except Exception:
            vtx_comps = []

        if not vtx_comps:
            try:
                info = cmds.polyInfo(face, faceToVertex=True) or []
                if not info:
                    continue
                line = safe_str(info[0])
                parts = line.replace(":", " ").split()
                indices = []
                for tok in parts:
                    try:
                        indices.append(int(tok))
                    except ValueError:
                        continue
                if len(indices) >= 5:
                    indices = indices[1:]
                vtx_comps = ["{0}.vtx[{1}]".format(shape, v) for v in indices]
            except Exception:
                continue

        pts = []
        for vtx in vtx_comps:
            p = cmds.xform(vtx, query=True, worldSpace=True, translation=True)
            pts.append((float(p[0]), float(p[1]), float(p[2])))
        if pts:
            yield i, pts


def _bbox_center(mesh_transform):
    bb = cmds.exactWorldBoundingBox(mesh_transform)
    return (
        0.5 * (bb[0] + bb[3]),
        0.5 * (bb[1] + bb[4]),
        0.5 * (bb[2] + bb[5]),
    )


def _face_normal(points4):
    p0, p1, p2, p3 = points4
    # Newell on quad
    nx = ny = nz = 0.0
    pts = [p0, p1, p2, p3, p0]
    for a, b in zip(pts, pts[1:]):
        nx += (a[1] - b[1]) * (a[2] + b[2])
        ny += (a[2] - b[2]) * (a[0] + b[0])
        nz += (a[0] - b[0]) * (a[1] + b[1])
    return (nx, ny, nz)


def _centroid(points):
    n = float(len(points))
    return (
        sum(p[0] for p in points) / n,
        sum(p[1] for p in points) / n,
        sum(p[2] for p in points) / n,
    )


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _ensure_outward(points4, mesh_center):
    """Reverse winding if face normal points toward mesh center (inward)."""
    n = _face_normal(points4)
    fc = _centroid(points4)
    outward = (fc[0] - mesh_center[0], fc[1] - mesh_center[1], fc[2] - mesh_center[2])
    if _dot(n, outward) < 0.0:
        return [points4[0], points4[3], points4[2], points4[1]]
    return list(points4)


def _as_transform(node):
    node = safe_str(node)
    if not cmds.objExists(node):
        return node
    ntype = cmds.nodeType(node)
    if ntype == "transform":
        return node
    if ntype == "nurbsSurface":
        parents = cmds.listRelatives(node, parent=True, fullPath=False) or []
        if parents:
            return safe_str(parents[0])
    return node


def _lerp(a, b, t):
    return (
        a[0] + (b[0] - a[0]) * t,
        a[1] + (b[1] - a[1]) * t,
        a[2] + (b[2] - a[2]) * t,
    )


def _maya_style_knots(n_cvs, degree):
    """
    Knot vector for Maya's `surface` command (requires -ku/-kv).

    Maya 2018 rules:
      - length = n_cvs + degree - 1
      - end multiplicity <= degree  (NOT degree+1)
    Examples:
      deg1, 2 CVs -> [0, 1]
      deg3, 4 CVs -> [0, 0, 0, 1, 1, 1]
    """
    n_cvs = int(n_cvs)
    degree = int(degree)
    n_knots = n_cvs + degree - 1
    if n_cvs == 2 and degree == 1:
        return [0.0, 1.0]
    knots = [0.0] * degree
    n_interior = n_knots - 2 * degree
    if n_interior > 0:
        for i in range(1, n_interior + 1):
            knots.append(float(i) / float(n_interior + 1))
    knots.extend([1.0] * degree)
    if len(knots) != n_knots:
        return [float(i) / float(max(n_knots - 1, 1)) for i in range(n_knots)]
    return knots


def _make_nurbs_from_quad(points4, name, degree_u=1, degree_v=1):
    """
    Create a NURBS patch for one quad.

    Maya 2018 `surface` ALWAYS needs -ku/-kv, with Maya-style knots.
    Primary path: loft (stable). Fallback: surface MEL with correct knots.
    """
    if len(points4) != 4:
        raise ValueError("Expected 4 points, got {0}".format(len(points4)))

    degree_u = max(1, int(degree_u))
    degree_v = max(1, int(degree_v))
    du = 1 if degree_u == 1 else min(degree_u, 3)
    dv = 1 if degree_v == 1 else min(degree_v, 3)

    p00, p10, p11, p01 = points4[0], points4[1], points4[2], points4[3]
    wanted = unique_name(safe_str(name))

    # Build CV rows along V (each row is a U curve)
    if du == 1 and dv == 1:
        rows = [[p00, p10], [p01, p11]]
    else:
        ts_u = [float(i) / du for i in range(du + 1)]
        ts_v = [float(i) / dv for i in range(dv + 1)]
        rows = []
        for v in ts_v:
            left = _lerp(p00, p01, v)
            right = _lerp(p10, p11, v)
            rows.append([_lerp(left, right, u) for u in ts_u])

    # --- Primary: loft (no knot flags needed; autoReverse OFF) ---
    curves = []
    try:
        for row in rows:
            curves.append(cmds.curve(degree=du, point=list(row)))
        result = cmds.loft(
            curves,
            ch=False,
            uniform=True,
            degree=dv,
            autoReverse=False,
            reverseSurfaceNormals=False,
            polygon=0,
            name=wanted,
        )
        if isinstance(result, (list, tuple)):
            result = result[0]
        surf = safe_str(_as_transform(result))
        if surf != wanted and cmds.objExists(surf):
            try:
                surf = safe_str(cmds.rename(surf, wanted))
            except Exception:
                pass
        return safe_str(_as_transform(surf))
    except Exception as loft_exc:
        loft_err = safe_str(loft_exc)
    finally:
        leftover = [c for c in curves if c and cmds.objExists(c)]
        if leftover:
            try:
                cmds.delete(leftover)
            except Exception:
                pass

    # --- Fallback: surface MEL with Maya-style -ku/-kv ---
    flat = []
    for row in rows:
        flat.extend(row)
    nu = len(rows[0])
    nv = len(rows)
    ku = _maya_style_knots(nu, du)
    kv = _maya_style_knots(nv, dv)

    parts = [
        'surface -name "{0}" -degreeU {1} -degreeV {2}'.format(wanted, du, dv)
    ]
    for k in ku:
        parts.append("-ku {0}".format(k))
    for k in kv:
        parts.append("-kv {0}".format(k))
    for pt in flat:
        parts.append("-p {0} {1} {2}".format(pt[0], pt[1], pt[2]))

    try:
        result = mel.eval(" ".join(parts))
    except Exception as mel_exc:
        raise RuntimeError(
            "loft:{0} | surface:{1}".format(loft_err, safe_str(mel_exc))
        )

    if isinstance(result, (list, tuple)):
        result = result[0]
    return safe_str(_as_transform(result))


def mesh_to_nurbs_group(
    mesh_transform,
    group_name=None,
    degree_u=DEFAULT_DEGREE_U,
    degree_v=DEFAULT_DEGREE_V,
    skip_non_quad=True,
    max_faces=DEFAULT_MAX_FACES,
):
    """
    Convert each face into a NURBS patch under a group.
    """
    mesh_transform = safe_str(mesh_transform)
    short = safe_str(mesh_transform.split("|")[-1])
    base_short = short.replace("_subDBake", "")
    group_name = safe_str(group_name or unique_name(base_short + "_NURBS"))

    shapes = cmds.listRelatives(mesh_transform, shapes=True, fullPath=True, type="mesh") or []
    nfaces = 0
    if shapes:
        nfaces = int(cmds.polyEvaluate(shapes[0], face=True) or 0)
        if max_faces and nfaces > int(max_faces):
            raise RuntimeError(
                "Too many faces after smooth ({0} > {1}). Lower smooth level.".format(
                    nfaces, max_faces
                )
            )

    mesh_center = _bbox_center(mesh_transform)
    group = safe_str(cmds.group(empty=True, name=group_name))

    surfaces = []
    skipped = []
    quad_count = 0
    face_total = 0

    # For CAD integrity default to bilinear unless user set higher degree
    # (UI still passes degree; 3 is ok but 1 is recommended)
    try:
        cmds.refresh(suspend=True)
        for face_id, pts in _iter_faces(mesh_transform):
            face_total += 1
            n = len(pts)
            if n != 4:
                if n == 3 and not skip_non_quad:
                    pts = [pts[0], pts[1], pts[2], pts[2]]
                else:
                    skipped.append((face_id, "non-quad verts={0}".format(n)))
                    continue

            pts = _ensure_outward(pts, mesh_center)
            patch_name = "{0}_f{1}".format(base_short, face_id)
            try:
                surf = _make_nurbs_from_quad(pts, patch_name, degree_u, degree_v)
                try:
                    parented = cmds.parent(surf, group)
                    if isinstance(parented, (list, tuple)):
                        surf = safe_str(parented[0].split("|")[-1])
                    else:
                        surf = safe_str(parented)
                except Exception as pe:
                    try:
                        full_surf = cmds.ls(surf, long=True)[0]
                        full_grp = cmds.ls(group, long=True)[0]
                        parented = cmds.parent(full_surf, full_grp)
                        surf = safe_str(
                            parented[0].split("|")[-1]
                            if isinstance(parented, (list, tuple))
                            else parented
                        )
                    except Exception:
                        skipped.append(
                            (face_id, "parent failed: {0}".format(safe_str(pe)))
                        )
                        if cmds.objExists(surf):
                            surfaces.append(surf)
                            quad_count += 1
                        continue
                surfaces.append(surf)
                quad_count += 1
            except Exception as exc:
                skipped.append((face_id, safe_str(exc)))
    finally:
        try:
            cmds.refresh(suspend=False)
        except Exception:
            pass

    children = cmds.listRelatives(group, children=True, type="transform") or []
    error_sample = ""
    if skipped:
        error_sample = safe_str(skipped[0][1])
    if face_total == 0:
        error_sample = "no faces iterated (mesh read failed)"

    return {
        "group": group,
        "surfaces": surfaces,
        "skipped_faces": skipped,
        "quad_count": quad_count,
        "face_total": face_total,
        "child_count": len(children),
        "error_sample": error_sample,
    }
