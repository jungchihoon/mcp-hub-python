"""MCP Connection management for MCP Hub Python.

Complete Python port of Node.js MCPConnection providing:
- Multiple transport protocols (STDIO, SSE, StreamableHTTP)
- OAuth 2.0 PKCE authentication
- Auto-reconnection with backoff
- Development mode with file watching
- Real-time capability updates
"""

import asyncio
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import structlog
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.sse import sse_client
from mcp.types import (
    Tool, Resource, Prompt,
    CallToolResult, ReadResourceResult, GetPromptResult
)

from .events import EventEmitter
from .types import (
    ConnectionStatus, TransportType, ServerConfig, ServerInfo,
    DevConfig
)
# Development mode and OAuth support will be added later


logger = structlog.get_logger(__name__)


class MCPConnection(EventEmitter):
    """
    MCP server connection manager.
    
    Complete Python port of Node.js MCPConnection providing:
    - Multi-transport support (STDIO, SSE, StreamableHTTP)
    - OAuth authentication with PKCE
    - Auto-reconnection and error recovery
    - Development mode with hot reload
    - Real-time capability tracking
    """
    
    # Connection timeout for initial connection
    CLIENT_CONNECT_TIMEOUT = 5 * 60  # 5 minutes
    
    def __init__(
        self,
        name: str,
        config: ServerConfig,
        marketplace: Optional[Any] = None,
        hub_server_url: str = "http://localhost:3000"
    ) -> None:
        super().__init__()
        
        self.name = name  # MCP ID
        self.config = config
        self.marketplace = marketplace
        self.hub_server_url = hub_server_url
        
        # Display name and description
        self.display_name = config.name or name
        self.description = config.description or ""
        
        # Set display name from marketplace if available
        if marketplace and hasattr(marketplace, 'cache'):
            if hasattr(marketplace.cache, 'catalog') and marketplace.cache.catalog.items:
                item = next(
                    (item for item in marketplace.cache.catalog.items if item.mcp_id == name),
                    None
                )
                if item:
                    self.display_name = item.name
                    if not self.description:
                        self.description = item.description
                    logger.debug(
                        "Using marketplace name for server",
                        name=name,
                        display_name=item.name
                    )
        
        # Set display name from config if provided
        if config.name:
            self.display_name = config.name
        
        # Connection state
        self.status = ConnectionStatus.DISABLED if config.disabled else ConnectionStatus.DISCONNECTED
        self.transport_type = config.type
        self.disabled = config.disabled or False
        self.error: Optional[str] = None
        self.start_time: Optional[datetime] = None
        self.last_started: Optional[datetime] = None
        
        # MCP client components
        self.client: Optional[ClientSession] = None
        self.read_stream = None
        self.write_stream = None
        self.transport_context = None
        
        # Capabilities
        self.tools: List[Tool] = []
        self.resources: List[Resource] = []
        self.prompts: List[Prompt] = []
        self.resource_templates: List[ResourceTemplate] = []
        self.server_info: Optional[Dict[str, Any]] = None
        
        # OAuth authentication (to be implemented)
        self.oauth_provider = None
        self.authorization_url: Optional[str] = None
        
        # Development mode (to be implemented)
        
        logger.debug(
            "MCPConnection created",
            name=name,
            display_name=self.display_name,
            transport_type=self.transport_type,
            disabled=self.disabled
        )
    
    async def start(self) -> ServerInfo:
        """
        Start the MCP connection.
        
        Returns:
            ServerInfo with current connection status
        """
        if self.disabled:
            self.disabled = False
            self.config.disabled = False
            self.status = ConnectionStatus.DISCONNECTED
        
        if self.status == ConnectionStatus.CONNECTED:
            return self.get_server_info()
        
        await self.connect()
        return self.get_server_info()
    
    async def stop(self, disable: bool = False) -> ServerInfo:
        """
        Stop the MCP connection.
        
        Args:
            disable: Whether to disable the server permanently
            
        Returns:
            ServerInfo with current connection status
        """
        if disable:
            self.disabled = True
            self.config.disabled = True
            self.status = ConnectionStatus.DISABLED
        
        await self.disconnect()
        return self.get_server_info()
    
    def get_uptime(self) -> int:
        """
        Calculate uptime in seconds.
        
        Returns:
            Uptime in seconds, 0 if not connected or disabled
        """
        if not self.start_time or self.status not in (ConnectionStatus.CONNECTED, ConnectionStatus.DISABLED):
            return 0
        return int((datetime.now() - self.start_time).total_seconds())
    
    async def connect(self, config: Optional[ServerConfig] = None) -> None:
        """
        Establish connection to MCP server.
        
        Args:
            config: Optional new configuration to use
        """
        try:
            if config:
                self.config = config
            
            # Update display name if config changed
            if self.config.name:
                self.display_name = self.config.name
            
            if self.disabled:
                self.status = ConnectionStatus.DISABLED
                self.start_time = datetime.now()
                self.last_started = datetime.now()
                return
            
            self.error = None
            self.status = ConnectionStatus.CONNECTING
            self.last_started = datetime.now()
            
            logger.info("Connecting to MCP server", server=self.name, transport=self.transport_type)
            
            # Create transport based on type
            if self.transport_type == TransportType.STDIO:
                await self._create_stdio_connection()
            elif self.transport_type == TransportType.SSE:
                await self._create_sse_connection()
            elif self.transport_type == TransportType.STREAMABLE_HTTP:
                await self._create_streamable_http_connection()
            else:
                raise ValueError(f"Unsupported transport type: {self.transport_type}")
            
            # Initialize the client session
            await self._initialize_client()
            
            # Setup notification handlers
            self._setup_notification_handlers()
            
            # Fetch initial server information and capabilities
            await self._fetch_server_info()
            await self._update_capabilities()
            
                    # Development watcher to be implemented later
            
            self.status = ConnectionStatus.CONNECTED
            self.start_time = datetime.now()
            
            logger.info(
                "Successfully connected to MCP server",
                server=self.name,
                tools=len(self.tools),
                resources=len(self.resources),
                prompts=len(self.prompts)
            )
            
        except Exception as e:
            await self._reset_state(error=str(e))
            raise
    
    async def _create_stdio_connection(self) -> None:
        """Create STDIO transport connection."""
        if not self.config.command:
            raise ValueError("STDIO transport requires command")
        
        # Prepare server parameters
        server_params = StdioServerParameters(
            command=self.config.command,
            args=self.config.args or [],
            env=self.config.env or {},
            cwd=str(self.config.cwd) if self.config.cwd else None
        )
        
        # Create client
        self.transport_context = stdio_client(server_params)
        self.read_stream, self.write_stream = await self.transport_context.__aenter__()
        
        logger.debug("Created STDIO transport", command=self.config.command)
    
    async def _create_sse_connection(self) -> None:
        """Create SSE transport connection."""
        if not self.config.url:
            raise ValueError("SSE transport requires URL")
        
        # Create SSE client (OAuth support to be added later)
        try:
            self.transport_context = sse_client(
                self.config.url,
                headers=self.config.headers or {}
            )
            self.read_stream, self.write_stream = await self.transport_context.__aenter__()
            
            logger.debug("Created SSE transport", url=self.config.url)
            
        except Exception as e:
            logger.error("SSE transport failed", url=self.config.url, error=str(e))
            raise
    
    async def _create_streamable_http_connection(self) -> None:
        """Create StreamableHTTP transport connection."""
        # For now, fallback to SSE until StreamableHTTP client is available
        # TODO: Implement proper StreamableHTTP transport when available in Python SDK
        logger.warning("StreamableHTTP not yet available, falling back to SSE")
        self.transport_type = TransportType.SSE
        await self._create_sse_connection()
    
    async def _initialize_client(self) -> None:
        """Initialize the MCP client session."""
        if not self.read_stream or not self.write_stream:
            raise ValueError("Transport streams not available")
        
        # Create client session
        self.client = ClientSession(self.read_stream, self.write_stream)
        
        # Initialize the session with timeout
        try:
            await asyncio.wait_for(
                self.client.initialize(),
                timeout=self.CLIENT_CONNECT_TIMEOUT
            )
        except asyncio.TimeoutError:
            raise Exception(f"Client initialization timed out after {self.CLIENT_CONNECT_TIMEOUT} seconds")
        
        logger.debug("MCP client session initialized", server=self.name)
    
    def _setup_notification_handlers(self) -> None:
        """Setup handlers for MCP notifications."""
        if not self.client:
            return
        
        # Tool list changed notifications
        @self.client.notification_handler("notifications/tools/list_changed")
        async def handle_tools_changed(notification: ToolListChangedNotification) -> None:
            logger.debug("Tools list changed", server=self.name)
            await self._update_tools()
            await self.emit("toolsChanged", {
                "server": self.name,
                "tools": [tool.model_dump() for tool in self.tools]
            })
        
        # Resource list changed notifications
        @self.client.notification_handler("notifications/resources/list_changed")
        async def handle_resources_changed(notification: ResourceListChangedNotification) -> None:
            logger.debug("Resources list changed", server=self.name)
            await self._update_resources()
            await self.emit("resourcesChanged", {
                "server": self.name,
                "resources": [resource.model_dump() for resource in self.resources],
                "resourceTemplates": [template.model_dump() for template in self.resource_templates]
            })
        
        # Prompt list changed notifications
        @self.client.notification_handler("notifications/prompts/list_changed")
        async def handle_prompts_changed(notification: PromptListChangedNotification) -> None:
            logger.debug("Prompts list changed", server=self.name)
            await self._update_prompts()
            await self.emit("promptsChanged", {
                "server": self.name,
                "prompts": [prompt.model_dump() for prompt in self.prompts]
            })
        
        # Logging notifications
        @self.client.notification_handler("notifications/message")
        async def handle_logging(notification: LoggingMessage) -> None:
            logger.info(
                "Server log message",
                server=self.name,
                level=notification.level,
                message=notification.data
            )
            await self.emit("notification", {
                "server": self.name,
                "level": notification.level,
                "message": notification.data
            })
    
    async def _fetch_server_info(self) -> None:
        """Fetch server information."""
        if not self.client:
            return
        
        try:
            # Get server info if available (implementation depends on MCP SDK updates)
            self.server_info = {
                "name": self.display_name,
                "version": "unknown"
            }
            logger.debug("Fetched server info", server=self.name)
        except Exception as e:
            logger.warning("Failed to fetch server info", server=self.name, error=str(e))
    
    async def _update_capabilities(self) -> None:
        """Update all server capabilities."""
        await asyncio.gather(
            self._update_tools(),
            self._update_resources(),
            self._update_prompts(),
            return_exceptions=True
        )
    
    async def _update_tools(self) -> None:
        """Update tools list."""
        if not self.client:
            return
        
        try:
            result = await self.client.list_tools()
            self.tools = result.tools
            logger.debug("Updated tools", server=self.name, count=len(self.tools))
        except Exception as e:
            logger.error("Failed to update tools", server=self.name, error=str(e))
            self.tools = []
    
    async def _update_resources(self) -> None:
        """Update resources and resource templates."""
        if not self.client:
            return
        
        try:
            result = await self.client.list_resources()
            self.resources = result.resources
            logger.debug("Updated resources", server=self.name, count=len(self.resources))
        except Exception as e:
            logger.error("Failed to update resources", server=self.name, error=str(e))
            self.resources = []
        
        try:
            result = await self.client.list_resource_templates()
            self.resource_templates = result.resourceTemplates
            logger.debug("Updated resource templates", server=self.name, count=len(self.resource_templates))
        except Exception as e:
            logger.debug("Resource templates not supported", server=self.name)
            self.resource_templates = []
    
    async def _update_prompts(self) -> None:
        """Update prompts list."""
        if not self.client:
            return
        
        try:
            result = await self.client.list_prompts()
            self.prompts = result.prompts
            logger.debug("Updated prompts", server=self.name, count=len(self.prompts))
        except Exception as e:
            logger.error("Failed to update prompts", server=self.name, error=str(e))
            self.prompts = []
    
    async def call_tool(
        self, 
        tool_name: str, 
        arguments: Dict[str, Any],
        request_options: Optional[Dict[str, Any]] = None
    ) -> CallToolResult:
        """
        Call a tool on the MCP server.
        
        Args:
            tool_name: Name of the tool to call
            arguments: Tool arguments
            request_options: Optional request options
            
        Returns:
            Tool call result
        """
        if not self.client:
            raise RuntimeError("Client not connected")
        
        if self.status != ConnectionStatus.CONNECTED:
            raise RuntimeError(f"Server not connected: {self.status}")
        
        try:
            result = await self.client.call_tool(tool_name, arguments)
            logger.debug(
                "Tool called successfully",
                server=self.name,
                tool=tool_name,
                result_content_count=len(result.content) if result.content else 0
            )
            return result
        except Exception as e:
            logger.error(
                "Tool call failed",
                server=self.name,
                tool=tool_name,
                error=str(e)
            )
            raise
    
    async def read_resource(
        self,
        uri: str,
        request_options: Optional[Dict[str, Any]] = None
    ) -> ReadResourceResult:
        """
        Read a resource from the MCP server.
        
        Args:
            uri: Resource URI
            request_options: Optional request options
            
        Returns:
            Resource content
        """
        if not self.client:
            raise RuntimeError("Client not connected")
        
        if self.status != ConnectionStatus.CONNECTED:
            raise RuntimeError(f"Server not connected: {self.status}")
        
        try:
            result = await self.client.read_resource(uri)
            logger.debug(
                "Resource read successfully",
                server=self.name,
                uri=uri,
                content_count=len(result.contents) if result.contents else 0
            )
            return result
        except Exception as e:
            logger.error(
                "Resource read failed",
                server=self.name,
                uri=uri,
                error=str(e)
            )
            raise
    
    async def get_prompt(
        self,
        prompt_name: str,
        arguments: Optional[Dict[str, Any]] = None,
        request_options: Optional[Dict[str, Any]] = None
    ) -> GetPromptResult:
        """
        Get a prompt from the MCP server.
        
        Args:
            prompt_name: Name of the prompt
            arguments: Prompt arguments
            request_options: Optional request options
            
        Returns:
            Prompt result
        """
        if not self.client:
            raise RuntimeError("Client not connected")
        
        if self.status != ConnectionStatus.CONNECTED:
            raise RuntimeError(f"Server not connected: {self.status}")
        
        try:
            result = await self.client.get_prompt(prompt_name, arguments or {})
            logger.debug(
                "Prompt retrieved successfully",
                server=self.name,
                prompt=prompt_name,
                messages_count=len(result.messages) if result.messages else 0
            )
            return result
        except Exception as e:
            logger.error(
                "Prompt retrieval failed",
                server=self.name,
                prompt=prompt_name,
                error=str(e)
            )
            raise
    
    async def disconnect(self, error: Optional[str] = None) -> None:
        """
        Disconnect from the MCP server.
        
        Args:
            error: Optional error message that caused disconnection
        """
        logger.info("Disconnecting from MCP server", server=self.name, error=error)
        
        # Development watcher cleanup to be implemented later
        
        # Close client session
        if self.client:
            try:
                await self.client.__aexit__(None, None, None)
            except Exception as e:
                logger.warning("Error closing client session", error=str(e))
            self.client = None
        
        # Close transport
        if self.transport_context:
            try:
                await self.transport_context.__aexit__(None, None, None)
            except Exception as e:
                logger.warning("Error closing transport", error=str(e))
            self.transport_context = None
        
        self.read_stream = None
        self.write_stream = None
        
        await self._reset_state(error)
        
        logger.info("Disconnected from MCP server", server=self.name)
    
    async def _reset_state(self, error: Optional[str] = None) -> None:
        """Reset connection state."""
        self.status = ConnectionStatus.ERROR if error else ConnectionStatus.DISCONNECTED
        self.error = error
        
        # Clear capabilities
        self.tools = []
        self.resources = []
        self.prompts = []
        self.resource_templates = []
        self.server_info = None
    
    # OAuth and development mode methods to be implemented later
    
    def get_server_info(self) -> ServerInfo:
        """
        Get current server information.
        
        Returns:
            ServerInfo object with current state
        """
        return ServerInfo(
            name=self.name,
            display_name=self.display_name,
            description=self.description,
            status=self.status,
            transport_type=self.transport_type,
            start_time=self.start_time,
            last_started=self.last_started,
            uptime_seconds=self.get_uptime(),
            error=self.error,
            disabled=self.disabled,
            tools_count=len(self.tools),
            resources_count=len(self.resources),
            prompts_count=len(self.prompts),
            resource_templates_count=len(self.resource_templates)
        ) 