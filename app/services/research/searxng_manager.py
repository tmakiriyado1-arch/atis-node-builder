"""SearXNG Local Manager - Start, stop, and manage local SearXNG instance.

This module provides functionality to run SearXNG as a local subprocess,
making NORA self-contained without requiring external Codespaces.

The manager:
- Starts SearXNG on localhost with custom settings
- Monitors the SearXNG process
- Provides health checks
- Handles graceful shutdown
- Manages configuration for local SearXNG instance

Configuration:
    SEARXNG_LOCAL_ENABLED: Enable local SearXNG (default: True)
    SEARXNG_LOCAL_PORT: Port for local SearXNG (default: 8888)
    SEARXNG_LOCAL_HOST: Host for local SearXNG (default: 127.0.0.1)
    SEARXNG_REPO_PATH: Path to atis-searxng repository
    SEARXNG_SETTINGS_PATH: Path to custom settings.yml
"""
from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional, AsyncGenerator

import httpx

from app import config
from app.logging import logger


class SearXNGManager:
    """Manager for local SearXNG instance.
    
    This class handles:
    - Starting SearXNG as a subprocess
    - Stopping SearXNG gracefully
    - Health checking the SearXNG instance
    - Providing the base URL for SearXNGProvider
    """
    
    def __init__(
        self,
        enabled: bool = True,
        host: str = "127.0.0.1",
        port: int = 8888,
        repo_path: Optional[str] = None,
        settings_path: Optional[str] = None,
        startup_timeout: float = 30.0,
        health_check_interval: float = 5.0,
    ) -> None:
        """Initialize the SearXNG manager.
        
        Args:
            enabled: Whether to use local SearXNG
            host: Host to bind SearXNG to (127.0.0.1 for local-only)
            port: Port to run SearXNG on
            repo_path: Path to atis-searxng repository
            settings_path: Path to custom settings.yml
            startup_timeout: Time to wait for SearXNG to start
            health_check_interval: Interval between health checks
        """
        # Configuration from environment or defaults
        self.enabled = enabled and getattr(config, 'SEARXNG_LOCAL_ENABLED', True)
        self.host = host
        self.port = int(os.getenv('SEARXNG_LOCAL_PORT', str(port)))
        self.startup_timeout = startup_timeout
        self.health_check_interval = health_check_interval
        
        # Determine repo path
        if repo_path:
            self.repo_path = Path(repo_path)
        else:
            # Try common locations
            candidates = [
                Path("/workspace/github__tmakiriyado1-arch__atis-searxng"),
                Path("/workspace/atis-searxng"),
                Path("../atis-searxng"),
                Path("./atis-searxng"),
            ]
            self.repo_path = None
            for candidate in candidates:
                if candidate.exists() and (candidate / "settings.yml").exists():
                    self.repo_path = candidate
                    break
        
        # Determine settings path
        if settings_path:
            self.settings_path = Path(settings_path)
        elif self.repo_path:
            self.settings_path = self.repo_path / "settings.yml"
        else:
            self.settings_path = None
        
        # Process and subprocess management
        self._process: Optional[subprocess.Popen] = None
        self._started: bool = False
        self._healthy: bool = False
        self._base_url: Optional[str] = None
        
        # Log configuration
        logger.info(f"[SEARXNG_MGR] Local SearXNG enabled: {self.enabled}")
        if self.repo_path:
            logger.info(f"[SEARXNG_MGR] SearXNG repo: {self.repo_path}")
        if self.settings_path:
            logger.info(f"[SEARXNG_MGR] Settings: {self.settings_path}")
        logger.info(f"[SEARXNG_MGR] Host: {self.host}, Port: {self.port}")
    
    @property
    def base_url(self) -> Optional[str]:
        """Get the base URL for the local SearXNG instance."""
        if not self.enabled or not self._started:
            return None
        return f"http://{self.host}:{self.port}"
    
    @property
    def is_running(self) -> bool:
        """Check if SearXNG process is running."""
        return self._process is not None and self._process.poll() is None
    
    @property
    def is_healthy(self) -> bool:
        """Check if SearXNG is healthy (running and responding)."""
        return self._healthy and self.is_running
    
    def _get_start_command(self) -> Optional[list]:
        """Get the command to start SearXNG."""
        if not self.repo_path:
            logger.error(f"[SEARXNG_MGR] No SearXNG repo found")
            return None
        
        venv_path = self.repo_path / ".venv"
        python_path = venv_path / "bin" / "python3" if venv_path.exists() else "python3"
        
        # Check if SearXNG is installed
        searxng_py = self.repo_path / "searx"
        if searxng_py.exists():
            # Run from source
            cmd = [
                str(python_path),
                "-m",
                "searx.webapp",
                "run",
            ]
        else:
            # Try pip-installed searxng
            cmd = [
                str(python_path),
                "-m",
                "searx.webapp",
                "run",
            ]
        
        return cmd
    
    async def start(self) -> bool:
        """Start the local SearXNG instance.
        
        Returns:
            True if SearXNG started successfully, False otherwise
        """
        if not self.enabled:
            logger.info(f"[SEARXNG_MGR] Local SearXNG disabled, skipping start")
            return False
        
        if self.is_running:
            logger.info(f"[SEARXNG_MGR] SearXNG already running on {self.base_url}")
            return self.is_healthy
        
        # Get start command
        cmd = self._get_start_command()
        if not cmd:
            logger.error(f"[SEARXNG_MGR] Cannot determine start command")
            return False
        
        # Set environment variables
        env = os.environ.copy()
        env['SEARXNG_PORT'] = str(self.port)
        env['SEARXNG_BIND_ADDRESS'] = self.host
        if self.settings_path:
            env['SEARXNG_SETTINGS_PATH'] = str(self.settings_path)
        
        # Modify settings for local use if needed
        if self.settings_path and self.host == "127.0.0.1":
            self._ensure_local_settings()
        
        logger.info(f"[SEARXNG_MGR] Starting SearXNG: {' '.join(cmd)}")
        logger.info(f"[SEARXNG_MGR] Environment: SEARXNG_PORT={self.port}, BIND={self.host}")
        
        try:
            # Start SearXNG in a subprocess
            self._process = subprocess.Popen(
                cmd,
                cwd=self.repo_path if self.repo_path else None,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                preexec_fn=os.setsid,  # Create new process group
            )
            
            # Wait for startup
            start_time = time.time()
            while time.time() - start_time < self.startup_timeout:
                if await self.check_health():
                    self._started = True
                    self._healthy = True
                    logger.info(f"[SEARXNG_MGR] SearXNG started successfully on {self.base_url}")
                    return True
                
                if not self.is_running:
                    # Process died
                    stdout, stderr = self._process.communicate(timeout=1)
                    logger.error(f"[SEARXNG_MGR] SearXNG process died during startup")
                    if stdout:
                        logger.error(f"[SEARXNG_MGR] stdout: {stdout.decode()[:500]}")
                    if stderr:
                        logger.error(f"[SEARXNG_MGR] stderr: {stderr.decode()[:500]}")
                    self._process = None
                    return False
                
                await asyncio.sleep(0.5)
            
            # Timeout
            logger.error(f"[SEARXNG_MGR] SearXNG startup timed out after {self.startup_timeout}s")
            await self.stop()
            return False
            
        except Exception as e:
            logger.error(f"[SEARXNG_MGR] Failed to start SearXNG: {type(e).__name__}: {e}")
            await self.stop()
            return False
    
    def _ensure_local_settings(self) -> None:
        """Ensure settings.yml is configured for local use."""
        if not self.settings_path or not self.settings_path.exists():
            return
        
        try:
            with open(self.settings_path, 'r') as f:
                content = f.read()
            
            # Check for localhost binding
            if f'bind_address: "127.0.0.1"' not in content and f'bind_address: 127.0.0.1' not in content:
                # Check if it's using 0.0.0.0
                if 'bind_address: "0.0.0.0"' in content or 'bind_address: 0.0.0.0' in content:
                    logger.warning(f"[SEARXNG_MGR] Changing bind_address from 0.0.0.0 to 127.0.0.1 for security")
                    content = content.replace('bind_address: "0.0.0.0"', 'bind_address: "127.0.0.1"')
                    content = content.replace('bind_address: 0.0.0.0', 'bind_address: 127.0.0.1')
                    with open(self.settings_path, 'w') as f:
                        f.write(content)
        except Exception as e:
            logger.warning(f"[SEARXNG_MGR] Could not update settings.yml: {e}")
    
    async def check_health(self) -> bool:
        """Check if SearXNG is healthy by making a test request.
        
        Returns:
            True if SearXNG responds to health check, False otherwise
        """
        if not self.is_running:
            self._healthy = False
            return False
        
        try:
            url = f"{self.base_url}/search?q=test&format=json"
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(url)
                if response.status_code == 200:
                    try:
                        data = response.json()
                        if 'results' in data:
                            self._healthy = True
                            return True
                    except:
                        pass
                
                # SearXNG might be starting up - check if we get a connection
                # or if it's a different error
                if response.status_code in (400, 404):
                    # SearXNG is running but might not be ready or has no results
                    self._healthy = True
                    return True
                
                self._healthy = False
                return False
                
        except httpx.ConnectError:
            # Not started yet
            self._healthy = False
            return False
        except Exception as e:
            logger.warning(f"[SEARXNG_MGR] Health check failed: {type(e).__name__}: {e}")
            self._healthy = False
            return False
    
    async def stop(self, force: bool = False) -> bool:
        """Stop the local SearXNG instance.
        
        Args:
            force: Force kill if graceful shutdown fails
            
        Returns:
            True if stopped successfully, False otherwise
        """
        if not self.is_running:
            return True
        
        logger.info(f"[SEARXNG_MGR] Stopping SearXNG...")
        
        try:
            if self._process:
                # Send SIGTERM to the process group
                os.killpg(os.getpgid(self._process.pid), signal.SIGTERM)
                
                # Wait for graceful shutdown
                try:
                    self._process.wait(timeout=10)
                    logger.info(f"[SEARXNG_MGR] SearXNG stopped gracefully")
                except subprocess.TimeoutExpired:
                    if force:
                        # Force kill
                        os.killpg(os.getpgid(self._process.pid), signal.SIGKILL)
                        self._process.wait(timeout=5)
                        logger.info(f"[SEARXNG_MGR] SearXNG force killed")
                    else:
                        logger.warning(f"[SEARXNG_MGR] SearXNG did not stop gracefully")
                        return False
            
            self._process = None
            self._started = False
            self._healthy = False
            return True
            
        except Exception as e:
            logger.error(f"[SEARXNG_MGR] Failed to stop SearXNG: {type(e).__name__}: {e}")
            self._process = None
            self._started = False
            self._healthy = False
            return False
    
    async def restart(self) -> bool:
        """Restart the SearXNG instance.
        
        Returns:
            True if restarted successfully, False otherwise
        """
        await self.stop()
        return await self.start()
    
    @asynccontextmanager
    async def session(self) -> AsyncGenerator['SearXNGManager', None]:
        """Context manager for SearXNG session.
        
        Usage:
            async with searxng_manager.session():
                # SearXNG is running and healthy
                results = await provider.search("test")
        """
        await self.start()
        try:
            yield self
        finally:
            await self.stop()


# Global SearXNG manager instance
searxng_manager: Optional[SearXNGManager] = None


def get_searxng_manager() -> SearXNGManager:
    """Get or create the global SearXNG manager instance."""
    global searxng_manager
    if searxng_manager is None:
        searxng_manager = SearXNGManager()
    return searxng_manager


async def start_local_searxng() -> Optional[str]:
    """Start local SearXNG and return its base URL.
    
    Returns:
        Base URL of the SearXNG instance, or None if failed
    """
    manager = get_searxng_manager()
    if await manager.start():
        return manager.base_url
    return None


async def stop_local_searxng() -> bool:
    """Stop local SearXNG.
    
    Returns:
        True if stopped successfully
    """
    manager = get_searxng_manager()
    return await manager.stop()
