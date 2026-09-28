#!/usr/bin/env python3
"""Setup script for local SearXNG instance.

This script:
1. Checks if atis-searxng repository is cloned
2. If not, clones it from GitHub
3. Sets up virtual environment
4. Installs SearXNG
5. Configures settings.yml for local use
6. Creates startup scripts

Usage:
    python scripts/setup_searxng.py
    
Environment variables:
    SEARXNG_REPO_URL: GitHub URL for atis-searxng (default: https://github.com/tmakiriyado1-arch/atis-searxng)
    SEARXNG_TARGET_PATH: Where to clone the repo (default: /workspace/github__tmakiriyado1-arch__atis-searxng)
    SEARXNG_PORT: Port to configure (default: 8888)
    SEARXNG_HOST: Host to bind to (default: 127.0.0.1)
"""
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional


class SearXNGSetup:
    """Setup local SearXNG instance."""
    
    def __init__(
        self,
        repo_url: str = "https://github.com/tmakiriyado1-arch/atis-searxng",
        target_path: str = "/workspace/github__tmakiriyado1-arch__atis-searxng",
        port: int = 8888,
        host: str = "127.0.0.1",
    ) -> None:
        self.repo_url = repo_url
        self.target_path = Path(target_path)
        self.port = port
        self.host = host
    
    def run(self) -> bool:
        """Run the full setup process."""
        print("=" * 80)
        print("Setting up local SearXNG instance")
        print("=" * 80)
        
        steps = [
            ("Check dependencies", self.check_dependencies),
            ("Clone repository", self.clone_repo),
            ("Setup virtual environment", self.setup_venv),
            ("Install SearXNG", self.install_searxng),
            ("Configure settings", self.configure_settings),
            ("Create startup script", self.create_startup_script),
            ("Verify installation", self.verify_installation),
        ]
        
        for step_name, step_func in steps:
            print(f"\n[ ] {step_name}...")
            try:
                if step_func():
                    print(f"[✓] {step_name} - Success")
                else:
                    print(f"[✗] {step_name} - Failed")
                    return False
            except Exception as e:
                print(f"[✗] {step_name} - Error: {e}")
                return False
        
        print("\n" + "=" * 80)
        print("SearXNG setup completed successfully!")
        print("=" * 80)
        print(f"\nRepository: {self.target_path}")
        print(f"Port: {self.port}")
        print(f"Host: {self.host}")
        print(f"\nTo start SearXNG:")
        print(f"  cd {self.target_path}")
        print(f"  ./scripts/start.sh")
        print(f"\nOr use the manager:")
        print(f"  from app.services.research.searxng_manager import start_local_searxng")
        print(f"  asyncio.run(start_local_searxng())")
        return True
    
    def check_dependencies(self) -> bool:
        """Check that required dependencies are installed."""
        required = ["git", "python3", "pip"]
        missing = []
        
        for cmd in required:
            try:
                result = subprocess.run(
                    [cmd, "--version"],
                    capture_output=True, text=True, timeout=5
                )
                if result.returncode != 0:
                    missing.append(cmd)
            except FileNotFoundError:
                missing.append(cmd)
        
        if missing:
            print(f"Missing dependencies: {', '.join(missing)}")
            return False
        
        # Check Python version
        result = subprocess.run(
            ["python3", "--version"],
            capture_output=True, text=True, timeout=5
        )
        version_str = result.stdout.strip()
        print(f"  Python version: {version_str}")
        
        # Parse version
        version = version_str.replace("Python ", "").split(".")
        major, minor = int(version[0]), int(version[1])
        if major < 3 or (major == 3 and minor < 10):
            print(f"  Error: Requires Python 3.10+, found {version_str}")
            return False
        
        return True
    
    def clone_repo(self) -> bool:
        """Clone the atis-searxng repository."""
        if self.target_path.exists():
            # Check if it's already a git repo with the right remote
            git_dir = self.target_path / ".git"
            if git_dir.exists():
                # Check remote URL
                result = subprocess.run(
                    ["git", "-C", str(self.target_path), "remote", "get-url", "origin"],
                    capture_output=True, text=True, timeout=5
                )
                if result.returncode == 0 and self.repo_url in result.stdout:
                    print(f"  Repository already cloned at {self.target_path}")
                    # Pull latest changes
                    subprocess.run(
                        ["git", "-C", str(self.target_path), "pull"],
                        capture_output=True, text=True, timeout=10
                    )
                    return True
        
        print(f"  Cloning {self.repo_url} to {self.target_path}")
        result = subprocess.run(
            ["git", "clone", self.repo_url, str(self.target_path)],
            capture_output=True, text=True, timeout=60
        )
        
        if result.returncode != 0:
            print(f"  Error: {result.stderr}")
            return False
        
        return True
    
    def setup_venv(self) -> bool:
        """Setup Python virtual environment."""
        venv_path = self.target_path / ".venv"
        
        if venv_path.exists():
            print(f"  Virtual environment already exists at {venv_path}")
            return True
        
        print(f"  Creating virtual environment at {venv_path}")
        result = subprocess.run(
            ["python3", "-m", "venv", str(venv_path)],
            cwd=self.target_path,
            capture_output=True, text=True, timeout=60
        )
        
        if result.returncode != 0:
            print(f"  Error: {result.stderr}")
            return False
        
        return True
    
    def install_searxng(self) -> bool:
        """Install SearXNG in the virtual environment."""
        venv_path = self.target_path / ".venv"
        pip_path = venv_path / "bin" / "pip"
        
        if not pip_path.exists():
            # Try alternative path for some systems
            pip_path = venv_path / "bin" / "pip3"
        
        if not pip_path.exists():
            print(f"  Error: pip not found in venv at {venv_path}")
            return False
        
        print(f"  Installing SearXNG using {pip_path}")
        
        # Install from source (editable mode)
        result = subprocess.run(
            [str(pip_path), "install", "-e", "."],
            cwd=self.target_path,
            capture_output=True, text=True, timeout=120
        )
        
        if result.returncode != 0:
            print(f"  Error: {result.stderr}")
            # Try alternative: install from requirements.txt
            req_file = self.target_path / "requirements.txt"
            if req_file.exists():
                result = subprocess.run(
                    [str(pip_path), "install", "-r", str(req_file)],
                    cwd=self.target_path,
                    capture_output=True, text=True, timeout=120
                )
                if result.returncode != 0:
                    print(f"  Error: {result.stderr}")
                    return False
            else:
                return False
        
        return True
    
    def configure_settings(self) -> bool:
        """Configure settings.yml for local use."""
        settings_path = self.target_path / "settings.yml"
        
        if not settings_path.exists():
            print(f"  Error: settings.yml not found at {settings_path}")
            return False
        
        print(f"  Configuring {settings_path}")
        
        # Read current settings
        with open(settings_path, 'r') as f:
            content = f.read()
        
        original = content
        
        # Update settings for local use
        changes = {
            'bind_address: "0.0.0.0"': f'bind_address: "{self.host}"',
            'bind_address: 0.0.0.0': f'bind_address: {self.host}',
            'port: 8888': f'port: {self.port}',
        }
        
        for old, new in changes.items():
            if old in content:
                content = content.replace(old, new)
                print(f"  Changed: {old} -> {new}")
        
        # Ensure JSON format is enabled
        if 'search.formats' not in content:
            content += "\nsearch.formats: [\"html\", \"json\"]\n"
            print(f"  Added: search.formats for JSON support")
        
        # Ensure GET method is enabled
        if 'server.method' not in content:
            content += "\nserver.method: \"GET\"\n"
            print(f"  Added: server.method for GET requests")
        
        # Ensure limiter is disabled
        if 'server.limiter' not in content:
            content += "\nserver.limiter: false\n"
            print(f"  Added: server.limiter disabled")
        
        # Write back if changed
        if content != original:
            with open(settings_path, 'w') as f:
                f.write(content)
            print(f"  Settings updated")
        else:
            print(f"  Settings already configured")
        
        return True
    
    def create_startup_script(self) -> bool:
        """Create startup script for SearXNG."""
        scripts_dir = self.target_path / "scripts"
        scripts_dir.mkdir(exist_ok=True)
        
        start_script = scripts_dir / "start.sh"
        
        # Create start.sh
        start_script_content = f"""#!/bin/bash
# Start script for SearXNG
# Generated by NORA setup

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV_PATH="$REPO_DIR/.venv"

if [ -d "$VENV_PATH" ]; then
    source "$VENV_PATH/bin/activate"
fi

export SEARXNG_PORT={self.port}
export SEARXNG_BIND_ADDRESS={self.host}

echo "Starting SearXNG on $SEARXNG_BIND_ADDRESS:$SEARXNG_PORT"
echo "Repository: $REPO_DIR"
echo "Press Ctrl+C to stop"

cd "$REPO_DIR"

# Check if searxng is installed
if python3 -c "import searx" 2>/dev/null; then
    exec python3 -m searx.webapp run
else
    echo "Error: SearXNG not installed. Run setup.sh first."
    exit 1
fi
"""
        
        with open(start_script, 'w') as f:
            f.write(start_script_content)
        
        # Make executable
        os.chmod(start_script, 0o755)
        
        print(f"  Created {start_script}")
        
        # Also create a simple Python startup script
        python_start = scripts_dir / "start.py"
        python_start_content = f"""#!/usr/bin/env python3
import os
import sys

# Set up paths
repo_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
venv_path = os.path.join(repo_dir, ".venv")

# Activate venv if it exists
if os.path.exists(venv_path):
    python_path = os.path.join(venv_path, "bin", "python3")
    if os.path.exists(python_path):
        os.execv(python_path, [python_path] + sys.argv)

# Set environment
os.environ['SEARXNG_PORT'] = '{self.port}'
os.environ['SEARXNG_BIND_ADDRESS'] = '{self.host}'

# Change to repo directory
os.chdir(repo_dir)

# Start SearXNG
from searx.webapp import run
run()
"""
        
        with open(python_start, 'w') as f:
            f.write(python_start_content)
        
        os.chmod(python_start, 0o755)
        
        print(f"  Created {python_start}")
        
        return True
    
    def verify_installation(self) -> bool:
        """Verify that SearXNG is installed correctly."""
        venv_path = self.target_path / ".venv"
        python_path = venv_path / "bin" / "python3"
        
        if not python_path.exists():
            python_path = venv_path / "bin" / "python"
        
        if not python_path.exists():
            print(f"  Warning: Python not found in venv, trying system python3")
            python_path = Path("/usr/bin/python3")
        
        print(f"  Verifying installation with {python_path}")
        
        # Check if searxng can be imported
        result = subprocess.run(
            [str(python_path), "-c", "import searx; print('SearXNG version:', searx.__version__)"],
            cwd=self.target_path,
            capture_output=True, text=True, timeout=10
        )
        
        if result.returncode == 0:
            print(f"  {result.stdout.strip()}")
            return True
        else:
            print(f"  Error: {result.stderr}")
            # Try without venv
            result = subprocess.run(
                ["python3", "-c", "import searx; print('SearXNG version:', searx.__version__)"],
                cwd=self.target_path,
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                print(f"  {result.stdout.strip()}")
                return True
            else:
                print(f"  Error: {result.stderr}")
                return False


def main():
    """Main entry point."""
    # Get configuration from environment
    repo_url = os.getenv("SEARXNG_REPO_URL", "https://github.com/tmakiriyado1-arch/atis-searxng")
    target_path = os.getenv("SEARXNG_TARGET_PATH", "/workspace/github__tmakiriyado1-arch__atis-searxng")
    port = int(os.getenv("SEARXNG_PORT", "8888"))
    host = os.getenv("SEARXNG_HOST", "127.0.0.1")
    
    setup = SearXNGSetup(
        repo_url=repo_url,
        target_path=target_path,
        port=port,
        host=host,
    )
    
    success = setup.run()
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
