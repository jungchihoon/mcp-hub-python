"""Configuration management for MCP Hub Python.

Complete Python port of the Node.js ConfigManager with enhanced features:
- File watching and change detection
- Smart diff calculation
- Environment variable resolution
- Validation and error handling
"""

import asyncio
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import structlog
from pydantic import ValidationError
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from .env_resolver import EnvResolver
from .events import EventEmitter
from .types import ConfigChanges, MCPServersConfig, ServerConfig


logger = structlog.get_logger(__name__)


class ConfigFileHandler(FileSystemEventHandler):
    """File system event handler for config file changes."""
    
    def __init__(self, config_manager: "ConfigManager") -> None:
        super().__init__()
        self.config_manager = config_manager
        
    def on_modified(self, event) -> None:
        """Handle file modification events."""
        if not event.is_directory and event.src_path == str(self.config_manager.config_path):
            logger.debug("Config file modified", path=event.src_path)
            asyncio.create_task(self.config_manager._handle_file_change())


class ConfigManager(EventEmitter):
    """
    Configuration manager with file watching and smart change detection.
    
    Complete Python port of Node.js ConfigManager providing:
    - Real-time file watching
    - Smart configuration diffing  
    - Environment variable resolution
    - Validation and error handling
    """
    
    # Key fields to compare for server config changes
    KEY_FIELDS = ["command", "args", "env", "disabled", "url", "headers", "dev", "name"]
    
    def __init__(
        self, 
        config_path_or_dict: Union[str, Path, Dict[str, Any]]
    ) -> None:
        super().__init__()
        self.config_path: Optional[Path] = None
        self.config: Optional[MCPServersConfig] = None
        self._previous_config: Optional[MCPServersConfig] = None
        self._observer: Optional[Observer] = None
        self._env_resolver = EnvResolver()
        
        if isinstance(config_path_or_dict, (str, Path)):
            self.config_path = Path(config_path_or_dict)
        elif isinstance(config_path_or_dict, dict):
            self.config = MCPServersConfig(**config_path_or_dict)
            self._previous_config = self.config.model_copy(deep=True)
        else:
            raise ValueError("config_path_or_dict must be a path or dictionary")
    
    def _diff_configs(
        self, 
        old_servers: Optional[Dict[str, ServerConfig]] = None,
        new_servers: Optional[Dict[str, ServerConfig]] = None
    ) -> ConfigChanges:
        """
        Calculate differences between old and new server configs.
        
        Args:
            old_servers: Previous server configurations
            new_servers: New server configurations
            
        Returns:
            ConfigChanges object with detailed change information
        """
        if old_servers is None:
            old_servers = {}
        if new_servers is None:
            new_servers = {}
            
        changes = ConfigChanges()
        
        # Find removed servers
        for name in old_servers:
            if name not in new_servers:
                changes.removed.append(name)
        
        # Find added/modified servers
        for name, new_config in new_servers.items():
            if name not in old_servers:
                changes.added.append(name)
            else:
                old_config = old_servers[name]
                
                # Check each key field for changes
                modified_fields = []
                for field in self.KEY_FIELDS:
                    old_value = getattr(old_config, field, None)
                    new_value = getattr(new_config, field, None)
                    
                    # Handle complex objects (env, args, headers, dev)
                    if field in ["args", "env", "headers", "dev"]:
                        if old_value != new_value:
                            modified_fields.append(field)
                    else:
                        if old_value != new_value:
                            modified_fields.append(field)
                
                if modified_fields:
                    changes.modified.append(name)
                    logger.debug(
                        "Server configuration modified",
                        server=name,
                        modified_fields=modified_fields
                    )
                else:
                    changes.unchanged.append(name)
        
        return changes
    
    async def update_config(
        self, 
        new_config_or_path: Union[str, Path, Dict[str, Any], MCPServersConfig]
    ) -> None:
        """
        Update configuration from new data or path.
        
        Args:
            new_config_or_path: New configuration data or file path
        """
        if isinstance(new_config_or_path, (str, Path)):
            # Update config path and reload
            self.config_path = Path(new_config_or_path)
            await self.load_config()
        elif isinstance(new_config_or_path, dict):
            # Update config directly
            new_config = MCPServersConfig(**new_config_or_path)
            await self._update_config_object(new_config)
        elif isinstance(new_config_or_path, MCPServersConfig):
            await self._update_config_object(new_config_or_path)
        else:
            raise ValueError("Invalid config type")
    
    async def _update_config_object(self, new_config: MCPServersConfig) -> None:
        """Update the configuration object and emit change events."""
        old_servers = self._previous_config.mcpServers if self._previous_config else {}
        new_servers = new_config.mcpServers
        
        # Calculate changes
        changes = self._diff_configs(old_servers, new_servers)
        
        # Update configs
        self.config = new_config
        self._previous_config = new_config.model_copy(deep=True)
        
        # Emit change event
        await self.emit("config_changed", {
            "config": new_config,
            "changes": changes
        })
        
        logger.info(
            "Configuration updated",
            added=len(changes.added),
            removed=len(changes.removed),
            modified=len(changes.modified),
            unchanged=len(changes.unchanged)
        )
    
    async def load_config(self) -> None:
        """Load configuration from file with validation and environment resolution."""
        if not self.config_path:
            raise ValueError("No config path specified")
        
        if not self.config_path.exists():
            raise FileNotFoundError(f"Config file not found: {self.config_path}")
        
        try:
            # Read and parse JSON
            content = self.config_path.read_text(encoding="utf-8")
            raw_config = json.loads(content)
            
            # Validate structure
            if "mcpServers" not in raw_config or not isinstance(raw_config["mcpServers"], dict):
                raise ValueError("Missing or invalid mcpServers configuration")
            
            # Validate and process each server configuration
            processed_servers = {}
            for name, server_data in raw_config["mcpServers"].items():
                try:
                    # Resolve environment variables in server config
                    resolved_data = await self._env_resolver.resolve_config(
                        server_data, 
                        ["env", "args", "command", "url", "headers"]
                    )
                    
                    # Validate server configuration
                    server_config = self._validate_server_config(name, resolved_data)
                    processed_servers[name] = server_config
                    
                except ValidationError as e:
                    logger.error(
                        "Invalid server configuration",
                        server=name,
                        error=str(e)
                    )
                    raise ValueError(f"Server '{name}' configuration error: {e}")
            
            # Create new config object
            new_config = MCPServersConfig(mcpServers=processed_servers)
            
            # Calculate changes if we have a previous config
            if self._previous_config:
                changes = self._diff_configs(
                    self._previous_config.mcpServers,
                    new_config.mcpServers
                )
                
                # Log successful load with changes
                logger.info(
                    "Config loaded successfully",
                    path=str(self.config_path),
                    server_count=len(processed_servers),
                    changes={
                        "added": len(changes.added),
                        "removed": len(changes.removed), 
                        "modified": len(changes.modified),
                        "unchanged": len(changes.unchanged)
                    }
                )
            else:
                logger.info(
                    "Config loaded successfully",
                    path=str(self.config_path),
                    server_count=len(processed_servers)
                )
            
            # Update configuration
            await self._update_config_object(new_config)
            
        except json.JSONDecodeError as e:
            logger.error("Invalid JSON in config file", path=str(self.config_path), error=str(e))
            raise ValueError(f"Invalid JSON in config file: {e}")
        except Exception as e:
            logger.error("Failed to load config", path=str(self.config_path), error=str(e))
            raise
    
    def _validate_server_config(self, name: str, server_data: Dict[str, Any]) -> ServerConfig:
        """
        Validate individual server configuration.
        
        Args:
            name: Server name
            server_data: Raw server configuration data
            
        Returns:
            Validated ServerConfig object
        """
        has_stdio_fields = "command" in server_data
        has_sse_fields = "url" in server_data
        
        # Check for mixed fields
        if has_stdio_fields and has_sse_fields:
            raise ValueError(f"Server '{name}' cannot mix stdio and sse fields")
        
        # Validate based on detected type
        if has_stdio_fields:
            # STDIO validation
            if not server_data.get("command"):
                raise ValueError(f"Server '{name}' missing command value")
            
            # Ensure args is a list
            if "args" not in server_data:
                server_data["args"] = []
            elif not isinstance(server_data["args"], list):
                raise ValueError(f"Server '{name}' args must be a list")
            
            # Validate env
            if "env" in server_data and not isinstance(server_data["env"], dict):
                raise ValueError(f"Server '{name}' has invalid environment config")
            
            server_data["type"] = "stdio"
            
        elif has_sse_fields:
            # SSE validation
            try:
                from urllib.parse import urlparse
                result = urlparse(server_data["url"])
                if not all([result.scheme, result.netloc]):
                    raise ValueError("Invalid URL format")
            except Exception as e:
                raise ValueError(f"Server '{name}' has invalid url: {e}")
            
            # Validate headers
            if "headers" in server_data and not isinstance(server_data["headers"], dict):
                raise ValueError(f"Server '{name}' has invalid headers config")
            
            server_data["type"] = "sse"
            
        else:
            raise ValueError(
                f"Server '{name}' must include either command (for stdio) or url (for sse)"
            )
        
        # Validate dev field (only for stdio servers)
        if "dev" in server_data:
            if not has_stdio_fields:
                raise ValueError(
                    f"Server '{name}' dev field is only supported for stdio servers"
                )
            # Additional dev validation could be added here
        
        return ServerConfig(**server_data)
    
    async def watch_config(self) -> None:
        """Start watching the configuration file for changes."""
        if not self.config_path:
            logger.warning("Cannot watch config: no config path specified")
            return
        
        if self._observer:
            logger.warning("Config watcher already running")
            return
        
        try:
            self._observer = Observer()
            handler = ConfigFileHandler(self)
            
            # Watch the directory containing the config file
            watch_dir = self.config_path.parent
            self._observer.schedule(handler, str(watch_dir), recursive=False)
            self._observer.start()
            
            logger.info("Started watching config file", path=str(self.config_path))
            
        except Exception as e:
            logger.error("Failed to start config watcher", error=str(e))
            raise
    
    async def stop_watching(self) -> None:
        """Stop watching the configuration file."""
        if self._observer:
            self._observer.stop()
            self._observer.join()
            self._observer = None
            logger.info("Stopped watching config file")
    
    async def _handle_file_change(self) -> None:
        """Handle configuration file change event."""
        try:
            # Small delay to ensure file write is complete
            await asyncio.sleep(0.1)
            await self.load_config()
        except Exception as e:
            logger.error("Failed to reload config after file change", error=str(e))
    
    def get_config(self) -> Optional[MCPServersConfig]:
        """Get the current configuration."""
        return self.config
    
    def get_server_config(self, server_name: str) -> Optional[ServerConfig]:
        """
        Get configuration for a specific server.
        
        Args:
            server_name: Name of the server
            
        Returns:
            ServerConfig object or None if not found
        """
        if not self.config:
            return None
        return self.config.mcpServers.get(server_name)
    
    async def save_config(self) -> None:
        """Save current configuration to file."""
        if not self.config_path or not self.config:
            raise ValueError("Cannot save: no config path or config data")
        
        try:
            # Convert to dict and write to file
            config_dict = {"mcpServers": {}}
            for name, server_config in self.config.mcpServers.items():
                config_dict["mcpServers"][name] = server_config.model_dump(
                    exclude_unset=True,
                    exclude_none=True
                )
            
            # Write with pretty formatting
            self.config_path.write_text(
                json.dumps(config_dict, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
            
            logger.info("Configuration saved", path=str(self.config_path))
            
        except Exception as e:
            logger.error("Failed to save config", path=str(self.config_path), error=str(e))
            raise
    
    async def cleanup(self) -> None:
        """Clean up resources."""
        await self.stop_watching()
        await self.emit("cleanup") 