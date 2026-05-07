"""Step 9 — caching and performance.

Provider responses are cached in-memory keyed by ``(provider.name,
signal_hash(signals))``. A second resolve() call with equal signals
hits the cache instead of the network. Disk caching for HTTP
responses is provided by ``metadatarr.resolve._http_cache`` (used by
several providers internally).
"""
from time import perf_counter

from mediavocab import MediaType, Signals
from metadatarr.resolve import resolve


def time_it(label: str, fn) -> float:
    t0 = perf_counter()
    fn()
    dt = perf_counter() - t0
    print(f"  {label:<24} {dt*1000:7.1f} ms")
    return dt


def main() -> None:
    sig = Signals(title="OK Computer", artist="Radiohead",
                  medium=MediaType.MUSIC)

    print("Resolving 'OK Computer' three times:")
    cold = time_it("1st call (cold cache)",   lambda: resolve(sig))
    warm = time_it("2nd call (warm cache)",   lambda: resolve(sig))
    warm2 = time_it("3rd call (warm cache)", lambda: resolve(sig))

    speedup = cold / max(warm, 1e-9)
    print(f"\nCache speedup on the 2nd call: {speedup:.0f}×")
    print(f"  (in-memory cache hit: every provider returns instantly)")
    print(f"\nThe cache key is (provider.name, signal_hash(signals)). Change")
    print(f"any identity field on Signals (title, year, runtime, …) and the")
    print(f"hash changes, so the cache misses.")


if __name__ == "__main__":
    main()
