"""Conservative duplicate removal for explicit, topologically identical crossings."""


def deduplicate_crossings(roads):
    groups = {}
    removed = set()
    replacements = {}
    for road in sorted(roads, key=lambda r: r.id):
        if road.road_subtype != "crossing" or road.bridge or road.tunnel:
            continue
        if road.road_category not in {"pedestrian", "cycle"}:
            continue
        # Equal XY alone cannot prove identical network topology. Preserve
        # different node identities, layers, widths and semantic attributes.
        forward = (
            tuple(zip(road.path, road.node_ids, strict=True))
            if len(road.node_ids) == len(road.path)
            else None
        )
        if forward is None:
            continue
        geometry = min(forward, tuple(reversed(forward)))
        key = (
            geometry,
            road.layer,
            road.width,
            road.road_category,
            road.road_type,
            road.name,
            road.surface,
            tuple(sorted(road.source_tags.items())),
        )
        if key not in groups:
            groups[key] = road
            continue
        original = groups[key]
        if original.id == road.id:
            raise ValueError("Duplicate crossing ID")
        keeper = replacements.setdefault(original.id, original.model_copy(deep=True))
        for field in ("sources", "source_ids", "source_osm_ids"):
            setattr(
                keeper,
                field,
                sorted(set(getattr(keeper, field)) | set(getattr(road, field))),
            )
        keeper.source_tags_by_id.update(road.source_tags_by_id)
        keeper.field_provenance.setdefault("crossing_duplicate_resolution", []).append(
            dict(
                id=road.id,
                sources=road.sources,
                source_osm_ids=road.source_osm_ids,
                source_tags=road.source_tags,
                node_ids=road.node_ids,
                rule="identical_path_nodes_layer_width_and_semantics",
            )
        )
        removed.add(road.id)
    return [replacements.get(r.id, r) for r in roads if r.id not in removed]
