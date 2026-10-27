# -*- coding: utf-8 -*-
"""
Plasticity-style SubD cage → NURBS (rewrite).

Algorithm:
  1. Read cage as Catmull-Clark control mesh
  2. Subdivide N times in pure Python (CC), tracking UV per original face
  3. Each original quad → (2^N+1)^2 point grid ≈ limit surface samples
  4. G0 stitch: force shared cage edges to identical polylines
  5. Build one bicubic NURBS patch per face using grid as CVs
  6. Group + export STEP
"""

from __future__ import absolute_import, print_function

import collections
import math

import maya.cmds as cmds
import maya.mel as mel

from ..utils.maya_helpers import unique_name
from ..utils.text_encoding import safe_str
from .cc_subdivide import build_cc_from_maya


DEFAULT_CC_LEVELS = 3  # denser limit sample → then extract 4×4 Bézier
G1_PASS_COUNT = 5


def _as_transform(node):
    node = safe_str(node)
    if not cmds.objExists(node):
        return node
    if cmds.nodeType(node) == "nurbsSurface":
        parents = cmds.listRelatives(node, parent=True) or []
        if parents:
            return safe_str(parents[0])
    return node


def _maya_uniform_knots(n_cvs, degree):
    """Maya surface knots: length = n_cvs + degree - 1, end mult <= degree."""
    n_cvs = int(n_cvs)
    degree = int(degree)
    if n_cvs < 2:
        raise ValueError("need >=2 cvs")
    degree = max(1, min(degree, n_cvs - 1))
    n_knots = n_cvs + degree - 1
    if degree == 1 and n_cvs == 2:
        return [0.0, 1.0]
    knots = [0.0] * degree
    interior = n_knots - 2 * degree
    if interior > 0:
        for i in range(1, interior + 1):
            knots.append(float(i) / float(interior + 1))
    knots.extend([1.0] * degree)
    if len(knots) != n_knots:
        return [float(i) / float(max(n_knots - 1, 1)) for i in range(n_knots)]
    return knots


def _dist2(a, b):
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2


def _avg_pt(a, b):
    return (
        0.5 * (a[0] + b[0]),
        0.5 * (a[1] + b[1]),
        0.5 * (a[2] + b[2]),
    )


def _edge_polyline(grid, edge_id):
    """
    Cage edge local id (face winding):
      0: v=0, u 0→1
      1: u=1, v 0→1
      2: v=1, u 1→0
      3: u=0, v 1→0
    """
    n = len(grid) - 1
    if edge_id == 0:
        return [grid[0][i] for i in range(n + 1)]
    if edge_id == 1:
        return [grid[i][n] for i in range(n + 1)]
    if edge_id == 2:
        return [grid[n][i] for i in range(n, -1, -1)]
    if edge_id == 3:
        return [grid[i][0] for i in range(n, -1, -1)]
    raise ValueError("bad edge_id")


def _set_edge_polyline(grid, edge_id, pts):
    n = len(grid) - 1
    if len(pts) != n + 1:
        raise ValueError("edge length mismatch")
    if edge_id == 0:
        for i, p in enumerate(pts):
            grid[0][i] = p
    elif edge_id == 1:
        for i, p in enumerate(pts):
            grid[i][n] = p
    elif edge_id == 2:
        for i, p in enumerate(pts):
            grid[n][n - i] = p
    elif edge_id == 3:
        for i, p in enumerate(pts):
            grid[n - i][0] = p
    else:
        raise ValueError("bad edge_id")


def _orient_match(ref_pts, other_pts):
    """Reverse other if needed so endpoints align with ref. Returns (pts, flipped)."""
    if len(ref_pts) != len(other_pts) or not ref_pts:
        return other_pts, False
    d_same = _dist2(ref_pts[0], other_pts[0]) + _dist2(ref_pts[-1], other_pts[-1])
    d_flip = _dist2(ref_pts[0], other_pts[-1]) + _dist2(ref_pts[-1], other_pts[0])
    if d_flip < d_same:
        return list(reversed(other_pts)), True
    return other_pts, False


def _shared_edge_map(grids, faces):
    edge_map = collections.defaultdict(list)
    for fid, fverts in enumerate(faces):
        if fid not in grids or len(fverts) != 4:
            continue
        for ei in range(4):
            a = fverts[ei]
            b = fverts[(ei + 1) % 4]
            key = (a, b) if a < b else (b, a)
            edge_map[key].append((fid, ei))
    return edge_map


def _inward_polyline(grid, edge_id):
    """First CV row inward from edge, same parameterization as _edge_polyline."""
    n = len(grid) - 1
    if n < 1:
        raise ValueError("grid too small for inward")
    if edge_id == 0:
        return [grid[1][i] for i in range(n + 1)]
    if edge_id == 1:
        return [grid[i][n - 1] for i in range(n + 1)]
    if edge_id == 2:
        return [grid[n - 1][i] for i in range(n, -1, -1)]
    if edge_id == 3:
        return [grid[i][1] for i in range(n, -1, -1)]
    raise ValueError("bad edge_id")


