"""chain_ontology — re-exported from the standalone `uco` (universal-chain-ontology) package.

The Link/Chain primitives now live in `uco` (zero-dependency, on PyPI). This module re-exports them so
every `from sdna.chain_ontology import X` keeps working unchanged, and the class identity is shared
(one `Link` everywhere — `sdna.chain_ontology.Link is uco.Link`).
"""
from uco import (
    LinkStatus,
    LinkResult,
    Link,
    Chain,
    EvalChain,
    Compiler,
    LinkConfig,
    ConfigLink,
)

__all__ = [
    "LinkStatus", "LinkResult", "Link", "Chain", "EvalChain", "Compiler", "LinkConfig", "ConfigLink",
]
