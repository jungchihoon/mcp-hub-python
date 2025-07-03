"""Main MCP Hub implementation for Python.

Complete Python port of Node.js MCPHub providing:
- Unified MCP server management
- Dynamic capability aggregation
- Real-time event distribution
- Server lifecycle management
"""

import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

import structlog
from mcp.types import Tool, Resource, Prompt, CallToolResult, ReadResourceResult, GetPromptResult

from .config import ConfigManager
from .connection import MCPConnection
from .events import EventEmitter
from .marketplace import Marketplace
from .types import (
    HubState, ConnectionStatus, ConfigChanges, ServerInfo, HubStats,
    MCPServersConfig, ServerConfig, SSEEvent, EventType, SubscriptionType
)


logger = structlog.get_logger(__name__)


class MCPHub(EventEmitter):
    """
    Central MCP Hub coordinator.
    
    Complete Python port of Node.js MCPHub providing:
    - Multi-server management and orchestration
    - Unified capability aggregation with namespacing
    - Real-time configuration reloading
    - Dynamic server addition/removal
    - Event-driven architecture
    """
    
    def __init__(
        self,
        config_manager: ConfigManager,
        marketplace: Optional[Marketplace] = None,
        hub_server_url: str = "http://localhost:3000"
    ) -> None:
        super().__init__()
        
        self.config_manager = config_manager
        self.marketplace = marketplace
        self.hub_server_url = hub_server_url
        
        # Hub state
        self.state = HubState.READY
        self.start_time = datetime.now()
        
        # Server connections
        self.connections: Dict[str, MCPConnection] = {}
        
        # Aggregated capabilities with namespacing
        self.tools: Dict[str, Tool] = {}  # namespaced_name -> Tool
        self.resources: Dict[str, Resource] = {}  # namespaced_name -> Resource
        self.prompts: Dict[str, Prompt] = {}  # namespaced_name -> Prompt
        
        # Tool/resource/prompt -> server mapping for routing
        self.tool_to_server: Dict[str, str] = {}
        self.resource_to_server: Dict[str, str] = {}
        self.prompt_to_server: Dict[str, str] = {}
        
        # Event subscriptions
        self.subscribers: Set[str] = set()
        
        # Setup config change handler
        self.config_manager.on("config_changed", self._handle_config_changed)
        
        logger.info("MCPHub initialized", hub_url=hub_server_url)
    
    async def start(self) -> None:
        """Start the MCP Hub and all configured servers."""
        logger.info("Starting MCP Hub")
        
        try:
            self.state = HubState.STARTING
            await self.emit("hubStateChanged", {"state": self.state})
            
            # Load initial configuration
            config = self.config_manager.get_config()
            if not config:
                await self.config_manager.load_config()
                config = self.config_manager.get_config()
            
            if config:
                await self._create_servers(config.mcpServers)
                await self._start_all_servers()
            
            self.state = HubState.READY
            await self.emit("hubStateChanged", {"state": self.state})
            
            logger.info(
                "MCP Hub started successfully",
                server_count=len(self.connections),
                connected_count=len([c for c in self.connections.values() if c.status == ConnectionStatus.CONNECTED])
            )
            
        except Exception as e:
            self.state = HubState.ERROR
            await self.emit("hubStateChanged", {"state": self.state, "error": str(e)})
            logger.error("Failed to start MCP Hub", error=str(e))
            raise
    
    async def stop(self) -> None:
        """Stop the MCP Hub and all servers."""
        logger.info("Stopping MCP Hub")
        
        try:
            self.state = HubState.STOPPING
            await self.emit("hubStateChanged", {"state": self.state})
            
            # Stop all servers
            disconnect_tasks = []
            for connection in self.connections.values():
                disconnect_tasks.append(connection.disconnect())
            
            if disconnect_tasks:
                await asyncio.gather(*disconnect_tasks, return_exceptions=True)
            
            self.connections.clear()
            await self._clear_capabilities()
            
            self.state = HubState.STOPPED
            await self.emit("hubStateChanged", {"state": self.state})
            
            logger.info("MCP Hub stopped")
            
        except Exception as e:
            logger.error("Error stopping MCP Hub", error=str(e))
            raise
    
    async def restart(self) -> None:
        """Restart the MCP Hub."""
        logger.info("Restarting MCP Hub")
        
        self.state = HubState.RESTARTING
        await self.emit("hubStateChanged", {"state": self.state})
        
        await self.stop()
        await self.start()
    
    async def _handle_config_changed(self, data: Dict[str, Any]) -> None:
        """Handle configuration changes."""
        config: MCPServersConfig = data["config"]
        changes: ConfigChanges = data["changes"]
        
        logger.info(
            "Configuration changed",
            added=len(changes.added),
            removed=len(changes.removed),
            modified=len(changes.modified)
        )
        
        await self.emit("subscriptionEvent", {
            "type": SubscriptionType.CONFIG_CHANGED,
            "data": {
                "changes": changes.model_dump(),
                "timestamp": datetime.now().isoformat()
            }
        })
        
        # Handle removed servers
        for server_name in changes.removed:
            await self._remove_server(server_name)
        
        # Handle added servers
        for server_name in changes.added:
            server_config = config.mcpServers[server_name]
            await self._add_server(server_name, server_config)
        
        # Handle modified servers
        for server_name in changes.modified:
            server_config = config.mcpServers[server_name]
            await self._update_server(server_name, server_config)
        
        await self.emit("subscriptionEvent", {
            "type": SubscriptionType.SERVERS_UPDATED,
            "data": {
                "servers": await self.get_servers_info(),
                "timestamp": datetime.now().isoformat()
            }
        })
    
    async def _create_servers(self, servers_config: Dict[str, ServerConfig]) -> None:
        """Create server connections from configuration."""
        for name, config in servers_config.items():
            connection = MCPConnection(
                name=name,
                config=config,
                marketplace=self.marketplace,
                hub_server_url=self.hub_server_url
            )
            
            # Setup event handlers
            await self._setup_connection_handlers(connection)
            
            self.connections[name] = connection
            
            logger.debug("Created server connection", server=name, type=config.type)
    
    async def _setup_connection_handlers(self, connection: MCPConnection) -> None:
        """Setup event handlers for a server connection."""
        
        async def handle_tools_changed(data: Dict[str, Any]) -> None:
            await self._update_server_capabilities(connection.name)
            await self.emit("subscriptionEvent", {
                "type": SubscriptionType.TOOL_LIST_CHANGED,
                "data": {
                    "server": connection.name,
                    "tools": [tool.model_dump() for tool in connection.tools],
                    "timestamp": datetime.now().isoformat()
                }
            })
        
        async def handle_resources_changed(data: Dict[str, Any]) -> None:
            await self._update_server_capabilities(connection.name)
            await self.emit("subscriptionEvent", {
                "type": SubscriptionType.RESOURCE_LIST_CHANGED,
                "data": {
                    "server": connection.name,
                    "resources": [resource.model_dump() for resource in connection.resources],
                    "timestamp": datetime.now().isoformat()
                }
            })
        
        async def handle_prompts_changed(data: Dict[str, Any]) -> None:
            await self._update_server_capabilities(connection.name)
            await self.emit("subscriptionEvent", {
                "type": SubscriptionType.PROMPT_LIST_CHANGED,
                "data": {
                    "server": connection.name,
                    "prompts": [prompt.model_dump() for prompt in connection.prompts],
                    "timestamp": datetime.now().isoformat()
                }
            })
        
        # Register event handlers
        connection.on("toolsChanged", handle_tools_changed)
        connection.on("resourcesChanged", handle_resources_changed)
        connection.on("promptsChanged", handle_prompts_changed)
    
    async def _start_all_servers(self) -> None:
        """Start all server connections."""
        start_tasks = []
        for connection in self.connections.values():
            if not connection.disabled:
                start_tasks.append(self._start_server_safe(connection))
        
        if start_tasks:
            await asyncio.gather(*start_tasks, return_exceptions=True)
        
        # Update capabilities after all servers have started
        await self._rebuild_capabilities()
    
    async def _start_server_safe(self, connection: MCPConnection) -> None:
        """Start a server connection with error handling."""
        try:
            await connection.start()
            logger.info("Server started", server=connection.name, status=connection.status)
        except Exception as e:
            logger.error("Failed to start server", server=connection.name, error=str(e))
    
    async def _add_server(self, name: str, config: ServerConfig) -> None:
        """Add a new server."""
        if name in self.connections:
            logger.warning("Server already exists, updating instead", server=name)
            await self._update_server(name, config)
            return
        
        connection = MCPConnection(
            name=name,
            config=config,
            marketplace=self.marketplace,
            hub_server_url=self.hub_server_url
        )
        
        await self._setup_connection_handlers(connection)
        self.connections[name] = connection
        
        if not config.disabled:
            await self._start_server_safe(connection)
            await self._update_server_capabilities(name)
        
        logger.info("Server added", server=name, status=connection.status)
    
    async def _update_server(self, name: str, config: ServerConfig) -> None:
        """Update an existing server."""
        connection = self.connections.get(name)
        if not connection:
            await self._add_server(name, config)
            return
        
        # Disconnect old connection
        await connection.disconnect()
        
        # Update configuration and reconnect
        await connection.connect(config)
        await self._update_server_capabilities(name)
        
        logger.info("Server updated", server=name, status=connection.status)
    
    async def _remove_server(self, name: str) -> None:
        """Remove a server."""
        connection = self.connections.get(name)
        if not connection:
            return
        
        await connection.disconnect()
        del self.connections[name]
        
        # Remove capabilities
        await self._remove_server_capabilities(name)
        
        logger.info("Server removed", server=name)
    
    async def _rebuild_capabilities(self) -> None:
        """Rebuild all capabilities from connected servers."""
        await self._clear_capabilities()
        
        for connection in self.connections.values():
            if connection.status == ConnectionStatus.CONNECTED:
                await self._update_server_capabilities(connection.name)
    
    async def _update_server_capabilities(self, server_name: str) -> None:
        """Update capabilities for a specific server."""
        connection = self.connections.get(server_name)
        if not connection or connection.status != ConnectionStatus.CONNECTED:
            return
        
        # Remove old capabilities for this server
        await self._remove_server_capabilities(server_name)
        
        # Add new capabilities with namespacing
        for tool in connection.tools:
            namespaced_name = f"{server_name}::{tool.name}"
            self.tools[namespaced_name] = tool
            self.tool_to_server[namespaced_name] = server_name
            
            # Also add without namespace if no conflict
            if tool.name not in self.tool_to_server:
                self.tools[tool.name] = tool
                self.tool_to_server[tool.name] = server_name
        
        for resource in connection.resources:
            namespaced_name = f"{server_name}::{resource.name}"
            self.resources[namespaced_name] = resource
            self.resource_to_server[namespaced_name] = server_name
            
            if resource.name not in self.resource_to_server:
                self.resources[resource.name] = resource
                self.resource_to_server[resource.name] = server_name
        
        for prompt in connection.prompts:
            namespaced_name = f"{server_name}::{prompt.name}"
            self.prompts[namespaced_name] = prompt
            self.prompt_to_server[namespaced_name] = server_name
            
            if prompt.name not in self.prompt_to_server:
                self.prompts[prompt.name] = prompt
                self.prompt_to_server[prompt.name] = server_name
        
        logger.debug(
            "Updated server capabilities",
            server=server_name,
            tools=len(connection.tools),
            resources=len(connection.resources),
            prompts=len(connection.prompts)
        )
    
    async def _remove_server_capabilities(self, server_name: str) -> None:
        """Remove capabilities for a specific server."""
        # Remove tools
        tools_to_remove = [name for name, srv in self.tool_to_server.items() if srv == server_name]
        for tool_name in tools_to_remove:
            self.tools.pop(tool_name, None)
            self.tool_to_server.pop(tool_name, None)
        
        # Remove resources
        resources_to_remove = [name for name, srv in self.resource_to_server.items() if srv == server_name]
        for resource_name in resources_to_remove:
            self.resources.pop(resource_name, None)
            self.resource_to_server.pop(resource_name, None)
        
        # Remove prompts
        prompts_to_remove = [name for name, srv in self.prompt_to_server.items() if srv == server_name]
        for prompt_name in prompts_to_remove:
            self.prompts.pop(prompt_name, None)
            self.prompt_to_server.pop(prompt_name, None)
    
    async def _clear_capabilities(self) -> None:
        """Clear all capabilities."""
        self.tools.clear()
        self.resources.clear()
        self.prompts.clear()
        self.tool_to_server.clear()
        self.resource_to_server.clear()
        self.prompt_to_server.clear()
    
    # Public API methods
    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> CallToolResult:
        """Call a tool through the appropriate server."""
        server_name = self.tool_to_server.get(tool_name)
        if not server_name:
            raise ValueError(f"Tool '{tool_name}' not found")
        
        connection = self.connections.get(server_name)
        if not connection:
            raise ValueError(f"Server '{server_name}' not found")
        
        # Extract original tool name (remove namespace if present)
        original_tool_name = tool_name.split("::")[-1] if "::" in tool_name else tool_name
        
        return await connection.call_tool(original_tool_name, arguments)
    
    async def read_resource(self, uri: str) -> ReadResourceResult:
        """Read a resource through the appropriate server."""
        resource_name = uri.split("/")[-1]  # Simple extraction
        server_name = self.resource_to_server.get(resource_name)
        if not server_name:
            raise ValueError(f"Resource '{resource_name}' not found")
        
        connection = self.connections.get(server_name)
        if not connection:
            raise ValueError(f"Server '{server_name}' not found")
        
        return await connection.read_resource(uri)
    
    async def get_prompt(self, prompt_name: str, arguments: Optional[Dict[str, Any]] = None) -> GetPromptResult:
        """Get a prompt through the appropriate server."""
        server_name = self.prompt_to_server.get(prompt_name)
        if not server_name:
            raise ValueError(f"Prompt '{prompt_name}' not found")
        
        connection = self.connections.get(server_name)
        if not connection:
            raise ValueError(f"Server '{server_name}' not found")
        
        # Extract original prompt name
        original_prompt_name = prompt_name.split("::")[-1] if "::" in prompt_name else prompt_name
        
        return await connection.get_prompt(original_prompt_name, arguments)
    
    def list_tools(self) -> List[Tool]:
        """List all available tools."""
        return list(self.tools.values())
    
    def list_resources(self) -> List[Resource]:
        """List all available resources."""
        return list(self.resources.values())
    
    def list_prompts(self) -> List[Prompt]:
        """List all available prompts."""
        return list(self.prompts.values())
    
    async def get_servers_info(self) -> List[ServerInfo]:
        """Get information about all servers."""
        return [connection.get_server_info() for connection in self.connections.values()]
    
    def get_hub_stats(self) -> HubStats:
        """Get hub statistics."""
        servers = list(self.connections.values())
        connected_count = len([s for s in servers if s.status == ConnectionStatus.CONNECTED])
        disabled_count = len([s for s in servers if s.disabled])
        failed_count = len([s for s in servers if s.status == ConnectionStatus.ERROR])
        
        return HubStats(
            total_servers=len(servers),
            connected_servers=connected_count,
            disabled_servers=disabled_count,
            failed_servers=failed_count,
            total_tools=len(self.tools),
            total_resources=len(self.resources),
            total_prompts=len(self.prompts),
            uptime_seconds=int((datetime.now() - self.start_time).total_seconds()),
            active_clients=len(self.subscribers)
        ) 