def _set_inward_polyline(grid, edge_id, pts, interior_only=True):
    """
    Write inward row. interior_only skips endpoints (they lie on side
    boundaries — moving them would break G0 with other neighbors).
    """
    n = len(grid) - 1
    if len(pts) != n + 1:
        raise ValueError("inward length mismatch")
    lo = 1 if (interior_only and n >= 2) else 0
    hi = n if (interior_only and n >= 2) else n + 1
    if edge_id == 0:
        for i in range(lo, hi):
            grid[1][i] = pts[i]
    elif edge_id == 1:
        for i in range(lo, hi):
            grid[i][n - 1] = pts[i]
    elif edge_id == 2:
        for i in range(lo, hi):
            grid[n - 1][n - i] = pts[i]
    elif edge_id == 3:
        for i in range(lo, hi):
            grid[n - i][1] = pts[i]
    else:
        raise ValueError("bad edge_id")


def stitch_grids_g0(grids, faces):
    """
    Force shared cage edges to identical sample polylines (positional G0).
    Returns (stitched_count, max_gap_before).
    """
    stitched = 0
    max_gap = 0.0
    for _key, ends in _shared_edge_map(grids, faces).items():
        if len(ends) != 2:
            continue
        (f0, e0), (f1, e1) = ends
        g0 = grids[f0]
        g1 = grids[f1]
        p0 = _edge_polyline(g0, e0)
        p1, _flipped = _orient_match(p0, _edge_polyline(g1, e1))
        before = 0.0
        for a, b in zip(p0, p1):
            before = max(before, math.sqrt(_dist2(a, b)))
        max_gap = max(max_gap, before)
        merged = [_avg_pt(a, b) for a, b in zip(p0, p1)]
        _set_edge_polyline(g0, e0, merged)
        p1_native = _edge_polyline(g1, e1)
        merged_for_g1, _ = _orient_match(p1_native, merged)
        _set_edge_polyline(g1, e1, merged_for_g1)
        stitched += 1
    return stitched, max_gap


def _inward_rc(edge_id, i, n):
    """Map (edge_id, param index i) → (row, col) of inward CV."""
    if edge_id == 0:
        return (1, i)
    if edge_id == 1:
        return (i, n - 1)
    if edge_id == 2:
        return (n - 1, n - i)
    if edge_id == 3:
        return (n - i, 1)
    raise ValueError("bad edge_id")


def stitch_grids_g1(grids, faces, include_ends=True):
    """
    Approximate G1 across shared edges: first inward CV row collinear
    through the shared edge with averaged cross-tangent.

    include_ends=True also adjusts inward endpoints (they lie on side
    boundaries). Side G0 is restored by a following stitch_grids_g0 pass.

    Returns (stitched_count, max_sin_before).
    """
    proposals = collections.defaultdict(list)  # (fid, r, c) -> [pt, ...]
    stitched = 0
    max_sin = 0.0

    for _key, ends in _shared_edge_map(grids, faces).items():
        if len(ends) != 2:
            continue
        (f0, e0), (f1, e1) = ends
        g0 = grids[f0]
        g1 = grids[f1]
        n = len(g0) - 1
        if n < 1:
            continue

        E = _edge_polyline(g0, e0)
        I0 = _inward_polyline(g0, e0)
        _E1, flipped = _orient_match(E, _edge_polyline(g1, e1))
        I1_raw = _inward_polyline(g1, e1)
        I1 = list(reversed(I1_raw)) if flipped else I1_raw

        i_lo = 0 if include_ends else 1
        i_hi = n + 1 if include_ends else n
        for i in range(i_lo, i_hi):
            e = E[i]
            ta = (I0[i][0] - e[0], I0[i][1] - e[1], I0[i][2] - e[2])
            tb = (e[0] - I1[i][0], e[1] - I1[i][1], e[2] - I1[i][2])
            cx = ta[1] * tb[2] - ta[2] * tb[1]
            cy = ta[2] * tb[0] - ta[0] * tb[2]
            cz = ta[0] * tb[1] - ta[1] * tb[0]
            cross = math.sqrt(cx * cx + cy * cy + cz * cz)
            la = math.sqrt(ta[0] ** 2 + ta[1] ** 2 + ta[2] ** 2)
            lb = math.sqrt(tb[0] ** 2 + tb[1] ** 2 + tb[2] ** 2)
            if la * lb > 1e-20:
                max_sin = max(max_sin, cross / (la * lb))
            t = (0.5 * (ta[0] + tb[0]), 0.5 * (ta[1] + tb[1]), 0.5 * (ta[2] + tb[2]))
            p0 = (e[0] + t[0], e[1] + t[1], e[2] + t[2])
            p1 = (e[0] - t[0], e[1] - t[1], e[2] - t[2])
            r0, c0 = _inward_rc(e0, i, n)
            proposals[(f0, r0, c0)].append(p0)
            j = (n - i) if flipped else i
            r1, c1 = _inward_rc(e1, j, n)
            proposals[(f1, r1, c1)].append(p1)

        stitched += 1

    for (fid, r, c), pts in proposals.items():
        if fid not in grids:
            continue
        sx = sy = sz = 0.0
        for p in pts:
            sx += p[0]
            sy += p[1]
            sz += p[2]
        inv = 1.0 / float(len(pts))
        grids[fid][r][c] = (sx * inv, sy * inv, sz * inv)

    return stitched, max_sin


