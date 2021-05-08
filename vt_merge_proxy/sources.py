import gzip

import pymbtiles
import requests
import vector_tile_base


class Source:
    def tilejson(self):
        return {}


class SourceMBTiles(Source):
    def __init__(self, mbtiles: str):
        self.src = pymbtiles.MBtiles(mbtiles)

    def tile(self, z: int, x: int, y: int, url_params: str):
        y = 2 ** z - 1 - y
        tile_data = self.src.read_tile(z=z, x=x, y=y)
        if not tile_data:
            return [None, None]
        else:
            tile_data = gzip.decompress(tile_data)
            return [vector_tile_base.VectorTile(tile_data), tile_data]


class SourceXYZ(Source):
    def __init__(self, template_url: str):
        self.template_url = template_url

    def tile(self, z: int, x: int, y: int, url_params: str):
        url = self.template_url.format_map({"z": z, "x": x, "y": y})
        if url_params:
            url = f"{url}?{url_params}"
        r = requests.get(url)
        if r.status_code == 200:
            return [vector_tile_base.VectorTile(r.content), r.content]
        else:
            print(r)
            return [None, None]  # TODO deal with error


class SourceTileJSON(SourceXYZ):
    def __init__(self, tilejson_url: str, tile_url: str = None):
        r = requests.get(tilejson_url)
        r.raise_for_status()
        self._tilejson = r.json()

        template_url = self._tilejson["tiles"][0]
        if tile_url:
            template_url = template_url[
                template_url.index("/", template_url.index("//") + 3) :
            ]
            template_url = tile_url + template_url

        super().__init__(template_url)

    def tilejson(self):
        return self._tilejson


def sourceFactory(source):
    if "tilejson_url" in source:
        return SourceTileJSON(**source)
    elif "mbtiles" in source:
        return SourceMBTiles(**source)
    else:
        raise NotImplementedError(source)
