"""python -m mcp_google_insights で MCP stdio サーバーを起動。"""

import warnings

warnings.filterwarnings(
    "ignore",
    category=FutureWarning,
    message=".*Python version.*",
)

from mcp_google_insights.stdio_server import run_stdio_loop

if __name__ == "__main__":
    run_stdio_loop()
