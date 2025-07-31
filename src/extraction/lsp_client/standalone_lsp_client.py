import asyncio
import json
import os
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from .abstract_client import BaseLSPClient
from src.logging.logging import get_logger

logger = get_logger(__name__)

class LSPClient(BaseLSPClient):
    """Universal LSP client to support any languages."""
    
    def __init__(self, server_config: Dict[str, Any]):
        self.server_config = server_config
        self.process = None
        self.reader = None
        self.writer = None
        self.request_id = 0
        # 🔧 New state for robust message handling
        self.responses = {}
        self.response_events = {}
        self._is_running = False
    
    async def start_server(self, workspace_root: str):
        """Start the LSP server."""
        try:
            cmd = self.server_config.get("command")

            if not cmd:
                logger.error(f"❌ No command specified for LSP server in config : {self.server_config.get('name', 'unknown')}")
                return False

            if isinstance(cmd, str):
                cmd = cmd.split()

            args = self.server_config.get("args", [])
            if args:
                cmd.extend(args)
            
            # 🔧 Add workspace as first argument for jdtls
            if cmd[0] == "jdtls":
                cmd.append(workspace_root)
            
            logger.info(f"🚀 Starting LSP server: {' '.join(cmd)}")
            logger.info(f"📁 Working directory: {workspace_root}")

            self.process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=workspace_root,
                preexec_fn=None if os.name == 'nt' else os.setsid
            )

            if not self.process or not self.process.stdout or not self.process.stdin:
                logger.error(f"❌ Failed to start LSP server: {self.server_config.get('name', 'unknown')}")
                return False

            logger.debug(f"✅ Process started with PID: {self.process.pid}")

            self.reader = self.process.stdout
            self.writer = self.process.stdin
            
            # 🔧 Start the main message reading loop
            self._is_running = True
            asyncio.create_task(self._message_reader_loop())
            
            # 🔧 Start monitoring stderr in background
            asyncio.create_task(self._monitor_stderr())
            
            # Initialize LSP      
            try:
                logger.debug("🔄 Initializing LSP server...")
                await asyncio.wait_for(self._initialize(workspace_root), timeout=10.0)
                logger.info(f"✅ LSP server started successfully")
                return True
                    
            except asyncio.TimeoutError:
                logger.error("❌ LSP server initialization timed out")
                await self.shutdown()
                return False
            
        except FileNotFoundError as e:
            logger.error(f"❌ LSP server executable not found: {cmd[0] if cmd else 'unknown'}")
            return False
        except Exception as e:
            logger.error(f"❌ Failed to start LSP server: {e}")
            return False

    async def shutdown(self):
        """Shutdown the LSP server gracefully."""
        self._is_running = False # Stop the reader loop
        try:
            if self.writer and not self.writer.is_closing():
                # Use a short timeout for shutdown sequence
                try:
                    await asyncio.wait_for(self._send_request("shutdown", None), timeout=5.0)
                except asyncio.TimeoutError:
                    logger.warning("Shutdown request timed out.")
                
                await self._send_notification("exit", None)

                self.writer.close()
                await self.writer.wait_closed()
                
            if self.process:
                try:
                    await asyncio.wait_for(self.process.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    # Force kill if needed
                    if self.process.returncode is None:
                        self.process.terminate()
                        await asyncio.sleep(1)
                        if self.process.returncode is None:
                            self.process.kill()
                
        except Exception as e:
            logger.error(f"Error shutting down LSP: {e}")
        finally:
            self.process = None
            self.reader = None
            self.writer = None
            self.responses.clear()
            self.response_events.clear()
            logger.info("🛑 LSP server shutdown complete.")
            return True
        
    async def _message_reader_loop(self):
        """Continuously read messages from the LSP server."""
        while self._is_running and not self.reader.at_eof():
            try:
                message = await self._read_message()
                if not message:
                    continue

                if "id" in message:
                    # This is a response to a request
                    request_id = message["id"]
                    self.responses[request_id] = message
                    if request_id in self.response_events:
                        self.response_events[request_id].set()
                elif "method" in message:
                    # This is a notification from the server
                    logger.debug(f"Received notification: {message['method']}")
                    # Handle specific notifications if needed in the future
                else:
                    logger.warning(f"Unknown message type received: {message}")

            except asyncio.CancelledError:
                break
            except Exception as e:
                if self.is_running:
                    logger.error(f"Error in message reader loop: {e}")
                    import traceback
                    traceback.print_exc()
        logger.debug("Message reader loop stopped.")

    async def _initialize(self, workspace_root: str):
        """Initialize the LSP server with enhanced capabilities."""
        init_params = {
            "processId": None,
            "rootPath": workspace_root,
            "rootUri": Path(workspace_root).as_uri(),
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
    
    async def _send_request(self, method: str, params: Any) -> Any:
        """Send a LSP request and wait for the response."""
        self.request_id += 1
        request_id = self.request_id
        
        request = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params
        }
        
        logger.debug(f"Sending LSP request: {method} (id: {request_id})")
        
        # Create an event to wait for the response
        event = asyncio.Event()
        self.response_events[request_id] = event
        
        await self._write_message(request)
        
        request_timeout = 10.0  # A more reasonable timeout
        try:
            await asyncio.wait_for(event.wait(), timeout=request_timeout)
            
            # The event was set, so the response is in self.responses
            response = self.responses.pop(request_id, None)
            if response and "error" in response:
                logger.error(f"LSP Error for {method}: {response['error']}")
                return None # Or raise an exception
            return response.get("result") if response else None

        except asyncio.TimeoutError:
            logger.error(f"❌ LSP request '{method}' (id: {request_id}) timed out after {request_timeout} seconds")
            return None
        finally:
            # Clean up the event
            self.response_events.pop(request_id, None)

    async def _send_notification(self, method: str, params: Any):
        """Send a LSP notification."""
        notification = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params
        }
        
        await self._write_message(notification)
    
    async def _write_message(self, message: Dict):
        """Écrire un message LSP."""
        content = json.dumps(message)
        header = f"Content-Length: {len(content)}\r\n\r\n"
        
        self.writer.write(header.encode('utf-8'))
        self.writer.write(content.encode('utf-8'))
        await self.writer.drain()
    
    async def _read_message(self) -> Optional[Dict]:
        """Read a complete LSP message with proper buffering."""
        try:
            # Lire les headers ligne par ligne
            headers = {}
            while True:
                header_line = await self.reader.readline()
                if not header_line:
                    logger.debug("No more data to read")
                    return None
                
                header = header_line.decode('utf-8').strip()
                
                # Ligne vide = fin des headers
                if not header:
                    break
                
                # Parser le header
                if ':' in header:
                    key, value = header.split(':', 1)
                    headers[key.strip().lower()] = value.strip()
                else:
                    logger.warning(f"Invalid header format: {header}")
            
            # Vérifier Content-Length
            if 'content-length' not in headers:
                logger.warning("Missing Content-Length header")
                return None
            
            try:
                content_length = int(headers['content-length'])
            except ValueError:
                logger.error(f"Invalid Content-Length: {headers['content-length']}")
                return None
            
            if content_length <= 0:
                logger.warning(f"Invalid content length: {content_length}")
                return None
            
            # 🔧 CORRECTION PRINCIPALE: Lire TOUT le contenu en boucle
            content_bytes = b''
            bytes_to_read = content_length
            
            while bytes_to_read > 0:
                chunk = await self.reader.read(bytes_to_read)
                if not chunk:
                    logger.error(f"Unexpected end of stream. Expected {content_length} bytes, got {len(content_bytes)}")
                    return None
                
                content_bytes += chunk
                bytes_to_read -= len(chunk)
                
                logger.debug(f"Read {len(chunk)} bytes, {bytes_to_read} remaining")
            
            # Décoder et parser le JSON
            try:
                content = content_bytes.decode('utf-8')
                
                # Vérifier que le JSON est complet
                if not content.strip():
                    logger.warning("Empty content received")
                    return None
                
                logger.debug(f"Received complete LSP message ({len(content)} chars)")
                logger.debug(f"Content starts with: {content[:100]}...")
                logger.debug(f"Content ends with: ...{content[-100:]}")
                
                # Parser le JSON
                message = json.loads(content)
                
                # Vérifier que le message est valide
                if not isinstance(message, dict):
                    logger.error(f"Invalid message format: {type(message)}")
                    return None
                
                return message
                
            except json.JSONDecodeError as e:
                logger.error(f"JSON decode error: {e}")
                logger.error(f"Content length: {len(content)}")
                logger.error(f"Content: {content}")
                return None
            except UnicodeDecodeError as e:
                logger.error(f"Unicode decode error: {e}")
                return None
                
        except Exception as e:
            logger.error(f"Error reading LSP message: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    # ================ Specialized LSP Request ================
    
    async def get_document_symbols(self, file_path: str, symbol_kind_list: Optional[List[int]] = None) -> Optional[List[Dict]]:
        """Get document symbols for a file with filtering by WantedKind."""
        try:
            file_uri = self._local_file_uri(file_path)
            params = {
                "textDocument": {"uri": file_uri}
            }
            
            result = await self._send_request("textDocument/documentSymbol", params)
            if result:
                # 🔧 Filter symbols recursively (parent + children)
                filtered_symbols = self._filter_symbols_by_kind(result, symbol_kind_list)
                return filtered_symbols
            
            return result
            
        except Exception as e:
            logger.debug(f"Document symbols failed: {e}")
            return None

    def _filter_symbols_by_kind(self, symbols: List[Dict], wanted_kinds: List[int]) -> List[Dict]:
        """Recursively filter symbols and their children by kind."""
        filtered = []
        
        for symbol in symbols:
            if not isinstance(symbol, dict):
                continue
                
            symbol_kind = symbol.get('kind', 0)
            symbol_name = symbol.get('name', 'unknown')
            
            # Check if this symbol should be included
            if symbol_kind in wanted_kinds:
                # Create a copy of the symbol to avoid modifying the original
                filtered_symbol = symbol.copy()
                
                # 🔧 Recursively filter children too
                if 'children' in symbol and symbol['children']:
                    filtered_children = self._filter_symbols_by_kind(symbol['children'], wanted_kinds)
                    filtered_symbol['children'] = filtered_children
                
                filtered.append(filtered_symbol)
                logger.debug(f"✅ Included symbol: {symbol_name} (kind: {symbol_kind})")
            else:
                logger.debug(f"❌ Filtered out symbol: {symbol_name} (kind: {symbol_kind})")
        
        return filtered

    async def get_definition(self, file_path: str, line: int, character: int, include_declaration: bool = True) -> Optional[List[Dict]]:
        """Get definition locations for a specific position in a file."""
        try:
            file_uri = self._local_file_uri(file_path)
            params = {
                "textDocument": {"uri": file_uri},
                "position": {"line": line, "character": character},
                "context": {"includeDeclaration": include_declaration}
            }
            
            result = await self._send_request("textDocument/definition", params)
            return result
            
        except Exception as e:
            logger.debug(f"Definition failed: {e}")
            return None

    async def did_open_file(self, file_path: str, language_id: Optional[str] = None) -> bool:
        """Notify the LSP server that a file has been opened. Return True if successful."""
        try:
            if not Path(file_path).exists():
                logger.error(f"File does not exist: {file_path}")
                return False
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            if not content.strip():
                logger.warning(f"File is empty: {file_path}")
            file_uri = self._local_file_uri(file_path)
            params = {
                "textDocument": {
                    "uri": file_uri,
                    "languageId": language_id or self.server_config.get("languageId", "python"),
                    "version": 1,
                    "text": content
                }
            }
            logger.debug(f"Opening file with LSP: {file_path} (language: {language_id})")
            await self._send_notification("textDocument/didOpen", params)
            logger.debug(f"✅ File opened successfully: {Path(file_path).name}")
            return True
        except Exception as e:
            logger.error(f"Did open file failed for {file_path}: {e}")
            return False

    async def get_references(self, file_path: str, line: int, character: int, include_declaration: bool = True) -> Optional[List[Dict]]:
        """Get all references to a symbol at a specific position."""
        try:
            file_uri = self._local_file_uri(file_path)
            params = {
                "textDocument": {"uri": file_uri},
                "position": {"line": line, "character": character},
                "context": {
                    "includeDeclaration": include_declaration
                }
            }
            logger.debug(f"Getting references for {file_path} at line {line}, character {character}")
            
            result = await self._send_request("textDocument/references", params)
            return result
            
        except Exception as e:
            logger.debug(f"References failed: {e}")
            return None    

    async def _monitor_stderr(self):
            """Monitor stderr for debugging."""
            if not self.process or not self.process.stderr:
                return
            
            try:
                while True:
                    line = await self.process.stderr.readline()
                    if not line:
                        break
                    
                    error_text = line.decode('utf-8', errors='ignore').strip()
                    if error_text:
                        logger.debug(f"LSP stderr: {error_text}")
                        
                        # Log important messages at higher level
                        if any(keyword in error_text.lower() for keyword in ['error', 'exception', 'failed']):
                            logger.warning(f"LSP error: {error_text}")
                            
            except Exception as e:
                logger.debug(f"Error monitoring stderr: {e}")
   
    @property
    def is_running(self) -> bool:
        """Check if the LSP server is currently running."""
        return self._is_running
    
    def _local_file_uri(self, file_path: str) -> str:
        """Return a file URI for the local file, cross-platform."""
        return Path(file_path).absolute().as_uri()
