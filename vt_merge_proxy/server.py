import yaml
from fastapi import FastAPI, Request, Response
from starlette.responses import RedirectResponse

from .merge import merge_tile, merge_tilejson
from .sources import sourceFactory

config = yaml.load(open("config.yaml").read(), Loader=yaml.BaseLoader)
print(config)

sources = [sourceFactory(source) for source in config["sources"].values()]

classes = config["merge"]

id = config["output"]["id"]
min_zoom = int(config["output"]["min_zoom"])
public_tiles_url = config["server"]["public_tiles_url"]

app = FastAPI()


@app.get("/")
async def read_root():
    return RedirectResponse(url=f"/data/{id}.json")


@app.get(f"/data/{id}/{{z}}/{{x}}/{{y}}.pbf")
async def tile(z: int, x: int, y: int, request: Request):
    data = merge_tile(
        min_zoom, *sources, classes, z, x, y, url_params=str(request.query_params)
    )
    return Response(content=data, media_type="application/vnd.vector-tile")


@app.get(f"/data/{id}.json")
async def tilejson(request: Request):
    return merge_tilejson(
        public_tiles_url, *sources, url_params=str(request.query_params)
    )
