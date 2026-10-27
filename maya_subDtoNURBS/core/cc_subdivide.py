# -*- coding: utf-8 -*-
"""
Pure-Python Catmull-Clark subdivision with per-original-face UV tracking.

Each current face knows its ancestor original face id (`face_orig`).
New face/edge/vertex points only store UV for that lineage → clean
(2^N+1)^2 grids per cage quad after N levels.
"""

from __future__ import absolute_import, print_function

import collections


def _avg(points):
    n = float(len(points))
    return (
        sum(p[0] for p in points) / n,
        sum(p[1] for p in points) / n,
        sum(p[2] for p in points) / n,
    )


def _lerp(a, b, t):
    return (
        a[0] + (b[0] - a[0]) * t,
        a[1] + (b[1] - a[1]) * t,
        a[2] + (b[2] - a[2]) * t,
    )


class CCMesh(object):
    def __init__(
        self,
        positions,
        faces,
        vert_face_uv=None,
        face_orig=None,
        n_orig_faces=None,
    ):
        self.positions = [tuple(p) for p in positions]
        self.faces = [list(f) for f in faces]
        self.n_orig_faces = (
            n_orig_faces if n_orig_faces is not None else len(self.faces)
        )
        if face_orig is None:
            self.face_orig = list(range(len(self.faces)))
        else:
            self.face_orig = list(face_orig)

        if vert_face_uv is None:
            self.vert_face_uv = [dict() for _ in self.positions]
            for fid, fverts in enumerate(self.faces):
                if len(fverts) != 4:
                    continue
                oid = self.face_orig[fid]
                uvs = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
                for vid, uv in zip(fverts, uvs):
                    self.vert_face_uv[vid][oid] = uv
        else:
            self.vert_face_uv = vert_face_uv

    def subdivide(self):
        positions = self.positions
        faces = self.faces
        n_verts = len(positions)

        edge_faces = collections.defaultdict(list)
        vert_faces = collections.defaultdict(list)
        vert_edges = collections.defaultdict(set)

        for fid, fverts in enumerate(faces):
            nv = len(fverts)
            for i, vid in enumerate(fverts):
                vert_faces[vid].append(fid)
                a = fverts[i]
                b = fverts[(i + 1) % nv]
                e = (a, b) if a < b else (b, a)
                edge_faces[e].append(fid)
                vert_edges[a].add(e)
                vert_edges[b].add(e)

        new_positions = []
        new_uv = []

        # Face points
        face_pt_index = {}
        face_pts = [None] * len(faces)
        for fid, fverts in enumerate(faces):
            fp = _avg([positions[v] for v in fverts])
            face_pts[fid] = fp
            face_pt_index[fid] = len(new_positions)
            new_positions.append(fp)
            oid = self.face_orig[fid]
            uvs = [
                self.vert_face_uv[v][oid]
                for v in fverts
                if oid in self.vert_face_uv[v]
            ]
            uv_map = {}
            if uvs:
                uv_map[oid] = (
                    sum(u[0] for u in uvs) / float(len(uvs)),
                    sum(u[1] for u in uvs) / float(len(uvs)),
                )
            new_uv.append(uv_map)

        # Edge points
        edge_pt_index = {}
        for e, fids in edge_faces.items():
            a, b = e
            if len(fids) == 2:
                ep = _avg(
                    [positions[a], positions[b], face_pts[fids[0]], face_pts[fids[1]]]
                )
            else:
                ep = _avg([positions[a], positions[b]])
            edge_pt_index[e] = len(new_positions)
            new_positions.append(ep)

            # UV only for orig faces that BOTH endpoints share
            uv_map = {}
            shared = set(self.vert_face_uv[a].keys()) & set(
                self.vert_face_uv[b].keys()
            )
            for oid in shared:
                ua = self.vert_face_uv[a][oid]
                ub = self.vert_face_uv[b][oid]
                uv_map[oid] = (0.5 * (ua[0] + ub[0]), 0.5 * (ua[1] + ub[1]))
            new_uv.append(uv_map)

        # Vertex points
        old_to_new = {}
        for vid in range(n_verts):
            n = len(vert_edges[vid])
            is_boundary = n == 0 or any(len(edge_faces[e]) < 2 for e in vert_edges[vid])
            if n == 0:
                vp = positions[vid]
            elif is_boundary:
                mids = []
                for e in vert_edges[vid]:
                    if len(edge_faces[e]) == 1:
                        mids.append(_avg([positions[e[0]], positions[e[1]]]))
                if len(mids) >= 2:
                    # cubic B-spline boundary: 1/8*prev + 3/4*v + 1/8*next ≈
                    mid_avg = _avg(mids)
                    V = positions[vid]
                    vp = (
                        0.75 * V[0] + 0.25 * mid_avg[0],
                        0.75 * V[1] + 0.25 * mid_avg[1],
                        0.75 * V[2] + 0.25 * mid_avg[2],
                    )
                elif mids:
                    V = positions[vid]
                    m = mids[0]
                    vp = (0.75 * V[0] + 0.25 * m[0], 0.75 * V[1] + 0.25 * m[1], 0.75 * V[2] + 0.25 * m[2])
                else:
                    vp = positions[vid]
            else:
                F = _avg([face_pts[f] for f in vert_faces[vid]])
                E = _avg(
                    [_avg([positions[e[0]], positions[e[1]]]) for e in vert_edges[vid]]
                )
                V = positions[vid]
                vp = (
                    (F[0] + 2.0 * E[0] + (n - 3) * V[0]) / float(n),
                    (F[1] + 2.0 * E[1] + (n - 3) * V[1]) / float(n),
                    (F[2] + 2.0 * E[2] + (n - 3) * V[2]) / float(n),
                )
            old_to_new[vid] = len(new_positions)
            new_positions.append(vp)
            new_uv.append(dict(self.vert_face_uv[vid]))

        # New faces + face_orig lineage
        new_faces = []
        new_face_orig = []
        for fid, fverts in enumerate(faces):
            nv = len(fverts)
            fp = face_pt_index[fid]
            oid = self.face_orig[fid]
            for i in range(nv):
                v0 = fverts[i]
                v1 = fverts[(i + 1) % nv]
                e = (v0, v1) if v0 < v1 else (v1, v0)
                ep = edge_pt_index[e]
                a_prev = fverts[(i - 1) % nv]
                e_prev = (a_prev, v0) if a_prev < v0 else (v0, a_prev)
                ep_prev = edge_pt_index[e_prev]
                new_faces.append([old_to_new[v0], ep, fp, ep_prev])
                new_face_orig.append(oid)

        return CCMesh(
            new_positions,
            new_faces,
            vert_face_uv=new_uv,
            face_orig=new_face_orig,
            n_orig_faces=self.n_orig_faces,
        )

    def subdivide_n(self, levels):
        m = self
        for _ in range(int(levels)):
            m = m.subdivide()
        return m

    def face_point_grid(self, orig_face_id, levels):
        """(2^levels+1)^2 grid [v][u] for one original quad, or None."""
        n = 1 << int(levels)
        buckets = {}
        for vid, uvmap in enumerate(self.vert_face_uv):
            if orig_face_id not in uvmap:
                continue
            u, v = uvmap[orig_face_id]
            u = max(0.0, min(1.0, float(u)))
            v = max(0.0, min(1.0, float(v)))
            iu = int(round(u * n))
            iv = int(round(v * n))
            iu = max(0, min(n, iu))
            iv = max(0, min(n, iv))
            ideal = (float(iu) / float(n), float(iv) / float(n))
            err = (u - ideal[0]) ** 2 + (v - ideal[1]) ** 2
            key = (iu, iv)
            if key not in buckets or err < buckets[key][0]:
                buckets[key] = (err, self.positions[vid])

        grid = [[None for _ in range(n + 1)] for _ in range(n + 1)]
        for iv in range(n + 1):
            for iu in range(n + 1):
                if (iu, iv) in buckets:
                    grid[iv][iu] = buckets[(iu, iv)][1]

        # Fill holes from corners if needed
        corners = [(0, 0), (0, n), (n, 0), (n, n)]
        if any(grid[i][j] is None for i, j in corners):
            return None

        for iv in range(n + 1):
            for iu in range(n + 1):
                if grid[iv][iu] is not None:
                    continue
                su = float(iu) / float(n)
                sv = float(iv) / float(n)
                grid[iv][iu] = _lerp(
                    _lerp(grid[0][0], grid[0][n], su),
                    _lerp(grid[n][0], grid[n][n], su),
                    sv,
                )
        return grid


