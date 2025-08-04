"""Unified LSP client supporting both Docker and standalone modes."""

import asyncio
import docker
import json
import os
import chardet
import urllib.parse
from pathlib import Path
from typing import Dict, List, Optional, Any
import traceback
from src.logging.logging import get_logger

logger = get_logger(__name__)


class LSPClient():
    """LSP client that supports both Docker and standalone modes."""
    
    def __init__(self, server_config: Dict[str, Any], request_timeout: float = 20.0, use_docker: bool = False):
        """Initialize the LSP client with configuration and mode."""
        self.server_config = server_config
        self.docker_client = None
        self.request_id = 0
        self.responses = {}
        self.response_events = {}
        self.workspace_path = None
        self.process = None
        self.reader = None
        self.writer = None
        self._is_running = False
        self.request_timeout = request_timeout
        self.server_capabilities = {}
        
        # Determine mode from config or parameter
        if use_docker:
            self.docker_mode = bool(server_config.get("docker_image"))
            if not self.docker_mode:
                logger.warning("Docker mode requested but no docker_image specified in config, using standalone mode")
        else:
            self.docker_mode = False
        
        logger.debug(f"LSP client mode: {'Docker' if self.docker_mode else 'Standalone'}")
        
    async def start_server(self, workspace_root: str) -> bool:
        """Start the LSP server in appropriate mode."""
        self.workspace_path = os.path.abspath(workspace_root)
        
        if self.docker_mode:
            return await self._start_docker_server()
        else:
            return await self._start_standalone_server()
            
    async def _start_docker_server(self) -> bool:
        """Start the LSP server in a Docker container."""
        try:
            # Initialize Docker client for image checking
            self.docker_client = docker.from_env()
            
            # Get configuration
            docker_image = self.server_config.get("docker_image")
            if not docker_image:
                logger.error("❌ No docker_image specified in LSP config")
                return False
                
            logger.info(f"🐳 Starting LSP server container: {docker_image}")
            
            # Ensure the Docker image exists
            try:
                self.docker_client.images.get(docker_image)
                logger.debug(f"✅ Docker image found: {docker_image}")
            except docker.errors.ImageNotFound:
                logger.error(f"❌ Docker image not found: {docker_image}")
                logger.info("💡 Build the image first")
                return False
            
            # Build docker command for stdio communication
            docker_cmd = [
                "docker", "run", 
                "--rm",                                      # Remove container when done
                "-i",                                        # Interactive mode for stdin
                "-v", f"{self.workspace_path}:/workspace",   # Mount workspace
                "-w", "/workspace",                          # Set working directory
                docker_image
            ]
            
            logger.debug(f"🚀 Docker command: {' '.join(docker_cmd)}")
            
            # Start the container process with stdio pipes
            self.process = await asyncio.create_subprocess_exec(
                *docker_cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=1024*1024  # 1MB buffer limit
            )
            
            if not self.process:
                logger.error("❌ Failed to start Docker container process")
                return False
                
            logger.info(f"⚙️ Container process started with PID: {self.process.pid}")
            
            # Check if process is still running after a short delay
            await asyncio.sleep(0.5)
            if self.process.returncode is not None:
                logger.error(f"❌ Container process exited immediately with code: {self.process.returncode}")
                stderr_output = await self.process.stderr.read()
                if stderr_output:
                    logger.error(f"Container stderr: {stderr_output.decode('utf-8', errors='ignore')}")
                return False
            
            # Start background tasks
            self._is_running = True
            asyncio.create_task(self._message_reader_loop())
            asyncio.create_task(self._monitor_stderr())

            # Initialize LSP server
            try:
                logger.info("🔄 Initializing LSP server...")
                workspace_uri = "/workspace" if self.docker_mode else self.workspace_path
                await asyncio.wait_for(self._initialize(workspace_uri), timeout=30.0)
                logger.info("✅ LSP server initialized successfully")
                return True
                
            except asyncio.TimeoutError:
                logger.error("❌ LSP server initialization timed out")
                await self.shutdown()
                return False
                
        except Exception as e:
            logger.error(f"❌ Failed to start Docker LSP server: {e}")
            traceback.print_exc()
            await self.shutdown()
            return False
    
    async def _start_standalone_server(self) -> bool:
        """Start the LSP server as a local process."""
        try:
            cmd = self.server_config.get("command")
            if not cmd:
                logger.error(f"❌ No command specified for LSP server: {self.server_config.get('name', 'unknown')}")
                return False

            if isinstance(cmd, str):
                cmd = cmd.split()

            args = self.server_config.get("args", [])
            if args:
                cmd.extend(args)
            
            # Special handling for certain LSP servers
            if cmd[0] == "jdtls":
                cmd.append(self.workspace_path)
            
            logger.info(f"🚀 Starting LSP server: {' '.join(cmd)}")
            logger.info(f"📁 Working directory: {self.workspace_path}")

            self.process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.workspace_path,
                preexec_fn=None if os.name == 'nt' else os.setsid
            )

            if not self.process or not self.process.stdout or not self.process.stdin:
                logger.error(f"❌ Failed to start LSP server: {self.server_config.get('name', 'unknown')}")
                return False

            logger.debug(f"✅ Process started with PID: {self.process.pid}")

            self.reader = self.process.stdout
            self.writer = self.process.stdin
            
            # Start background tasks
            self._is_running = True
            asyncio.create_task(self._message_reader_loop())
            asyncio.create_task(self._monitor_stderr())
            
            # Initialize LSP server     
            try:
                logger.debug("🔄 Initializing LSP server...")
                await asyncio.wait_for(self._initialize(self.workspace_path), timeout=30.0)
                logger.info("✅ LSP server started successfully")
                return True
                    
            except asyncio.TimeoutError:
                logger.error("❌ LSP server initialization timed out")
                await self.shutdown()
                return False
            
        except FileNotFoundError:
            logger.error(f"❌ LSP server executable not found: {cmd[0] if cmd else 'unknown'}")
            return False
        except Exception as e:
            logger.error(f"❌ Failed to start LSP server: {e}")
            traceback.print_exc()
            return False

    async def shutdown(self):
        """Shutdown the LSP server and clean up resources."""
        if not self._is_running:
            return
        
        self._is_running = False
        
        try:
            # Send LSP shutdown sequence
            if self.process and ((self.docker_mode and self.process.stdin and not self.process.stdin.is_closing()) or 
                               (not self.docker_mode and self.writer and not self.writer.is_closing())):
                try:
                    await asyncio.wait_for(self._send_request("shutdown", {}), timeout=5.0)
                    await self._send_notification("exit", {})
                except:
                    pass  # Ignore shutdown errors
            
            # Terminate the process
            if self.process:
                self.process.terminate()
                try:
                    await asyncio.wait_for(self.process.wait(), timeout=5.0)
                    logger.debug("Process terminated gracefully")
                except asyncio.TimeoutError:
                    logger.warning("Process didn't stop gracefully, killing...")
                    self.process.kill()
                    await self.process.wait()
                
                self.process = None
            
            # Clean up mode-specific resources
            if self.docker_mode and self.docker_client:
                self.docker_client.close()
                self.docker_client = None
            elif not self.docker_mode and self.writer:
                self.writer.close()
                try:
                    await self.writer.wait_closed()
                except:
                    pass
                self.writer = None
                self.reader = None
            
            # Clear state
            self.responses.clear()
            self.response_events.clear()
            self.request_id = 0

            logger.info("✅ LSP client shutdown complete")

        except Exception as e:
            logger.error(f"Error during shutdown: {e}")

    async def _monitor_stderr(self):
        """Monitor stderr from the LSP server for error messages."""
        if not self.process or not self.process.stderr:
            return
            
        try:
            while self._is_running and self.process:
                try:
                    line = await asyncio.wait_for(
                        self.process.stderr.readline(), 
                        timeout=1.0
                    )
                    if not line:
                        break
                        
                    error_text = line.decode('utf-8', errors='ignore').strip()
                    if error_text:
                        # Filter out common noise
                        if any(noise in error_text.lower() for noise in [
                            'deprecation', 'warning:', 'info:'
                        ]):
                            logger.debug(f"LSP: {error_text}")
                        elif any(error in error_text.lower() for error in [
                            'error', 'exception', 'failed', 'fatal'
                        ]):
                            logger.warning(f"LSP error: {error_text}")
                        else:
                            logger.debug(f"LSP: {error_text}")
                            
                except asyncio.TimeoutError:
                    continue  # No stderr output, continue monitoring
                    
        except Exception as e:
            logger.debug(f"Error monitoring stderr: {e}")

    async def _message_reader_loop(self):
        """Read LSP messages from server stdout."""
        try:
            while self._is_running and self.process:
                try:
                    message = await self._read_lsp_message()
                    if message is None:
                        if self._is_running:
                            logger.debug("No more messages from server")
                        break
                        
                    await self._handle_lsp_message(message)
                    
                except Exception as e:
                    if self._is_running:
                        logger.error(f"Error in message reader: {e}")
                    break
                    
        except Exception as e:
            logger.error(f"Error in message reader loop: {e}")
        finally:
            logger.debug("Message reader loop stopped")
    
    async def _read_lsp_message(self) -> Optional[Dict]:
        """Read a complete LSP message from server stdout."""
        try:
            # Read headers
            headers = {}
            while True:
                if self.docker_mode:
                    line = await self.process.stdout.readline()
                else:
                    line = await self.reader.readline()
                    
                if not line:
                    return None
                    
                header_line = line.decode('utf-8').strip()
                if not header_line:  # Empty line = end of headers
                    break
                    
                if ':' in header_line:
                    key, value = header_line.split(':', 1)
                    headers[key.strip().lower()] = value.strip()
            
            # Get content length
            content_length = int(headers.get('content-length', 0))
            if content_length <= 0:
                logger.warning(f"Invalid content length: {content_length}")
                return None
            
            # Read the JSON content
            if self.docker_mode:
                content_bytes = await self.process.stdout.readexactly(content_length)
            else:
                # For standalone mode, read in chunks to ensure we get all data
                content_bytes = b''
                bytes_to_read = content_length
                
                while bytes_to_read > 0:
                    chunk = await self.reader.read(bytes_to_read)
                    if not chunk:
                        break
                    content_bytes += chunk
                    bytes_to_read -= len(chunk)
                
                if len(content_bytes) < content_length:
                    logger.warning(f"Incomplete read: got {len(content_bytes)}/{content_length} bytes")
                    return None
            
            content = content_bytes.decode('utf-8')
            
            # Parse JSON message
            message = json.loads(content)
            logger.debug(f"📨 Received: {message.get('method', f'response-{message.get('id', '?')}')}")
            return message
            
        except asyncio.IncompleteReadError:
            logger.debug("Incomplete read from server (server may be shutting down)")
            return None
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LSP message JSON: {e}")
            return None
        except Exception as e:
            logger.error(f"Error reading LSP message: {e}")
            return None
    
    async def _handle_lsp_message(self, message: Dict):
        """Handle incoming LSP message (response or notification)."""
        try:
            # Handle responses to our requests
            if "id" in message and ("result" in message or "error" in message):
                request_id = message["id"]
                self.responses[request_id] = message
                
                # Wake up waiting request
                if request_id in self.response_events:
                    self.response_events[request_id].set()
            
            # Handle server notifications
            elif "method" in message:
                await self._handle_server_notification(message)
                
        except Exception as e:
            logger.error(f"Error handling LSP message: {e}")
    
    async def _handle_server_notification(self, message: Dict):
        """Handle notifications from the LSP server."""
        method = message['method']
        params = message.get('params', {})
        
        if method == "window/logMessage":
            log_type = params.get('type', 1)  # 1=Error, 2=Warning, 3=Info, 4=Log
            log_message = params.get('message', '')
            
            # Filter common noise
            if 'didOpen' in log_message and 'is still open' in log_message:
                logger.debug(f"LSP: {log_message}")
            elif log_type == 1:  # Error
                logger.warning(f"LSP Error: {log_message}")
            elif log_type == 2:  # Warning
                logger.debug(f"LSP Warning: {log_message}")
            else:  # Info/Log
                logger.debug(f"LSP: {log_message}")
                
        elif method == "window/showMessage":
            message_type = params.get('type', 3)
            show_message = params.get('message', '')
            
            if message_type <= 2:  # Error or Warning
                logger.warning(f"LSP: {show_message}")
            else:
                logger.debug(f"LSP: {show_message}")
        else:
            logger.debug(f"📥 Server notification: {method}")
    
    async def _write_lsp_message(self, message: Dict):
        """Write an LSP message to server stdin."""
        if self.docker_mode:
            if not self.process or not self.process.stdin or self.process.stdin.is_closing():
                raise Exception("Container stdin not available")
        else:
            if not self.writer or self.writer.is_closing():
                raise Exception("Process stdin not available")
            
        try:
            # Serialize message
            content = json.dumps(message, separators=(',', ':'))
            content_bytes = content.encode('utf-8')
            
            # Build LSP message with headers
            header = f"Content-Length: {len(content_bytes)}\r\n\r\n"
            full_message = header.encode('utf-8') + content_bytes
            
            # Send to process
            if self.docker_mode:
                self.process.stdin.write(full_message)
                await self.process.stdin.drain()
            else:
                self.writer.write(full_message)
                await self.writer.drain()
            
            logger.debug(f"📤 Sent: {message.get('method', f'response-{message.get('id', '?')}')}")
            
        except Exception as e:
            logger.error(f"Error writing to server stdin: {e}")
            raise
    
    async def _send_request(self, method: str, params: Any, timeout: Optional[float] = None) -> Any:
        """Send a request to the LSP server and wait for response."""
        self.request_id += 1
        request_id = self.request_id

        request = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params
        }

        # Create event for response
        event = asyncio.Event()
        self.response_events[request_id] = event

        try:
            await self._write_lsp_message(request)

            # Use appropriate timeout for different operations
            if timeout is None:
                if method in ['textDocument/documentSymbol', 'textDocument/references']:
                    timeout = 60.0
                else:
                    timeout = self.request_timeout

            # Wait for response
            await asyncio.wait_for(event.wait(), timeout=timeout)
            
            response = self.responses.pop(request_id, None)
            if response and "error" in response:
                error = response["error"]
                logger.error(f"LSP error for {method}: {error}")
                return None
                
            return response.get("result") if response else None
            
        except asyncio.TimeoutError:
            logger.error(f"❌ LSP request '{method}' timed out after {timeout}s")
            return None
        finally:
            # Clean up
            self.response_events.pop(request_id, None)
            self.responses.pop(request_id, None)
    
    async def _send_notification(self, method: str, params: Any):
        """Send a notification to the LSP server."""
        notification = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params
        }
        await self._write_lsp_message(notification)

    async def _initialize(self, workspace_root: str):
        """Initialize the LSP server."""
        # Determine the correct root URI based on mode
        if self.docker_mode:
            root_uri = f"file://{workspace_root}"
        else:
            root_uri = Path(workspace_root).as_uri()
            
        init_params = {
            "processId": None,
            "rootPath": workspace_root,
            "rootUri": root_uri,
            "capabilities": {
                "textDocument": {
                    "documentSymbol": {
                        "hierarchicalDocumentSymbolSupport": True,
                        "symbolKind": {"valueSet": list(range(1, 27))}
                    },
                    "definition": {"linkSupport": True},
                    "references": {"dynamicRegistration": False}
                },
                "workspace": {
                    "symbol": {
                        "symbolKind": {"valueSet": list(range(1, 27))}
                    }
                }
            },
            "initializationOptions": self.server_config.get("initializationOptions", {
                "settings": {
                    "python": {
                        "analysis": {
                            "autoSearchPaths": True,
                            "diagnosticMode": "workspace",
                            "useLibraryCodeForTypes": True
                        }
                    }
                }
            })
        }
        
        result = await self._send_request("initialize", init_params)
        if result and "capabilities" in result:
            self.server_capabilities = result["capabilities"]
            
            # Log capabilities
            logger.debug("=== LSP Server Capabilities ===")
            caps = self.server_capabilities
            logger.debug(f"📄 Document Symbols: {'✅' if caps.get('documentSymbolProvider') else '❌'}")
            logger.debug(f"📚 Definitions: {'✅' if caps.get('definitionProvider') else '❌'}")
            logger.debug(f"🔍 References: {'✅' if caps.get('referencesProvider') else '❌'}")
            logger.debug("=== End Capabilities ===")

        await self._send_notification("initialized", {})
        return result

    # ================ LSP Operations ================

    async def get_document_symbols(self, file_path: str, symbol_kind_list: Optional[List[int]] = None, timeout: Optional[float] = None) -> Optional[List[Dict]]:
        """Get document symbols for a file."""
        try:
            file_uri = self._get_file_uri(file_path)
            params = {"textDocument": {"uri": file_uri}}
            
            result = await self._send_request("textDocument/documentSymbol", params, timeout=timeout)
            
            if not result:
                return []
            
            if symbol_kind_list:
                return self._filter_symbols_by_kind(result, symbol_kind_list)
            
            return result
            
        except Exception as e:
            logger.error(f"Document symbols failed for {file_path}: {e}")
            return None
    
    async def get_references(self, file_path: str, line: int, character: int, include_declaration: bool = True, timeout: Optional[float] = None) -> Optional[List[Dict]]:
        """Get all references to a symbol at a specific position."""
        try:
            file_uri = self._get_file_uri(file_path)
            params = {
                "textDocument": {"uri": file_uri},
                "position": {"line": line, "character": character},
                "context": {"includeDeclaration": include_declaration}
            }
            return await self._send_request("textDocument/references", params, timeout=timeout)
        except Exception as e:
            logger.error(f"Get references failed: {e}")
            return None
    
    async def get_definition(self, file_path: str, line: int, character: int, timeout: Optional[float] = None) -> Optional[List[Dict]]:
        """Get definitions for a symbol at a specific position."""
        try:
            file_uri = self._get_file_uri(file_path)
            params = {
                "textDocument": {"uri": file_uri},
                "position": {"line": line, "character": character}
            }
            return await self._send_request("textDocument/definition", params, timeout=timeout)
        except Exception as e:
            logger.error(f"Get definition failed: {e}")
            return None
    
    async def did_open_file(self, file_path: str, language_id: Optional[str] = None) -> bool:
        """Notify LSP server that a file has been opened."""
        try:
            if not Path(file_path).exists():
                logger.error(f"File does not exist: {file_path}")
                return False
                
            file_uri = self._get_file_uri(file_path)
            content = self._read_file_as_utf8(file_path)
            
            lang_id = (
                language_id or 
                self.server_config.get("languageId") or 
                self.server_config.get("language_id") or 
                "plaintext"
            )
            
            params = {
                "textDocument": {
                    "uri": file_uri,
                    "languageId": lang_id,
                    "version": 1,
                    "text": content
                }
            }
            
            await self._send_notification("textDocument/didOpen", params)
            logger.debug(f"✅ File opened successfully: {Path(file_path).name}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to open file {file_path}: {e}")
            return False

    # ================ Helper Methods ================

    def _get_file_uri(self, file_path: str) -> str:
        """Get file URI based on current mode."""
        if self.docker_mode:
            return self._get_docker_file_uri(file_path)
        else:
            return self._get_standalone_file_uri(file_path)

    def _get_docker_file_uri(self, file_path: str) -> str:
        """Convert local file path to container file URI."""
        if file_path.startswith("/workspace/"):
            return f"file://{file_path}"

        abs_workspace = os.path.abspath(self.workspace_path)
        abs_file = os.path.abspath(file_path)
        
        try:
            rel_path = os.path.relpath(abs_file, abs_workspace)
            container_path = "/workspace/" + rel_path.replace("\\", "/")
            return f"file://{container_path}"
        except ValueError:
            # Files outside workspace
            logger.warning(f"File outside workspace: {file_path}")
            return f"file://{file_path}"

    def _get_standalone_file_uri(self, file_path: str) -> str:
        """Convert local file path to file URI for standalone mode."""
        return Path(file_path).absolute().as_uri()

    def _read_file_as_utf8(self, file_path: str) -> str:
        """Read file content as UTF-8."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return f.read()
        except UnicodeDecodeError:
            # Auto-detect encoding and convert
            with open(file_path, 'rb') as f:
                raw_data = f.read()
                detected = chardet.detect(raw_data)
                encoding = detected.get('encoding', 'utf-8')
            
            return raw_data.decode(encoding, errors='replace')

    def _filter_symbols_by_kind(self, symbols: List[Dict], wanted_kinds: List[int]) -> List[Dict]:
        """Recursively filter symbols and their children by kind."""
        if not wanted_kinds:
            return symbols
        
        filtered = []
        
        for symbol in symbols:
            if not isinstance(symbol, dict):
                continue
            
            symbol_kind = symbol.get('kind', 0)
            symbol_name = symbol.get('name', 'unknown')
            
            # First recursively filter children - this will only include children that match wanted_kinds
            filtered_children = []
            if 'children' in symbol and symbol['children']:
                filtered_children = self._filter_symbols_by_kind(symbol['children'], wanted_kinds)
            
            # Include if THIS symbol matches OR has matching children
            if symbol_kind in wanted_kinds or filtered_children:
                # Create a copy to avoid modifying original
                filtered_symbol = symbol.copy()
                
                # Always set children to the filtered list (could be empty)
                # This ensures we only include children that are in wanted_kinds
                if 'children' in symbol:  # Only if original had children
                    if filtered_children:
                        filtered_symbol['children'] = filtered_children
                    else:
                        # Remove children key if no children passed the filter
                        del filtered_symbol['children']
                        
                filtered.append(filtered_symbol)
                logger.debug(f"✅ Included symbol: {symbol_name} (kind: {symbol_kind})")
            else:
                logger.debug(f"❌ Filtered out symbol: {symbol_name} (kind: {symbol_kind})")
        
        return filtered

    @property
    def is_running(self) -> bool:
        """Check if the LSP server is running."""
        return self._is_running and self.process is not None