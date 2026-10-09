# Zero-to-hero — `metadatarr` learning path

A nine-step progression from "first lookup" to "writing your own provider".
Each script stands alone (no shared state) and only depends on `metadatarr`
+ `mediavocab` being installed. Run them in order:

```bash
for f in examples/learn/[0-9]*.py; do
  echo "=== $f ==="
  python "$f"
done
```

| # | File | What you learn |
|---|---|---|
| 1 | `01_first_lookup.py` | Shortest useful program — `resolve(Signals(title=…))` |
| 2 | `02_three_axis_routing.py` | How `(media, playback_type, genre_filter)` gates dispatch |
| 3 | `03_search_vs_resolve.py` | When to ask for the candidate union vs the consensus |
| 4 | `04_consolidator_anatomy.py` | `ResolveResult.accepted` / `dropped` / `conflicts` |
| 5 | `05_variants_fanout.py` | `include_variants=True` for cuts, editions, fanedits |
| 6 | `06_direct_provider.py` | Bypass the resolver, talk to one provider |
| 7 | `07_voice_agent_routing.py` | Verb → `PlaybackType` for "play"/"watch"/"read" |
| 8 | `08_writing_a_provider.py` | Subclass `MetadataProvider`, declare three axes, `register()` |
| 9 | `09_caching_and_performance.py` | The `signal_hash` cache and how to keep it warm |
| 10 | `10_diagnostics.py` | `ResolveResult.provider_errors` — telling "no match" from "the lookup broke" |

Most queries hit live APIs (MusicBrainz, Wikidata, OpenLibrary, …). They're
keyless and fast; expect occasional rate-limit hiccups (treat as transient).

The other examples in this directory are problem-specific recipes (variant
fan-out for fanedits, music-video disambiguation, channel scanning, etc.).
Start with `learn/` if you're new; the recipes are reference once you've
done the tour.
