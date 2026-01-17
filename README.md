# SDNA - Sanctuary DNA

Gnostic agent workflow composition for Claude Agent SDK.

**Ariadne** (threading) + **Poimandres** (generation) = **SDNA** spiral

## Installation

```bash
pip install sdna-agent-sdk
```

## Quick Start

```python
from sdna import ariadne, human, inject_file, sdnac, sdna_flow, HermesConfig

# 1. Build Ariadne thread (context prep)
thread = ariadne('my-thread',
    inject_file('spec.md', 'spec'),
    human('Approve spec?', 'approval'),  # Pauses for human input
)

# 2. Create HermesConfig (the message)
config = HermesConfig(
    name="generator",
    system_prompt="You are a code generator...",
)

# 3. Combine into SDNAC
unit = sdnac('generate-code', thread, config)

# 4. Execute
result = await unit.execute({'initial': 'context'})
```

## The Trinity

| Component | Role | What It Does |
|-----------|------|--------------|
| **Ariadne** | Threader | Context manipulation: inject, weave, dovetail, human input |
| **Poimandres** | Divine Mind | Generation moment - takes config, runs agent, returns output |
| **HermesConfig** | The Message | Runner configuration Ariadne sends to Poimandres |

## Decision Tree: What to Build

```
Is this continuous improvement / optimization loop?
├── YES → SDNA^F (SDNAFlowchain)
│         Optimizer + target pairs. Meta-optimization.
│
└── NO → Are you composing multiple agent units in sequence?
    ├── YES → SDNAF (SDNAFlow)
    │         Flow of SDNACs. Sequential execution.
    │
    └── NO → SDNAC
              Single unit: AriadneChain → HermesConfig → Poimandres executes
```

## Ariadne Elements

```python
from sdna import (
    ariadne,           # Create chain
    human,             # Human input stop step
    inject_file,       # Inject file contents
    inject_func,       # Inject function result
    inject_literal,    # Inject literal value
    inject_env,        # Inject env variable
    weave,             # Context surgery between sessions
)
```

## License

MIT
