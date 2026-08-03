"""ANVISA (Brazil) drug product scraper — migrated onto the engine.

Brazilian national drug registry — Portuguese-language brand names, active
ingredients, therapeutic classes. Downloads the ANVISA open-data CSV directly
(no auth). Single bulk download + parse, not offset-paginated, so it is
modelled as one page: :meth:`fetch` downloads and parses the whole CSV and
returns ``(all_rows, None)`` on cursor 0.

The original never deduplicated rows, so ``id_field`` is left empty.

Schema per row:
  tipo_produto, nome_produto, data_finalizacao, categoria_regulatoria,
  numero_registro, data_vencimento, numero_processo, classe_terapeutica,
  empresa_detentora, situacao, principio_ativo

TLS verification is disabled, matching the original's ``verify=False`` +
``urllib3.disable_warnings`` (server cert issue).

Run it::

    python -m metadatarr.scrapers anvisa_drugs [--output DIR]
"""
from __future__ import annotations

import csv
import io
from typing import List

import requests

from metadatarr.scrapers.engine import Page, Source, register, run_cli

CSV_URL = "https://dados.anvisa.gov.br/dados/DADOS_ABERTOS_MEDICAMENTOS.csv"


@register
class AnvisaDrugsSource(Source):
    name = "anvisa_drugs"
    id_field = ""
    default_delay = 0.0

    def initial_cursor(self) -> int:
        return 0

    def fetch(self, cursor: int) -> Page:
        if cursor is None:
            return [], None

        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        s = requests.Session()
        s.headers["User-Agent"] = (
            "Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0"
        )
        r = s.get(CSV_URL, timeout=120, verify=False, stream=True)
        r.raise_for_status()

        raw = b""
        for chunk in r.iter_content(65536):
            raw += chunk
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("latin-1")

        reader = csv.DictReader(io.StringIO(text), delimiter=";")
        rows: List[dict] = []
        for item in reader:
            clean = {k.strip().lstrip("﻿"): v.strip().strip('"') for k, v in item.items() if k}
            rows.append({
                "tipo_produto": clean.get("TIPO_PRODUTO", ""),
                "nome_produto": clean.get("NOME_PRODUTO", ""),
                "data_finalizacao": clean.get("DATA_FINALIZACAO_PROCESSO", ""),
                "categoria_regulatoria": clean.get("CATEGORIA_REGULATORIA", ""),
                "numero_registro": clean.get("NUMERO_REGISTRO_PRODUTO", ""),
                "data_vencimento": clean.get("DATA_VENCIMENTO_REGISTRO", ""),
                "numero_processo": clean.get("NUMERO_PROCESSO", ""),
                "classe_terapeutica": clean.get("CLASSE_TERAPEUTICA", ""),
                "empresa_detentora": clean.get("EMPRESA_DETENTORA_REGISTRO", ""),
                "situacao": clean.get("SITUACAO_REGISTRO", ""),
                "principio_ativo": clean.get("PRINCIPIO_ATIVO", ""),
            })

        return rows, None


if __name__ == "__main__":
    raise SystemExit(run_cli(AnvisaDrugsSource))
