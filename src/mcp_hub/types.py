"""Type definitions for MCP Hub Python."""

from __future__ import annotations

import asyncio
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field


class ConnectionStatus(str, Enum):
    """MCP connection status."""
    CONNECTED = "connected"
    CONNECTING = "connecting"
    DISCONNECTED = "disconnected"
    UNAUTHORIZED = "unauthorized"
    DISABLED = "disabled"
    ERROR = "error"


class TransportType(str, Enum):
    """MCP transport types."""
    STDIO = "stdio"
    SSE = "sse"
    STREAMABLE_HTTP = "streamable-http"


class HubState(str, Enum):
    """Hub lifecycle states."""
    STARTING = "starting"
    READY = "ready"
    RESTARTING = "restarting"
    ERROR = "error"
    STOPPING = "stopping"
    STOPPED = "stopped"


class EventType(str, Enum):
    """Server-Sent Event types."""
    HUB_STATE = "hub_state"
    SUBSCRIPTION_EVENT = "subscription_event"
    SERVER_STATUS = "server_status"
    TOOLS_CHANGED = "tools_changed"
    RESOURCES_CHANGED = "resources_changed"
    PROMPTS_CHANGED = "prompts_changed"


class SubscriptionType(str, Enum):
    """Subscription event types."""
    CONFIG_CHANGED = "config_changed"
    SERVERS_UPDATING = "servers_updating"
    SERVERS_UPDATED = "servers_updated"
    TOOL_LIST_CHANGED = "tool_list_changed"
    RESOURCE_LIST_CHANGED = "resource_list_changed"
    PROMPT_LIST_CHANGED = "prompt_list_changed"


# Configuration Models
class DevConfig(BaseModel):
    """Development mode configuration."""
    enabled: bool = False
    watch: List[str] = Field(default_factory=list)
    cwd: Optional[Path] = None
    restart_delay: float = 1.0


class ServerConfig(BaseModel):
    """MCP server configuration."""
    name: Optional[str] = None
    description: Optional[str] = None
    disabled: bool = False
    
    # STDIO configuration
    command: Optional[str] = None
    args: List[str] = Field(default_factory=list)
    env: Dict[str, str] = Field(default_factory=dict)
    cwd: Optional[Path] = None
    
    # Remote configuration  
    url: Optional[str] = None
    headers: Dict[str, str] = Field(default_factory=dict)
    
    # Development mode
    dev: Optional[DevConfig] = None
    
    # Transport type (auto-detected)
    type: Optional[TransportType] = None

    def __post_init__(self) -> None:
        """Auto-detect transport type."""
        if self.command is not None:
            self.type = TransportType.STDIO
        elif self.url is not None:
            self.type = TransportType.SSE
        else:
            raise ValueError("Server must specify either 'command' (STDIO) or 'url' (SSE)")


class MCPServersConfig(BaseModel):
    """Root configuration for MCP servers."""
    mcpServers: Dict[str, ServerConfig] = Field(default_factory=dict)


# Runtime Models
class ServerInfo(BaseModel):
    """Server runtime information."""
    name: str
    display_name: str
    description: str
    status: ConnectionStatus
    transport_type: Optional[TransportType] = None
    start_time: Optional[datetime] = None
    last_started: Optional[datetime] = None
    uptime_seconds: int = 0
    error: Optional[str] = None
    disabled: bool = False
    
    # Server capabilities
    tools_count: int = 0
    resources_count: int = 0
    prompts_count: int = 0
    resource_templates_count: int = 0


class ConfigChanges(BaseModel):
    """Configuration change details."""
    added: List[str] = Field(default_factory=list)
    removed: List[str] = Field(default_factory=list)  
    modified: List[str] = Field(default_factory=list)
    unchanged: List[str] = Field(default_factory=list)


class HubStats(BaseModel):
    """Hub statistics."""
    total_servers: int
    connected_servers: int
    disabled_servers: int
    failed_servers: int
    total_tools: int
    total_resources: int
    total_prompts: int
    uptime_seconds: int
    active_clients: int


# SSE Event Models
class SSEEvent(BaseModel):
    """Server-Sent Event."""
    type: EventType
    data: Dict[str, Any]
    timestamp: datetime = Field(default_factory=datetime.now)


class HubStateEvent(BaseModel):
    """Hub state change event."""
    state: HubState
    server_id: str
    pid: int
    port: int
    timestamp: datetime
    message: Optional[str] = None
    error: Optional[str] = None


# Marketplace Models  
class MarketplaceItem(BaseModel):
    """Marketplace server item."""
    mcp_id: str = Field(alias="mcpId")
    github_url: str = Field(alias="githubUrl")
    name: str
    author: str
    description: str
    codicon_icon: str = Field(alias="codiconIcon")
    logo_url: str = Field(alias="logoUrl")
    category: str
    tags: List[str]
    requires_api_key: bool = Field(alias="requiresApiKey")
    is_recommended: bool = Field(alias="isRecommended")
    github_stars: int = Field(alias="githubStars")
    download_count: int = Field(alias="downloadCount")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")


class MarketplaceCatalog(BaseModel):
    """Marketplace catalog."""
    items: List[MarketplaceItem]
    last_updated: Optional[datetime] = None
    total_count: int = 0


# OAuth Models
class OAuthConfig(BaseModel):
    """OAuth configuration."""
    client_id: str
    client_secret: str
    authorization_url: str
    token_url: str
    scopes: List[str] = Field(default_factory=list)
    redirect_uri: str = "http://localhost:3000/auth/callback"


# Utility Types
LogLevel = Union[str, int]
JSONValue = Union[str, int, float, bool, None, Dict[str, Any], List[Any]]
ConfigDict = Dict[str, Any] 