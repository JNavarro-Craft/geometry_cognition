from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from gc_mcp.geometry_kernel.tools import compute_geometry_features
from fastmcp import FastMCP


mcp = FastMCP("geometry_kernel")


@mcp.tool(name="compute_geometry_features")
def compute_geometry_features_tool(payload: dict) -> dict:
    return compute_geometry_features(payload)


def run_server() -> None:
    mcp.run()


if __name__ == "__main__":
    run_server()
