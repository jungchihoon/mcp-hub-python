"""Command-line interface for MCP Hub Python."""

import asyncio
import os
import signal
import sys
from pathlib import Path
from typing import Optional

import click
import structlog
import uvicorn
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from .config import ConfigManager
from .hub import MCPHub  
from .marketplace import Marketplace
from .server import app


# Setup logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer()
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger(__name__)
console = Console()


@click.command()
@click.option(
    "--port", "-p",
    type=int,
    required=True,
    help="Port to run the HTTP server on"
)
@click.option(
    "--config", "-c",
    type=click.Path(exists=True, path_type=Path),
    required=True,
    help="Path to MCP servers configuration file"
)
@click.option(
    "--host",
    default="localhost",
    help="Host to bind the server to"
)
@click.option(
    "--watch", "-w",
    is_flag=True,
    help="Watch configuration file for changes"
)
@click.option(
    "--auto-shutdown",
    is_flag=True,
    help="Automatically shutdown when no clients are connected"
)
@click.option(
    "--shutdown-delay",
    type=int,
    default=10,
    help="Delay in seconds before auto-shutdown"
)
@click.option(
    "--marketplace-url",
    help="Custom marketplace registry URL"
)
@click.option(
    "--cache-dir",
    type=click.Path(path_type=Path),
    help="Directory for caching marketplace data"
)
@click.option(
    "--log-level",
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"]),
    default="INFO",
    help="Log level"
)
@click.option(
    "--reload",
    is_flag=True,
    help="Enable auto-reload for development"
)
def main(
    port: int,
    config: Path,
    host: str = "localhost",
    watch: bool = False,
    auto_shutdown: bool = False,
    shutdown_delay: int = 10,
    marketplace_url: Optional[str] = None,
    cache_dir: Optional[Path] = None,
    log_level: str = "INFO",
    reload: bool = False
) -> None:
    """
    MCP Hub Python - Central coordinator for MCP servers.
    
    Start a hub server that manages multiple MCP servers and provides
    a unified interface for MCP clients.
    """
    
    # Set environment variables for the server
    os.environ["MCP_HUB_CONFIG"] = str(config.absolute())
    os.environ["MCP_HUB_WATCH"] = str(watch).lower()
    os.environ["MCP_HUB_AUTO_SHUTDOWN"] = str(auto_shutdown).lower()
    os.environ["MCP_HUB_SHUTDOWN_DELAY"] = str(shutdown_delay)
    
    if marketplace_url:
        os.environ["MCP_HUB_MARKETPLACE_URL"] = marketplace_url
    
    if cache_dir:
        os.environ["MCP_HUB_CACHE_DIR"] = str(cache_dir.absolute())
    
    # Display startup banner
    display_banner(port, config, host)
    
    # Validate configuration file
    try:
        config_manager = ConfigManager(config)
        asyncio.run(config_manager.load_config())
        console.print("✅ Configuration file validated successfully", style="green")
    except Exception as e:
        console.print(f"❌ Configuration validation failed: {e}", style="red")
        sys.exit(1)
    
    # Setup signal handlers for graceful shutdown
    setup_signal_handlers()
    
    # Start the server
    try:
        console.print(f"🚀 Starting MCP Hub on {host}:{port}", style="blue")
        
        uvicorn.run(
            "mcp_hub.server:app",
            host=host,
            port=port,
            log_level=log_level.lower(),
            reload=reload,
            access_log=True
        )
        
    except KeyboardInterrupt:
        console.print("\n👋 Gracefully shutting down...", style="yellow")
    except Exception as e:
        console.print(f"❌ Server error: {e}", style="red")
        sys.exit(1)


