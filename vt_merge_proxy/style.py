from typing import Any, Dict

import requests
from mergedeep import merge


class StyleGL:
    def __init__(self, url: str, overwrite: Dict[str, Any] = None):
        r = requests.get(url)
        r.raise_for_status()
        self._gljson = r.json()

        if overwrite:
            self._gljson = merge(self._gljson, overwrite)

    def json(self):
        return self._gljson
