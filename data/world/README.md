# data/world/

Curated geo-temporal anchors for the World Geo Timeline.

`historical_events.json` stores observed historical events with:

- real latitude/longitude
- observed date
- causal tags
- source reference into the internal knowledge corpus
- curated causal links

This folder is not raw news storage. News enters through the World forecast/geotimeline APIs as audited observations, then shifts forecast weights without rewriting observed history.

Compact correction history is stored separately under `data/runtime/world_forecast_revisions.jsonl`. It records scenario deltas and source-audit summaries, not full article bodies.