def display_banner(port: int, config_path: Path, host: str) -> None:
    """Display startup banner."""
    
    banner_text = Text()
    banner_text.append("🐍 MCP Hub Python\n", style="bold blue")
    banner_text.append("Central coordinator for MCP servers\n\n", style="dim")
    
    banner_text.append(f"📊 Management UI: ", style="bold")
    banner_text.append(f"http://{host}:{port}\n", style="cyan")
    
    banner_text.append(f"🔗 MCP Endpoint: ", style="bold") 
    banner_text.append(f"http://{host}:{port}/mcp\n", style="cyan")
    
    banner_text.append(f"⚙️  Configuration: ", style="bold")
    banner_text.append(f"{config_path}\n", style="green")
    
    panel = Panel(
        banner_text,
        title="[bold green]MCP Hub Starting[/bold green]",
        border_style="blue",
        padding=(1, 2)
    )
    
    console.print(panel)


def setup_signal_handlers() -> None:
    """Setup signal handlers for graceful shutdown."""
    
    def signal_handler(signum, frame):
        console.print(f"\n🛑 Received signal {signum}, shutting down...", style="yellow")
        sys.exit(0)
    
    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Windows doesn't have SIGHUP
    if hasattr(signal, 'SIGHUP'):
        signal.signal(signal.SIGHUP, signal_handler)


@click.group()
def cli():
    """MCP Hub Python CLI tools."""
    pass


@cli.command()
@click.option(
    "--config", "-c",
    type=click.Path(exists=True, path_type=Path),
    required=True,
    help="Path to MCP servers configuration file"
)
def validate(config: Path) -> None:
    """Validate MCP servers configuration file."""
    
    console.print(f"🔍 Validating configuration: {config}", style="blue")
    
    try:
        config_manager = ConfigManager(config)
        asyncio.run(config_manager.load_config())
        
        # Get server count
        mcp_config = config_manager.get_config()
        server_count = len(mcp_config.mcpServers) if mcp_config else 0
        
        console.print("✅ Configuration is valid!", style="green")
        console.print(f"📊 Found {server_count} server(s) configured", style="blue")
        
        # Display server summary
        if mcp_config:
            for name, server_config in mcp_config.mcpServers.items():
                status = "🔴 disabled" if server_config.disabled else "🟢 enabled"
                transport = server_config.type or "auto-detect"
                console.print(f"  • {name} ({transport}) - {status}")
        
    except Exception as e:
        console.print(f"❌ Configuration validation failed:", style="red")
        console.print(f"    {e}", style="red")
        sys.exit(1)


@cli.command()
@click.option(
    "--url",
    default="https://mcp-hub.vercel.app/api/servers",
    help="Marketplace registry URL"
)
@click.option(
    "--cache-dir",
    type=click.Path(path_type=Path),
    help="Cache directory"
)
def marketplace(url: str, cache_dir: Optional[Path]) -> None:
    """Fetch and display marketplace information."""
    
    async def fetch_marketplace():
        console.print(f"🛍️  Fetching marketplace from: {url}", style="blue")
        
        cache_file = None
        if cache_dir:
            cache_file = cache_dir / "marketplace-cache.json"
        
        marketplace = Marketplace(registry_url=url, cache_file=cache_file)
        
        try:
            await marketplace.initialize()
            catalog = marketplace.get_catalog()
            
            if catalog:
                console.print(f"✅ Found {len(catalog.items)} servers in marketplace", style="green")
                
                # Display categories
                categories = marketplace.get_categories()
                console.print(f"📂 Categories: {', '.join(categories)}", style="blue")
                
                # Display popular servers
                popular = marketplace.get_popular_items(limit=5)
                if popular:
                    console.print("\n🌟 Popular servers:", style="bold")
                    for item in popular:
                        console.print(f"  • {item.name} by {item.author} ({item.github_stars} ⭐)")
                
            else:
                console.print("❌ No marketplace data available", style="red")
                
        except Exception as e:
            console.print(f"❌ Failed to fetch marketplace: {e}", style="red")
        finally:
            await marketplace.cleanup()
    
    asyncio.run(fetch_marketplace())


if __name__ == "__main__":
    main() 