def build_cc_from_maya(mesh_transform):
    import maya.cmds as cmds
    from ..utils.text_encoding import safe_str

    mesh_transform = safe_str(mesh_transform)
    shapes = (
        cmds.listRelatives(mesh_transform, shapes=True, fullPath=True, type="mesh")
        or []
    )
    if not shapes:
        raise RuntimeError("No mesh under {0}".format(mesh_transform))
    shape = safe_str(shapes[0])
    n_verts = int(cmds.polyEvaluate(shape, vertex=True))
    n_faces = int(cmds.polyEvaluate(shape, face=True))

    positions = []
    for i in range(n_verts):
        p = cmds.xform(
            "{0}.vtx[{1}]".format(shape, i),
            query=True,
            worldSpace=True,
            translation=True,
        )
        positions.append((float(p[0]), float(p[1]), float(p[2])))

    faces = []
    for fid in range(n_faces):
        # polyInfo keeps winding order (polyListComponentConversion may not)
        vids = []
        info = cmds.polyInfo("{0}.f[{1}]".format(shape, fid), faceToVertex=True) or []
        if info:
            line = safe_str(info[0]).replace(":", " ")
            nums = []
            for tok in line.split():
                try:
                    nums.append(int(tok))
                except ValueError:
                    continue
            # "FACE id: v0 v1 v2 v3" → drop face id
            if len(nums) >= 4:
                vids = nums[1:]
            elif len(nums) == 3:
                vids = nums
        if len(vids) < 3:
            comps = cmds.polyListComponentConversion(
                "{0}.f[{1}]".format(shape, fid), fromFace=True, toVertex=True
            )
            comps = cmds.ls(comps, flatten=True) or []
            for c in comps:
                try:
                    vids.append(int(c.split("[")[-1].rstrip("]")))
                except Exception:
                    pass
        if len(vids) >= 3:
            faces.append(vids)

    return CCMesh(positions, faces)