def _sample_grid_bilinear(grid, u, v):
    """u,v in [0,1] on an (n+1)x(n+1) grid[v][u]."""
    n = len(grid) - 1
    fu = max(0.0, min(float(n), u * float(n)))
    fv = max(0.0, min(float(n), v * float(n)))
    i0 = int(math.floor(fu))
    j0 = int(math.floor(fv))
    i1 = min(i0 + 1, n)
    j1 = min(j0 + 1, n)
    su = fu - float(i0)
    sv = fv - float(j0)
    p00 = grid[j0][i0]
    p10 = grid[j0][i1]
    p01 = grid[j1][i0]
    p11 = grid[j1][i1]

    def lerp(p, q, t):
        return (
            p[0] + (q[0] - p[0]) * t,
            p[1] + (q[1] - p[1]) * t,
            p[2] + (q[2] - p[2]) * t,
        )

    return lerp(lerp(p00, p10, su), lerp(p01, p11, su), sv)


def extract_bezier4(grid):
    """Downsample any >=4 grid to a 4×4 bicubic Bézier CV net."""
    if len(grid) == 4 and len(grid[0]) == 4:
        return [list(row) for row in grid]
    ts = (0.0, 1.0 / 3.0, 2.0 / 3.0, 1.0)
    return [[_sample_grid_bilinear(grid, u, v) for u in ts] for v in ts]


def enforce_g0_g1(grids, faces, passes=G1_PASS_COUNT):
    """
    Alternate G0 (shared boundary CVs) and full-row G1 until stable.
    Full-row G1 moves side-boundary CVs; the next G0 re-syncs neighbors.
    """
    stitched = 0
    pre_gap = 0.0
    g1_stitched = 0
    g1_sin = 0.0
    for p in range(int(passes)):
        s0, gap = stitch_grids_g0(grids, faces)
        s1, sinb = stitch_grids_g1(grids, faces, include_ends=True)
        if p == 0:
            stitched, pre_gap = s0, gap
            g1_sin = sinb
        g1_stitched = s1
        # final G0 so exported boundaries match exactly
    s0, gap = stitch_grids_g0(grids, faces)
    if stitched == 0:
        stitched, pre_gap = s0, gap
    return {
        "stitched_edges": stitched,
        "pre_stitch_gap": pre_gap,
        "g1_stitched_edges": g1_stitched,
        "g1_sin_before": g1_sin,
        "g1_passes": int(passes),
    }


def _create_surface_from_grid(grid, name, degree=3):
    """
    Build NURBS using grid points as CVs (exact boundary CVs → STP G0).
    Fallback to loft if MEL surface fails.
    """
    wanted = unique_name(safe_str(name))
    nv = len(grid)
    nu = len(grid[0])
    degree = int(degree)
    du = max(1, min(degree, nu - 1))
    dv = max(1, min(degree, nv - 1))

    ku = _maya_uniform_knots(nu, du)
    kv = _maya_uniform_knots(nv, dv)
    flat = []
    for row in grid:
        flat.extend(row)
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
        if isinstance(result, (list, tuple)):
            result = result[0]
        return safe_str(_as_transform(result))
    except Exception:
        pass

    # Fallback: loft (interpolation — weaker STP edge match)
    curves = []
    try:
        for row in grid:
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
        surf = _as_transform(result)
        if surf != wanted and cmds.objExists(surf):
            try:
                surf = cmds.rename(surf, wanted)
            except Exception:
                pass
        return safe_str(_as_transform(surf))
    finally:
        dead = [c for c in curves if c and cmds.objExists(c)]
        if dead:
            try:
                cmds.delete(dead)
            except Exception:
                pass


