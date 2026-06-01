# HANDOFF
Updated: 2026-06-01 | Branch: master (2 unpushed) | HEAD: `385ba89` feat(cockpit): remove Signals, Model subpage tabs, news declutter + photos + keyword chips

## Left off
Whole session was a cockpit UX + news overhaul (off the factor-model roadmap): removed the dead Signals page, folded Model Variants/Outcomes into tabs under Model & Backtest, decluttered the news page (advanced filters behind a ⚙ toggle), and rebuilt news visuals — on-brand topic cards → real rotating Pexels photos + LLM-generated fast-read keyword `#chips`. The factor-model thread ([ADR 0036](docs/decisions/0036-horizon-resolved-factor-evaluation.md) follow-up) is untouched and is the substantive next work.

## Pick up here
1. **ADR 0036 follow-up — horizon-resolved promotion gate** (↔ Track 3.3a): store `natural_horizon` in the registry + switch promotion from raw-IC t-stat to net-of-cost IR at that horizon. Data already in [tools/ic_decay.py](tools/ic_decay.py); needs `tools/backtest_pit.py` + registry + a turnover/cost model.
2. **§3.2.6 `industry_id` one-hot + §3.2.7 macro betas** — last build-now factors; new `signals/` + `tools/reconstruct_pit.py` (check `macro_history` coverage first).
3. **`pt_upside` re-verify (2026-08)** — reinforced by ic_decay (IC 0.67/t=28 @252d = survivorship); `tools.backtest_pit --signal pt_upside` once ≥3 fresh `analyst_consensus_snapshots` exist.

## Watch out
- **`_get_news_pool` is a 300s DISK cache** (`data/.cockpit_cache/_get_news_pool__hours=*.pkl`) that **survives restart** — after changing news card fields or downloading images, `rm` those `.pkl` (or wait 300s) or the change won't show. (bg_image stayed null after restart until I cleared it.)
- **News photos are gitignored** (`cockpit/static/news_img/`) — on a fresh deploy re-run `python -m sources.news_images` (needs `PEXELS_API_KEY`, now in `run_pipeline.sh`) or cards fall back to the gradient visual.
- **Keyword backfill** (`news_classifier --backfill-keywords`) was a one-time 30d pass (still finishing in background at handoff); articles >30d have no keywords. New articles get them via the nightly `compute` classifier automatically.

## Active plan
[docs/plans/0002-100-factors-and-model.md](docs/plans/0002-100-factors-and-model.md) — Phase 3.2 (42/50 PIT-shipped). This session was a cockpit drive-by, off-roadmap.
