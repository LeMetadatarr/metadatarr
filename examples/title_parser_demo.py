"""Demonstrate the mediavocab title parser + metadatarr's signals_from_title adapter.

Run:  python examples/title_parser_demo.py
"""
from mediavocab.text import parse_title
from metadatarr.resolve.title_parser import signals_from_title

TITLES = [
    # Year + cut
    "Alien (1979) Director's Cut [Blu-ray]",
    "Blade Runner 2049 (2017) - Theatrical Version",
    "Metropolis (1927) [Restored Colorized Edition]",
    # Season / episode
    "Breaking Bad S03E07 One Minute (2010)",
    "The Wire - Season 2 (2002) [DVD]",
    # Music
    "Dark Side of the Moon - Deluxe Edition (1973) [Vinyl]",
    "Abbey Road - 50th Anniversary Remaster [4K UHD]",
    # AKA / multi-language
    "Spirited Away / Sen to Chihiro no Kamikakushi (2001) [Dubbed]",
    "Amelie (Le Fabuleux Destin d'Amélie Poulain) (2001)",
    # Fanedits
    "The Hobbit - Tolkien Edit [Extended Cut] (2012-2014)",
    # Format only
    "Inception [4K UHD Blu-ray]",
    # Minimal
    "Some Movie",
]

print(f"{'RAW TITLE':<55} {'YEAR':>5}  {'CUT':<14}  {'FORMAT':<12}  AKA / SEASON")
print("-" * 110)

for raw in TITLES:
    r = parse_title(raw)
    sig = signals_from_title(raw)
    year = str(r.year) if r.year else "-"
    cut  = r.variant_kind.value if r.variant_kind else "-"
    fmt  = r.source_format or "-"
    se   = f"S{r.season}E{r.episode}" if r.season and r.episode else (
           f"S{r.season}" if r.season else "-")
    aka  = ", ".join(r.aka) if r.aka else ""
    lang = r.language_hint or ""
    extras = " | ".join(filter(None, [se if se != "-" else "", aka, lang]))
    print(f"{raw:<55} {year:>5}  {cut:<14}  {fmt:<12}  {extras}")
