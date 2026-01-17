"""
SDNA - Sanctuary Dragon Activity Chain

The spiral of Ariadne and Poimandres.

SDNAC = AriadneChain → HermesConfig → Poimandres executes → repeat
SDNAF = flow of SDNACs
SDNA^F = optimizer + target pairs
"""

from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
from pydantic import BaseModel, Field

from .config import HermesConfig
from .ariadne import AriadneChain, AriadneResult, AriadneStatus
from . import poimandres


# =============================================================================
# STATUS & RESULT
# =============================================================================

class SDNAStatus(str, Enum):
    SUCCESS = "success"
    BLOCKED = "blocked"
    ERROR = "error"
    AWAITING_INPUT = "awaiting_input"


@dataclass
class SDNAResult:
    status: SDNAStatus
    context: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    resume_path: Optional[List[int]] = None
    pending_prompt: Optional[str] = None
    pending_input_key: Optional[str] = None


# =============================================================================
# SDNAC (Ariadne → HermesConfig → Poimandres)
# =============================================================================

class SDNAC:
    """
    Single SDNAC unit: AriadneChain preps context, then Poimandres executes config.
    """

    def __init__(self, name: str, ariadne: AriadneChain, config: HermesConfig):
        self.name = name
        self.ariadne = ariadne
        self.config = config

    async def execute(self, context: Optional[Dict[str, Any]] = None) -> SDNAResult:
        ctx = dict(context) if context else {}

        # Ariadne preps the thread
        ariadne_result = await self.ariadne.execute(ctx)
        ctx = ariadne_result.context

        if ariadne_result.status == AriadneStatus.AWAITING_INPUT:
            return SDNAResult(
                status=SDNAStatus.AWAITING_INPUT,
                context=ctx,
                pending_prompt=ariadne_result.pending_prompt,
                pending_input_key=ariadne_result.pending_input_key,
            )
        elif ariadne_result.status == AriadneStatus.ERROR:
            return SDNAResult(status=SDNAStatus.ERROR, context=ctx, error=ariadne_result.error)

        # Poimandres generates
        poimandres_result = await poimandres.execute(self.config, ctx)

        if poimandres_result.blocked:
            return SDNAResult(status=SDNAStatus.BLOCKED, context=ctx)
        elif not poimandres_result.success:
            return SDNAResult(status=SDNAStatus.ERROR, context=ctx, error=poimandres_result.error)

        ctx.update(poimandres_result.output)
        return SDNAResult(status=SDNAStatus.SUCCESS, context=ctx)


# =============================================================================
# SDNAF (flow of SDNACs)
# =============================================================================

class SDNAFlow:
    """SDNAF - Flow of SDNACs."""

    def __init__(self, name: str, sdnacs: List[SDNAC]):
        self.name = name
        self.sdnacs = sdnacs

    async def execute(self, context: Optional[Dict[str, Any]] = None) -> SDNAResult:
        ctx = dict(context) if context else {}

        for i, sdnac in enumerate(self.sdnacs):
            result = await sdnac.execute(ctx)
            ctx = result.context

            if result.status != SDNAStatus.SUCCESS:
                result.resume_path = [i]
                return result

        return SDNAResult(status=SDNAStatus.SUCCESS, context=ctx)


# =============================================================================
# CONFIGS (serializable)
# =============================================================================

class SDNACConfig(BaseModel):
    """Serializable config for SDNAC."""
    name: str
    ariadne_elements: List[dict]
    hermes_config: dict


class OptimizerSDNACConfig(SDNACConfig):
    """Config for optimizer SDNAC."""
    optimization_target: str
    optimization_strategy: str
    feedback_key: str = "optimizer_feedback"


class SDNAFlowConfig(BaseModel):
    """Config for SDNAF."""
    name: str
    sdnacs: List[SDNACConfig]


# =============================================================================
# SDNA^F (optimizer + target pairs)
# =============================================================================

class SDNAFlowchain:
    """SDNA^F - optimizer + target pairs."""

    def __init__(self, name: str, pairs: List[Tuple[OptimizerSDNACConfig, SDNACConfig]]):
        self.name = name
        self.pairs = pairs

    async def execute(self, context: Optional[Dict[str, Any]] = None) -> SDNAResult:
        ctx = dict(context) if context else {}
        # Implementation: run target, then optimizer reviews
        # (Full implementation requires hydration from configs)
        return SDNAResult(status=SDNAStatus.SUCCESS, context=ctx)


# =============================================================================
# CONSTRUCTORS
# =============================================================================

def sdnac(name: str, ariadne: AriadneChain, config: HermesConfig) -> SDNAC:
    """
    Create an SDNAC unit: AriadneChain preps context, then Poimandres executes.

    Args:
        name: Unit identifier
        ariadne: AriadneChain for context preparation
        config: HermesConfig (the message Ariadne sends)

    Example:
        unit = sdnac('generate',
            ariadne('prep', inject_file('spec.md', 'spec')),
            HermesConfig(name='gen', system_prompt='...')
        )
        result = await unit.execute({'initial': 'context'})
    """
    return SDNAC(name, ariadne, config)


def sdna_flow(name: str, *sdnacs: SDNAC) -> SDNAFlow:
    """
    Create an SDNAF: sequential flow of SDNACs.

    Args:
        name: Flow identifier
        *sdnacs: SDNAC units to execute in sequence

    Example:
        flow = sdna_flow('pipeline', unit1, unit2, unit3)
        result = await flow.execute()
        # Stops on first non-SUCCESS, returns resume_path
    """
    return SDNAFlow(name, list(sdnacs))
