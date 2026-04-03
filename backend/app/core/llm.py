"""
LLM 客户端 — OpenAI 兼容接口封装
支持：文本生成、Embedding、流式输出
"""
import json
import hashlib
from typing import AsyncGenerator, List

import httpx
from app.core.config import settings
from app.core.logger import logger


class LLMClient:
    """LLM 文本生成"""

    def __init__(self):
        self.base_url = settings.SILICONFLOW_BASE_URL
        self.api_key  = settings.SILICONFLOW_API_KEY
        self.model    = settings.LLM_MODEL

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def chat(self, messages: list, temperature: float = 0.3, max_tokens: int = 1024) -> str:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                headers=self._headers(),
                json={
                    "model": self.model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                },
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"].strip()

    async def chat_json(self, messages: list) -> dict:
        """要求返回 JSON 格式"""
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                headers=self._headers(),
                json={
                    "model": self.model,
                    "messages": messages,
                    "temperature": 0,
                    "max_tokens": 512,
                    "response_format": {"type": "json_object"},
                },
            )
            resp.raise_for_status()
            raw = resp.json()["choices"][0]["message"]["content"]
            return json.loads(raw)

    async def stream(self, messages: list) -> AsyncGenerator[str, None]:
        async with httpx.AsyncClient(timeout=120) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                headers=self._headers(),
                json={
                    "model": self.model,
                    "messages": messages,
                    "stream": True,
                    "temperature": 0.3,
                    "max_tokens": 1024,
                },
            ) as resp:
                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        data = line[6:]
                        if data.strip() == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data)
                            delta = chunk["choices"][0]["delta"].get("content", "")
                            if delta:
                                yield delta
                        except Exception:
                            pass


class EmbedClient:
    """Embedding 客户端"""

    def __init__(self):
        self.base_url = settings.SILICONFLOW_BASE_URL
        self.api_key  = settings.SILICONFLOW_API_KEY
        self.model    = settings.EMBED_MODEL

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def embed_one(self, text: str) -> List[float]:
        return (await self.embed_batch([text]))[0]

    async def embed_batch(self, texts: List[str], batch_size: int = 32) -> List[List[float]]:
        all_vecs = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i: i + batch_size]
            logger.debug(f"Embedding batch {i}~{i + len(batch)}/{len(texts)}")
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    f"{self.base_url}/embeddings",
                    headers=self._headers(),
                    json={"model": self.model, "input": batch},
                )
                resp.raise_for_status()
                items = sorted(resp.json()["data"], key=lambda x: x["index"])
                all_vecs.extend(item["embedding"] for item in items)
        return all_vecs


# 单例
llm_client   = LLMClient()
embed_client = EmbedClient()
