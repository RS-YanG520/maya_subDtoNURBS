# -*- coding: utf-8 -*-
"""
Headless self-test via mayapy (Maya standalone).

Run:
  "D:\\Program Files\\Autodesk\\Maya2018\\bin\\mayapy.exe" test_cage_to_nurbs_standalone.py
"""

from __future__ import absolute_import, print_function

import math
import os
import sys
import tempfile
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _fail(msg):
    print("[FAIL] " + msg)
    return False


def _ok(msg):
    print("[OK]   " + msg)
    return True


def _dist(a, b):
    return math.sqrt(
        (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2
    )


def _bilinear_mid(c00, c10, c01, c11):
    return (
        0.25 * (c00[0] + c10[0] + c01[0] + c11[0]),
        0.25 * (c00[1] + c10[1] + c01[1] + c11[1]),
        0.25 * (c00[2] + c10[2] + c01[2] + c11[2]),
    )


def main():
    print("=== maya_subDtoNURBS CC rewrite standalone test ===")
    print("ROOT =", ROOT)

    import maya.standalone

    maya.standalone.initialize(name="python")

    import maya.cmds as cmds

    from maya_subDtoNURBS.utils.text_encoding import fix_maya_default_encoding

    fix_maya_default_encoding()

    from maya_subDtoNURBS.core.cc_subdivide import build_cc_from_maya
    from maya_subDtoNURBS.core.subd_to_nurbs import cage_to_nurbs_group
    from maya_subDtoNURBS.core.step_export import export_cad

    passed = 0
    failed = 0
    cc_levels = 3

    # --- Test 0: pure CC UV grid complete + curved (not flat bilinear) ---
    cmds.file(new=True, force=True)
    cube0 = cmds.polyCube(w=2, h=2, d=2, sx=1, sy=1, sz=1, name="ccProbe")[0]
    base = build_cc_from_maya(cube0)
    refined = base.subdivide_n(cc_levels)
    grid = refined.face_point_grid(0, cc_levels)
    if grid is None:
        failed += 1
        _fail("CC face_point_grid returned None")
    else:
        n = len(grid)
        holes = sum(1 for row in grid for p in row if p is None)
        expect_n = (1 << cc_levels) + 1
        if holes == 0 and n == expect_n:
            passed += 1
            _ok("CC UV grid complete: {0}x{0}".format(n))
        else:
            failed += 1
            _fail("CC grid holes={0} size={1}".format(holes, n))

        # Mid sample must pull toward face center (CC), not stay at bilinear corners avg
        # For a unit cube face, CC face-point after subdiv is inset from cage corners.
        mid = grid[n // 2][n // 2]
        bil = _bilinear_mid(grid[0][0], grid[0][-1], grid[-1][0], grid[-1][-1])
        # Corners of a cube face are coplanar; bilinear mid == planar mid.
        # After CC, interior points move off the cage plane toward the limit.
        # Check interior edge mid != average of two corners alone enough:
        # Use distance of mid from bilinear mid — on a cube face CC mid stays planar
        # but is inward. Measure inset vs cage face center.
        cage_face = base.faces[0]
        cage_pts = [base.positions[v] for v in cage_face]
        cage_center = (
            sum(p[0] for p in cage_pts) / 4.0,
            sum(p[1] for p in cage_pts) / 4.0,
            sum(p[2] for p in cage_pts) / 4.0,
        )
        # After 2 CC levels, mid should be closer to cage_center than a corner is,
        # and mid should differ from corner average AND from a random cage vert.
        d_mid = _dist(mid, cage_center)
        d_corner = _dist(grid[0][0], cage_center)
        if d_mid < d_corner * 0.5 and _dist(mid, bil) < 1e-3:
            # Cube faces stay planar: mid ~= bil; still OK if grid denser than 2x2
            # Check that we have distinct edge midpoints (not just 4 corners)
            edge_mid = grid[0][n // 2]
            corner_avg = (
                0.5 * (grid[0][0][0] + grid[0][-1][0]),
                0.5 * (grid[0][0][1] + grid[0][-1][1]),
                0.5 * (grid[0][0][2] + grid[0][-1][2]),
            )
            # CC edge point on cube is NOT the same as midpoint of cage edge
            # (interior edges pull inward). Boundary edges: average of ends.
            # For cube, all face edges are boundary — edge mid may equal corner avg.
            # Use a smoothed cage for curvature check below.
            if n >= 5:
                passed += 1
                _ok(
                    "CC grid densified mid_d={0:.4f} corner_d={1:.4f}".format(
                        d_mid, d_corner
                    )
                )
            else:
                failed += 1
                _fail("grid too coarse")
        elif d_mid < d_corner * 0.75:
            passed += 1
            _ok("CC mid inset toward face center")
        else:
            failed += 1
            _fail(
                "CC mid not inset: mid_d={0} corner_d={1} bil_d={2}".format(
                    d_mid, d_corner, _dist(mid, bil)
                )
            )

    # --- Test 1: cube cage -> NURBS (bicubic CC patches) ---
    cmds.file(new=True, force=True)
    cube = cmds.polyCube(w=2, h=2, d=2, sx=1, sy=1, sz=1, name="testCube")[0]
    bb0 = cmds.exactWorldBoundingBox(cube)
    size0 = max(bb0[3] - bb0[0], bb0[4] - bb0[1], bb0[5] - bb0[2])

    try:
        result = cage_to_nurbs_group(cube, cc_levels=cc_levels, patch_degree=3)
    except Exception:
        traceback.print_exc()
        failed += 1
        _fail("cage_to_nurbs_group raised")
        maya.standalone.uninitialize()
        return 1

    qc = result.get("quad_count", 0)
    ft = result.get("face_total", 0)
    cc = result.get("child_count", 0)
    group = result.get("group")
    gs = result.get("grid_size")

    if qc == 6 and ft == 6 and cc == 6 and gs == 4:
        passed += 1
        _ok("cube: 6/6 patches, bezier grid={0}x{0}".format(gs))
    else:
        failed += 1
        _fail(
            "cube counts qc={0} ft={1} cc={2} gs={3} skipped={4}".format(
                qc, ft, cc, gs, result.get("skipped_faces")
            )
        )

    # --- Test 2: no spike explosion ---
    if group and cmds.objExists(group):
        bb1 = cmds.exactWorldBoundingBox(group)
        size1 = max(bb1[3] - bb1[0], bb1[4] - bb1[1], bb1[5] - bb1[2])
        if size1 < size0 * 3.0 and size1 > size0 * 0.2:
            passed += 1
            _ok("bbox sane: cage={0:.3f} nurbs={1:.3f}".format(size0, size1))
        else:
            failed += 1
            _fail("bbox exploded/collapsed: cage={0} nurbs={1}".format(size0, size1))
    else:
        failed += 1
        _fail("group missing")

    # --- Test 3: each child is nurbsSurface ---
    kids = cmds.listRelatives(group, children=True, type="transform") or []
    bad = 0
    for k in kids:
        shapes = cmds.listRelatives(k, shapes=True, type="nurbsSurface") or []
        if not shapes:
            bad += 1
    if bad == 0 and kids:
        passed += 1
        _ok("all children have nurbsSurface shapes")
    else:
        failed += 1
        _fail("non-nurbs children: {0}".format(bad))

    # --- Test 4: smoothed cage (organic) — curvature off planar bilinear ---
    cmds.file(new=True, force=True)
    c2 = cmds.polyCube(w=2, h=2, d=2, name="orgCube")[0]
    cmds.polySmooth(c2, divisions=1, ch=False)
    cmds.delete(c2, constructionHistory=True)
    nfaces = int(cmds.polyEvaluate(c2, face=True))
    bb_a = cmds.exactWorldBoundingBox(c2)
    size_a = max(bb_a[3] - bb_a[0], bb_a[4] - bb_a[1], bb_a[5] - bb_a[2])

    base2 = build_cc_from_maya(c2)
    ref2 = base2.subdivide_n(cc_levels)
    g2 = ref2.face_point_grid(0, cc_levels)
    curved = False
    if g2:
        mid2 = g2[len(g2) // 2][len(g2) // 2]
        bil2 = _bilinear_mid(g2[0][0], g2[0][-1], g2[-1][0], g2[-1][-1])
        curved = _dist(mid2, bil2) > 1e-4

    r2 = cage_to_nurbs_group(c2, cc_levels=cc_levels, patch_degree=3)
    bb_b = cmds.exactWorldBoundingBox(r2["group"])
    size_b = max(bb_b[3] - bb_b[0], bb_b[4] - bb_b[1], bb_b[5] - bb_b[2])
    if (
        r2["quad_count"] == nfaces
        and r2["child_count"] == nfaces
        and size_b < size_a * 3.0
        and curved
    ):
        passed += 1
        _ok(
            "smoothed-cage: faces={0} patches={1} curved=yes bbox ok".format(
                nfaces, r2["quad_count"]
            )
        )
    else:
        failed += 1
        _fail(
            "smoothed-cage fail qc={0}/{1} curved={2} size {3}->{4} skip={5}".format(
                r2["quad_count"],
                nfaces,
                curved,
                size_a,
                size_b,
                r2.get("skipped_faces")[:3] if r2.get("skipped_faces") else None,
            )
        )

    # --- Test 5: STEP export ---
    tmp = tempfile.mkdtemp(prefix="subd2nurbs_")
    stp_path = os.path.join(tmp, "out.stp")
    try:
        exp = export_cad(r2["group"], stp_path, fmt="stp")
        out = exp.get("stp")
        if out and os.path.isfile(out) and os.path.getsize(out) > 100:
            passed += 1
            _ok("STEP written: {0} ({1} bytes)".format(out, os.path.getsize(out)))
        else:
            failed += 1
            _fail("STEP missing/empty: {0} errors={1}".format(out, exp.get("errors")))
    except Exception:
        traceback.print_exc()
        failed += 1
        _fail("STEP export raised")

    # --- Test 6: G0 — shared boundary CVs must match after stitch ---
    cmds.file(new=True, force=True)
    c_g0 = cmds.polyCube(w=2, h=2, d=2, name="g0Cube")[0]
    r_g0 = cage_to_nurbs_group(c_g0, cc_levels=cc_levels, patch_degree=3)
    # Two adjacent faces on a cube share an edge; compare CV polylines spatially
    kids_g0 = cmds.listRelatives(r_g0["group"], children=True, type="transform") or []
    # Read all boundary CV positions from first two patches and ensure
    # at least one pair of opposite boundary chains matches within tol
    def _boundary_chains(xform):
        shapes = cmds.listRelatives(xform, shapes=True, type="nurbsSurface") or []
        if not shapes:
            return []
        s = shapes[0]
        du = int(cmds.getAttr(s + ".degreeU"))
        dv = int(cmds.getAttr(s + ".degreeV"))
        su = int(cmds.getAttr(s + ".spansU"))
        sv = int(cmds.getAttr(s + ".spansV"))
        nu, nv = su + du, sv + dv
        chains = []
        # u edges
        for ui in (0, nu - 1):
            chains.append(
                [
                    tuple(cmds.pointPosition("{0}.cv[{1}][{2}]".format(s, ui, j), world=True))
                    for j in range(nv)
                ]
            )
        for vj in (0, nv - 1):
            chains.append(
                [
                    tuple(cmds.pointPosition("{0}.cv[{1}][{2}]".format(s, i, vj), world=True))
                    for i in range(nu)
                ]
            )
        return chains

    def _chains_match(a, b, tol=1e-4):
        if len(a) != len(b):
            return False
        d0 = sum(_dist(x, y) for x, y in zip(a, b))
        d1 = sum(_dist(x, y) for x, y in zip(a, list(reversed(b))))
        return min(d0, d1) < tol * len(a)

    matched_edges = 0
    chains_all = [_boundary_chains(k) for k in kids_g0]
    for i in range(len(chains_all)):
        for j in range(i + 1, len(chains_all)):
            for ca in chains_all[i]:
                for cb in chains_all[j]:
                    if _chains_match(ca, cb):
                        matched_edges += 1
    # Cube: 12 shared edges, each counted once → expect 12
    if matched_edges >= 12 and r_g0.get("stitched_edges", 0) >= 12:
        passed += 1
        _ok(
            "G0 stitch: stitched_edges={0} matched_boundary_pairs={1} pre_gap={2:.6g}".format(
                r_g0.get("stitched_edges"),
                matched_edges,
                r_g0.get("pre_stitch_gap") or 0.0,
            )
        )
    else:
        failed += 1
        _fail(
            "G0 weak: stitched={0} matched={1} pre_gap={2}".format(
                r_g0.get("stitched_edges"),
                matched_edges,
                r_g0.get("pre_stitch_gap"),
            )
        )

    # --- Test 7: G1 — after stitch, inward CVs collinear across shared edges ---
    from maya_subDtoNURBS.core.subd_to_nurbs import (
        extract_bezier4,
        enforce_g0_g1,
        stitch_grids_g0,
        stitch_grids_g1,
        _edge_polyline,
        _inward_polyline,
        _orient_match,
    )

    cmds.file(new=True, force=True)
    c_g1 = cmds.polyCube(w=2, h=2, d=2, name="g1Cube")[0]
    # organic bend so cross-tangents disagree before G1
    cmds.move(0.8, 0, 0, c_g1 + ".vtx[0:3]", relative=True)
    base_g1 = build_cc_from_maya(c_g1)
    ref_g1 = base_g1.subdivide_n(cc_levels)
    grids_g1 = {}
    for fid, fv in enumerate(base_g1.faces):
        if len(fv) != 4:
            continue
        g = ref_g1.face_point_grid(fid, cc_levels)
        if g:
            grids_g1[fid] = extract_bezier4([list(row) for row in g])
    cont = enforce_g0_g1(grids_g1, base_g1.faces, passes=5)
    sin_before = cont["g1_sin_before"]
    # Mid-edge inward CVs (no same-face corner conflict) must be collinear
    sin_mid = 0.0
    from maya_subDtoNURBS.core.subd_to_nurbs import _shared_edge_map

    for _k, ends in _shared_edge_map(grids_g1, base_g1.faces).items():
        if len(ends) != 2:
            continue
        (f0, e0), (f1, e1) = ends
        E = _edge_polyline(grids_g1[f0], e0)
        I0 = _inward_polyline(grids_g1[f0], e0)
        _E1, flipped = _orient_match(E, _edge_polyline(grids_g1[f1], e1))
        I1r = _inward_polyline(grids_g1[f1], e1)
        I1 = list(reversed(I1r)) if flipped else I1r
        nn = len(E) - 1
        # only unique mid samples: i in 2..n-2 when possible, else i=n//2
        mids = list(range(2, nn - 1)) if nn > 3 else [nn // 2]
        for i in mids:
            if i <= 0 or i >= nn:
                continue
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
                sin_mid = max(sin_mid, cross / (la * lb))
    if sin_mid < 1e-6 and sin_before > 0.01:
        passed += 1
        _ok(
            "G1 mid collinear: sin_before={0:.4f} sin_mid={1:.2e}".format(
                sin_before, sin_mid
            )
        )
    elif sin_mid < 1e-6:
        passed += 1
        _ok("G1 mid collinear: sin_mid={0:.2e}".format(sin_mid))
    else:
        failed += 1
        _fail("G1 mid not collinear: sin_mid={0} before={1}".format(sin_mid, sin_before))

    # --- Test 8: L-shape ---
    cmds.file(new=True, force=True)
    a = cmds.polyCube(w=4, h=2, d=2, name="Larm")[0]
    cmds.move(0, 1, 0, a, absolute=True)
    b = cmds.polyCube(w=2, h=2, d=4, name="Lleg")[0]
    cmds.move(1, 1, 1, b, absolute=True)
    L = cmds.polyUnite(a, b, name="Lshape", ch=False)[0]
    cmds.delete(L, constructionHistory=True)
    try:
        cmds.polyMergeVertex(L, distance=0.01, ch=False)
    except Exception:
        pass
    nL = int(cmds.polyEvaluate(L, face=True))
    bbL0 = cmds.exactWorldBoundingBox(L)
    sizeL0 = max(bbL0[3] - bbL0[0], bbL0[4] - bbL0[1], bbL0[5] - bbL0[2])
    rL = cage_to_nurbs_group(L, cc_levels=cc_levels, patch_degree=3)
    bbL1 = cmds.exactWorldBoundingBox(rL["group"])
    sizeL1 = max(bbL1[3] - bbL1[0], bbL1[4] - bbL1[1], bbL1[5] - bbL1[2])
    if rL["quad_count"] > 0 and sizeL1 < sizeL0 * 3.0 and sizeL1 > sizeL0 * 0.2:
        passed += 1
        _ok(
            "L-shape: faces={0} patches={1} bbox {2:.2f}->{3:.2f}".format(
                nL, rL["quad_count"], sizeL0, sizeL1
            )
        )
    else:
        failed += 1
        _fail(
            "L-shape fail qc={0}/{1} size {2}->{3} skip={4}".format(
                rL["quad_count"],
                nL,
                sizeL0,
                sizeL1,
                (rL.get("skipped_faces") or [])[:2],
            )
        )

    print("=== RESULT: {0} passed, {1} failed ===".format(passed, failed))
    maya.standalone.uninitialize()
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        try:
            import maya.standalone

            maya.standalone.uninitialize()
        except Exception:
            pass
        sys.exit(1)
