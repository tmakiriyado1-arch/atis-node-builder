#!/usr/bin/env python3
"""Test script for local SearXNG integration.

This script tests:
1. SearXNG manager initialization
2. Local SearXNG startup (if repo exists)
3. SearXNGProvider with local instance
4. Search queries for ZERA and SAPP

Usage:
    python test_searxng_local.py
"""
import asyncio
import os
import sys

# Add the project to path
sys.path.insert(0, '/workspace/github__tmakiriyado1-arch__atis-node-builder')

# Set environment variables for testing
os.environ['SEARXNG_LOCAL_ENABLED'] = 'true'
os.environ['SEARXNG_LOCAL_PORT'] = '8888'
os.environ['SEARXNG_LOCAL_HOST'] = '127.0.0.1'


async def test_searxng_manager():
    """Test SearXNG manager."""
    print("=" * 80)
    print("Testing SearXNG Manager")
    print("=" * 80)
    
    from app.services.research.searxng_manager import get_searxng_manager, SearXNGManager
    
    manager = get_searxng_manager()
    
    print(f"Manager enabled: {manager.enabled}")
    print(f"Manager host: {manager.host}")
    print(f"Manager port: {manager.port}")
    print(f"Repo path exists: {manager.repo_path is not None}")
    if manager.repo_path:
        print(f"Repo path: {manager.repo_path}")
    
    # Try to start SearXNG
    print("\nAttempting to start local SearXNG...")
    base_url = await manager.start()
    
    if base_url:
        print(f"✓ SearXNG started at: {base_url}")
        print(f"Health check: {await manager.check_health()}")
        return manager
    else:
        print("✗ Failed to start SearXNG")
        print("This is expected if atis-searxng is not cloned/configured")
        return None


async def test_searxng_provider(manager=None):
    """Test SearXNGProvider."""
    print("\n" + "=" * 80)
    print("Testing SearXNGProvider")
    print("=" * 80)
    
    from app.services.research.searxng_provider import SearXNGProvider
    
    # Test with default configuration
    provider = SearXNGProvider()
    
    print(f"Provider base_url: {provider.base_url}")
    print(f"Provider use_local: {provider.use_local}")
    print(f"Provider local_available: {provider._local_available}")
    
    # Test queries
    queries = [
        "ZERA",
        "Southern African Power Pool (SAPP)",
        "African Development Bank (AfDB)",
    ]
    
    print("\nTesting search queries:")
    for query in queries:
        print(f"\n  Query: {query}")
        try:
            results = await provider.search(query, max_results=5)
            print(f"  Results: {len(results)}")
            for i, r in enumerate(results[:3]):
                title = r.get('title', 'N/A')[:60]
                url = r.get('url', 'N/A')[:80]
                print(f"    {i+1}. {title} -> {url}")
        except Exception as e:
            print(f"  Error: {type(e).__name__}: {e}")
    
    return provider


async def test_with_external_url():
    """Test SearXNGProvider with external URL."""
    print("\n" + "=" * 80)
    print("Testing SearXNGProvider with External URL")
    print("=" * 80)
    
    from app.services.research.searxng_provider import SearXNGProvider
    
    # Test with external URL (will get 404 but should handle gracefully)
    provider = SearXNGProvider(
        base_url="https://crispy-potato-vpr6pwwjrqxvfwx5p-8888.app.github.dev",
        use_local=False,
    )
    
    print(f"Provider base_url: {provider.base_url}")
    print(f"Provider use_local: {provider.use_local}")
    
    # Test a query
    query = "ZERA"
    print(f"\n  Query: {query}")
    results = await provider.search(query, max_results=5)
    print(f"  Results: {len(results)} (expected 0 due to 404, but should not crash)")
    
    return provider


async def main():
    """Main test function."""
    print("Local SearXNG Integration Test")
    print("=" * 80)
    
    # Test manager
    manager = await test_searxng_manager()
    
    # Test provider
    await test_searxng_provider(manager)
    
    # Test with external URL
    await test_with_external_url()
    
    print("\n" + "=" * 80)
    print("Test completed!")
    print("=" * 80)
    
    if manager and manager.is_running:
        print("\nNote: Local SearXNG is still running. Stop it with:")
        print("  from app.services.research.searxng_manager import stop_local_searxng")
        print("  asyncio.run(stop_local_searxng())")


if __name__ == "__main__":
    asyncio.run(main())
