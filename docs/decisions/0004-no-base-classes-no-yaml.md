# 0004 — No base classes, no YAML config
**2026-04-09 · Accepted**

**Decision.** Each source/signal is a plain Python module with a clear function (`fetch_bhavcopy(date)`, `compute_piotroski(snapshot_date)`). Shared *convention*, not inheritance. All config in `config.py` as Python dicts.

**Why.** Earlier proposal had `BaseSource` / `BaseSignal` + YAML registries to "swap a source via one YAML line." We never actually needed that. ~10 sources, each idiosyncratic — abstraction added complexity without saving any.

**Trade-offs.**
- New source = new file + one entry in `config.PIPELINE_STEPS`. No registry, no metaclass.
- IDE goto-definition works on every constant
- Slight risk of inconsistency across sources — relies on review, not class hierarchy
- Revisit if we ever truly need interchangeable implementations of the same source (we don't)

**Not chosen.** Pydantic (overkill for our scale). Hydra/OmegaConf (ML-experiment tool).

**References.** `config.py` · `pipeline.py`
