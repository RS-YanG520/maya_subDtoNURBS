# -*- coding: utf-8 -*-
"""
Verbose debug harness for cage->NURBS.

  $env:MAYA_APP_DIR="$env:TEMP\\maya_subDtoNURBS_test_app"
  & "D:\\Program Files\\Autodesk\\Maya2018\\bin\\mayapy.exe" debug_convert.py
"""

from __future__ import absolute_import, print_function

import math
import os
import sys
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _dist(a, b):
    return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(3)))


def _avg(pts):
    n = float(len(pts))
    return tuple(sum(p[i] for p in pts) / n for i in range(3))


def diagnose_group(group, source_mesh, label):
    import maya.cmds as cmds

    print("---- diagnose: {0} ----".format(label))
    kids = cmds.listRelatives(group, children=True, type="transform") or []
    print("  children:", len(kids))
    bb_s = cmds.exactWorldBoundingBox(source_mesh)
    bb_g = cmds.exactWorldBoundingBox(group)
    size_s = max(bb_s[3] - bb_s[0], bb_s[4] - bb_s[1], bb_s[5] - bb_s[2])
    size_g = max(bb_g[3] - bb_g[0], bb_g[4] - bb_g[1], bb_g[5] - bb_g[2])
    print("  bbox source={0:.4f} group={1:.4f} ratio={2:.3f}".format(
        size_s, size_g, size_g / max(size_s, 1e-8)
    ))

    # Face centers of source
    shapes = cmds.listRelatives(source_mesh, shapes=True, type="mesh") or []
    shape = shapes[0]
    nfaces = int(cmds.polyEvaluate(shape, face=True))
    face_centers = []
    for i in range(nfaces):
        vids = cmds.polyListComponentConversion(
            "{0}.f[{1}]".format(shape, i), fromFace=True, toVertex=True
        )
        vids = cmds.ls(vids, flatten=True) or []
        pts = [
            cmds.xform(v, q=True, ws=True, t=True) for v in vids
        ]
        face_centers.append(_avg([(p[0], p[1], p[2]) for p in pts]))

    spikes = 0
    flipped_hint = 0
    for k in kids:
        sh = cmds.listRelatives(k, shapes=True, type="nurbsSurface") or []
        if not sh:
            print("  ! no nurbsSurface on", k)
            continue
        # sample surface center cv bbox vs nearest face
        cvs = cmds.ls(k + ".cv[*][*]", flatten=True) or []
        if not cvs:
            # try shape path
            cvs = cmds.ls(sh[0] + ".cv[*][*]", flatten=True) or []
        pts = []
        for cv in cvs[:64]:
            pts.append(tuple(cmds.pointPosition(cv, world=True)))
        if not pts:
            print("  ! no CVs on", k)
            continue
        sc = _avg(pts)
        # nearest face center
        nearest = min(face_centers, key=lambda fc: _dist(fc, sc)) if face_centers else sc
        d = _dist(sc, nearest)
        extent = max(_dist(p, sc) for p in pts)
        if d > size_s * 0.5 or extent > size_s * 0.8:
            spikes += 1
            print("  SPIKE? {0} dist_to_face={1:.3f} cv_extent={2:.3f}".format(k, d, extent))

        # Normal hint: compare surface endNormal approx via loft orientation
        # Use closestPointOnSurface + normal if node available — skip if not

    print("  spike_suspects={0}".format(spikes))
    return spikes == 0 and size_g < size_s * 3.0


def build_L():
    import maya.cmds as cmds

    a = cmds.polyCube(w=4, h=2, d=2, name="Larm")[0]
    cmds.move(0, 1, 0, a)
    b = cmds.polyCube(w=2, h=2, d=4, name="Lleg")[0]
    cmds.move(1, 1, 1, b)
    L = cmds.polyUnite(a, b, name="Lshape", ch=False)[0]
    cmds.delete(L, ch=True)
    try:
        cmds.polyMergeVertex(L, distance=0.01, ch=False)
    except Exception:
        pass
    return L


def build_organic():
    """Closer to user SubD cage: cube smoothed then lightly deformed."""
    import maya.cmds as cmds

    c = cmds.polyCube(w=3, h=2, d=2, sx=2, sy=2, sz=2, name="organic")[0]
    cmds.polySmooth(c, divisions=1, ch=False)
    cmds.delete(c, ch=True)
    # pull a few verts to make bean-like
    n = int(cmds.polyEvaluate(c, vertex=True))
    for i in range(0, min(n, 8)):
        cmds.move(0.15, 0.1, 0.0, "{0}.vtx[{1}]".format(c, i), relative=True)
    return c


def main():
    print("=== DEBUG CONVERT ===")
    import maya.standalone

    maya.standalone.initialize(name="python")
    import maya.cmds as cmds

    from maya_subDtoNURBS.utils.text_encoding import fix_maya_default_encoding

    fix_maya_default_encoding()
    from maya_subDtoNURBS.core.subd_to_nurbs import cage_to_nurbs_group
    from maya_subDtoNURBS.core.cage_topology import CageMesh

    cases = [
        ("cube", lambda: cmds.polyCube(w=2, h=2, d=2, name="dbgCube")[0]),
        ("L", build_L),
        ("organic", build_organic),
    ]

    all_ok = True
    for name, builder in cases:
        print("\n######## CASE {0} ########".format(name))
        cmds.file(new=True, force=True)
        mesh = builder()
        cage = CageMesh(mesh)
        print("  verts={0} faces={1}".format(cage.n_verts, cage.n_faces))
        quads = sum(1 for f in cage.faces if len(f) == 4)
        print("  quads={0} nonquad={1}".format(quads, cage.n_faces - quads))

        # dump first 3 faces winding + Maya normal
        for fid in range(min(3, cage.n_faces)):
            info = cmds.polyInfo("{0}.f[{1}]".format(cage.shape, fid), faceNormals=True)
            print("  face{0} verts={1} normalInfo={2}".format(
                fid, cage.faces[fid], info
            ))

        result = cage_to_nurbs_group(mesh, use_neighborhood=False, patch_degree=1)
        print("  result qc={0} ft={1} cc={2} skipped={3}".format(
            result["quad_count"],
            result["face_total"],
            result["child_count"],
            result.get("skipped_faces")[:5],
        ))
        ok = diagnose_group(result["group"], mesh, name)
        if not ok:
            all_ok = False
            print("  >>> CASE FAILED")
        else:
            print("  >>> CASE OK")

        # Also try reverseSurface pass simulation: check if any surface needs flip
        kids = cmds.listRelatives(result["group"], c=True, type="transform") or []
        print("  sample children:", kids[:5])

    print("\n=== DEBUG DONE all_ok={0} ===".format(all_ok))
    maya.standalone.uninitialize()
    return 0 if all_ok else 2


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
