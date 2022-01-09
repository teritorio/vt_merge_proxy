import json
import os
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import requests
import yaml
from fastapi import FastAPI, Header, HTTPException, Request, Response
from starlette.responses import RedirectResponse

from .merge import merge_tile, merge_tilejson
from .sources import Source, sourceFactory
from .tile_in_poly import TileInPoly

app = FastAPI()


config = yaml.load(
    open(os.environ.get("CONFIG", "config.yaml")).read(), Loader=yaml.BaseLoader
)
print(config)

if not config.get("server"):
    config["server"] = {}

public_base_path = config["server"].get("public_base_path", "")
public_tile_url_prefixes = config["server"].get("public_tile_url_prefixes", [])


config_style_by_host: Dict[str, Dict[str, Any]] = defaultdict(dict)
for (config_id, style) in config["styles"].items():
    for host in style["hosts"]:
        config_style_by_host[host][style["id"]] = style


@app.get("/")
async def read_root():
    return RedirectResponse(url="/styles.json")


def public_host(request: Request):
    forwarded = request.headers.get("Forwarded")
    if forwarded:
        for f in forwarded.split(",")[0].split(";"):
            k, v = f.split("=")
            if k == "host":
                return v.split(":")[0]
    return request.url.hostname


def public_url(request: Request, host_prefix=""):
    d = {
        "proto": None,
        "host": None,
        "port": None,
    }

    try:
        forwarded = request.headers.get("Forwarded")
        for f in forwarded.split(",")[0].split(";"):
            k, v = f.split("=")
            d[k] = v
    except Exception:
        pass
    finally:
        proto = d["proto"] or request.url.scheme or "http"
        host = d["host"] or request.url.hostname or "localhost"
        port = d["port"] or request.url.port or ""
        if port:
            port = f":{port}"
        return f"{proto}://{host_prefix}{host}{port}"


@app.get("/styles.json")
async def styles(request: Request):
    host = public_host(request)
    if host not in config_style_by_host:
        raise HTTPException(status_code=404)

    return [
        # TODO add version and name
        {
            "id": style_conf["id"],
            "url": public_url(request)
            + public_base_path
            + app.url_path_for("tilejson", style_id=style_id),
        }
        for (style_id, style_conf) in config_style_by_host[host].items()
    ]


@dataclass
class LayerConfig(object):
    fields: List[str]
    classes: List


@dataclass
class MergeConfig(object):
    sources: List[Source]
    min_zoom: int
    tile_in_poly: Optional[TileInPoly]
    layers: Dict[str, LayerConfig]


merge_config: Dict[str, Dict[str, Any]] = defaultdict(dict)
for (host, style_id_confs) in config_style_by_host.items():
    for (style_id, conf) in style_id_confs.items():
        tile_in_poly = None
        if "polygon" in conf:
            tile_in_poly = TileInPoly(open(conf["polygon"]))

        merge_config[host][style_id] = MergeConfig(
            sources=[sourceFactory(source) for source in conf["sources"].values()],
            min_zoom=int(conf["output"]["min_zoom"]),
            tile_in_poly=tile_in_poly,
            layers={
                layer: LayerConfig(
                    fields=merge_layer and merge_layer.get("fields"),
                    classes=merge_layer
                    and merge_layer.get("classes")
                    and json.loads(open(merge_layer["classes"], "r").read()),
                )
                for layer, merge_layer in conf["merge_layers"].items()
            },
        )


@app.get("/data/{style_id}/{z}/{x}/{y}.pbf")
async def tile(style_id: str, z: int, x: int, y: int, request: Request):
    try:
        host = public_host(request)
        if host not in config_style_by_host:
            raise HTTPException(status_code=404)

        mc = merge_config[host][style_id]
        data = merge_tile(
            mc.min_zoom,
            mc.sources[0],
            mc.sources[1],
            mc.layers,
            z,
            x,
            y,
            headers=request.headers,
            url_params=str(request.query_params),
            tile_in_poly=mc.tile_in_poly,
        )
        return Response(content=data, media_type="application/vnd.vector-tile")
    except requests.exceptions.HTTPError as error:
        raise HTTPException(
            status_code=error.response.status_code, detail=error.response.reason
        )


@app.get("/data/{style_id}.json")
async def tilejson(style_id: str, request: Request):
    try:
        path = f"{public_base_path}/data/{style_id}/{{z}}/{{x}}/{{y}}.pbf"
        if not public_tile_url_prefixes:
            style_public_tile_urls = [public_url(request) + path]
        else:
            style_public_tile_urls = [
                public_url(request, host_prefix=public_tile_url_prefixe) + path
                for public_tile_url_prefixe in public_tile_url_prefixes
            ]

        host = public_host(request)
        if host not in config_style_by_host:
            raise HTTPException(status_code=404)

        mc = merge_config[host][style_id]
        return merge_tilejson(
            style_public_tile_urls,
            mc.sources[0],
            mc.sources[1],
            mc.layers.keys(),
            headers=request.headers,
            url_params=str(request.query_params),
        )
    except requests.exceptions.HTTPError as error:
        raise HTTPException(
            status_code=error.response.status_code, detail=error.response.reason
        )
