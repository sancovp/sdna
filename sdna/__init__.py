"""
SDNA - Sanctuary DNA

Gnostic agent workflow DSL for Claude Agent SDK.
Ariadne (threading) + Poimandres (generation) = SDNA spiral.

Components:
- Ariadne: context threading (inject, weave, human input)
- Poimandres: generation moment (execute)
- SDNA: spiral composition (SDNAC → SDNAF → SDNA^F)
"""

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
from . import poimandres

__all__ = [
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
]
