# -*- coding: utf-8 -*-
"""
Polygon cage topology helpers for SubD→NURBS conversion.

Builds vertex/face adjacency so we can extract the 4x4 vertex neighborhood
around each quad (regular Catmull-Clark / bicubic B-spline patch).
"""

from __future__ import absolute_import, print_function

import maya.cmds as cmds

from ..utils.text_encoding import safe_str


class CageMesh(object):
    """Lightweight quad-cage topology from a Maya mesh transform."""

    def __init__(self, mesh_transform):
        self.transform = safe_str(mesh_transform)
        shapes = cmds.listRelatives(
            self.transform, shapes=True, fullPath=True, type="mesh"
        ) or []
        if not shapes:
            raise RuntimeError("No mesh shape under {0}".format(self.transform))
        self.shape = safe_str(shapes[0])

        self.n_verts = int(cmds.polyEvaluate(self.shape, vertex=True) or 0)
        self.n_faces = int(cmds.polyEvaluate(self.shape, face=True) or 0)

        # positions[vid] = (x,y,z) world
        self.positions = []
        for i in range(self.n_verts):
            p = cmds.xform(
                "{0}.vtx[{1}]".format(self.shape, i),
                query=True,
                worldSpace=True,
                translation=True,
            )
            self.positions.append((float(p[0]), float(p[1]), float(p[2])))

        # faces[fid] = [v0,v1,v2,v3,...] winding from Maya
        self.faces = []
        # vertex -> ordered neighbor list (CCW around vertex, best-effort)
        self.v_neighbors = [[] for _ in range(self.n_verts)]
        # edge (min,max) -> list of face ids
        self.edge_faces = {}

        for fid in range(self.n_faces):
            vids = self._face_vertices(fid)
            self.faces.append(vids)
            n = len(vids)
            for i in range(n):
                a = vids[i]
                b = vids[(i + 1) % n]
                self._add_neighbor(a, b)
                self._add_neighbor(b, a)
                e = (a, b) if a < b else (b, a)
                self.edge_faces.setdefault(e, []).append(fid)

        # Order neighbors around each vertex using face fans
        self._order_neighbors()

    def _face_vertices(self, fid):
        face = "{0}.f[{1}]".format(self.shape, fid)
        comps = cmds.polyListComponentConversion(face, fromFace=True, toVertex=True)
        comps = cmds.ls(comps, flatten=True) or []
        vids = []
        for c in comps:
            # ...vtx[N]
            try:
                vids.append(int(c.split("[")[-1].rstrip("]")))
            except Exception:
                continue
        if len(vids) >= 3:
            return vids
        # polyInfo fallback
        info = cmds.polyInfo(face, faceToVertex=True) or []
        if not info:
            return []
        line = safe_str(info[0]).replace(":", " ")
        nums = []
        for tok in line.split():
            try:
                nums.append(int(tok))
            except ValueError:
                continue
        if len(nums) >= 4:
            return nums[1:]
        return nums

    def _add_neighbor(self, a, b):
        if b not in self.v_neighbors[a]:
            self.v_neighbors[a].append(b)

    def _order_neighbors(self):
        """Order vertex neighbors by walking incident faces (CCW-ish)."""
        ordered = []
        for vid in range(self.n_verts):
            nbrs = self.v_neighbors[vid]
            if len(nbrs) <= 2:
                ordered.append(list(nbrs))
                continue
            # Build link: for each incident face containing vid, edge pair
            next_map = {}
            for fid, fverts in enumerate(self.faces):
                if vid not in fverts:
                    continue
                n = len(fverts)
                idx = fverts.index(vid)
                prev_v = fverts[(idx - 1) % n]
                next_v = fverts[(idx + 1) % n]
                next_map[prev_v] = next_v
            # Walk ring
            start = nbrs[0]
            ring = [start]
            cur = start
            for _ in range(len(nbrs) + 2):
                nxt = next_map.get(cur)
                if nxt is None or nxt in ring:
                    break
                ring.append(nxt)
                cur = nxt
            # If incomplete, keep unordered unique
            if len(ring) < len(nbrs):
                for b in nbrs:
                    if b not in ring:
                        ring.append(b)
            ordered.append(ring)
        self.v_neighbors = ordered

    def valence(self, vid):
        return len(self.v_neighbors[vid])

    def is_regular_face(self, fid):
        """True if face is quad and all 4 corners have valence 4."""
        verts = self.faces[fid]
        if len(verts) != 4:
            return False
        return all(self.valence(v) == 4 for v in verts)

    def extract_4x4(self, fid):
        """
        Extract 4x4 vertex positions for a regular quad face.

        Layout (rows = V, cols = U), matching bicubic B-spline CVs:
          [0][0] .. [0][3]
          ...
          [3][0] .. [3][3]

        Face corners map to center 2x2:
          [1][1]=c0, [1][2]=c1, [2][2]=c2, [2][1]=c3
        where face winding is c0,c1,c2,c3.

        Returns list of 4 rows of 4 (x,y,z) tuples, or None if irregular.
        """
        if not self.is_regular_face(fid):
            return None

        c0, c1, c2, c3 = self.faces[fid]

        def nbrs(v):
            return self.v_neighbors[v]

        def other_two(v, a, b):
            """The two neighbors of v that are not a or b (valence 4)."""
            out = [n for n in nbrs(v) if n != a and n != b]
            return out

        # At c0: neighbors include c1 and c3. Other two: toward (-U) and (-V)
        o0 = other_two(c0, c1, c3)
        if len(o0) != 2:
            return None
        # Distinguish: which shares a face with edge c0-c1 vs c0-c3
        # Walk: from c0, neighbor after c3 in ring going away from face -> v01 direction
        ring0 = nbrs(c0)
        # Find index of c1 and c3 in ring
        try:
            i_c1 = ring0.index(c1)
            i_c3 = ring0.index(c3)
        except ValueError:
            return None

        # In CCW ring around c0, face occupies sector c1..c3 or c3..c1
        # The neighbor immediately "outside" past c1 (away from c3) is [1][0] side...
        # Simpler geometric approach:
        n00_cand, n10_from_c0 = o0[0], o0[1]

        # Classify using face adjacency:
        # Vertex connected to both c0 and c3 but not on face -> along edge c0-c3 outside = [0][1] or [2][1]
        def common_neighbors(a, b):
            return [v for v in nbrs(a) if v in nbrs(b) and v != a and v != b]

        # Across edge c0-c1: the other face's far vertices
        # Outer vertex on the left of directed edge c0->c1
        def outer_across_edge(a, b, face_exclude):
            e = (a, b) if a < b else (b, a)
            faces = self.edge_faces.get(e, [])
            for f in faces:
                if f == face_exclude:
                    continue
                fverts = self.faces[f]
                # vertex in fverts not a or b
                extras = [v for v in fverts if v != a and v != b]
                return extras
            return []

        # Build center first
        # [1][1]=c0 [1][2]=c1 [2][2]=c2 [2][1]=c3
        grid = [[None] * 4 for _ in range(4)]
        grid[1][1] = c0
        grid[1][2] = c1
        grid[2][2] = c2
        grid[2][1] = c3

        # Edge mid-ring from one-ring
        # [1][0]: neighbor of c0 opposite to c1 (along -U from c0)
        # [0][1]: neighbor of c0 opposite to c3 (along -V from c0)
        # Using ring order at c0: assume CCW. Face interior between c1 and c3.
        # If going CCW c1 -> ... -> c3 through interior, exterior arcs give outer verts.

        # Determine orientation of ring relative to face
        # Rotate ring so we start at c1; next should go toward exterior or interior
        n = len(ring0)
        # Two arcs from c1 to c3
        def arc(start, end):
            i = ring0.index(start)
            out = []
            for k in range(1, n):
                v = ring0[(i + k) % n]
                out.append(v)
                if v == end:
                    break
            return out

        arc_a = arc(c1, c3)  # may be short (through face = just empty of extras) or long
        arc_b = arc(c3, c1)

        # The arc that only contains face-adjacent path might be direct: if c1's next is c3, empty
        # Exterior arc has the two outer neighbors for c0... actually for valence 4,
        # ring is [c1, x, c3, y] or [c1, c3, y, x] etc.
        # The two not c1/c3 are exactly o0.

        # Assign using opposite-across-edge:
        # Across c0-c1 (other face): extras typically one vertex for quad = [0][2] area...
        ex_c0c1 = outer_across_edge(c0, c1, fid)
        ex_c1c2 = outer_across_edge(c1, c2, fid)
        ex_c2c3 = outer_across_edge(c2, c3, fid)
        ex_c3c0 = outer_across_edge(c3, c0, fid)

        # For quads, each opposite face contributes 2 verts; pick the ones forming the ring
        # Use neighbor opposite:
        # [1][0] = the neighbor of c0 that is not c1,c3 and shares edge-face with c0-c3? 
        # Geometric: project

        def not_face(v):
            return v not in (c0, c1, c2, c3)

        # [1][0]: unique neighbor of c0 among o0 that appears in ex_c3c0 or is "left of c0->c3"
        # Prefer: neighbor of both... 

        # Standard construction from half edges:
        # v10 = other neighbor of c0 when walking around opposite to face along edge c0-c3
        # From ring0 ordered CCW: find c3 then previous is [0][1], find c1 then next is [1][0]
        # Depends on winding of ring matching face.

        i3 = ring0.index(c3)
        i1 = ring0.index(c1)
        # If face is CCW c0->c1->c2->c3, then around c0 local CCW might be c1, exterior..., c3
        # Neighbor CW from c1 (previous in CCW ring) is exterior on c0-c1 side = [0][2]? 

        # Try: prev(c1) in ring = grid[0][2] candidate path
        prev_c1 = ring0[(i1 - 1) % n]
        next_c1 = ring0[(i1 + 1) % n]
        prev_c3 = ring0[(i3 - 1) % n]
        next_c3 = ring0[(i3 + 1) % n]

        # One of prev/next of c1 is c0 (the center). The other is outer.
        def other_end(prev, nxt, center):
            if prev == center:
                return nxt
            if nxt == center:
                return prev
            # neither is center — pick not on face
            for v in (prev, nxt):
                if v != center and not_face(v):
                    return v
            return prev

        # At c0, ring neighbors of interest:
        # next after c1 away from face interior
        # If ring CCW and face uses c1 then later c3, then next_c1 if not toward c3 is outer
        if next_c1 != c3 and next_c1 != c0 and not_face(next_c1):
            grid[1][0] = next_c1  # tentative -U from c0 along ring
        elif prev_c1 != c3 and prev_c1 != c0 and not_face(prev_c1):
            grid[1][0] = prev_c1

        if next_c3 != c1 and next_c3 != c0 and not_face(next_c3):
            grid[0][1] = next_c3
        elif prev_c3 != c1 and prev_c3 != c0 and not_face(prev_c3):
            grid[0][1] = prev_c3

        # Fill remaining using the same logic at each corner
        # c1: face neighbors c0, c2
        ring1 = nbrs(c1)
        try:
            i0 = ring1.index(c0)
            i2 = ring1.index(c2)
        except ValueError:
            return None
        n1 = len(ring1)
        for cand in (ring1[(i0 - 1) % n1], ring1[(i0 + 1) % n1]):
            if cand != c2 and not_face(cand) and cand != c0:
                if grid[0][2] is None:
                    grid[0][2] = cand
                elif grid[1][3] is None and cand != grid[0][2]:
                    grid[1][3] = cand
        for cand in (ring1[(i2 - 1) % n1], ring1[(i2 + 1) % n1]):
            if cand != c0 and not_face(cand) and cand != c2:
                if grid[1][3] is None:
                    grid[1][3] = cand
                elif grid[0][2] is None and cand != grid[1][3]:
                    grid[0][2] = cand

        # Use opposite-face extras more reliably
        def pick_outer(extras, already):
            for v in extras:
                if not_face(v) and v not in already:
                    return v
            return extras[0] if extras else None

        def dist(a, b):
            pa, pb = self.positions[a], self.positions[b]
            return (pa[0] - pb[0]) ** 2 + (pa[1] - pb[1]) ** 2 + (pa[2] - pb[2]) ** 2

        # Refill systematically from edge opposites
        # Edge c0-c1 -> upper row near [0][1],[0][2]
        ex = outer_across_edge(c0, c1, fid)
        if len(ex) >= 1:
            if len(ex) == 2:
                ex = sorted(ex, key=lambda v: dist(v, c0))
                grid[0][1] = ex[0]
                grid[0][2] = ex[1]
            else:
                grid[0][1] = ex[0]

        ex = outer_across_edge(c1, c2, fid)
        if len(ex) == 2:
            ex = sorted(ex, key=lambda v: dist(v, c1))
            grid[1][3] = ex[0]
            grid[2][3] = ex[1]
        elif len(ex) == 1:
            grid[1][3] = ex[0]

        ex = outer_across_edge(c2, c3, fid)
        if len(ex) == 2:
            ex = sorted(ex, key=lambda v: dist(v, c3))
            grid[3][1] = ex[0]
            grid[3][2] = ex[1]
        elif len(ex) == 1:
            grid[3][2] = ex[0]

        ex = outer_across_edge(c3, c0, fid)
        if len(ex) == 2:
            ex = sorted(ex, key=lambda v: dist(v, c0))
            grid[1][0] = ex[0]
            grid[2][0] = ex[1]
        elif len(ex) == 1:
            grid[1][0] = ex[0]

        # Corners of 4x4: common neighbors of edge-outers
        def find_corner(a, b):
            if a is None or b is None:
                return None
            common = [v for v in nbrs(a) if v in nbrs(b)]
            for v in common:
                if not_face(v) and v != a and v != b:
                    return v
            return common[0] if common else None

        if grid[0][0] is None:
            grid[0][0] = find_corner(grid[0][1], grid[1][0])
        if grid[0][3] is None:
            grid[0][3] = find_corner(grid[0][2], grid[1][3])
        if grid[3][3] is None:
            grid[3][3] = find_corner(grid[3][2], grid[2][3])
        if grid[3][0] is None:
            grid[3][0] = find_corner(grid[3][1], grid[2][0])

        # Validate
        for r in range(4):
            for c in range(4):
                if grid[r][c] is None:
                    return None

        # Convert indices to positions; also ensure consistent orientation
        rows = []
        for r in range(4):
            rows.append([self.positions[grid[r][c]] for c in range(4)])
        return rows

    def face_corner_positions(self, fid):
        verts = self.faces[fid]
        return [self.positions[v] for v in verts]
