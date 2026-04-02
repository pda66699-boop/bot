# Logic V5 Architecture

`v5` introduces a parallel assessment engine that does not replace `v4` in place.

Pipeline:

1. `validation_v5.py`
   - validates question ids and answer keys
   - calculates completeness
   - returns `ok | incomplete | invalid`
2. `assessment_engine_v5.py`
   - scores answer-level `paei`, `traits`, and `stage_signals`
   - aggregates traits into clusters
   - evaluates every stage with hard gates and weighted fit
   - classifies into `exact_stage | transitional_state | mixed_stage | undefined`
   - computes multi-factor confidence
   - derives warnings and simple history-based regress/recovery flags
3. `report_builder_v5.py`
   - builds report text and report JSON from the final classification object only

Data files:

- `data/questions_v3.yaml`
- `data/traits.yaml`
- `data/stage_definitions_v5.yaml`
- `data/report_templates_v5.yaml`

Runtime switching:

- `bot/assessment.py` chooses `v4` or `v5`
- feature flag: `USE_V5_ENGINE=1`

Compatibility:

- Telegram flow, append-only storage, leads, Sheets, and admin notifications stay intact
- `v4` remains available as fallback when the flag is off
