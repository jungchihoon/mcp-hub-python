"""
MCP Hub Python - A central coordinator for MCP servers and clients

This is a complete Python implementation of MCP Hub, providing:
- Unified MCP Server Endpoint (/mcp)
- Management Interface (/api/*)  
- Real-time events via Server-Sent Events
- Dynamic server management
- OAuth authentication support
- Marketplace integration
"""

from .hub import MCPHub
from .connection import MCPConnection
from .config import ConfigManager
from .marketplace import Marketplace

__version__ = "1.0.0"
__author__ = "MCP Hub Python Team"
__email__ = "team@mcphub.dev"

__all__ = [
    "MCPHub",
    "MCPConnection", 
    "ConfigManager",
    "Marketplace",
] 