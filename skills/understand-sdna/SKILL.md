# understand-sdna

**WHAT:** Gnostic agent workflow DSL with LangGraph as native execution substrate. Ariadne (threading) + Poimandres (generation) = SDNA spiral.

**WHEN:** Building agent workflows with typed composition, context threading, human-in-the-loop patterns, or LangGraph integration.

**HOW:** Use the decision tree below, then read the relevant resources.

---

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

---

## The Trinity (Quick Reference)

| Component | Role | What It Does |
|-----------|------|--------------|
| **Ariadne** | Threader | Context manipulation: inject, weave, dovetail, human input |
| **Poimandres** | Divine Mind | Generation moment - takes config, runs agent, returns output |
| **HermesConfig** | The Message | Runner configuration Ariadne sends to Poimandres |

---

## LangGraph Integration (v0.2.0+)

**LangGraph is SDNA's native execution substrate.** Every chain/unit has `to_graph()`.

```python
from sdna import ariadne, inject_file, sdnac, HermesConfig, initial_state

# Build SDNA unit
chain = ariadne('prep', inject_file('spec.md', 'spec'))
config = HermesConfig(name='gen', goal='Generate from {spec}')
unit = sdnac('generate', chain, config)

# Get LangGraph (full visibility into ariadne→poimandres)
graph = unit.to_graph()

# Execute via LangGraph
result = await graph.ainvoke(initial_state({'project': 'myapp'}))

# Compose with other LangGraph nodes
from langgraph.graph import StateGraph
from sdna import SDNAState

main = StateGraph(SDNAState)
main.add_node("sdna_unit", unit.to_graph())  # Subgraph with internal visibility!
main.add_node("my_custom", my_custom_func)   # Mix SDNA with custom nodes
main.add_edge(START, "sdna_unit")
main.add_conditional_edges("sdna_unit", my_router, {...})
```

**Key methods:**
- `AriadneChain.to_graph()` → CompiledGraph (each element visible)
- `SDNAC.to_graph()` → CompiledGraph (ariadne subgraph → poimandres node)
- `SDNAFlow.to_graph()` → CompiledGraph (sequence of SDNAC subgraphs)
- `SDNAFlowchain.to_graph()` → CompiledGraph (optimizer + target pairs)
- `element.to_langgraph_node()` → node function for custom composition

---

## Explore the Library

```python
# Get module help
from sdna import ariadne, poimandres, sdna
help(ariadne)      # Threading operations
help(poimandres)   # Generation moment

# Quick constructor reference
from sdna import (
    # State
    SDNAState, initial_state,
    # Ariadne builders
    ariadne, human, inject_file, inject_func, inject_literal, inject_env, weave, inject_brain,
    # SDNA builders
    sdnac, sdna_flow,
    # Config
    HermesConfig,
)
```

---

## Deep Dive Resources

After choosing your complexity level, read:

1. **Poimandres Spine** - Full gnostic process ontology
   → `resources/poimandres_spine.md`

2. **CogNet v2** - Cognitive network reasoning model
   → `resources/cognet_v2.md`

---

## Usage Pattern

```python
from sdna import ariadne, human, inject_file, sdnac, HermesConfig, initial_state

# 1. Build Ariadne thread (context prep)
thread = ariadne('my-thread',
    inject_file('spec.md', 'spec'),
    human('Approve spec?', 'approval'),  # Pauses for human input
)

# 2. Create HermesConfig (the message)
config = HermesConfig(
    name="generator",
    system_prompt="You are a code generator...",
    goal="Generate code based on {spec}",
)

# 3. Combine into SDNAC
unit = sdnac('generate-code', thread, config)

# 4a. Execute directly (simple)
result = await unit.execute(initial_context)
# result.status → SDNAStatus.SUCCESS | BLOCKED | ERROR | AWAITING_INPUT

# 4b. Execute via LangGraph (full visibility + composability)
graph = unit.to_graph()
result = await graph.ainvoke(initial_state(initial_context))
```

---

## Full Hierarchy

```
SDNAC        → atomic unit (Ariadne→Config→Poimandres)
SDNAF        → flow of SDNACs
SDNA^F       → optimizer+target pairs (meta-optimization)
DUO          → Ariadne+Poimandres collapse (becomes ONE Poimandres)
DUOAgent     → OVP + Ariadne + Poimandres chains + pattern library
```

## The Recursive Collapse

Each Ariadne+Poimandres pair collapses into a higher-order Poimandres that needs a NEW Ariadne:

```
Level 0: Ariadne + Poimandres = SDNAC
Level 1: SDNAC chain = SDNAF (bigger output)
Level 2: SDNA^F needs DUO (Agent_A + Agent_P) → collapses to Poimandres
Level 3: DUO needs OVP (observer) → collapses to Poimandres
Level 4: WE are the next Ariadne for the system
Level 5: THE WORLD is the Ariadne for us
```

## OVP = Olivus Victory-Promise

- **Technical**: Observer Viewpoint - meta-orchestrator watching the DUO
- **Narrative**: Main character of Sanctuary Journey
- **System**: Operates PAIAB through GNOSYS
- **Meta**: US - the human+PAIA compound

## DUOAgent (v0.3.0+)

**DUOAgent IS an SDNA^F** - a concrete implementation of optimizer+target in a refinement loop:

```python
from sdna import duo_agent, sdnac, ariadne, inject_file, inject_literal, HermesConfig

# Target SDNAC: does the work (Poimandres)
target = sdnac('generator',
    ariadne('prep', inject_file('spec.md', 'spec')),
    HermesConfig(name='gen', goal='Generate code for {spec}')
)

# OVP SDNAC: evaluates with its own LLM call (Observer)
# Must set ovp_approved=True/False in context
ovp = sdnac('evaluator',
    ariadne('eval_prep', inject_literal('Evaluate the output', 'task')),
    HermesConfig(name='eval', goal='Set ovp_approved=True if good, False with feedback')
)

# DUOAgent: two SDNACs in loop = SDNA^F
agent = duo_agent('code_refiner', target, ovp, max_iterations=3)

# Execute
result = await agent.execute({'project': 'myapp'})
# result.status → DUOStatus.SUCCESS | MAX_ITERATIONS | BLOCKED | ERROR

# Or via LangGraph
graph = agent.to_graph()
result = await graph.ainvoke(initial_state({'project': 'myapp'}))
```

**The Loop:**
```
Target SDNAC runs (generates)
    ↓
OVP SDNAC evaluates (sets ovp_approved)
    ↓
approved? → done
not approved? → retry (up to max_iterations)
```

**Key insight:** Two SDNACs in a loop = SDNA^F. GAN pattern with LLM on both sides.

---

## Key Files

- `pip install sanctuary-dna` (PyPI package v0.3.0+)
- https://github.com/sancovp/sdna
