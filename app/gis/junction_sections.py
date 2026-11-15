"""Local junction plateaus in the derived profile constraint system.

Only node-connected ground automotive profiles participate. Joining variables
before grade/curvature projection preserves the constraints simultaneously.
"""

from collections import defaultdict

import numpy as np


def merge_junction_sections(profiles, roads, mappings, seeds, factor):
    parent = list(range(len(seeds)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def join(a, b):
        parent[find(b)] = find(a)

    nodes = defaultdict(list)
    for p in profiles:
        r = roads[p.road_id]
        if r.bridge or r.tunnel or r.layer != 0 or r.road_category != "automotive":
            continue
        for i, node in p.sample_node_ids.items():
            nodes[node].append((p, i))
    zones = []
    for node, entries in sorted(nodes.items()):
        if len({p.road_id for p, _ in entries}) < 2:
            continue
        directions = []
        for p, i in entries:
            for j in (i - 1, i + 1):
                if 0 <= j < len(p.xy):
                    d = np.array(p.xy[j]) - p.xy[i]
                    directions.append(d / np.linalg.norm(d))
        if len(directions) == 2 and abs(np.dot(*directions)) > 0.985:
            continue
        radius = factor * max(roads[p.road_id].width for p, _ in entries)
        variables = set()
        for p, i in entries:
            distances = np.array(p.distances)
            # Include the first station beyond the radius so the constant zone
            # is not shortened by coarse/nonuniform source sampling.
            a = max(0, int(np.searchsorted(distances, distances[i] - radius)) - 1)
            b = min(
                len(distances),
                int(np.searchsorted(distances, distances[i] + radius)) + 1,
            )
            variables.update(mappings[p.road_id][a:b])
        ordered = sorted(variables)
        for v in ordered[1:]:
            join(ordered[0], v)
        zones.append(
            dict(
                node=node,
                radiusMeters=radius,
                roads=sorted({p.road_id for p, _ in entries}),
                variables=len(ordered),
            )
        )
    new_seeds = defaultdict(list)
    new_ids = {}
    for i, values in seeds.items():
        k = new_ids.setdefault(find(i), len(new_ids))
        new_seeds[k].extend(values)
    result = {
        rid: [new_ids[find(i)] for i in indices] for rid, indices in mappings.items()
    }
    return result, new_seeds, zones
