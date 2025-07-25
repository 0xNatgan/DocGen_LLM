"""LLM client for interfacing with language models."""

import asyncio
import json
import os
from typing import Dict, List, Optional, Any, AsyncGenerator, Union
from dataclasses import dataclass
from src.logging.logging import get_logger
from enum import Enum
import httpx


logger = get_logger(__name__)

class LLMProvider(Enum):
    """Supported LLM providers."""
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    OLLAMA = "ollama"
    GEMINI = "gemini"

@dataclass
class LLMMessage:
    """Represents a message in the conversation."""
    role: str  # "system", "user", "assistant"
    content: str
    context: Optional[str] = None  # Optional context for the message

@dataclass
class LLMResponse:
    """Response from LLM."""
    content: str
    model: str
    usage: Dict[str, Any]
    finish_reason: str

class LLMClient:
    """LLM client that encapsulates language model interactions."""
    
    def __init__(self, provider: str = "openai", model: str = None, api_key: str = None, 
                 base_url: str = None, temperature: float = 0.3, max_tokens: int = 2000):
        """
        Initialize LLM client.
        
        Args:
            provider: LLM provider ("openai", "anthropic", "ollama")
            model: Model name
            api_key: API key for the provider
            base_url: Custom base URL (mainly for Ollama)
            temperature: Response randomness (0.0 to 1.0)
            max_tokens: Maximum tokens in response
        """
        self.provider = provider.lower()
        self.model = model or self._get_default_model()
        self.api_key = api_key or self._get_api_key()
        self.base_url = base_url or self._get_default_base_url()
        self.temperature = temperature
        self.max_tokens = max_tokens
        
        # HTTP client for API calls
        self.client = None
        self.is_initialized = False
        
        # Conversation history
        self.conversation: List[LLMMessage] = []
    
    def _get_default_model(self) -> str:
        """Get default model for provider."""
        defaults = {
            "openai": "gpt-3.5-turbo",
            "anthropic": "claude-3-haiku-20240307",
            "ollama": "openheremes",
        }
        return defaults.get(self.provider, "gpt-3.5-turbo")
        
    def _get_api_key(self) -> Optional[str]:
        """Get API key from environment."""
        if self.provider == "openai":
            return os.getenv("OPENAI_API_KEY")
        elif self.provider == "anthropic":
            return os.getenv("ANTHROPIC_API_KEY")
        return None
    
    def _get_default_base_url(self) -> str:
        """Get default base URL for provider."""
        urls = {
            "openai": "https://api.openai.com/v1",
            "anthropic": "https://api.anthropic.com",
            "ollama": "http://localhost:11434"
        }
        return urls.get(self.provider, "")
    
    async def initialize(self) -> bool:
        """Initialize the client."""
        try:
            timeout = httpx.Timeout(60.0)
            self.client = httpx.AsyncClient(timeout=timeout)
            
            # Test connection based on provider
            if await self._test_connection():
                self.is_initialized = True
                logger.info(f"✅ LLM client initialized: {self.provider} ({self.model})")
                return True
            else:
                logger.error(f"❌ Failed to connect to {self.provider}")
                return False
                
        except Exception as e:
            logger.error(f"LLM client initialization failed: {e}")
            return False
    
    async def _test_connection(self) -> bool:
        """Test connection to the LLM provider."""
        try:
            if self.provider == "ollama":
                response = await self.client.get(f"{self.base_url}/api/tags")
                return response.status_code == 200
                
            elif self.provider in ["openai", "anthropic"]:
                # For API-based providers, we'll test on first actual request
                return self.api_key is not None
                
            return False
            
        except Exception as e:
            logger.debug(f"Connection test failed: {e}")
            return False
    
    async def ask(self, prompt: str, system_prompt: str = None) -> str:
        """
        Ask a single question to the LLM.
        
        Args:
            prompt: User prompt/question
            system_prompt: Optional system prompt for context
            
        Returns:
            LLM response as string
        """
        if not self.is_initialized:
            await self.initialize()
        
        messages = []
        if system_prompt:
            messages.append(LLMMessage(role="system", content=system_prompt))
        messages.append(LLMMessage(role="user", content=prompt))

        logger.info(f"Sending prompt to {self.provider}: {messages}")

        response = await self.chat(messages)
        return response.content
    
    async def chat(self, messages: List[LLMMessage]) -> LLMResponse:
        """
        Send messages to LLM and get response.
        
        Args:
            messages: List of messages in the conversation
            
        Returns:
            LLM response object
        """
        if not self.is_initialized:
            raise RuntimeError("LLM client not initialized")
        
        if self.provider == "openai":
            return await self._openai_chat(messages)
        elif self.provider == "anthropic":
            return await self._anthropic_chat(messages)
        elif self.provider == "ollama":
            return await self._ollama_chat(messages)
        else:
            raise ValueError(f"Unsupported provider: {self.provider}")
    
    async def chat_stream(self, messages: List[LLMMessage]) -> AsyncGenerator[str, None]:
        """
        Stream chat response from LLM.
        
        Args:
            messages: List of messages in the conversation
            
        Yields:
            Chunks of the response as they arrive
        """
        if not self.is_initialized:
            raise RuntimeError("LLM client not initialized")
        
        if self.provider == "openai":
            async for chunk in self._openai_stream(messages):
                yield chunk
        elif self.provider == "anthropic":
            async for chunk in self._anthropic_stream(messages):
                yield chunk
        elif self.provider == "ollama":
            async for chunk in self._ollama_stream(messages):
                yield chunk
        else:
            raise ValueError(f"Unsupported provider: {self.provider}")
    
    async def _openai_chat(self, messages: List[LLMMessage]) -> LLMResponse:
        """Handle OpenAI chat completion."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": self.model,
            "messages": [{"role": msg.role, "content": msg.content} for msg in messages],
            "temperature": self.temperature
        }
        
        if self.max_tokens:
            payload["max_tokens"] = self.max_tokens
        
        response = await self.client.post(
            f"{self.base_url}/chat/completions",
            json=payload,
            headers=headers
        )
        response.raise_for_status()
        
        data = response.json()
        choice = data["choices"][0]
        
        return LLMResponse(
            content=choice["message"]["content"],
            model=data["model"],
            usage=data.get("usage", {}),
            finish_reason=choice["finish_reason"]
        )
    
    async def _anthropic_chat(self, messages: List[LLMMessage]) -> LLMResponse:
        """Handle Anthropic chat completion."""
        headers = {
            "x-api-key": self.api_key,
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01"
        }
        
        # Separate system message from conversation
        system_msg = None
        conv_messages = []
        
        for msg in messages:
            if msg.role == "system":
                system_msg = msg.content
            else:
                conv_messages.append({"role": msg.role, "content": msg.content})
        
        payload = {
            "model": self.model,
            "messages": conv_messages,
            "max_tokens": self.max_tokens or 1000,
            "temperature": self.temperature
        }
        
        if system_msg:
            payload["system"] = system_msg
        
        response = await self.client.post(
            f"{self.base_url}/v1/messages",
            json=payload,
            headers=headers
        )
        response.raise_for_status()
        
        data = response.json()
        
        return LLMResponse(
            content=data["content"][0]["text"],
            model=data["model"],
            usage=data.get("usage", {}),
            finish_reason=data.get("stop_reason", "stop")
        )
    
    async def _ollama_chat(self, messages: List[LLMMessage]) -> LLMResponse:
        """Handle Ollama chat completion."""
        payload = {
            "model": self.model,
            "messages": [{"role": msg.role, "content": msg.content} for msg in messages],
            "stream": False,
            "think": True,
            "options": {
                "temperature": self.temperature
            }
        }
        
        response = await self.client.post(
            f"{self.base_url}/api/chat",
            json=payload
        )
        response.raise_for_status()
        
        data = response.json()
        
        return LLMResponse(
            content=data["message"]["content"],
            model=data.get("model", self.model),
            usage=data.get("usage", {}),
            finish_reason="stop"
        )
    
    async def _openai_stream(self, messages: List[LLMMessage]) -> AsyncGenerator[str, None]:
        """Stream OpenAI response."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": self.model,
            "messages": [{"role": msg.role, "content": msg.content} for msg in messages],
            "temperature": self.temperature,
            "stream": True
        }
        
        if self.max_tokens:
            payload["max_tokens"] = self.max_tokens
        
        async with self.client.stream(
            "POST",
            f"{self.base_url}/chat/completions",
            json=payload,
            headers=headers
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    data_str = line[6:]  # Remove "data: " prefix
                    if data_str.strip() == "[DONE]":
                        break
                    try:
                        data = json.loads(data_str)
                        if data["choices"][0]["delta"].get("content"):
                            yield data["choices"][0]["delta"]["content"]
                    except json.JSONDecodeError:
                        continue
    
    async def _anthropic_stream(self, messages: List[LLMMessage]) -> AsyncGenerator[str, None]:
        """Stream Anthropic response."""
        # Anthropic streaming implementation would go here
        # For now, fall back to regular chat
        response = await self._anthropic_chat(messages)
        yield response.content
    
    async def _ollama_stream(self, messages: List[LLMMessage]) -> AsyncGenerator[str, None]:
        """Stream Ollama response."""
        payload = {
            "model": self.model,
            "messages": [{"role": msg.role, "content": msg.content} for msg in messages],
            "stream": True,
            "think": True, 
            "options": {
                "temperature": self.temperature
            }
        }
        
        async with self.client.stream(
            "POST",
            f"{self.base_url}/api/chat",
            json=payload
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if line:
                    try:
                        data = json.loads(line)
                        if data.get("message", {}).get("content"):
                            yield data["message"]["content"]
                    except json.JSONDecodeError:
                        continue
    

 # ================= Continuous conversation methods ========================
    def add_to_conversation(self, role: str, content: str):
        """Add message to conversation history."""
        self.conversation.append(LLMMessage(role=role, content=content))
    
    def get_conversation(self) -> List[LLMMessage]:
        """Get current conversation history."""
        return self.conversation.copy()
    
    def clear_conversation(self):
        """Clear conversation history."""
        self.conversation.clear()
    
    async def continue_conversation(self, user_message: str) -> str:
        """Continue the ongoing conversation."""
        self.add_to_conversation("user", user_message)
        
        response = await self.chat(self.conversation)
        self.add_to_conversation("assistant", response.content)
        
        return response.content
    
    async def shutdown(self):
        """Shutdown the client."""
        if self.client:
            await self.client.aclose()
            logger.info("✅ LLM client shutdown complete")
    
    def __str__(self) -> str:
        return f"LLMClient(provider={self.provider}, model={self.model})"
    
    def __repr__(self) -> str:
        return self.__str__()