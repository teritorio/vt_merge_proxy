import copy
import random
from typing import Optional

import vector_tile_base  # type: ignore

from .tile_in_poly import TileInPoly


# Monkey patch
def FeatureAttributes___setitem__(self, key, value):
    if not isinstance(key, str) and not isinstance(key, bytes):
        raise TypeError("Keys must be of type str or bytes")
    self._decode_attr()
    self._attr[key] = value
    # self._encode_attr() # Disable encoding at each __setitem__()


vector_tile_base.FeatureAttributes.__setitem__ = FeatureAttributes___setitem__


def layer_extract(tile, layer_name: str):
    return next(filter(lambda layer: layer.name == layer_name, tile.layers), None)


def get_attribute(attributes, key: str, default=None):
    return default if key not in attributes else attributes[key]


def get_classes(fields, feature):
    attributes = feature.attributes
    return [get_attribute(attributes, field) for field in fields]


def match_class_list(fields, feature, classes):
    feature_class = get_classes(fields, feature)
    return any(map(lambda classs: classs == feature_class[: len(classs)], classes))


def include_feature(fields, feature, classes, point_in_poly):
    if not point_in_poly or point_in_poly(*feature.get_points()[0]):
        return match_class_list(fields, feature, classes)
    else:
        return False


def exclude_features(fields, features, classes, point_in_poly):
    if classes:
        return list(
            filter(
                lambda feature: not include_feature(
                    fields, feature, classes, point_in_poly
                ),
                features,
            )
        )
    else:
        return features


def include_features(fields, features, classes, point_in_poly):
    if classes:
        return list(
            filter(
                lambda feature: include_feature(
                    fields, feature, classes, point_in_poly
                ),
                features,
            )
        )
    else:
        return []


# FIXME hardcoded fields
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
                get_attribute(a.attributes, "zoom", 18),
                get_attribute(a.attributes, "priority", 9999),
            ],
        )
        for rank, feature in enumerate(poi):
            feature.attributes["rank"] = rank  # Monkey patched to disable encoding

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
    # FIXME decode/encode to be done only if changed
    f.attributes._decode_attr()
    # FIXME Attribut re-encoding : slowest step
    # https://github.com/mapbox/vector-tile-base/blob/master/vector_tile_base/engine.py#L251
    feature.attributes = f.attributes._attr


def build_tile(build_layer_name, model, features):
    layer = None
    if model:
        for layer in model.layers:
            if layer.name == build_layer_name:
                layer.name = "_"
                break

    layer = model.add_layer(build_layer_name)

    if features:
        for feature in features:
            build_feature(layer, feature)

    return model


def merge_tile(
    min_zoom,
    full,
    partial,
    layer,
    fields,
    classes,
    z: int,
    x: int,
    y: int,
    headers,
    url_params: str,
    tile_in_poly: Optional[TileInPoly],
):
    full_tile, full_raw_tile = full.tile(
        z=z, x=x, y=y, headers=headers, url_params=url_params
    )
    if z < min_zoom:
        return full_raw_tile

    if tile_in_poly and tile_in_poly.is_tile_outside_poly(z, x, y):
        return full_raw_tile

    if tile_in_poly and tile_in_poly.is_tile_inside_poly(z, x, y):
        tile_in_poly = None  # Disable geo filter

    if full_tile:
        full_tile_layer = layer_extract(full_tile, layer)
        if full_tile_layer:
            full_features = exclude_features(
                fields,
                full_tile_layer.features,
                classes,
                tile_in_poly and tile_in_poly.point_in_poly(z, x, y),
            )
        else:
            full_features = []
    else:
        full_features = None

    partial_tile, _ = partial.tile(
        z=z, x=x, y=y, headers=headers, url_params=url_params
    )
    if partial_tile:
        partial_tile_layer = layer_extract(partial_tile, layer)
        if partial_tile_layer:
            partial_features = include_features(
                fields,
                partial_tile_layer.features,
                classes,
                tile_in_poly and tile_in_poly.point_in_poly(z, x, y),
            )
        else:
            partial_features = []
    else:
        partial_features = None

    if partial_features is None or partial_tile_layer is None or not partial_features:
        if full_features is None:
            return None
        elif full_tile_layer is None:
            return full_raw_tile
        elif len(full_features) == len(full_tile_layer.features):
            return full_raw_tile
        else:
            merge_features = build_tile(layer, full_tile, full_features)
            return merge_features.serialize()

    else:
        if full_features is None or full_tile_layer is None:
            features = partial_features
        else:
            features = rank(full_features + partial_features)

        merge_features = build_tile(layer, full_tile, features)
        return merge_features.serialize()


def merge_tilejson(public_tile_urls, full, partial, headers, url_params: str):
    full_tilejson = full.tilejson(headers, url_params)
    partial_tilejson = partial.tilejson(headers, url_params)

    partial_attribution = partial_tilejson.get("attribution", "")
    full_attribution = full_tilejson.get("attribution", "")
    attributions = partial_attribution + "," + full_attribution
    attributions = attributions.replace("/a> <a", "/a>,<a").split(",")
    attributions = set(
        [attribution.strip() for attribution in attributions if attribution.strip()]
    )
    attributions = " ".join(attributions)

    tilejson = copy.deepcopy(full_tilejson)
    tilejson["attribution"] = attributions

    if public_tile_urls:
        tilejson["tiles"] = public_tile_urls

    if url_params:
        tilejson["tiles"] = [url + f"?{url_params}" for url in public_tile_urls]

    return tilejson
