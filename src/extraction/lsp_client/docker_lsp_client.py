"""Docker-based LSP client for containerized language servers."""

import asyncio
import docker
import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Any
import traceback
from .abstract_client import BaseLSPClient
from src.logging.logging import get_logger

logger = get_logger(__name__)


class DockerLSPClient(BaseLSPClient):
    """LSP client that communicates with containerized language servers."""
    
    def __init__(self, server_config: Dict[str, Any], request_timeout: float = 20.0):
        self.server_config = server_config
        self.container = None
        self.docker_client = None
        self.request_id = 0
        self.responses = {}
        self.response_events = {}
        self.workspace_path = None
        self.process = None
        self._is_running = False
        self.request_timeout = request_timeout  # Default timeout for requests

    async def start_server(self, workspace_root: str) -> bool:
        """Start the LSP server in a Docker container."""
        try:
            # Initialize Docker client
            self.docker_client = docker.from_env()
            self.workspace_path = workspace_root
            
            # Get configuration
            docker_image = self.server_config.get("docker_image")
            if not docker_image:
                logger.error("❌ No docker_image specified in LSP config")
                return False
                
            logger.info(f"🐳 Starting LSP server container: {docker_image}")
            
            # Ensure the Docker image exists
            try:
                self.docker_client.images.get(docker_image)
            except docker.errors.ImageNotFound:
                logger.error(f"❌ Docker image not found: {docker_image}")
                logger.info("💡 Try running: docker/build-lsp-images.sh")
                return False
            
            # Use docker run with interactive mode and stdin/stdout pipes
            docker_cmd = [
                "docker", "run", "--rm", "-i", 
                "-v", f"{os.path.abspath(workspace_root)}:/workspace",
                "-w", "/workspace",
                docker_image
            ]
            
            # Add any command arguments specified in config
            args = self.server_config.get("args", [])
            if args:
                docker_cmd.extend(args)
                logger.info(f"📝 Added container arguments: {args}")
            
            logger.info(f"🚀 Running Docker command: {' '.join(docker_cmd)}")
            
            # Start the container process
            self.process = await asyncio.create_subprocess_exec(
                *docker_cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            if not self.process:
                logger.error("❌ Failed to start Docker container process")
                return False
                
            logger.info(f"⚙️ Container process started with PID: {self.process.pid}")
            
            # Start message processing
            self._is_running = True
            asyncio.create_task(self._message_reader_loop())
            
            # Start monitoring stderr for error messages
            asyncio.create_task(self._monitor_stderr())

            # Initialize LSP
            try:
                logger.info("🔄 Initializing LSP server...")
                await asyncio.wait_for(self._initialize("/workspace"), timeout=30.0)
                logger.info(f"✅ LSP server initialized successfully")
                return True
                
            except asyncio.TimeoutError:
                logger.error("❌ LSP server initialization timed out")
                await self.shutdown()
                return False
                
        except Exception as e:
            logger.error(f"❌ Failed to start Docker LSP server: {e}")
            traceback.print_exc()
            return False
    
    async def _monitor_stderr(self):
        """Monitor stderr from the Docker container process for error messages."""
        if not self.process or not self.process.stderr:
            return
        try:
            while self.is_running:
                line = await self.process.stderr.readline()
                if not line:
                    break
                error_text = line.decode('utf-8', errors='ignore').strip()
                if error_text:
                    logger.debug(f"Docker LSP stderr: {error_text}")
                    # Log important messages at higher level
                    if any(keyword in error_text.lower() for keyword in ['error', 'exception', 'failed']):
                        logger.warning(f"Docker LSP error: {error_text}")
        except Exception as e:
            logger.debug(f"Error monitoring Docker stderr: {e}")

    async def shutdown(self):
        """Shutdown the LSP server and clean up."""
        try:
            self._is_running = False
            
            if self.process:
                logger.info("🛑 Stopping Docker container process...")
                try:
                    # Send shutdown request first
                    if self.process.stdin and not self.process.stdin.is_closing():
                        await self._send_request("shutdown", {})
                        await self._send_notification("exit", {})
                except:
                    pass  # Ignore errors during shutdown
                
                # Terminate process
                self.process.terminate()
                try:
                    await asyncio.wait_for(self.process.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    logger.warning("Container process didn't stop gracefully, killing...")
                    self.process.kill()
                    
                self.process = None
                
            if self.docker_client:
                self.docker_client.close()
            
            self.container.kill()
            logger.info("✅ Docker LSP client shutdown complete.")
            self.container.remove(force=True)
            logger.info("✅ Docker container removed.")
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")
        finally:
            self._is_running = False
            self.container = None
            self.docker_client = None
            self.request_id = 0
            self.responses.clear()
            self.response_events.clear()
            logger.info("Docker LSP client shutdown complete.")

    async def _message_reader_loop(self):
        """Read messages from the Docker container process."""
        try:
            while self.is_running and self.process:
                try:
                    # Read message from container stdout
                    message = await self._read_message()
                    if message is None:
                        break
                        
                    # Handle LSP message
                    await self._handle_message(message)
                    
                except Exception as e:
                    if self.is_running:
                        logger.error(f"Error reading from container: {e}")
                    break
                    
        except Exception as e:
            logger.error(f"Error in Docker message reader loop: {e}")
        finally:
            logger.debug("Docker message reader loop stopped.")
    
    async def _read_message(self) -> Optional[Dict]:
        """Read a complete LSP message from container stdout."""
        try:
            if not self.process or not self.process.stdout:
                return None
                
            # Read headers
            headers = {}
            while True:
                line = await self.process.stdout.readline()
                if not line:
                    logger.debug("No more data from container")
                    return None
                    
                header = line.decode('utf-8').strip()
                if not header:  # Empty line marks end of headers
                    break
                    
                if ':' in header:
                    key, value = header.split(':', 1)
                    headers[key.strip().lower()] = value.strip()
            
            # Get content length
            content_length = int(headers.get('content-length', 0))
            if content_length <= 0:
                logger.warning(f"Invalid content length: {content_length}")
                return None
            
            # Read content with retry logic for partial reads
            content_bytes = b""
            remaining = content_length
            
            while remaining > 0:
                chunk = await self.process.stdout.read(remaining)
                if not chunk:
                    logger.error(f"Unexpected EOF. Expected {content_length} bytes, got {len(content_bytes)}")
                    return None
                content_bytes += chunk
                remaining -= len(chunk)
            
            if len(content_bytes) != content_length:
                logger.error(f"Expected {content_length} bytes, got {len(content_bytes)}")
                return None
                
            # Parse JSON
            content = content_bytes.decode('utf-8')
            message = json.loads(content)
            
            logger.debug(f"Received LSP message: {message.get('method', 'response')}")
            return message
            
        except Exception as e:
            logger.error(f"Error reading LSP message: {e}")
            return None
    
    async def _handle_message(self, message: Dict):
        """Handle incoming LSP message."""
        try:
            if "id" in message and "result" in message:
                # Response to our request
                request_id = message["id"]
                self.responses[request_id] = message

                # Signal waiting request
                if request_id in self.response_events:
                    self.response_events[request_id].set()

            elif "method" in message:
                # Notification or request from server
                method = message['method']
                params = message.get('params', {})

                # Handle standard LSP log messages
                if method == "window/logMessage":
                    log_message = params.get('message', '')
                    log_type = params.get('type', 1)  # 1=Error, 2=Warning, 3=Info, 4=Log

                    if log_type == 1:
                        logger.error(f"LSP: {log_message}")
                    elif log_type == 2:
                        logger.debug(f"LSP: {log_message}")
                    elif log_type == 3:
                        logger.debug(f"LSP: {log_message}")
                    else:
                        logger.debug(f"LSP: {log_message}")

                elif method == "window/showMessage":
                    show_message = params.get('message', '')
                    message_type = params.get('type', 3)  # 1=Error, 2=Warning, 3=Info, 4=Log

                    if message_type == 1:
                        logger.error(f"LSP: {show_message}")
                    elif message_type == 2:
                        logger.debug(f"LSP: {show_message}")
                    elif message_type == 3:
                        logger.debug(f"LSP: {show_message}")
                    else:
                        logger.debug(f"LSP: {show_message}")

                else:
                    logger.debug(f"Received notification: {method}")

        except Exception as e:
            logger.error(f"Error handling message: {e}")
    
    async def _write_message(self, message: Dict):
        """Write a message to the Docker container."""
        try:
            if not self.process or not self.process.stdin:
                logger.error("No process stdin available")
                return
                
            content = json.dumps(message)
            header = f"Content-Length: {len(content)}\r\n\r\n"
            full_message = header + content
            
            # Send to container
            self.process.stdin.write(full_message.encode('utf-8'))
            await self.process.stdin.drain()
            
            logger.debug(f"Sent LSP message: {message.get('method', 'response-' + str(message.get('id', '?')))}")
            
        except Exception as e:
            logger.error(f"Error writing message to container: {e}")
    
    async def _initialize(self, workspace_root: str):
        """Initialize the LSP server."""
        init_params = {
            "processId": None,
            "rootPath": workspace_root,
            "rootUri": f"file://{workspace_root}",
             "capabilities": {
                "textDocument": {
                    "documentSymbol": {
                        "hierarchicalDocumentSymbolSupport": True,
                        "symbolKind": {
                            "valueSet": list(range(1, 27))
                        }
                    },
                    "gotoDefinition": {
                        "linkSupport": True
                    }
                },
                "workspace": {
                    "symbol": {
                        "symbolKind": {
                            "valueSet": list(range(1, 27))
                        }
                    }
                }
            },
            # 🔧 Add initialization options for pyright
            "initializationOptions": {
                "settings": {
                    "python": {
                        "analysis": {
                            "autoSearchPaths": True,
                            "diagnosticMode": "workspace",
                            "useLibraryCodeForTypes": True
                        }
                    }
                }
            }
        }
        
        result = await self._send_request("initialize", init_params)
        if result and "capabilities" in result:
            self.server_capabilities = result["capabilities"]
            
            # 🔧 Log what capabilities are actually supported
            logger.debug("=== LSP Server Capabilities ===")
            
            # Check each capability we care about
            references = self.server_capabilities.get("referencesProvider")
            goto_definition = self.server_capabilities.get("definitionProvider")
            document_symbol = self.server_capabilities.get("documentSymbolProvider")
            
            logger.debug(f"📄 Document Symbols: {'✅' if document_symbol else '❌'}")
            logger.debug(f"📚 Definitions: {'✅' if goto_definition else '❌'}")
            logger.debug(f"🔍 References: {'✅' if references else '❌'}")
            
            logger.debug("=== End Capabilities ===")
        else:
            logger.warning("No server capabilities received!")

        await self._send_notification("initialized", {})
        return result
    
    async def _send_request(self, method: str, params: Any, timeout: Optional[float] = None) -> Any:
        """Send a request to the LSP server with a timeout."""
        self.request_id += 1
        request_id = self.request_id

        request = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params
        }

        # Create response event
        event = asyncio.Event()
        self.response_events[request_id] = event

        await self._write_message(request)

        # Determine timeout
        if timeout is None:
            # Use longer timeout for complex operations
            if method in ['textDocument/documentSymbol', 'textDocument/references']:
                timeout = max(self.request_timeout, 60.0)
            else:
                timeout = self.request_timeout

        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
            response = self.responses.pop(request_id, None)
            return response.get("result") if response else None
        except asyncio.TimeoutError:
            logger.error(f"❌ LSP request '{method}' timed out after {timeout}s")
            return None
        finally:
            self.response_events.pop(request_id, None)
    
    async def _send_notification(self, method: str, params: Any):
        """Send a notification to the LSP server."""
        notification = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params
        }
        await self._write_message(notification)

    # ================ Specialized LSP Request ================

    async def get_document_symbols(self, file_path: str, symbol_kind_list: Optional[List[int]] = None, timeout: Optional[float] = None) -> Optional[List[Dict]]:
        """Get document symbols for a file, optionally filtered by symbol kind."""
        try:
            # Convert absolute path to container path
            container_path = file_path.replace(os.path.abspath(self.workspace_path), "/workspace")
            file_uri = f"file://{container_path}"
            
            params = {"textDocument": {"uri": file_uri}}
            result = await self._send_request("textDocument/documentSymbol", params, timeout=timeout)

            if result and symbol_kind_list:
                return self._filter_symbols_by_kind(result, symbol_kind_list)
            return result
            
        except Exception as e:
            logger.debug(f"Document symbols failed: {e}")
            return None
    
    def _filter_symbols_by_kind(self, symbols: List[Dict], wanted_kinds: List[int]) -> List[Dict]:
        """Filter symbols by kind."""
        # If no filtering requested, return all symbols
        if not wanted_kinds:
            return symbols
            
        filtered = []
        for symbol in symbols:
            symbol_matches = symbol.get("kind") in wanted_kinds
            
            # Handle nested symbols
            filtered_children = []
            if "children" in symbol:
                filtered_children = self._filter_symbols_by_kind(symbol["children"], wanted_kinds)
            
            # Include symbol if it matches or has matching children
            if symbol_matches or filtered_children:
                symbol_copy = symbol.copy()
                if filtered_children:
                    symbol_copy["children"] = filtered_children
                elif "children" in symbol_copy:
                    # Remove children if none match (but keep symbol if it matches)
                    del symbol_copy["children"]
                filtered.append(symbol_copy)
                
        return filtered
    
    async def get_references(self, file_path: str, line: int, character: int, include_declaration: bool = True, timeout: Optional[float] = None) -> Optional[List[Dict]]:
        
        """Get all references to a symbol at a specific position."""
        try:
            container_path = file_path.replace(os.path.abspath(self.workspace_path), "/workspace")
            file_uri = f"file://{container_path}"
            params = {
                "textDocument": {"uri": file_uri},
                "position": {"line": line, "character": character},
                "context": {"includeDeclaration": include_declaration}
            }
            return await self._send_request("textDocument/references", params, timeout=timeout)
        except Exception as e:
            logger.debug(f"Get references failed: {e}")
            return None
    
    async def did_open_file(self, file_path: str, language_id: Optional[str] = None) -> bool:
        """Notify LSP server that a file has been opened. Return True if successful."""
        try:
            container_path = file_path.replace(os.path.abspath(self.workspace_path), "/workspace")
            file_uri = f"file://{container_path}"
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            lang_id = (
                language_id
                or self.server_config.get("languageId")
                or self.server_config.get("language_id")
                or "plaintext"
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
            return True
        except Exception as e:
            if "is still open" in str(e):
                logger.warning(f"File already open in LSP server: {file_path}. Skipping.")
            else:
                logger.error(f"Unexpected error opening file {file_path}: {e}")

    async def get_definition(self, file_path: str, line: int, character: int, include_declaration: bool = True, timeout: Optional[float] = None) -> Optional[List[Dict]]:
        """Get definitions for a symbol at a specific position."""
        try:
            container_path = file_path.replace(os.path.abspath(self.workspace_path), "/workspace")
            file_uri = f"file://{container_path}"
            params = {
                "textDocument": {"uri": file_uri},
                "position": {"line": line, "character": character},
                "context": {"includeDeclaration": include_declaration}
            }
            return await self._send_request("textDocument/definition", params, timeout=timeout)
        except Exception as e:
            logger.error(f"Get definition failed: {e}")
            return None
        
    @property
    def is_running(self) -> bool:
        """Check if the LSP server is currently running."""
        return self._is_running