"""
DUO V2 - Full 4-step DUOChain with gate position and tag extraction.

Ariadne → Poimandres → Ariadne gates → OVP gates

DuoAgentV2 IS a DUOChain with an additional ariadne_gate position
between Poimandres and OVP. Overrides execute() to implement the
4-step inner loop while preserving DUOChain type identity.

Uses extract_tags/match_tags for orchestration.
"""

from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from enum import Enum

from .sdna import SDNAC, SDNAStatus
from .tags import extract_tags, match_tags, has_tag, tag_equals, ANY
from .duo_chain import (
    DUOChain, DUOChainResult, DUOChainStatus,
    PositionResult, PositionStatus,
    SDNACPosition, SDNACOVPPosition,
)


class DUOv2Status(str, Enum):
    SUCCESS = "success"
    MAX_ITERATIONS = "max_iterations"
    BLOCKED = "blocked"
    ERROR = "error"


@dataclass
class DUOv2Result:
    status: DUOv2Status
    context: Dict[str, Any] = field(default_factory=dict)
    iterations: int = 0
    error: Optional[str] = None
    final_deliverable: Optional[str] = None


class DuoAgentV2(DUOChain):
    """
    Full DUO pattern: Ariadne → Poimandres → Ariadne gates → OVP gates.

    Extends DUOChain with a 4th position (ariadne_gate) between P and OVP.
    Uses XML tag extraction for orchestration instead of context keys.

    Expected tags:
    - Ariadne (A-type challenger): <challenge>...</challenge>
    - Poimandres (P-type generator): <deliverable>...</deliverable>
    - Ariadne gate (A-type gate): <gate-passed>true/false</gate-passed>, <gate-feedback>...</gate-feedback>
    - OVP (OVP-type observer): <ovp-approved>true/false</ovp-approved>, <ovp-feedback>...</ovp-feedback>
    """

    def __init__(
        self,
        name: str,
        ariadne: SDNAC,      # A-type: Challenger
        poimandres: SDNAC,    # P-type: Generator
        ariadne_gate: SDNAC,  # A-type: Gate
        ovp: SDNAC,           # OVP-type: Observer
        max_iterations: int = 5,
    ):
        # Initialize DUOChain base with wrapped positions
        super().__init__(
            name=name,
            ariadne=SDNACPosition(ariadne),
            poimandres=SDNACPosition(poimandres),
            ovp=SDNACOVPPosition(ovp),
            max_n=1,
            max_duo_cycles=max_iterations,
        )
        # Store raw SDNACs for direct access
        self._ariadne_sdnac = ariadne
        self._poimandres_sdnac = poimandres
        self._ariadne_gate_sdnac = ariadne_gate
        self._ovp_sdnac = ovp
        self.max_iterations = max_iterations

    async def execute(self, context=None) -> DUOv2Result:
        """
        Run the full 4-step DUO loop.

        A-type challenges → P-type generates → A-type gates → OVP-type approves.
        Gate rejection loops back to A. OVP rejection loops back to A.
        """
        ctx = dict(context) if context else {}
        ctx["attempt_feedback"] = "(first attempt)"

        for iteration in range(self.max_iterations):
            ctx["duo_iteration"] = iteration + 1
            ctx["duo_cycle"] = iteration + 1

            # Step 1: Ariadne challenges (A-type)
            result = await self._ariadne_sdnac.execute(ctx)
            if result.status == SDNAStatus.ERROR:
                return DUOv2Result(status=DUOv2Status.ERROR, error=result.error, iterations=iteration + 1)

            output = result.context.get("text", "")
            ctx.update(result.context)
            tags = extract_tags(output, ["challenge"])
            ctx["challenge"] = tags.get("challenge") or output

            # Step 2: Poimandres generates (P-type)
            result = await self._poimandres_sdnac.execute(ctx)
            if result.status == SDNAStatus.ERROR:
                return DUOv2Result(status=DUOv2Status.ERROR, error=result.error, iterations=iteration + 1)

            output = result.context.get("text", "")
            ctx.update(result.context)
            tags = extract_tags(output, ["deliverable"])
            ctx["deliverable"] = tags.get("deliverable") or output

            # Step 3: Ariadne gates (A-type gate)
            result = await self._ariadne_gate_sdnac.execute(ctx)
            if result.status == SDNAStatus.ERROR:
                return DUOv2Result(status=DUOv2Status.ERROR, error=result.error, iterations=iteration + 1)

            output = result.context.get("text", "")
            ctx.update(result.context)
            tags = extract_tags(output, ["gate-passed", "gate-feedback"])

            if not tag_equals(tags, "gate-passed", "true"):
                ctx["attempt_feedback"] = tags.get("gate-feedback") or "Gate rejected, try again"
                continue  # Loop back to Ariadne

            # Step 4: OVP approves (OVP-type)
            result = await self._ovp_sdnac.execute(ctx)
            if result.status == SDNAStatus.ERROR:
                return DUOv2Result(status=DUOv2Status.ERROR, error=result.error, iterations=iteration + 1)

            output = result.context.get("text", "")
            ctx.update(result.context)
            tags = extract_tags(output, ["ovp-approved", "ovp-feedback"])

            if tag_equals(tags, "ovp-approved", "true"):
                return DUOv2Result(
                    status=DUOv2Status.SUCCESS,
                    context=ctx,
                    iterations=iteration + 1,
                    final_deliverable=ctx.get("deliverable"),
                )

            ctx["attempt_feedback"] = tags.get("ovp-feedback") or "OVP rejected, try again"

        return DUOv2Result(
            status=DUOv2Status.MAX_ITERATIONS,
            context=ctx,
            iterations=self.max_iterations,
        )


def duo_agent_v2(
    name: str,
    ariadne: SDNAC,
    poimandres: SDNAC,
    ariadne_gate: SDNAC,
    ovp: SDNAC,
    max_iterations: int = 5,
) -> DuoAgentV2:
    """
    Create a DuoAgentV2: Full 4-step DUOChain pattern.

    Ariadne (A-type) → Poimandres (P-type) → Ariadne gate (A-type) → OVP (OVP-type)

    Args:
        name: Agent identifier
        ariadne: A-type Challenger SDNAC (outputs <challenge>)
        poimandres: P-type Generator SDNAC (outputs <deliverable>)
        ariadne_gate: A-type Gate SDNAC (outputs <gate-passed>true/false</gate-passed>)
        ovp: OVP-type Observer SDNAC (outputs <ovp-approved>true/false</ovp-approved>)
        max_iterations: Maximum iterations (default: 5)
    """
    return DuoAgentV2(name, ariadne, poimandres, ariadne_gate, ovp, max_iterations)
