"""AEMPS CIMA (Spain) drug registry scraper — migrated onto the engine.

Paginates the CIMA REST API (``pagina=N``, 1-indexed) to retrieve all
registered medicines. The API reports its own ``totalFilas``/``tamanioPagina``
on every page, so :meth:`fetch` is overridden to compute the total-pages end
signal directly rather than relying on a short-page check.

Schema per row:
  nregistro, nombre, laboratorio_titular, laboratorio_comercializador,
  vias_administracion[], forma_farmaceutica, vtm, dosis,
  comercializado, receta, generico, huerfano, language, source

TLS verification is disabled, matching the original's ``verify=False`` +
``urllib3.disable_warnings``.

Run it::

    python -m metadatarr.scrapers aemps_drugs [--output DIR] [--delay SECS]
"""
from __future__ import annotations

import math
from typing import Any, Dict, Optional

from metadatarr.scrapers.engine import Page, PaginatedJSONSource, register, run_cli

BASE = "https://cima.aemps.es/cima/rest/medicamentos"
PAGE_SIZE = 200


@register
class AempsDrugsSource(PaginatedJSONSource):
    name = "aemps_drugs"
    id_field = "nregistro"
    default_delay = 0.5

    base = BASE
    results_key = "resultados"
    page_size = PAGE_SIZE
    accept = "application/json"

    def session(self):
        if self._session is None:
            try:
                from unblock_requests import CloudflareSession
                s = CloudflareSession()
            except Exception:
                import requests
                s = requests.Session()
            s.headers.update({
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0",
                "Accept": self.accept,
            })
            s.verify = False
            self._session = s
        return self._session

    def initial_cursor(self) -> int:
        return 1  # 1-indexed page, matching the original's `pagina` param

    def map_row(self, item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        vias = [v.get("nombre", "") for v in item.get("viasAdministracion", [])]
        ff = item.get("formaFarmaceutica") or {}
        vtm = item.get("vtm") or {}
        return {
            "nregistro": item.get("nregistro", ""),
            "nombre": item.get("nombre", ""),
            "laboratorio_titular": item.get("labtitular", ""),
            "laboratorio_comercializador": item.get("labcomercializador", ""),
            "vias_administracion": vias,
            "forma_farmaceutica": ff.get("nombre", ""),
            "vtm": vtm.get("nombre", ""),
            "dosis": item.get("dosis", ""),
            "comercializado": item.get("comercializado", None),
            "receta": item.get("receta", None),
            "generico": item.get("generico", None),
            "huerfano": item.get("huerfano", None),
            "language": "es",
            "source": "aemps_cima",
        }

    def fetch(self, cursor: int) -> Page:
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        page = int(cursor or 1)
        data = self.get_json(self.base, {"pagina": page})
        total = int(data.get("totalFilas", 0))
        page_size = int(data.get("tamanioPagina", self.page_size)) or self.page_size
        total_pages = math.ceil(total / page_size) if page_size else 0

        rows = [self.map_row(item) for item in data.get("resultados", [])]
        next_cursor = page + 1 if page < total_pages else None
        return rows, next_cursor


if __name__ == "__main__":
    raise SystemExit(run_cli(AempsDrugsSource))
