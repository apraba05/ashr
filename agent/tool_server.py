"""One-tool MCP server used by the eval scenarios."""

import warnings

warnings.filterwarnings(
    "ignore", message="Field 'lifespan' has an incomplete definition"
)

from mcp.server.fastmcp import FastMCP

POLICIES = {
    "refund_window": "30 days",
    "primary_region": "us-east-1",
    "support_sla": "4 hours",
    "audit_retention": "90 days",
}

mcp = FastMCP("policy-lookup", log_level="ERROR")


@mcp.tool()
def lookup_policy(key: str) -> str:
    """Return one frozen company-policy value by key."""
    if key not in POLICIES:
        raise ValueError(f"unknown policy key: {key}")
    return POLICIES[key]


if __name__ == "__main__":
    mcp.run(transport="stdio")
