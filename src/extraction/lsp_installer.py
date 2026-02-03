"""Automatic LSP server installation utilities."""

import asyncio
import subprocess
import shutil
import sys
from typing import Dict, Optional, Tuple
from pathlib import Path
from src.logging.logging import get_logger

logger = get_logger(__name__)


class LSPInstaller:
    """Handles automatic installation of LSP servers."""
    
    def __init__(self):
        """Initialize the LSP installer."""
        self.available_package_managers = self._detect_package_managers()
        
    def _detect_package_managers(self) -> Dict[str, bool]:
        """Detect which package managers are available on the system."""
        managers = {
            'npm': shutil.which('npm') is not None,
            'pip': shutil.which('pip') is not None or shutil.which('pip3') is not None,
            'go': shutil.which('go') is not None,
            'rustup': shutil.which('rustup') is not None,
            'cargo': shutil.which('cargo') is not None,
            'brew': shutil.which('brew') is not None,
            'apt': shutil.which('apt') is not None,
            'apt-get': shutil.which('apt-get') is not None,
            'dotnet': shutil.which('dotnet') is not None,
        }
        logger.debug(f"Available package managers: {[k for k, v in managers.items() if v]}")
        return managers
    
    def can_install(self, install_command: str) -> bool:
        """Check if we can install a package based on its install command."""
        if not install_command:
            return False
        
        # Check which package manager is needed
        if 'npm install' in install_command:
            return self.available_package_managers.get('npm', False)
        elif 'pip install' in install_command:
            return self.available_package_managers.get('pip', False)
        elif 'go install' in install_command:
            return self.available_package_managers.get('go', False)
        elif 'rustup' in install_command:
            return self.available_package_managers.get('rustup', False)
        elif 'cargo install' in install_command:
            return self.available_package_managers.get('cargo', False)
        elif 'brew install' in install_command:
            return self.available_package_managers.get('brew', False)
        elif 'apt install' in install_command or 'apt-get install' in install_command:
            return self.available_package_managers.get('apt', False) or self.available_package_managers.get('apt-get', False)
        elif 'dotnet tool install' in install_command:
            return self.available_package_managers.get('dotnet', False)
        
        return False
    
    async def install_lsp_server(self, server_name: str, install_command: str, interactive: bool = True) -> Tuple[bool, str]:
        """
        Install an LSP server using the provided install command.
        
        Args:
            server_name: Name of the LSP server
            install_command: Installation command from config
            interactive: Whether to prompt user for confirmation
            
        Returns:
            Tuple of (success: bool, message: str)
        """
        if not self.can_install(install_command):
            return False, f"Cannot auto-install {server_name}: required package manager not available"
        
        # Ask for user confirmation if interactive
        if interactive:
            logger.info(f"📦 LSP server '{server_name}' is not installed.")
            logger.info(f"💡 Would you like to install it automatically?")
            logger.info(f"   Command: {install_command}")
            
            try:
                response = input("Install now? (y/n): ").strip().lower()
                if response not in ['y', 'yes']:
                    return False, "Installation cancelled by user"
            except (EOFError, KeyboardInterrupt):
                return False, "Installation cancelled by user"
        
        # Parse and execute the installation command
        logger.info(f"🔧 Installing {server_name}...")
        
        try:
            # Extract the actual command (remove comments and alternatives)
            cmd = self._parse_install_command(install_command)
            if not cmd:
                return False, f"Could not parse install command: {install_command}"
            
            # Run the installation
            process = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
                logger.info(f"✅ Successfully installed {server_name}")
                return True, f"Successfully installed {server_name}"
            else:
                error_msg = stderr.decode('utf-8', errors='ignore') if stderr else "Unknown error"
                logger.error(f"❌ Failed to install {server_name}: {error_msg}")
                return False, f"Installation failed: {error_msg}"
                
        except Exception as e:
            logger.error(f"❌ Error during installation: {e}")
            return False, f"Installation error: {str(e)}"
    
    def _parse_install_command(self, install_command: str) -> Optional[str]:
        """
        Parse the install command from config, handling comments and alternatives.
        
        Args:
            install_command: Raw install command from config
            
        Returns:
            Cleaned command string or None
        """
        # Remove comments (anything after #)
        cmd = install_command.split('#')[0].strip()
        
        # Handle "or" alternatives - take the first one that's available
        if ' or ' in cmd.lower():
            alternatives = [alt.strip() for alt in cmd.split(' or ')]
            for alt in alternatives:
                # Check if this alternative's package manager is available
                if self.can_install(alt):
                    return alt
            return alternatives[0]  # Fallback to first alternative
        
        # Handle URL-based downloads (not auto-installable)
        if 'http://' in cmd or 'https://' in cmd or 'Download from' in cmd:
            return None
        
        return cmd if cmd else None
    
    def get_pip_command(self) -> str:
        """Get the appropriate pip command (pip or pip3)."""
        if shutil.which('pip3'):
            return 'pip3'
        elif shutil.which('pip'):
            return 'pip'
        else:
            return 'pip'  # Fallback
    
    async def verify_installation(self, command: str) -> bool:
        """
        Verify that an LSP server was successfully installed.
        
        Args:
            command: The command to check (e.g., 'pyright-langserver')
            
        Returns:
            True if command is now available, False otherwise
        """
        return shutil.which(command) is not None
