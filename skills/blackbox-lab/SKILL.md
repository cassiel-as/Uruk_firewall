---
name: blackbox-lab
description: |
  Dispatcher mode that runs assumption-isolation thought experiments. Fired
  when user asks "what if X had not happened" / "假設冇咗 X" / 反事實
  / counterfactual reasoning, or when the dispatcher routes to mode
  `blackboxlab`. Tracks the cost-coordinate shift between observed history
  and the counterfactual scenario.

  Triggers: 假設 / 如果 / what if / counterfactual / 反事實 / 抽走 / 假如冇
---

# Blackbox Lab

## What it does

Stage 4 dispatcher mode that isolates a single causal variable and traces
what the world's coordinate space looks like without it. Output captures:

- the variable removed
- the cost transfer that historically rode on it
- the predicted alternative cost landing point
- which existing CAU files anchor the comparison

## When it fires

- Dispatcher (`dispatcher.txt`) classifies the input as counterfactual
- User explicitly invokes `/blackbox`
- Query contains a hypothetical removal of a known historical cause

## Source

- Prompt: `config/prompts/blackboxlab.txt`
- Mode wiring: `app.py` event_generator → dispatch → `blackboxlab` mode
- Related corpus: `data/causal_db/CAU-*.md`

## Output shape

Free-form analytical text grounded in the 八律 + 四律 framework. Should
surface at minimum: removed variable, primary cost transfer disrupted,
secondary effects within ~100 years, and which CAU files were consulted.
