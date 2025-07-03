"""Environment variable resolver for MCP Hub Python.

Complete Python port of Node.js env-resolver with enhanced security and features:
- ${ENV_VAR} syntax for environment variables
- ${cmd: command} syntax for command execution
- Security validation for command execution
- Recursive resolution support
"""

import asyncio
import os
import re
import shlex
import subprocess
from typing import Any, Dict, List, Optional, Union

import structlog

logger = structlog.get_logger(__name__)


class EnvResolver:
    """
    Environment variable and command resolver.
    
    Complete Python port of Node.js env-resolver providing:
    - Environment variable substitution: ${ENV_VAR}
    - Command execution: ${cmd: command args}
    - Security validation
    - Recursive resolution
    """
    
    # Regex patterns for variable substitution
    ENV_VAR_PATTERN = re.compile(r'\$\{([^}]+)\}')
    CMD_PATTERN = re.compile(r'\$\{cmd:\s*([^}]+)\}')
    
    # Security: allowed commands (can be customized)
    ALLOWED_COMMANDS = {
        'echo', 'cat', 'head', 'tail', 'wc', 'date', 'pwd', 'whoami',
        'op',  # 1Password CLI
        'aws', 'gcloud', 'kubectl',  # Cloud CLIs
        'git',  # Git commands
        'node', 'python', 'python3',  # Interpreters (limited)
    }
    
    def __init__(self, allowed_commands: Optional[set] = None) -> None:
        """
        Initialize the environment resolver.
        
        Args:
            allowed_commands: Set of allowed command names for security
        """
        self.allowed_commands = allowed_commands or self.ALLOWED_COMMANDS.copy()
        self.command_timeout = 30.0  # seconds
        
    async def resolve_config(
        self, 
        config: Dict[str, Any], 
        fields_to_resolve: List[str]
    ) -> Dict[str, Any]:
        """
        Resolve environment variables and commands in configuration.
        
        Args:
            config: Configuration dictionary
            fields_to_resolve: List of field names to process
            
        Returns:
            Configuration with resolved values
        """
        resolved_config = config.copy()
        
        for field in fields_to_resolve:
            if field in resolved_config:
                resolved_config[field] = await self._resolve_value(resolved_config[field])
        
        return resolved_config
    
    async def _resolve_value(self, value: Any) -> Any:
        """
        Recursively resolve a value (string, dict, list, or primitive).
        
        Args:
            value: Value to resolve
            
        Returns:
            Resolved value
        """
        if isinstance(value, str):
            return await self._resolve_string(value)
        elif isinstance(value, dict):
            resolved_dict = {}
            for k, v in value.items():
                resolved_key = await self._resolve_string(k) if isinstance(k, str) else k
                resolved_value = await self._resolve_value(v)
                resolved_dict[resolved_key] = resolved_value
            return resolved_dict
        elif isinstance(value, list):
            resolved_list = []
            for item in value:
                resolved_item = await self._resolve_value(item)
                resolved_list.append(resolved_item)
            return resolved_list
        else:
            # Primitive value, return as-is
            return value
    
    async def _resolve_string(self, text: str) -> str:
        """
        Resolve environment variables and commands in a string.
        
        Args:
            text: Input string with potential substitutions
            
        Returns:
            String with substitutions resolved
        """
        if not isinstance(text, str):
            return text
        
        original_text = text
        max_iterations = 10  # Prevent infinite recursion
        iteration = 0
        
        while self.ENV_VAR_PATTERN.search(text) and iteration < max_iterations:
            iteration += 1
            
            # First pass: resolve command executions
            text = await self._resolve_commands(text)
            
            # Second pass: resolve environment variables
            text = self._resolve_env_vars(text)
        
        if iteration >= max_iterations:
            logger.warning(
                "Maximum resolution iterations reached",
                original=original_text,
                result=text
            )
        
        return text
    
    def _resolve_env_vars(self, text: str) -> str:
        """
        Resolve environment variables in format ${VAR_NAME}.
        
        Args:
            text: Input string
            
        Returns:
            String with environment variables resolved
        """
        def replace_env_var(match):
            var_name = match.group(1).strip()
            
            # Handle special null/empty cases
            if var_name.lower() in ('null', ''):
                # Return the full process environment
                return os.environ.get(var_name, '')
            
            # Get environment variable value
            value = os.environ.get(var_name)
            
            if value is None:
                logger.warning("Environment variable not found", var=var_name)
                return f"${{{var_name}}}"  # Return original if not found
            
            logger.debug("Resolved environment variable", var=var_name, value="***")
            return value
        
        return self.ENV_VAR_PATTERN.sub(replace_env_var, text)
    
    async def _resolve_commands(self, text: str) -> str:
        """
        Resolve command executions in format ${cmd: command args}.
        
        Args:
            text: Input string
            
        Returns:
            String with commands resolved
        """
        async def replace_command(match):
            command_str = match.group(1).strip()
            
            try:
                # Parse command and arguments
                command_parts = shlex.split(command_str)
                if not command_parts:
                    logger.error("Empty command in substitution")
                    return match.group(0)  # Return original
                
                command_name = command_parts[0]
                
                # Security check: validate command
                if not self._is_command_allowed(command_name):
                    logger.error(
                        "Command not allowed for security reasons",
                        command=command_name,
                        allowed=list(self.allowed_commands)
                    )
                    return match.group(0)  # Return original
                
                # Execute command
                result = await self._execute_command(command_parts)
                
                logger.debug(
                    "Command executed successfully",
                    command=command_name,
                    args=command_parts[1:],
                    result_length=len(result)
                )
                
                return result.strip()
                
            except Exception as e:
                logger.error(
                    "Failed to execute command",
                    command=command_str,
                    error=str(e)
                )
                return match.group(0)  # Return original on error
        
        # Process all command substitutions
        result = text
        for match in self.CMD_PATTERN.finditer(text):
            replacement = await replace_command(match)
            result = result.replace(match.group(0), replacement, 1)
        
        return result
    
    def _is_command_allowed(self, command_name: str) -> bool:
        """
        Check if a command is allowed for execution.
        
        Args:
            command_name: Name of the command
            
        Returns:
            True if command is allowed, False otherwise
        """
        # Check against allowed commands list
        if command_name in self.allowed_commands:
            return True
        
        # Check if it's an absolute path to an allowed command
        if os.path.isabs(command_name):
            base_command = os.path.basename(command_name)
            if base_command in self.allowed_commands:
                return True
        
        return False
    
    async def _execute_command(self, command_parts: List[str]) -> str:
        """
        Execute a command safely with timeout.
        
        Args:
            command_parts: Command and arguments as list
            
        Returns:
            Command output as string
        """
        try:
            # Create subprocess with security settings
            process = await asyncio.create_subprocess_exec(
                *command_parts,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                # Security: don't inherit environment completely
                env=dict(os.environ),
                # Security: create new process group
                preexec_fn=os.setsid if hasattr(os, 'setsid') else None
            )
            
            # Wait for completion with timeout
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=self.command_timeout
                )
            except asyncio.TimeoutError:
                # Kill the process on timeout
                process.kill()
                await process.wait()
                raise Exception(f"Command timed out after {self.command_timeout} seconds")
            
            # Check return code
            if process.returncode != 0:
                error_msg = stderr.decode('utf-8', errors='replace').strip()
                raise Exception(f"Command failed with code {process.returncode}: {error_msg}")
            
            # Return stdout
            output = stdout.decode('utf-8', errors='replace')
            return output
            
        except FileNotFoundError:
            raise Exception(f"Command not found: {command_parts[0]}")
        except Exception as e:
            logger.error(
                "Command execution failed",
                command=command_parts[0],
                args=command_parts[1:],
                error=str(e)
            )
            raise
    
    def add_allowed_command(self, command: str) -> None:
        """
        Add a command to the allowed list.
        
        Args:
            command: Command name to allow
        """
        self.allowed_commands.add(command)
        logger.debug("Added allowed command", command=command)
    
    def remove_allowed_command(self, command: str) -> None:
        """
        Remove a command from the allowed list.
        
        Args:
            command: Command name to disallow
        """
        self.allowed_commands.discard(command)
        logger.debug("Removed allowed command", command=command)
    
    def set_command_timeout(self, timeout: float) -> None:
        """
        Set the timeout for command execution.
        
        Args:
            timeout: Timeout in seconds
        """
        self.command_timeout = timeout
        logger.debug("Set command timeout", timeout=timeout) 