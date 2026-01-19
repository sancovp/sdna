"""
SDNA - Sanctuary DNA

Gnostic agent workflow DSL with LangGraph as native execution substrate.
Ariadne (threading) + Poimandres (generation) = SDNA spiral.

Components:
- Ariadne: context threading (inject, weave, human input)
- Poimandres: generation moment (execute)
- SDNA: spiral composition (SDNAC → SDNAF → SDNA^F)
- State: SDNAState TypedDict for LangGraph execution

Every chain has to_graph() which returns a LangGraph CompiledGraph.
Every element has to_langgraph_node() for custom composition.
"""

from .state import SDNAState, initial_state
from .config import HermesConfig, DovetailModel, HermesConfigInput
from .tools import BlockedReport, parse_blocked_from_text, get_cached_reports, clear_cached_reports
from .runner import agent_step, StepResult, StepStatus
from .ariadne import (
    AriadneChain, AriadneResult, AriadneStatus,
    AriadneElement, HumanInput, InjectConfig, WeaveConfig, BrainInjectConfig,
    ariadne, human, inject_file, inject_func, inject_literal, inject_env, weave, inject_brain,
)
from .brain import Brain, BrainConfig, Neuron, CognitionResult
from .sdna import (
    SDNAC, SDNAFlow, SDNAFlowchain,
    SDNAResult, SDNAStatus,
    SDNACConfig, OptimizerSDNACConfig, SDNAFlowConfig,
    sdnac, sdna_flow,
)
from .duo import DUOAgent, DUOResult, DUOStatus, duo_agent
from .duo_v2 import DuoAgentV2, DUOv2Result, DUOv2Status, duo_agent_v2
from .tags import extract_tags, match_tags, has_tag, tag_equals, tag_contains, ANY
from . import poimandres

__all__ = [
    # State (LangGraph substrate)
    "SDNAState",
    "initial_state",
    # Config
    "HermesConfig",
    "DovetailModel",
    "HermesConfigInput",
    # Tools
    "BlockedReport",
    "parse_blocked_from_text",
    "get_cached_reports",
    "clear_cached_reports",
    # Runner
    "agent_step",
    "StepResult",
    "StepStatus",
    # Ariadne (context threading)
    "AriadneChain",
    "AriadneResult",
    "AriadneStatus",
    "AriadneElement",
    "HumanInput",
    "InjectConfig",
    "WeaveConfig",
    "BrainInjectConfig",
    "ariadne",
    "human",
    "inject_file",
    "inject_func",
    "inject_literal",
    "inject_env",
    "weave",
    "inject_brain",
    # Brain (neural knowledge retrieval)
    "Brain",
    "BrainConfig",
    "Neuron",
    "CognitionResult",
    # Poimandres (generation moment)
    "poimandres",
    # SDNA (spiral composition)
    "SDNAC",
    "SDNAFlow",
    "SDNAFlowchain",
    "SDNAResult",
    "SDNAStatus",
    "SDNACConfig",
    "OptimizerSDNACConfig",
    "SDNAFlowConfig",
    "sdnac",
    "sdna_flow",
    # DUO (refinement loop)
    "DUOAgent",
    "DUOResult",
    "DUOStatus",
    "duo_agent",
    # DUO V2 (full 4-step pattern)
    "DuoAgentV2",
    "DUOv2Result",
    "DUOv2Status",
    "duo_agent_v2",
    # Tags (extraction/matching)
    "extract_tags",
    "match_tags",
    "has_tag",
    "tag_equals",
    "tag_contains",
    "ANY",
]
