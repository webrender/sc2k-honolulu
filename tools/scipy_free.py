"""Small grid helpers so the project doesn't need SciPy."""
from collections import deque

import numpy as np


def distance_to(mask):
    """Chebyshev distance (in tiles) from each cell to the nearest True cell of mask."""
    n, m = mask.shape
    dist = np.full(mask.shape, 10 ** 6, dtype=np.int32)
    q = deque()
    for x, y in zip(*np.nonzero(mask)):
        dist[x, y] = 0
        q.append((x, y))
    while q:
        x, y = q.popleft()
        d = dist[x, y] + 1
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                X, Y = x + dx, y + dy
                if 0 <= X < n and 0 <= Y < m and dist[X, Y] > d:
                    dist[X, Y] = d
                    q.append((X, Y))
    return dist


def thin(mask):
    """Zhang-Suen thinning of a boolean grid to one-cell-wide lines."""
    img = np.pad(mask.astype(np.uint8), 1)
    changed = True
    while changed:
        changed = False
        for step in (0, 1):
            p = img
            P2, P3, P4 = p[:-2, 1:-1], p[:-2, 2:], p[1:-1, 2:]
            P5, P6, P7 = p[2:, 2:], p[2:, 1:-1], p[2:, :-2]
            P8, P9 = p[1:-1, :-2], p[:-2, :-2]
            nb = [P2, P3, P4, P5, P6, P7, P8, P9]
            B = sum(n.astype(int) for n in nb)
            seq = nb + [P2]
            A = sum(((seq[i] == 0) & (seq[i + 1] == 1)).astype(int) for i in range(8))
            if step == 0:
                c = (P2 * P4 * P6 == 0) & (P4 * P6 * P8 == 0)
            else:
                c = (P2 * P4 * P8 == 0) & (P2 * P6 * P8 == 0)
            rm = (p[1:-1, 1:-1] == 1) & (B >= 2) & (B <= 6) & (A == 1) & c
            if rm.any():
                img[1:-1, 1:-1][rm] = 0
                changed = True
    return img[1:-1, 1:-1].astype(bool)


def four_connect(mask):
    """Add a corner cell wherever two cells touch only diagonally."""
    m = mask.copy()
    n, k = m.shape
    for x in range(n - 1):
        for y in range(k):
            for dy in (-1, 1):
                Y = y + dy
                if 0 <= Y < k and m[x, y] and m[x + 1, Y] and not m[x + 1, y] and not m[x, Y]:
                    m[x + 1, y] = True
    return m


def assignment(cost):
    """Minimum-cost assignment (the Hungarian method), for rows <= columns: the column
    each row gets, so that no two rows share one and the total cost is least."""
    n, m = cost.shape
    big = 1e18
    u, v = np.zeros(n + 1), np.zeros(m + 1)
    owner, way = np.zeros(m + 1, dtype=int), np.zeros(m + 1, dtype=int)
    for i in range(1, n + 1):
        owner[0], j0 = i, 0
        minv, used = np.full(m + 1, big), np.zeros(m + 1, dtype=bool)
        while True:
            used[j0] = True
            i0 = owner[j0]
            cur = cost[i0 - 1] - u[i0] - v[1:]
            free = ~used[1:]
            better = free & (cur < minv[1:])
            minv[1:][better] = cur[better]
            way[1:][better] = j0
            cand = np.where(free, minv[1:], big)
            j1 = int(np.argmin(cand)) + 1
            delta = cand[j1 - 1]
            u[owner[used]] += delta
            v[used] -= delta
            minv[1:][free] -= delta
            j0 = j1
            if owner[j0] == 0:
                break
        while j0:
            j1 = way[j0]
            owner[j0] = owner[j1]
            j0 = j1
    out = np.zeros(n, dtype=int)
    for j in range(1, m + 1):
        if owner[j]:
            out[owner[j] - 1] = j - 1
    return out