def _align_grid_to_maya_normal(grid, maya_normal):
    """Flip U if Newell normal of grid corners disagrees with Maya face normal."""
    if not maya_normal:
        return grid
    c00, c10 = grid[0][0], grid[0][-1]
    c01, c11 = grid[-1][0], grid[-1][-1]
    pts = [c00, c10, c11, c01, c00]
    nx = ny = nz = 0.0
    for a, b in zip(pts, pts[1:]):
        nx += (a[1] - b[1]) * (a[2] + b[2])
        ny += (a[2] - b[2]) * (a[0] + b[0])
        nz += (a[0] - b[0]) * (a[1] + b[1])
    if nx * maya_normal[0] + ny * maya_normal[1] + nz * maya_normal[2] < 0.0:
        return [list(reversed(row)) for row in grid]
    return grid


def _maya_face_normal(shape, fid):
    import re

    info = cmds.polyInfo("{0}.f[{1}]".format(shape, fid), faceNormals=True) or []
    if not info:
        return None
    m = re.search(
        r"([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)\s+"
        r"([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)\s+"
        r"([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)",
        safe_str(info[0]),
    )
    if not m:
        return None
    return (float(m.group(1)), float(m.group(2)), float(m.group(3)))


def cage_to_nurbs_group(
    mesh_transform,
    group_name=None,
    cc_levels=DEFAULT_CC_LEVELS,
    patch_degree=3,
    # legacy kwargs ignored (kept so old callers don't crash)
    use_neighborhood=False,
    prefer_bicubic=True,
):
    """
    Convert SubD/polygon cage → NURBS group via CC subdivision sampling + G0 stitch.
    """
    mesh_transform = safe_str(mesh_transform)
    short = safe_str(mesh_transform.split("|")[-1])
    group_name = safe_str(group_name or unique_name(short + "_NURBS"))
    cc_levels = max(1, min(int(cc_levels), 4))
    patch_degree = max(1, min(int(patch_degree), 3))

    base = build_cc_from_maya(mesh_transform)
    shapes = cmds.listRelatives(mesh_transform, shapes=True, fullPath=True, type="mesh") or []
    shape = safe_str(shapes[0])

    refined = base.subdivide_n(cc_levels)

    grids = {}
    normals = {}
    skipped = []
    face_total = 0

    for fid, fverts in enumerate(base.faces):
        face_total += 1
        if len(fverts) != 4:
            skipped.append((fid, "non-quad verts={0}".format(len(fverts))))
            continue
        grid = refined.face_point_grid(fid, cc_levels)
        if grid is None:
            skipped.append((fid, "UV grid incomplete after CC"))
            continue
        # Dense CC samples → single-span bicubic Bézier (4×4 CVs)
        grids[fid] = extract_bezier4([list(row) for row in grid])
        normals[fid] = _maya_face_normal(shape, fid)

    # Multi-pass G0/G1 on Bézier nets (full inward row + re-sync sides)
    cont = enforce_g0_g1(grids, base.faces, passes=G1_PASS_COUNT)
    stitched = cont["stitched_edges"]
    pre_gap = cont["pre_stitch_gap"]
    g1_stitched = cont["g1_stitched_edges"]
    g1_sin = cont["g1_sin_before"]
    grid_size = 4

    for fid in list(grids.keys()):
        grids[fid] = _align_grid_to_maya_normal(grids[fid], normals.get(fid))

    group = safe_str(cmds.group(empty=True, name=group_name))
    surfaces = []
    quad_count = 0

    try:
        cmds.refresh(suspend=True)
        for fid in sorted(grids.keys()):
            patch_name = "{0}_f{1}".format(short, fid)
            try:
                surf = _create_surface_from_grid(
                    grids[fid], patch_name, degree=patch_degree
                )
                try:
                    parented = cmds.parent(surf, group)
                    if isinstance(parented, (list, tuple)):
                        surf = safe_str(parented[0].split("|")[-1])
                    else:
                        surf = safe_str(parented)
                except Exception:
                    try:
                        cmds.parent(
                            cmds.ls(surf, long=True)[0],
                            cmds.ls(group, long=True)[0],
                        )
                    except Exception as pe:
                        skipped.append((fid, "parent:{0}".format(safe_str(pe))))
                        continue
                surfaces.append(surf)
                quad_count += 1
            except Exception as exc:
                skipped.append((fid, safe_str(exc)))
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
        error_sample = "no faces"

    return {
        "group": group,
        "surfaces": surfaces,
        "skipped_faces": skipped,
        "quad_count": quad_count,
        "face_total": face_total,
        "child_count": len(children),
        "regular_count": quad_count,
        "approx_count": 0,
        "rejected_nbh": 0,
        "cc_levels": cc_levels,
        "grid_size": grid_size,
        "stitched_edges": stitched,
        "pre_stitch_gap": pre_gap,
        "g1_stitched_edges": g1_stitched,
        "g1_sin_before": g1_sin,
        "g1_passes": cont.get("g1_passes", G1_PASS_COUNT),
        "error_sample": error_sample,
        "mode": "cc_limit_patch",
    }
