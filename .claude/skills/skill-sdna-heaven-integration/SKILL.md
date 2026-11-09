---
name: skill-sdna-heaven-integration
description: 'WHAT: ''''''How HermesConfig fields map to HeavenAgentConfig+HeavenHermesConfig

  WHEN: ''''''When creating any SDNAC/SDNAFlow that needs to execute via Heaven backend
  on MiniMax or Anthropic'''''''
---

'''How SDNA and Heaven integrate: SDNAC(AriadneChain→HermesConfig→Poimandres) is the atomic unit. heaven_runner.py bridges HermesConfig to HeavenAgentConfig(WHO)+HeavenHermesConfig(WHAT) and calls hermes_step(). SDNAFlow=Chain of SDNACs. MiniMax defaults. MCP server translation. Block report handling. Context threads through via dict.''' '''Replayable skill pattern - understand=context only''' '''Sanctuary DNA — the agent execution framework. AriadneChain+HermesConfig+Poimandres=SDNAC''' '''Skill category classification''' '''Personal domain category enum for observation tagging''' '''Sanctuary DNA — the agent execution framework combining Ariadne (context) '''The bridge between SDNA configs and Heaven agent execution via heaven_runner.py''' '''How HermesConfig fields map to HeavenAgentConfig+HeavenHermesConfig '''When creating any SDNAC/SDNAFlow that needs to execute via Heaven backend on MiniMax or Anthropic''' '''A configured SDNAC that executes through Heaven hermes_step with proper provider '''Depends on understanding the chain ontology to compose SDNACs into flows and eval chains'''

---
## Skill Contents

- `reference.md` — detailed reference (read for full docs)
