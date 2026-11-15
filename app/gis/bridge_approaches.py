"""Pin only exact bridge abutments; never merge grade-separated span crossings."""

import numpy as np


def approach_constraints(profiles, roads, mappings, epsilon=0.0001):
    fixed = {}
    connections = []
    for bridge in profiles:
        br = roads[bridge.road_id]
        if not br.bridge or br.tunnel:
            continue
        xy = np.asarray(bridge.xy)
        for end in (0, -1):
            segment = 0 if end == 0 else len(xy) - 2
            delta = xy[segment + 1] - xy[segment]
            gradient = (
                delta
                * (bridge.heights[segment + 1] - bridge.heights[segment])
                / np.dot(delta, delta)
            )
            for ground in profiles:
                gr = roads[ground.road_id]
                if gr.bridge or gr.tunnel or gr.layer != 0:
                    continue
                compatible = gr.road_category == br.road_category or (
                    br.road_category == "pedestrian" and gr.road_category == "steps"
                )
                if not compatible or ground.road_id not in mappings:
                    continue
                for approach_end in (0, -1):
                    if np.linalg.norm(xy[end] - ground.xy[approach_end]) > epsilon:
                        continue
                    # Two station values establish both abutment Y and tangent
                    # grade. Remaining ramp is solved by existing constraints.
                    indices = (
                        (0, 1)
                        if approach_end == 0
                        else (len(ground.xy) - 1, len(ground.xy) - 2)
                    )
                    for index in indices:
                        value = bridge.heights[end] + float(
                            np.dot(np.array(ground.xy[index]) - xy[end], gradient)
                        )
                        variable = mappings[ground.road_id][index]
                        if variable in fixed and abs(fixed[variable] - value) > 1e-6:
                            raise ValueError("Incompatible bridge approach constraints")
                        fixed[variable] = value
                    connections.append(
                        dict(
                            bridge=bridge.road_id,
                            bridgeEndpoint=end,
                            approach=ground.road_id,
                            approachEndpoint=approach_end,
                            bridgeLayer=br.layer,
                            approachLayer=gr.layer,
                            method="exact_abutment_and_tangent_constraint",
                            epsilonMeters=epsilon,
                        )
                    )
    return fixed, connections
