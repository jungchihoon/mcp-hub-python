"""FastAPI-based HTTP server for MCP Hub Python."""

import asyncio
import os
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Dict, List, Optional
from pathlib import Path

import structlog
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse, HTMLResponse
from pydantic import BaseModel

from .config import ConfigManager
from .hub import MCPHub
from .marketplace import Marketplace
from .types import HubState, ServerInfo, HubStats
from .sse_manager import SSEManager


logger = structlog.get_logger(__name__)


# Request/Response models
class ToolCallRequest(BaseModel):
    name: str
    arguments: Dict[str, Any]


class ResourceReadRequest(BaseModel):
    uri: str


class PromptGetRequest(BaseModel):
    name: str
    arguments: Optional[Dict[str, Any]] = None


class ServerControlRequest(BaseModel):
    action: str  # "start", "stop", "restart"


# Global state
hub: Optional[MCPHub] = None
sse_manager: Optional[SSEManager] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan context manager."""
    global hub, sse_manager
    
    logger.info("Starting MCP Hub server")
    
    try:
        # Initialize SSE manager
        sse_manager = SSEManager()
        
        # Get config path from environment
        config_path = os.getenv("MCP_HUB_CONFIG", "./mcp-servers.json")
        config_manager = ConfigManager(config_path)
        
        # Initialize marketplace
        marketplace = Marketplace()
        await marketplace.initialize()
        
        # Initialize hub
        hub = MCPHub(config_manager, marketplace)
        await hub.start()
        
        # Setup hub event handlers
        async def handle_hub_state_changed(data: Dict[str, Any]) -> None:
            await sse_manager.broadcast({
                "type": "hub_state",
                "data": data
            })
        
        async def handle_subscription_event(data: Dict[str, Any]) -> None:
            await sse_manager.broadcast({
                "type": "subscription_event",
                "data": data
            })
        
        # Register event handlers
        hub.on("hubStateChanged", handle_hub_state_changed)
        hub.on("subscriptionEvent", handle_subscription_event)
        
        logger.info("MCP Hub server started successfully")
        
        yield
        
    except Exception as e:
        logger.error("Failed to start MCP Hub server", error=str(e))
        raise
    finally:
        # Cleanup
        if hub:
            await hub.stop()
        if sse_manager:
            await sse_manager.cleanup()
        
        logger.info("MCP Hub server stopped")


# Create FastAPI app
app = FastAPI(
    title="MCP Hub Python",
    description="Central coordinator for MCP servers",
    version="1.0.0",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure as needed
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Home page
@app.get("/")
async def home():
    """Serve the web UI."""
    templates_dir = Path(__file__).parent / "templates"
    html_file = templates_dir / "index.html"
    
    try:
        with open(html_file, 'r', encoding='utf-8') as f:
            html_content = f.read()
        return HTMLResponse(content=html_content)
    except FileNotFoundError:
        return HTMLResponse(
            content="<h1>MCP Hub</h1><p>웹 UI 파일을 찾을 수 없습니다.</p>",
            status_code=404
        )


# Health check
@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "hub_state": hub.state if hub else "not_initialized"
    }


# Hub status
@app.get("/api/status")
async def get_hub_status():
    """Get hub status and statistics."""
    if not hub:
        raise HTTPException(status_code=503, detail="Hub not initialized")
    
    stats = hub.get_hub_stats()
    servers_info = await hub.get_servers_info()
    
    return {
        "state": hub.state,
        "stats": stats.model_dump(),
        "servers": [info.model_dump() for info in servers_info]
    }


# Hub statistics (for web UI)
@app.get("/api/stats")
async def get_hub_stats():
    """Get hub statistics."""
    if not hub:
        raise HTTPException(status_code=503, detail="Hub not initialized")
    
    stats = hub.get_hub_stats()
    return stats.model_dump()


# Server management
@app.get("/api/servers")
async def list_servers() -> List[ServerInfo]:
    """List all servers."""
    if not hub:
        raise HTTPException(status_code=503, detail="Hub not initialized")
    
    servers_info = await hub.get_servers_info()
    return [info.model_dump() for info in servers_info]


@app.post("/api/servers/{server_name}/control")
async def control_server(server_name: str, request: ServerControlRequest):
    """Control a server (start/stop/restart)."""
    if not hub:
        raise HTTPException(status_code=503, detail="Hub not initialized")
    
    connection = hub.connections.get(server_name)
    if not connection:
        raise HTTPException(status_code=404, detail="Server not found")
    
    try:
        if request.action == "start":
            result = await connection.start()
        elif request.action == "stop":
            result = await connection.stop()
        elif request.action == "restart":
            await connection.stop()
            result = await connection.start()
        else:
            raise HTTPException(status_code=400, detail="Invalid action")
        
        return result.model_dump()
        
    except Exception as e:
        logger.error("Server control failed", server=server_name, action=request.action, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/servers/{server_name}/reconnect")
async def reconnect_server(server_name: str):
    """Reconnect a server."""
    if not hub:
        raise HTTPException(status_code=503, detail="Hub not initialized")
    
    connection = hub.connections.get(server_name)
    if not connection:
        raise HTTPException(status_code=404, detail="Server not found")
    
    try:
        # Stop and restart the connection
        await connection.stop()
        await connection.start()
        
        return {
            "status": "success",
            "message": f"Server {server_name} reconnected successfully",
            "server_status": connection.status.value
        }
        
    except Exception as e:
        logger.error("Server reconnection failed", server=server_name, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


# MCP capabilities
@app.get("/api/tools")
async def list_tools():
    """List all available tools."""
    if not hub:
        raise HTTPException(status_code=503, detail="Hub not initialized")
    
    tools = hub.list_tools()
    return [tool.model_dump() for tool in tools]


@app.get("/api/resources")
async def list_resources():
    """List all available resources."""
    if not hub:
        raise HTTPException(status_code=503, detail="Hub not initialized")
    
    resources = hub.list_resources()
    return [resource.model_dump() for resource in resources]


@app.get("/api/prompts")
async def list_prompts():
    """List all available prompts."""
    if not hub:
        raise HTTPException(status_code=503, detail="Hub not initialized")
    
    prompts = hub.list_prompts()
    return [prompt.model_dump() for prompt in prompts]


# MCP operations
@app.post("/api/tools/call")
async def call_tool(request: ToolCallRequest):
    """Call a tool."""
    if not hub:
        raise HTTPException(status_code=503, detail="Hub not initialized")
    
    try:
        result = await hub.call_tool(request.name, request.arguments)
        return result.model_dump()
    except Exception as e:
        logger.error("Tool call failed", tool=request.name, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/resources/read")
async def read_resource(request: ResourceReadRequest):
    """Read a resource."""
    if not hub:
        raise HTTPException(status_code=503, detail="Hub not initialized")
    
    try:
        result = await hub.read_resource(request.uri)
        return result.model_dump()
    except Exception as e:
        logger.error("Resource read failed", uri=request.uri, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/prompts/get")
async def get_prompt(request: PromptGetRequest):
    """Get a prompt."""
    if not hub:
        raise HTTPException(status_code=503, detail="Hub not initialized")
    
    try:
        result = await hub.get_prompt(request.name, request.arguments)
        return result.model_dump()
    except Exception as e:
        logger.error("Prompt get failed", prompt=request.name, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


# Marketplace
@app.get("/api/marketplace/catalog")
async def get_marketplace_catalog():
    """Get marketplace catalog."""
    if not hub or not hub.marketplace:
        raise HTTPException(status_code=503, detail="Marketplace not available")
    
    catalog = hub.marketplace.get_catalog()
    if not catalog:
        raise HTTPException(status_code=503, detail="Marketplace catalog not loaded")
    
    return catalog.model_dump()


@app.get("/api/marketplace/search")
async def search_marketplace(
    q: Optional[str] = None,
    category: Optional[str] = None,
    tags: Optional[str] = None,
    requires_api_key: Optional[bool] = None
):
    """Search marketplace."""
    if not hub or not hub.marketplace:
        raise HTTPException(status_code=503, detail="Marketplace not available")
    
    tag_list = tags.split(",") if tags else None
    
    items = hub.marketplace.search(
        query=q,
        category=category,
        tags=tag_list,
        requires_api_key=requires_api_key
    )
    
    return [item.model_dump() for item in items]


# Server-Sent Events
@app.get("/api/events")
async def events_stream(request: Request):
    """Server-Sent Events stream."""
    if not sse_manager:
        raise HTTPException(status_code=503, detail="SSE not available")
    
    async def event_generator():
        client_id = await sse_manager.add_client()
        
        try:
            while True:
                # Check if client disconnected
                if await request.is_disconnected():
                    break
                
                # Get events for this client
                events = await sse_manager.get_events(client_id)
                
                for event in events:
                    yield f"data: {event}\n\n"
                
                # Small delay to prevent busy waiting
                await asyncio.sleep(0.1)
                
        finally:
            await sse_manager.remove_client(client_id)
    
    return StreamingResponse(
        event_generator(),
        media_type="text/plain",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"  # Disable nginx buffering
        }
    )


# MCP Server endpoint (unified interface)
@app.post("/mcp")
async def mcp_endpoint(request: Request):
    """Unified MCP server endpoint."""
    if not hub:
        raise HTTPException(status_code=503, detail="Hub not initialized")
    
    try:
        # Parse MCP request
        data = await request.json()
        
        # Route request based on method
        method = data.get("method")
        params = data.get("params", {})
        
        if method == "tools/list":
            tools = hub.list_tools()
            result = {"tools": [tool.model_dump() for tool in tools]}
            
        elif method == "tools/call":
            tool_name = params.get("name")
            arguments = params.get("arguments", {})
            result = await hub.call_tool(tool_name, arguments)
            result = result.model_dump()
            
        elif method == "resources/list":
            resources = hub.list_resources()
            result = {"resources": [resource.model_dump() for resource in resources]}
            
        elif method == "resources/read":
            uri = params.get("uri")
            result = await hub.read_resource(uri)
            result = result.model_dump()
            
        elif method == "prompts/list":
            prompts = hub.list_prompts()
            result = {"prompts": [prompt.model_dump() for prompt in prompts]}
            
        elif method == "prompts/get":
            name = params.get("name")
            arguments = params.get("arguments", {})
            result = await hub.get_prompt(name, arguments)
            result = result.model_dump()
            
        else:
            raise HTTPException(status_code=400, detail=f"Unknown method: {method}")
        
        return {
            "jsonrpc": "2.0",
            "id": data.get("id"),
            "result": result
        }
        
    except Exception as e:
        logger.error("MCP endpoint error", error=str(e))
        return {
            "jsonrpc": "2.0",
            "id": data.get("id") if "data" in locals() else None,
            "error": {
                "code": -32603,
                "message": str(e)
            }
        }


# Exception handlers
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler."""
    logger.error("Unhandled exception", path=request.url.path, error=str(exc))
    
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "message": str(exc)
        }
    ) 