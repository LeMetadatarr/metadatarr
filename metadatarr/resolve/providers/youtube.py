"""YouTube (regular, non-music) metadata provider via :mod:`tutubo`.

**Conceptual scope.** YouTube is a hosting platform, not a metadata
catalog. A YouTube ``video_id`` identifies *one upload*, not a song / film
/ show — the same work has thousands of uploads, none authoritative.
Treating ``video_id`` as a music-track id would be a category error.

This provider is therefore intentionally narrow:

- It only emits :class:`MediaType`-aware matches for content that's
  **original to YouTube** — channels, vlogs, video essays, original-to-YT
  podcasts, etc. — and even then it never claims ``MediaType.MUSIC``.
- It surfaces ``youtube_video_id`` (the upload) and
  ``youtube_channel_id`` (the channel that uploaded it).
- It emits :class:`EntityRole.CHANNEL` relations, never ``ARTIST`` or
  ``ALBUM``. A channel is not an artist.

For music — including matches that *happen* to live on YouTube — use the
separate ``youtube_music`` provider, which keys off YT Music's proper
artist / album ``browseId`` entity records.
"""
from __future__ import annotations

import logging
from typing import Optional

from tutubo import classify_video_dict, search_yt
from tutubo.content_type import ContentType

from metadatarr.resolve.base import MetadataProvider, ProviderMatch, register
from metadatarr.resolve.entities import EntityRole, ProviderEntity
from mediavocab.models import ExternalIds
from mediavocab import MediaType
from mediavocab.models.signals import Signals

LOG = logging.getLogger("metadatarr.resolve.providers.youtube")

_MUSIC_CONTENT_TYPES = {ContentType.MUSIC_AUDIO, ContentType.MUSIC_VIDEO, ContentType.CONCERT}


class YouTubeProvider(MetadataProvider):
    """Regular YouTube — channel + upload identifiers only.

    Skips ``MediaType.MUSIC`` lookups entirely; those go through the
    ``youtube_music`` provider.
    """

    name = "youtube"
    media = {MediaType.MOVIE, MediaType.EPISODIC_SERIES, MediaType.PODCAST, MediaType.GENERIC}

    def is_available(self) -> bool:
        return True

    def lookup(self, signals: Signals) -> Optional[ProviderMatch]:
        if not signals.title:
            return None
        if signals.medium == MediaType.MUSIC:
            return None

        try:
            results = list(search_yt(signals.title, as_dict=True, max_res=3))
        except Exception as exc:
            LOG.warning("youtube search failed: %s", exc)
            return None

        if not results:
            return None
        top = results[0]

        title = top.get("title") or signals.title
        video_id = top.get("videoId") or top.get("video_id")
        channel_name = top.get("channel") or top.get("uploader") or top.get("author")
        channel_id = top.get("channelId") or top.get("channel_id")

        runtime = top.get("length")
        try:
            runtime = float(runtime) if runtime is not None else None
        except (TypeError, ValueError):
            runtime = None

        ctype = classify_video_dict(top)

        # Skip music content — let youtube_music provider handle it.
        if ctype in _MUSIC_CONTENT_TYPES and signals.medium != MediaType.MUSIC_VIDEO:
            return None

        extra = {}
        if video_id:
            extra["youtube_video_id"] = str(video_id)
        if channel_id:
            extra["youtube_channel_id"] = str(channel_id)
        extra["youtube_content_type"] = ctype.value

        relations: dict = {}
        if channel_name:
            channel_extra: dict = {}
            if channel_id:
                channel_extra["youtube_channel_id"] = str(channel_id)
            relations[EntityRole.CHANNEL] = [ProviderEntity(
        role=EntityRole.CHANNEL,
                name=str(channel_name),
                external_ids=ExternalIds(extra=channel_extra),
            )]

        # Derive MediaType from ContentType so the signal is populated rather than absent.
        inferred_medium_str = ctype.to_medium()
        try:
            inferred_medium = MediaType(inferred_medium_str)
        except ValueError:
            inferred_medium = MediaType.GENERIC

        return ProviderMatch(
            provider=self.name,
            confidence=0.5,
            signals=Signals(
                title=title,
                runtime=runtime,
                medium=inferred_medium,
            ),
            external_ids=ExternalIds(extra=extra),
            relations=relations,
        )


register(YouTubeProvider())
