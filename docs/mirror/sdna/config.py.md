# doc(m): sdna/config.py

**Module:** `sdna/sdna/config.py`  •  **Mirrors:** the module 1:1 (IMPL — what the code IS)  •  **Projected from the HALO SEEM store:** 1 sealed boundary lands here

## Features whose sealed boundary lands in this module

### Webbing_Agent — feature boundary (no Giint_Feature node declared)

- **user action:** the sophia daemon ensures the webbing worker at start, or an operator ticks it, and concepts the main agent left as unstructured prose get real graph structure added instead of staying as auto stubs
- **doc(v):** (none declared — the join key is unfilled)
- **outputs to:** `['meta_sophia_audit']`
- **sealed:** v16, key `cef0933c5813ddb0`, commit `62111dda1`, valid from 2026-09-28T18:07:06
- **ranges in this module** (layer order):
  - `L4 agent_run` · `sdna/config.py:25-63` — HeavenAgentArgs, the heaven half of the SDNA HermesConfig the webber builds: max_tool_calls is a BaseHeavenAgent constructor argument and not a HeavenAgentConfig field, so it has its own field here instead of extra_agent_kwargs, which HeavenAgentConfig drops
- **also passes through:** `knowledge/carton-mcp/webbing_agent_worker.py`, `knowledge/carton-mcp/webbing_agent.py`, `sdna/heaven_runner.py`, `knowledge/carton-mcp/add_concept_tool.py`, `knowledge/carton-mcp/webbing_write_guard.py`, `knowledge/carton-mcp/test_webbing_write_guard.py`, `knowledge/carton-mcp/test_webbing_agent.py`, `tests/test_heaven_runner_max_tool_calls.py`

---

Projected by `seem docm` from the SEEM index (index.json, validity.json, the drafts); `doc-mirror-commit` regenerates it on every change of this module. Never written by hand and never by a spawned model (issue #225): what is not sealed in HALO SEEM is not in this doc(m).
