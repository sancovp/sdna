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
from .config import HermesConfig, DovetailModel, HermesConfigInput, HeavenInputs, HeavenAgentArgs, HeavenHermesArgs
from .claude_code_commands import ClaudeCodeSession, get_session, list_tmux_sessions, find_claude_session
from .context_engineering import (
    TransitionAction, ActivateLoop, WeaveContext, InjectContext, RunSequence, NextTarget,
    Heartbeat, HeartbeatScheduler, heartbeat
)
from .slinky_context import (
    ContentLocation, SessionScanner, CartonStore,
    SlinkyCompressor, CompressionResult, compress_session
)
from .slinky_manager import (
    SlinkyWatcher, SlinkyRollup, GiintIntegration, SlinkyState, CompressionEvent,
    start_slinky, stop_slinky, get_slinky_status
)
from .tools import BlockedReport, parse_blocked_from_text, get_cached_reports, clear_cached_reports
from .crystal_ball import (
    CrystalBallError,
    CrystalBallPaths,
    CrystalBallRunner,
    get_crystal_ball_runner,
    cb_map_cypher_to_cb,
    cb_enrich_story_machine_cb,
    cb_read_cb_stats,
    cb_bootstrap_story_machine,
    cb_llm_suggest,
)
from .crystal_ball_flow import create_flow as create_crystal_ball_flow, run as run_crystal_ball_flow
from .runner import agent_step, StepResult, StepStatus
from .heaven_runner import heaven_agent_step
from .ariadne import (
    AriadneChain, AriadneResult, AriadneStatus,
    AriadneElement, HumanInput, InjectConfig, WeaveConfig, BrainInjectConfig,
    ariadne, human, inject_file, inject_func, inject_literal, inject_env, weave, inject_brain,
)
from .brain import Brain, BrainConfig, Neuron, CognitionResult
from .sdna import (
    SDNAC, SDNAFlow, SDNAFlowchain,
    SDNAResult, SDNAStatus,
    SDNAFlowchainResult, SDNAFlowchainStatus,
    SDNACConfig, OptimizerSDNACConfig, SDNAFlowConfig,
    sdnac, sdna_flow, sdna_flowchain,
)
from .duo import DUOAgent, DUOResult, DUOStatus, duo_agent
from .duo_v2 import DuoAgentV2, DUOv2Result, DUOv2Status, duo_agent_v2
from .duo_chain import (
    DUOChain, DUOChainResult, DUOChainStatus,
    PositionResult, PositionStatus, DUOPosition,
    SDNACPosition, SDNACOVPPosition, PassthroughPosition, CallablePosition,
    AutoDUOAgent,
    duo_chain, auto_duo_agent,
)
from .orchestrated_duo_chain import (
    OrchestratedDUOChain, OrchestratedDUOChainResult, OrchestratedDUOChainStatus,
    orchestrated_duo_chain,
)
from .tags import extract_tags, match_tags, has_tag, tag_equals, tag_contains, ANY
# code_agent removed - hooks now in CAVE
from . import poimandres
from .defaults import get_default_mcp_servers, get_default_hermes_config, default_config

__all__ = [
    # State (LangGraph substrate)
    "SDNAState",
    "initial_state",
    # Config
    "HermesConfig",
    "DovetailModel",
    "HermesConfigInput",
    "HeavenInputs",
    "HeavenAgentArgs",
    "HeavenHermesArgs",
    # Tools
    "BlockedReport",
    "parse_blocked_from_text",
    "get_cached_reports",
    "clear_cached_reports",
    "CrystalBallError",
    "CrystalBallPaths",
    "CrystalBallRunner",
    "get_crystal_ball_runner",
    "cb_map_cypher_to_cb",
    "cb_enrich_story_machine_cb",
    "cb_read_cb_stats",
    "cb_bootstrap_story_machine",
    "cb_llm_suggest",
    "create_crystal_ball_flow",
    "run_crystal_ball_flow",
    # Runner
    "agent_step",
    "heaven_agent_step",
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
    "SDNAFlowchainResult",
    "SDNAFlowchainStatus",
    "SDNACConfig",
    "OptimizerSDNACConfig",
    "SDNAFlowConfig",
    "sdnac",
    "sdna_flow",
    "sdna_flowchain",
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
    # DUOChain (abstract state machine)
    "DUOChain",
    "DUOChainResult",
    "DUOChainStatus",
    "PositionResult",
    "PositionStatus",
    "DUOPosition",
    "SDNACPosition",
    "SDNACOVPPosition",
    "PassthroughPosition",
    "CallablePosition",
    "AutoDUOAgent",
    "duo_chain",
    "auto_duo_agent",
    # OrchestratedDUOChain (external OVP pattern)
    "OrchestratedDUOChain",
    "OrchestratedDUOChainResult",
    "OrchestratedDUOChainStatus",
    "orchestrated_duo_chain",
    # Tags (extraction/matching)
    "extract_tags",
    "match_tags",
    "has_tag",
    "tag_equals",
    "tag_contains",
    "ANY",
    # code_agent removed - hooks now in CAVE
    # Defaults (MCP configs)
    "get_default_mcp_servers",
    "get_default_hermes_config",
    "default_config",
    # Claude Code Commands
    "ClaudeCodeSession",
    "get_session",
    "list_tmux_sessions",
    "find_claude_session",
    # Transition Actions (for chaining context ops with loop transitions)
    "TransitionAction",
    "ActivateLoop",
    "WeaveContext",
    "InjectContext",
    "RunSequence",
    "NextTarget",
    # Heartbeat system
    "Heartbeat",
    "HeartbeatScheduler",
    "heartbeat",
    # Slinky Context (hierarchical compression)
    "ContentLocation",
    "SessionScanner",
    "CartonStore",
    "SlinkyCompressor",
    "CompressionResult",
    "compress_session",
    # Slinky Manager (GIINT-integrated background compressor)
    "SlinkyWatcher",
    "SlinkyRollup",
    "GiintIntegration",
    "SlinkyState",
    "CompressionEvent",
    "start_slinky",
    "stop_slinky",
    "get_slinky_status",
]
