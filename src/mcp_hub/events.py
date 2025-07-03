"""Event system for MCP Hub Python.

Python implementation of Node.js-style EventEmitter with async support.
"""

import asyncio
from typing import Any, Callable, Dict, List, Optional, Union
import weakref

import structlog

logger = structlog.get_logger(__name__)


class EventEmitter:
    """
    Python implementation of Node.js EventEmitter with async support.
    
    Provides event-driven architecture similar to Node.js EventEmitter
    but designed for Python async/await patterns.
    """
    
    def __init__(self) -> None:
        self._events: Dict[str, List[Callable]] = {}
        self._max_listeners: int = 10
        self._listener_count: Dict[str, int] = {}
    
    def on(self, event: str, listener: Callable) -> "EventEmitter":
        """
        Register an event listener.
        
        Args:
            event: Event name
            listener: Callback function (can be sync or async)
            
        Returns:
            Self for method chaining
        """
        if event not in self._events:
            self._events[event] = []
            self._listener_count[event] = 0
        
        self._events[event].append(listener)
        self._listener_count[event] += 1
        
        # Warn about potential memory leaks
        if self._listener_count[event] > self._max_listeners:
            logger.warning(
                "Possible EventEmitter memory leak detected",
                event=event,
                listener_count=self._listener_count[event],
                max_listeners=self._max_listeners
            )
        
        return self
    
    def once(self, event: str, listener: Callable) -> "EventEmitter":
        """
        Register a one-time event listener.
        
        Args:
            event: Event name
            listener: Callback function (can be sync or async)
            
        Returns:
            Self for method chaining
        """
        def once_wrapper(*args, **kwargs):
            # Remove the listener before calling it
            self.off(event, once_wrapper)
            
            # Call the original listener
            if asyncio.iscoroutinefunction(listener):
                return asyncio.create_task(listener(*args, **kwargs))
            else:
                return listener(*args, **kwargs)
        
        # Store reference to original listener for removal
        once_wrapper._original_listener = listener
        
        return self.on(event, once_wrapper)
    
    def off(self, event: str, listener: Optional[Callable] = None) -> "EventEmitter":
        """
        Remove event listener(s).
        
        Args:
            event: Event name
            listener: Specific listener to remove (if None, removes all)
            
        Returns:
            Self for method chaining
        """
        if event not in self._events:
            return self
        
        if listener is None:
            # Remove all listeners for this event
            count = len(self._events[event])
            self._events[event].clear()
            self._listener_count[event] = 0
            logger.debug("Removed all listeners", event=event, count=count)
        else:
            # Remove specific listener
            listeners = self._events[event]
            to_remove = []
            
            for i, l in enumerate(listeners):
                # Check for direct match or once wrapper match
                if (l == listener or 
                    (hasattr(l, '_original_listener') and l._original_listener == listener)):
                    to_remove.append(i)
            
            # Remove in reverse order to maintain indices
            for i in reversed(to_remove):
                listeners.pop(i)
                self._listener_count[event] -= 1
        
        return self
    
    def remove_listener(self, event: str, listener: Callable) -> "EventEmitter":
        """Alias for off() method."""
        return self.off(event, listener)
    
    def remove_all_listeners(self, event: Optional[str] = None) -> "EventEmitter":
        """
        Remove all listeners for an event or all events.
        
        Args:
            event: Event name (if None, removes all listeners for all events)
            
        Returns:
            Self for method chaining
        """
        if event is None:
            total_removed = sum(self._listener_count.values())
            self._events.clear()
            self._listener_count.clear()
            logger.debug("Removed all listeners for all events", count=total_removed)
        else:
            self.off(event)
        
        return self
    
    async def emit(self, event: str, *args, **kwargs) -> bool:
        """
        Emit an event to all registered listeners.
        
        Args:
            event: Event name
            *args: Positional arguments to pass to listeners
            **kwargs: Keyword arguments to pass to listeners
            
        Returns:
            True if event had listeners, False otherwise
        """
        if event not in self._events or not self._events[event]:
            return False
        
        listeners = self._events[event].copy()  # Copy to avoid modification during iteration
        
        # Create tasks for async listeners and call sync listeners immediately
        tasks = []
        
        for listener in listeners:
            try:
                if asyncio.iscoroutinefunction(listener):
                    # Async listener - create task
                    task = asyncio.create_task(listener(*args, **kwargs))
                    tasks.append(task)
                else:
                    # Sync listener - call immediately
                    listener(*args, **kwargs)
            except Exception as e:
                logger.error(
                    "Error in event listener",
                    event=event,
                    listener=str(listener),
                    error=str(e)
                )
        
        # Wait for all async listeners to complete
        if tasks:
            try:
                await asyncio.gather(*tasks, return_exceptions=True)
            except Exception as e:
                logger.error("Error waiting for async listeners", event=event, error=str(e))
        
        return True
    
    def emit_sync(self, event: str, *args, **kwargs) -> bool:
        """
        Emit an event synchronously (only calls sync listeners).
        
        Args:
            event: Event name
            *args: Positional arguments to pass to listeners
            **kwargs: Keyword arguments to pass to listeners
            
        Returns:
            True if event had listeners, False otherwise
        """
        if event not in self._events or not self._events[event]:
            return False
        
        listeners = self._events[event].copy()
        
        for listener in listeners:
            try:
                if not asyncio.iscoroutinefunction(listener):
                    listener(*args, **kwargs)
                else:
                    logger.warning(
                        "Skipping async listener in sync emit",
                        event=event,
                        listener=str(listener)
                    )
            except Exception as e:
                logger.error(
                    "Error in sync event listener",
                    event=event,
                    listener=str(listener),
                    error=str(e)
                )
        
        return True
    
    def listeners(self, event: str) -> List[Callable]:
        """
        Get all listeners for an event.
        
        Args:
            event: Event name
            
        Returns:
            List of listener functions
        """
        return self._events.get(event, []).copy()
    
    def listener_count(self, event: str) -> int:
        """
        Get the number of listeners for an event.
        
        Args:
            event: Event name
            
        Returns:
            Number of listeners
        """
        return self._listener_count.get(event, 0)
    
    def event_names(self) -> List[str]:
        """
        Get list of all events that have listeners.
        
        Returns:
            List of event names
        """
        return [event for event, listeners in self._events.items() if listeners]
    
    def set_max_listeners(self, max_listeners: int) -> "EventEmitter":
        """
        Set the maximum number of listeners per event.
        
        Args:
            max_listeners: Maximum number of listeners
            
        Returns:
            Self for method chaining
        """
        self._max_listeners = max_listeners
        return self
    
    def get_max_listeners(self) -> int:
        """
        Get the maximum number of listeners per event.
        
        Returns:
            Maximum number of listeners
        """
        return self._max_listeners 