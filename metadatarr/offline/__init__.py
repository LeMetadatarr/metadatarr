# SPDX-License-Identifier: Apache-2.0
"""A read-only local SQLite copy of the public LeData metadata datasets.

``metadatarr-sync`` downloads the parquet datasets from the Hugging Face Hub
and builds one SQLite file per set (:mod:`metadatarr.offline.sync`,
:mod:`metadatarr.offline.build`). :mod:`metadatarr.offline.layer` lets the
resolver, the enrichment and the catalogue lookup answer from those files
before asking a live provider. The layer is off unless
``METADATARR_OFFLINE_DIR`` is set. See ``docs/offline.md``.
"""
