from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import requests


class LLMError(RuntimeError):
    pass


def _env(name: str, default: Optional[str] = None) -> Optional[str]:
    v = os.getenv(name)
    return v if v not in (None, "") else default


@dataclass
class OllamaClient:
    base_url: str = "http://127.0.0.1:11434"
    model: str = "qwen3.5:9b"
    timeout_s: int = 180
    num_gpu: int = -1

    def chat(self, system: str, user: str, temperature: float = 0.05) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "think": False,
            "options": {
                "temperature": temperature,
                "top_p": 0.8,
                "top_k": 10,
                "repeat_penalty": 1.0,
                "num_gpu": self.num_gpu,
            },
        }
        r = requests.post(f"{self.base_url}/api/chat", json=payload, timeout=self.timeout_s)
        if r.status_code != 200:
            raise LLMError(f"Ollama HTTP {r.status_code}: {r.text[:400]}")
        data = r.json()
        return (data.get("message") or {}).get("content", "")

    def warmup(self) -> None:
        try:
            _ = self.chat(system="Du bist hilfreich.", user="Hi", temperature=0.0)
        except Exception:
            # Warmup ist optional; Fehler nicht fatal
            pass


@dataclass
class OpenAICompatClient:
    """
    Für LM Studio (OpenAI-compatible API) oder andere OpenAI-Compat Server.
    Standard LM Studio: http://127.0.0.1:1234/v1
    """

    base_url: str = "http://127.0.0.1:1234/v1"
    model: str = "local-model"
    api_key: Optional[str] = None
    timeout_s: int = 180

    def chat(self, system: str, user: str, temperature: float = 0.05) -> str:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
        }
        r = requests.post(
            f"{self.base_url}/chat/completions",
            headers=headers,
            json=payload,
            timeout=self.timeout_s,
        )
        if r.status_code != 200:
            raise LLMError(f"OpenAI-compat HTTP {r.status_code}: {r.text[:400]}")
        data = r.json()
        choices = data.get("choices") or []
        if not choices:
            raise LLMError("OpenAI-compat: keine choices im Response")
        msg = (choices[0].get("message") or {}).get("content")
        if msg is None:
            raise LLMError("OpenAI-compat: message.content fehlt")
        return msg


def build_client_from_env() -> Any:
    provider = (_env("LLM_PROVIDER", "ollama") or "ollama").lower().strip()
    model = _env("LLM_MODEL", "qwen3.5:9b") or "qwen3.5:9b"

    if provider == "ollama":
        base_url = _env("OLLAMA_BASE_URL", "http://127.0.0.1:11434") or "http://127.0.0.1:11434"
        num_gpu = int(_env("OLLAMA_NUM_GPU", "-1") or "-1")
        timeout_s = int(_env("LLM_TIMEOUT_S", "180") or "180")
        return OllamaClient(base_url=base_url, model=model, num_gpu=num_gpu, timeout_s=timeout_s)

    if provider in ("lmstudio", "openai", "openai_compat", "openai-compatible"):
        base_url = _env("OPENAI_BASE_URL", "http://127.0.0.1:1234/v1") or "http://127.0.0.1:1234/v1"
        api_key = _env("OPENAI_API_KEY", None)
        timeout_s = int(_env("LLM_TIMEOUT_S", "180") or "180")
        return OpenAICompatClient(base_url=base_url, model=model, api_key=api_key, timeout_s=timeout_s)

    raise LLMError(f"Unbekannter LLM_PROVIDER: {provider}")


def parse_json_response(text: str) -> Dict[str, Any]:
    """
    Robust gegen LLMs, die ```json ... ``` oder Text außenrum liefern.
    """
    t = text.strip()
    # Entferne Codefences
    if t.startswith("```"):
        t = t.strip("`")
        # Häufiges Muster: json\n{...}
        if "\n" in t:
            t = t.split("\n", 1)[1].strip()
    # Extrahiere erstes JSON-Objekt
    if not t.startswith("{"):
        start = t.find("{")
        end = t.rfind("}")
        if start != -1 and end != -1 and end > start:
            t = t[start : end + 1]
    return json.loads(t)

