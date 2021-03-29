import random

import vector_tile_base


def layer_extract(tile, layer_name: str):
    return next(filter(lambda layer: layer.name == layer_name, tile.layers), None)


def get_attribute(attributes, key: str, default=None):
    return default if key not in attributes else attributes[key]


def get_classes(fields, poi):
    attributes = poi.attributes
    return [get_attribute(attributes, field) for field in fields]


def match_class_list(fields, poi, classes):
    return get_classes(poi, fields) in classes


def exclude_poi(fields, pois, classes):
    if classes:
        return list(
            filter(lambda poi: not match_class_list(fields, poi, classes), pois)
        )
    else:
        return pois


def include_poi(fields, pois, classes):
    if classes:
        return list(filter(lambda poi: match_class_list(fields, poi, classes), pois))
    else:
        return []


def rank(features):
    grid = {}
    for f in features:
        x, y = f.get_geometry()[0]
        x = (x + 50) // 100
        y = (y + 50) // 100
        h = (x, y)
        if h not in grid:
            grid[h] = []
        grid[h].append(f)

    for _, group_features in grid.items():
        poi = sorted(
            group_features,
            key=lambda a: [
                get_attribute(
                    # FIXME check zoom def
                    a.attributes,
                    "tourism_zoom",
                    18,
                ),
                get_attribute(a.attributes, "tourism_priority", 9999),
            ],
        )
        # FIXME Does not work
        for rank, feature in enumerate(poi):
            feature.attributes["tourism_rank"] = rank

    return features


def build_feature(merge_tile_layer, f):
    if f.type == "point":
        feature = merge_tile_layer.add_point_feature()
        feature.add_points(f.get_geometry())
    elif f.type == "line_string":
        feature = merge_tile_layer.add_line_string_feature()
        for g in f.get_geometry():
            feature.add_line_string(g)
    elif f.type == "polygon":
        feature = merge_tile_layer.add_polygon_feature()
        for g in f.get_geometry():
            for q in g:
                feature.add_ring(q)
    elif f.type == "spline":
        feature = merge_tile_layer.add_spline_feature()
        feature.add_spline(f.get_geometry())
    else:
        raise Exception(f.type)

    feature.id = f.id if f.id is not None else random.randrange(2 ** 32)
    f.attributes._decode_attr()
    feature.attributes = f.attributes._attr


def build_tile(model, poi):
    merge_poi = vector_tile_base.VectorTile()
    if model:
        for layer in model.layers:
            if layer.name != "poi":
                merge_tile_layer = merge_poi.add_layer(layer.name)
                for feature in layer.features:
                    build_feature(merge_tile_layer, feature)

    if poi:
        merge_tile_layer = merge_poi.add_layer("poi")
        for feature in poi:
            build_feature(merge_tile_layer, feature)

    return merge_poi


def merge_tile(
    min_zoom, full, partial, merge_layer, z: int, x: int, y: int, url_params: str
):
    full_tile, full_raw_tile = full.tile(z=z, x=x, y=y, url_params=url_params)
    if z < min_zoom:
        return full_raw_tile

    layer = merge_layer["layer"]
    fields = merge_layer["fields"]
    classes = merge_layer["classes"]

    if full_tile:
        full_tile_layer = layer_extract(full_tile, layer)
        if full_tile_layer:
            full_poi = exclude_poi(fields, full_tile_layer.features, classes)
        else:
            full_poi = []
    else:
        full_poi = None

    partial_tile, _ = partial.tile(z=z, x=x, y=y, url_params=url_params)
    if partial_tile:
        partial_tile_layer = layer_extract(partial_tile, layer)
        if partial_tile_layer:
            partial_poi = include_poi(fields, partial_tile_layer.features, classes)
        else:
            partial_poi = []
    else:
        partial_poi = None

    if partial_poi is None or partial_tile_layer is None or not partial_poi:
        if full_poi is None:
            return None
        elif full_tile_layer is None:
            return full_raw_tile
        elif len(full_poi) == len(full_tile_layer.features):
            return full_raw_tile
        else:
            merge_poi = build_tile(full_tile, full_poi)
            return merge_poi.serialize()

    else:
        if full_poi is None or full_tile_layer is None:
            poi = partial_poi
        else:
            poi = rank(full_poi + partial_poi)

        merge_poi = build_tile(full_tile, poi)
        return merge_poi.serialize()


def merge_tilejson(public_tile_urls, full, partial, url_params: str):
    full_tilejson = full.tilejson()
    partial_tilejson = partial.tilejson()

    attributions = partial_tilejson.get("attribution", "").split(
        ","
    ) + full_tilejson.get("attribution", "").split(",")
    attributions = [
        attribution.strip() for attribution in attributions if attribution.strip()
    ]
    attributions = ", ".join(attributions)
    full_tilejson["attribution"] = attributions

    if public_tile_urls:
        full_tilejson["tiles"] = public_tile_urls

    if url_params:
        full_tilejson["tiles"] = [url + f"?{url_params}" for url in public_tile_urls]

    return full_tilejson
