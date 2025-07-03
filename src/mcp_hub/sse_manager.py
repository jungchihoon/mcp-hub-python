"""Server-Sent Events manager for MCP Hub Python."""

import asyncio
import json
import uuid
from collections import defaultdict, deque
from typing import Any, Dict, List, Optional

import structlog


logger = structlog.get_logger(__name__)


class SSEManager:
    """Server-Sent Events manager for real-time updates."""
    
    def __init__(self, max_events_per_client: int = 100):
        self.max_events_per_client = max_events_per_client
        self.clients: Dict[str, deque] = {}
        self.client_queues: Dict[str, asyncio.Queue] = {}
        self._lock = asyncio.Lock()
    
    async def add_client(self) -> str:
        """Add a new SSE client and return client ID."""
        client_id = str(uuid.uuid4())
        
        async with self._lock:
            self.clients[client_id] = deque(maxlen=self.max_events_per_client)
            self.client_queues[client_id] = asyncio.Queue()
        
        logger.debug("SSE client added", client_id=client_id)
        return client_id
    
    async def remove_client(self, client_id: str) -> None:
        """Remove an SSE client."""
        async with self._lock:
            self.clients.pop(client_id, None)
            queue = self.client_queues.pop(client_id, None)
            if queue:
                # Clear the queue
                while not queue.empty():
                    try:
                        queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
        
        logger.debug("SSE client removed", client_id=client_id)
    
    async def broadcast(self, event: Dict[str, Any]) -> None:
        """Broadcast an event to all connected clients."""
        event_data = json.dumps(event)
        
        async with self._lock:
            for client_id in list(self.clients.keys()):
                try:
                    # Add to client's event queue
                    await self.client_queues[client_id].put(event_data)
                    
                    # Also add to deque for backup
                    self.clients[client_id].append(event_data)
                    
                except Exception as e:
                    logger.warning("Failed to send event to client", client_id=client_id, error=str(e))
                    # Remove failed client
                    await self.remove_client(client_id)
        
        logger.debug("Event broadcasted", event_type=event.get("type"), clients=len(self.clients))
    
    async def send_to_client(self, client_id: str, event: Dict[str, Any]) -> None:
        """Send an event to a specific client."""
        event_data = json.dumps(event)
        
        async with self._lock:
            if client_id in self.clients:
                try:
                    await self.client_queues[client_id].put(event_data)
                    self.clients[client_id].append(event_data)
                except Exception as e:
                    logger.warning("Failed to send event to client", client_id=client_id, error=str(e))
                    await self.remove_client(client_id)
    
    async def get_events(self, client_id: str) -> List[str]:
        """Get pending events for a client."""
        if client_id not in self.client_queues:
            return []
        
        events = []
        queue = self.client_queues[client_id]
        
        # Get all available events without blocking
        while True:
            try:
                event = queue.get_nowait()
                events.append(event)
            except asyncio.QueueEmpty:
                break
        
        return events
    
    def get_client_count(self) -> int:
        """Get the number of connected clients."""
        return len(self.clients)
    
    async def cleanup(self) -> None:
        """Clean up all clients and resources."""
        async with self._lock:
            client_ids = list(self.clients.keys())
            for client_id in client_ids:
                await self.remove_client(client_id)
        
        logger.info("SSE manager cleaned up") 