"""Marketplace integration for MCP Hub Python."""

import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import httpx
import structlog

from .events import EventEmitter
from .types import MarketplaceItem, MarketplaceCatalog


logger = structlog.get_logger(__name__)


class MarketplaceCache:
    """Cache for marketplace data."""
    
    def __init__(self):
        self.catalog: Optional[MarketplaceCatalog] = None
        self.last_updated: Optional[datetime] = None
        self.cache_duration = timedelta(hours=1)  # Cache for 1 hour
    
    def is_valid(self) -> bool:
        """Check if cache is still valid."""
        if not self.catalog or not self.last_updated:
            return False
        return datetime.now() - self.last_updated < self.cache_duration
    
    def update(self, catalog: MarketplaceCatalog) -> None:
        """Update cache with new catalog."""
        self.catalog = catalog
        self.last_updated = datetime.now()


class Marketplace(EventEmitter):
    """MCP Hub marketplace integration."""
    
    DEFAULT_REGISTRY_URL = "https://mcp-hub.vercel.app/api/servers"
    
    def __init__(
        self,
        registry_url: Optional[str] = None,
        cache_file: Optional[Path] = None
    ):
        super().__init__()
        
        self.registry_url = registry_url or self.DEFAULT_REGISTRY_URL
        self.cache_file = cache_file
        self.cache = MarketplaceCache()
        
        # HTTP client
        self.client = httpx.AsyncClient(
            timeout=30.0,
            headers={"User-Agent": "MCP-Hub-Python/1.0.0"}
        )
    
    async def initialize(self) -> None:
        """Initialize marketplace."""
        logger.info("Initializing marketplace", registry=self.registry_url)
        
        # Try to load from cache file first
        if self.cache_file and self.cache_file.exists():
            await self._load_from_cache_file()
        
        # If cache is invalid, fetch from registry
        if not self.cache.is_valid():
            await self.fetch_catalog()
        
        logger.info(
            "Marketplace initialized",
            items=len(self.cache.catalog.items) if self.cache.catalog else 0
        )
    
    async def fetch_catalog(self) -> MarketplaceCatalog:
        """Fetch catalog from registry."""
        logger.info("Fetching marketplace catalog", url=self.registry_url)
        
        try:
            response = await self.client.get(self.registry_url)
            response.raise_for_status()
            
            data = response.json()
            
            # Parse items
            items = []
            for item_data in data.get("servers", []):
                try:
                    item = MarketplaceItem(**item_data)
                    items.append(item)
                except Exception as e:
                    logger.warning("Invalid marketplace item", error=str(e), data=item_data)
            
            catalog = MarketplaceCatalog(
                items=items,
                last_updated=datetime.now(),
                total_count=len(items)
            )
            
            # Update cache
            self.cache.update(catalog)
            
            # Save to cache file if configured
            if self.cache_file:
                await self._save_to_cache_file()
            
            await self.emit("catalog_updated", {"catalog": catalog})
            
            logger.info("Marketplace catalog fetched", items=len(items))
            return catalog
            
        except Exception as e:
            logger.error("Failed to fetch marketplace catalog", error=str(e))
            
            # Return empty catalog on error
            empty_catalog = MarketplaceCatalog(items=[], total_count=0)
            if not self.cache.catalog:
                self.cache.update(empty_catalog)
            
            return self.cache.catalog or empty_catalog
    
    async def _load_from_cache_file(self) -> None:
        """Load catalog from cache file."""
        try:
            data = json.loads(self.cache_file.read_text())
            
            items = [MarketplaceItem(**item_data) for item_data in data.get("items", [])]
            last_updated_str = data.get("last_updated")
            last_updated = datetime.fromisoformat(last_updated_str) if last_updated_str else None
            
            catalog = MarketplaceCatalog(
                items=items,
                last_updated=last_updated,
                total_count=len(items)
            )
            
            self.cache.catalog = catalog
            self.cache.last_updated = last_updated
            
            logger.debug("Loaded marketplace catalog from cache", items=len(items))
            
        except Exception as e:
            logger.warning("Failed to load marketplace cache", error=str(e))
    
    async def _save_to_cache_file(self) -> None:
        """Save catalog to cache file."""
        if not self.cache.catalog:
            return
        
        try:
            data = {
                "items": [item.model_dump(by_alias=True) for item in self.cache.catalog.items],
                "last_updated": self.cache.last_updated.isoformat() if self.cache.last_updated else None,
                "total_count": self.cache.catalog.total_count
            }
            
            # Ensure directory exists
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            
            # Write to file
            self.cache_file.write_text(json.dumps(data, indent=2))
            
            logger.debug("Saved marketplace catalog to cache")
            
        except Exception as e:
            logger.warning("Failed to save marketplace cache", error=str(e))
    
    def get_catalog(self) -> Optional[MarketplaceCatalog]:
        """Get current catalog."""
        return self.cache.catalog
    
    def search(
        self,
        query: Optional[str] = None,
        category: Optional[str] = None,
        tags: Optional[List[str]] = None,
        requires_api_key: Optional[bool] = None
    ) -> List[MarketplaceItem]:
        """Search marketplace items."""
        if not self.cache.catalog:
            return []
        
        items = self.cache.catalog.items
        
        # Filter by query
        if query:
            query_lower = query.lower()
            items = [
                item for item in items
                if (query_lower in item.name.lower() or
                    query_lower in item.description.lower() or
                    query_lower in item.author.lower())
            ]
        
        # Filter by category
        if category:
            items = [item for item in items if item.category.lower() == category.lower()]
        
        # Filter by tags
        if tags:
            tag_set = {tag.lower() for tag in tags}
            items = [
                item for item in items
                if any(tag.lower() in tag_set for tag in item.tags)
            ]
        
        # Filter by API key requirement
        if requires_api_key is not None:
            items = [item for item in items if item.requires_api_key == requires_api_key]
        
        return items
    
    def get_item(self, mcp_id: str) -> Optional[MarketplaceItem]:
        """Get item by MCP ID."""
        if not self.cache.catalog:
            return None
        
        return next(
            (item for item in self.cache.catalog.items if item.mcp_id == mcp_id),
            None
        )
    
    def get_categories(self) -> List[str]:
        """Get all unique categories."""
        if not self.cache.catalog:
            return []
        
        categories = {item.category for item in self.cache.catalog.items}
        return sorted(categories)
    
    def get_tags(self) -> List[str]:
        """Get all unique tags."""
        if not self.cache.catalog:
            return []
        
        tags = set()
        for item in self.cache.catalog.items:
            tags.update(item.tags)
        
        return sorted(tags)
    
    def get_popular_items(self, limit: int = 10) -> List[MarketplaceItem]:
        """Get popular items sorted by GitHub stars."""
        if not self.cache.catalog:
            return []
        
        items = sorted(
            self.cache.catalog.items,
            key=lambda x: x.github_stars,
            reverse=True
        )
        
        return items[:limit]
    
    def get_recommended_items(self) -> List[MarketplaceItem]:
        """Get recommended items."""
        if not self.cache.catalog:
            return []
        
        return [item for item in self.cache.catalog.items if item.is_recommended]
    
    async def cleanup(self) -> None:
        """Clean up resources."""
        await self.client.aclose() 