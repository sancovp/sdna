"""
DUO V2 - Full 4-step pattern with tag extraction.

Ariadne → Poimandres → Ariadne gates → OVP gates

Uses extract_tags/match_tags for orchestration.
"""

from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from enum import Enum

from .sdna import SDNAC, SDNAStatus
from .tags import extract_tags, match_tags, has_tag, tag_equals, ANY


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


class DuoAgentV2:
    """
    Full DUO pattern: Ariadne → Poimandres → Ariadne gates → OVP gates.

    Each agent outputs XML tags. Orchestration via extract_tags/match_tags.

    Expected tags:
    - Ariadne (challenger): <challenge>...</challenge>
    - Poimandres (generator): <deliverable>...</deliverable>
    - Ariadne (gate): <gate-passed>true/false</gate-passed>, <gate-feedback>...</gate-feedback>
    - OVP (observer): <ovp-approved>true/false</ovp-approved>, <ovp-feedback>...</ovp-feedback>
    """

    def __init__(
        self,
        name: str,
        ariadne: SDNAC,      # Challenger
        poimandres: SDNAC,   # Generator
        ariadne_gate: SDNAC, # Gate
        ovp: SDNAC,          # Observer
        max_iterations: int = 5,
    ):
        self.name = name
        self.ariadne = ariadne
        self.poimandres = poimandres
        self.ariadne_gate = ariadne_gate
        self.ovp = ovp
        self.max_iterations = max_iterations

    async def execute(self, context: Optional[Dict[str, Any]] = None) -> DUOv2Result:
        """Run the full DUO loop."""
        ctx = dict(context) if context else {}
        ctx["attempt_feedback"] = "(first attempt)"

        for iteration in range(self.max_iterations):
            ctx["duo_iteration"] = iteration + 1

            # Step 1: Ariadne challenges
            result = await self.ariadne.execute(ctx)
            if result.status == SDNAStatus.ERROR:
                return DUOv2Result(status=DUOv2Status.ERROR, error=result.error, iterations=iteration + 1)

            output = result.context.get("text", "")
            tags = extract_tags(output, ["challenge"])
            ctx["challenge"] = tags.get("challenge") or output

            # Step 2: Poimandres generates
            result = await self.poimandres.execute(ctx)
            if result.status == SDNAStatus.ERROR:
                return DUOv2Result(status=DUOv2Status.ERROR, error=result.error, iterations=iteration + 1)

            output = result.context.get("text", "")
            tags = extract_tags(output, ["deliverable"])
            ctx["deliverable"] = tags.get("deliverable") or output

            # Step 3: Ariadne gates
            result = await self.ariadne_gate.execute(ctx)
            if result.status == SDNAStatus.ERROR:
                return DUOv2Result(status=DUOv2Status.ERROR, error=result.error, iterations=iteration + 1)

            output = result.context.get("text", "")
            tags = extract_tags(output, ["gate-passed", "gate-feedback"])

            if not tag_equals(tags, "gate-passed", "true"):
                ctx["attempt_feedback"] = tags.get("gate-feedback") or "Gate rejected, try again"
                continue  # Loop back to Ariadne

            # Step 4: OVP approves
            result = await self.ovp.execute(ctx)
            if result.status == SDNAStatus.ERROR:
                return DUOv2Result(status=DUOv2Status.ERROR, error=result.error, iterations=iteration + 1)

            output = result.context.get("text", "")
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
    Create a DuoAgentV2: Full 4-step pattern.

    Ariadne → Poimandres → Ariadne gates → OVP gates

    Args:
        name: Agent identifier
        ariadne: Challenger SDNAC (outputs <challenge>)
        poimandres: Generator SDNAC (outputs <deliverable>)
        ariadne_gate: Gate SDNAC (outputs <gate-passed>true/false</gate-passed>)
        ovp: Observer SDNAC (outputs <ovp-approved>true/false</ovp-approved>)
        max_iterations: Maximum iterations (default: 5)
    """
    return DuoAgentV2(name, ariadne, poimandres, ariadne_gate, ovp, max_iterations)
