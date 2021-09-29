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
    return request.headers.get("X-Forwarded-Host", request.url.hostname)


def public_url(request: Request, host_prefix=""):
    h = request.headers
    proto = h.get("X-Forwarded-Proto", request.url.scheme)
    host = host_prefix + h.get("X-Forwarded-Host", request.url.hostname)
    port = h.get("X-Forwarded-Port", request.url.port)
    if port:
        port = f":{port}"
    return f"{proto}://{host}{port}"


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
class MergeConfig(object):
    sources: List[Source]
    min_zoom: int
    tile_in_poly: Optional[TileInPoly]
    layer: str
    fields: List[str]
    classes: List


merge_config: Dict[str, Dict[str, Any]] = defaultdict(dict)
for (host, style_id_confs) in config_style_by_host.items():
    for (style_id, conf) in style_id_confs.items():
        merge_layer = conf["merge_layer"]

        tile_in_poly = None
        if "polygon" in merge_layer:
            tile_in_poly = TileInPoly(open(merge_layer["polygon"]))

        merge_config[host][style_id] = MergeConfig(
            sources=[sourceFactory(source) for source in conf["sources"].values()],
            min_zoom=int(conf["output"]["min_zoom"]),
            tile_in_poly=tile_in_poly,
            layer=merge_layer["layer"],
            fields=merge_layer["fields"],
            classes=json.loads(open(merge_layer["classes"], "r").read()),
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
            mc.layer,
            mc.fields,
            mc.classes,
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
            headers=request.headers,
            url_params=str(request.query_params),
        )
    except requests.exceptions.HTTPError as error:
        raise HTTPException(
            status_code=error.response.status_code, detail=error.response.reason
        )
