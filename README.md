# vt_merge_proxy

Vector tile proxy to merge datasources

# Run

```
uvicorn vt_merge_proxy.server:app
```

# Dev

```
uvicorn vt_merge_proxy.server:app --reload
```

# Config

`config.yaml`

```yaml
styles:
    teritorio-proxy:
        sources:
            full:
                tilejson_url: https://vecto-dev.teritorio.xyz/data/teritorio-dev.json
                tile_url: http://localhost:3000
            partial:
                mbtiles: restaurent-20200819.mbtiles

        merge_layer:
            layer: poi_tourism
            fields: [superclass, class, subclass]
            classes:
                - [catering, food, restaurant]

        output:
            min_zoom: 14

server:
    public_tilejson_url: https://vecto-dev.teritorio.xyz
    public_tile_urls:
       - https://vecto-dev.teritorio.xyz
```
