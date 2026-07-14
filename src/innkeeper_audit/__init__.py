"""innkeeper-audit — autopilot night audit for small hotels.

Pipeline: fetch (3x MCP) -> normalize -> deterministic match -> adjudicate
(LLM on the mismatch residue only) -> expected-loss policy gate -> signed
Merkle night close.
"""

__version__ = "1.0.0"
PIPELINE_VERSION = f"innkeeper-audit/{__version__}+rules-v1"
