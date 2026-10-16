#!/usr/bin/env python
"""lifedb MCP 服务入口 (shim — 真身在 lifedb/mcp.py, pip 安装后为 lifedb-mcp)"""
from lifedb.mcp import mcp

if __name__ == "__main__":
    mcp.run()  # stdio transport
