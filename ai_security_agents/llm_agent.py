"""
M0ST LLM Agent — Wrapper for LLM-based reverse engineering inference.

Supports OpenAI, Anthropic, Mistral, and local LLM backends.
Enhanced context construction with PKG-aware prompting (M0ST Step 6).
"""

import json
import logging
import os
from typing import Any, Dict, List, Optional

from core.capabilities import Capability

logger = logging.getLogger("m0st.llm_agent")

try:
    import openai
    _OPENAI_AVAILABLE = True
except ImportError:
    _OPENAI_AVAILABLE = False

try:
    import anthropic
    _ANTHROPIC_AVAILABLE = True
except ImportError:
    _ANTHROPIC_AVAILABLE = False


class LLMAgent:
    """LLM-based reasoning agent for reverse engineering tasks."""

    CAPABILITIES = {Capability.LLM_INFERENCE, Capability.SEMANTIC_REASON}
    TOOL_REGISTRY: Dict[str, Any] = {}

    def __init__(self, provider: str = "openai", model: Optional[str] = None,
                 api_key: Optional[str] = None, api_base: Optional[str] = None,
                 temperature: float = 0.2, max_tokens: int = 2048):
        self.provider = provider.lower()
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.model = model or self._default_model()
        self.api_key = api_key or self._resolve_api_key()
        self.api_base = api_base
        self.client = self._init_client()

    # ── Public inference methods ───────────────────────────────────────────

    def infer_function_name(self, disassembly: str = "", pseudocode: str = "",
                            metadata: Optional[Dict] = None,
                            gnn_embedding: Optional[List[float]] = None) -> Dict[str, Any]:
        prompt = self._build_prompt(
            task="infer_function_name",
            instruction='Analyze the following reverse-engineered function and suggest a descriptive function name. Return JSON with keys: "name" (string), "confidence" (0.0-1.0), "reasoning" (string).',
            disassembly=disassembly, pseudocode=pseudocode,
            metadata=metadata, gnn_embedding=gnn_embedding,
        )
        return self._query_json(prompt)

    def infer_variable_names(self, disassembly: str = "", pseudocode: str = "",
                             metadata: Optional[Dict] = None,
                             gnn_embedding: Optional[List[float]] = None) -> Dict[str, Any]:
        prompt = self._build_prompt(
            task="infer_variable_names",
            instruction='Analyze the following code and suggest descriptive names for variables (registers, stack slots). Return JSON with key "variables": list of {"original": str, "suggested": str, "type_hint": str, "reasoning": str}.',
            disassembly=disassembly, pseudocode=pseudocode,
            metadata=metadata, gnn_embedding=gnn_embedding,
        )
        return self._query_json(prompt)

    def infer_types(self, disassembly: str = "", pseudocode: str = "",
                    metadata: Optional[Dict] = None,
                    gnn_embedding: Optional[List[float]] = None) -> Dict[str, Any]:
        prompt = self._build_prompt(
            task="infer_types",
            instruction='Analyze the code and infer data types for parameters, return values, and local variables. Return JSON with keys: "parameters": list of {"name": str, "type": str}, "return_type": str, "locals": list of {"name": str, "type": str}, "reasoning": str.',
            disassembly=disassembly, pseudocode=pseudocode,
            metadata=metadata, gnn_embedding=gnn_embedding,
        )
        return self._query_json(prompt)

    def summarize_function(self, disassembly: str = "", pseudocode: str = "",
                           metadata: Optional[Dict] = None,
                           gnn_embedding: Optional[List[float]] = None) -> Dict[str, Any]:
        prompt = self._build_prompt(
            task="summarize_function",
            instruction='Provide a comprehensive summary of what this function does. Return JSON with keys: "summary" (string), "behavior" (string), "side_effects" (list of strings), "algorithmic_intent" (string), "complexity_estimate" (string).',
            disassembly=disassembly, pseudocode=pseudocode,
            metadata=metadata, gnn_embedding=gnn_embedding,
        )
        return self._query_json(prompt)

    def explain_basic_block(self, block_disassembly: str = "",
                            block_addr: Optional[int] = None,
                            context: Optional[Dict] = None) -> Dict[str, Any]:
        extra_context = ""
        if block_addr is not None:
            extra_context += f"\n[BLOCK_ADDRESS]: 0x{block_addr:x}"
        if context:
            extra_context += f"\n[CONTEXT]: {json.dumps(context)}"
        prompt = self._build_prompt(
            task="explain_basic_block",
            instruction='Explain what this basic block of assembly does in plain English. Return JSON with keys: "explanation" (string), "purpose" (string), "data_flow" (string describing register/memory changes).',
            disassembly=block_disassembly, extra=extra_context,
        )
        return self._query_json(prompt)

    def explain_cfg_region(self, region_disassembly: str = "",
                           region_edges: Optional[List] = None,
                           metadata: Optional[Dict] = None,
                           gnn_embedding: Optional[List[float]] = None) -> Dict[str, Any]:
        extra = ""
        if region_edges:
            extra += f"\n[CFG_EDGES]: {json.dumps(region_edges)}"
        prompt = self._build_prompt(
            task="explain_cfg_region",
            instruction='Analyze this CFG region (loop, branch, or subgraph) and explain its behavior. Return JSON with keys: "explanation" (string), "pattern" (string - e.g., loop, if-else, switch), "iteration_behavior" (string if loop), "exit_conditions" (list of strings).',
            disassembly=region_disassembly, metadata=metadata,
            gnn_embedding=gnn_embedding, extra=extra,
        )
        return self._query_json(prompt)

    def annotate_code(self, pseudocode: str = "", disassembly: str = "",
                      metadata: Optional[Dict] = None) -> Dict[str, Any]:
        prompt = self._build_prompt(
            task="annotate_code",
            instruction='Add detailed inline comments to the following code. Return JSON with key "annotated_code" (string with comments added).',
            disassembly=disassembly, pseudocode=pseudocode, metadata=metadata,
        )
        return self._query_json(prompt)

    def detect_vulnerabilities(self, disassembly: str = "", pseudocode: str = "",
                               metadata: Optional[Dict] = None) -> Dict[str, Any]:
        prompt = self._build_prompt(
            task="detect_vulnerabilities",
            instruction='Analyze this code for security vulnerabilities. Return JSON with key "vulnerabilities": list of {"type": str, "severity": str, "description": str, "location": str, "recommendation": str}.',
            disassembly=disassembly, pseudocode=pseudocode, metadata=metadata,
        )
        return self._query_json(prompt)

    # ── Tool-calling support ───────────────────────────────────────────────

    @classmethod
    def register_tool(cls, name: str, handler, description: str = ""):
        cls.TOOL_REGISTRY[name] = {"handler": handler, "description": description}

    def resolve_tool_call(self, tool_name: str, arguments: Dict) -> Any:
        tool = self.TOOL_REGISTRY.get(tool_name)
        if tool is None:
            return {"error": f"Unknown tool: {tool_name}"}
        try:
            return tool["handler"](**arguments)
        except Exception as e:
            return {"error": str(e)}

    # ── Enhanced prompt construction (Step 6) ──────────────────────────────

    def build_prompt(self, task: str, instruction: str, disassembly: str = "",
                     pseudocode: str = "", metadata: Optional[Dict] = None,
                     gnn_embedding: Optional[List[float]] = None,
                     extra: str = "", context_functions: Optional[List[str]] = None,
                     call_chains: Optional[List[str]] = None,
                     data_flow: Optional[str] = None) -> str:
        """Public interface for prompt construction."""
        return self._build_prompt(
            task=task, instruction=instruction, disassembly=disassembly,
            pseudocode=pseudocode, metadata=metadata, gnn_embedding=gnn_embedding,
            extra=extra, context_functions=context_functions,
            call_chains=call_chains, data_flow=data_flow,
        )

    def query(self, prompt: str) -> str:
        """Public interface for raw LLM query."""
        return self._query(prompt)

    def _build_prompt(self, task: str, instruction: str, disassembly: str = "",
                      pseudocode: str = "", metadata: Optional[Dict] = None,
                      gnn_embedding: Optional[List[float]] = None,
                      extra: str = "", context_functions: Optional[List[str]] = None,
                      call_chains: Optional[List[str]] = None,
                      data_flow: Optional[str] = None) -> str:
        parts = [
            "You are an expert reverse engineer and binary analyst.",
            f"Task: {task}", "", instruction, "",
        ]
        if gnn_embedding:
            trunc = gnn_embedding[:32]
            parts.append(
                f"[CFG_EMBEDDING]: {json.dumps(trunc)} "
                f"(dim={len(gnn_embedding)}, showing first 32)"
            )
            parts.append("Use the CFG embedding to understand structural patterns.")
            parts.append("")
        if disassembly:
            parts.append(f"[DISASSEMBLY]:\n{disassembly}\n")
        if pseudocode:
            parts.append(f"[PSEUDOCODE]:\n{pseudocode}\n")
        if context_functions:
            parts.append(f"[CONTEXT_FUNCTIONS]:\n" + "\n".join(context_functions) + "\n")
        if call_chains:
            parts.append(f"[CALL_CHAINS]:\n" + "\n".join(call_chains) + "\n")
        if data_flow:
            parts.append(f"[DATAFLOW_SUMMARY]:\n{data_flow}\n")
        if metadata:
            dataflow = metadata.pop("dataflow_summary", None)
            if dataflow:
                parts.append(f"[DATAFLOW_SUMMARY]:\n{dataflow}\n")
            parts.append(f"[METADATA]: {json.dumps(metadata, default=str)}\n")
        if extra:
            parts.append(extra + "\n")
        parts.append("Respond ONLY with valid JSON. Do not include markdown fences or explanations outside the JSON.")
        return "\n".join(parts)

    # ── LLM query ──────────────────────────────────────────────────────────

    def _query(self, prompt: str) -> str:
        if self.client is None:
            return json.dumps({"error": f"No LLM client available for provider '{self.provider}'."})
        try:
            if self.provider == "openai":
                return self._query_openai(prompt)
            elif self.provider == "anthropic":
                return self._query_anthropic(prompt)
            elif self.provider in ("mistral", "local"):
                return self._query_openai_compat(prompt)
            else:
                return json.dumps({"error": f"Unsupported provider: {self.provider}"})
        except Exception as e:
            return json.dumps({"error": f"LLM query failed: {str(e)}"})

    def _query_json(self, prompt: str, max_retries: int = 2) -> Dict[str, Any]:
        """
        Query the LLM and extract valid JSON from the response.

        Implements robust JSON extraction:
        1. Strip markdown fences, thinking tags, preamble text
        2. Find first '{' and last '}' to extract JSON substring
        3. On first failure, retry once with an explicit JSON-repair prompt
        4. Fallback: wrap raw response into a structured dict
        """
        raw = self._query(prompt)
        logger.debug("LLM raw response (attempt 1): %s", raw[:500])

        parsed = self._extract_json(raw)
        if parsed is not None:
            return parsed

        # Log the full failing response for debugging
        logger.debug("Raw LLM text that failed JSON parse (first 800 chars): %s", repr(raw[:800]))

        # Retry once with explicit repair prompt instead of repeating the same query
        logger.debug("JSON parse failed on first attempt, retrying with repair prompt.")
        repair_prompt = (
            "Your previous response was not valid JSON. "
            "Convert the following text into ONLY a valid JSON object. "
            "Output nothing except the JSON object — no markdown, no explanation, "
            "no code fences.\n\n"
            + raw[:3000]
        )
        raw2 = self._query(repair_prompt)
        logger.debug("LLM repair response: %s", raw2[:500])

        parsed = self._extract_json(raw2)
        if parsed is not None:
            return parsed

        logger.debug("JSON extraction failed after repair attempt. Using fallback.")
        # Build a usable fallback from the raw text
        return self._build_fallback(raw)

    @staticmethod
    def _extract_json(text: str) -> Optional[Dict[str, Any]]:
        """
        Attempt to extract a JSON object from raw LLM output.

        Handles: markdown fences, <thinking> tags, preamble text,
        unescaped newlines inside strings, trailing commas.
        """
        import re as _re

        text = text.strip()

        # Strip <thinking>...</thinking> blocks (Anthropic extended thinking)
        text = _re.sub(r"<thinking>.*?</thinking>", "", text, flags=_re.DOTALL).strip()

        # Strip markdown fences (```json ... ``` or ``` ... ```)
        text = _re.sub(r"```(?:json)?\s*\n?", "", text).strip()

        # Attempt 1: parse the full text
        try:
            result = json.loads(text)
            if isinstance(result, dict):
                return result
        except (json.JSONDecodeError, ValueError):
            pass

        # Attempt 2: find first '{' and last '}' and extract substring
        first_brace = text.find("{")
        last_brace = text.rfind("}")
        if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
            candidate = text[first_brace:last_brace + 1]
            try:
                result = json.loads(candidate)
                if isinstance(result, dict):
                    return result
            except (json.JSONDecodeError, ValueError):
                pass

            # Attempt 3: fix common JSON issues
            cleaned = candidate
            # Remove trailing commas before } or ]
            cleaned = _re.sub(r",\s*([}\]])", r"\1", cleaned)
            # Escape literal newlines inside string values
            # (newlines that appear between quotes)
            cleaned = _re.sub(
                r'"((?:[^"\\]|\\.)*)"',
                lambda m: '"' + m.group(1).replace('\n', '\\n').replace('\r', '') + '"',
                cleaned,
            )
            try:
                result = json.loads(cleaned)
                if isinstance(result, dict):
                    return result
            except (json.JSONDecodeError, ValueError):
                pass

            # Attempt 4: line-by-line reconstruction — drop non-JSON lines
            lines = candidate.split("\n")
            reconstructed = []
            for line in lines:
                stripped = line.strip()
                # Skip lines that look like prose (no JSON tokens)
                if stripped and not any(c in stripped for c in '{}[]:,"'):
                    continue
                reconstructed.append(line)
            if reconstructed:
                try:
                    result = json.loads("\n".join(reconstructed))
                    if isinstance(result, dict):
                        return result
                except (json.JSONDecodeError, ValueError):
                    pass

        return None

    @staticmethod
    def _build_fallback(raw: str) -> Dict[str, Any]:
        """Build a usable fallback dict from raw LLM text."""
        text = raw.strip()[:1000] if raw.strip() else "No response"
        # Try to extract a one-line summary from the first sentence
        first_sentence = text.split(".")[0].strip() if "." in text else text[:200]
        return {
            "summary": first_sentence,
            "behavior": text[:500],
            "raw_response": raw[:2000],
            "error": "Failed to parse JSON from LLM response",
            "side_effects": [],
            "algorithmic_intent": "",
            "complexity_estimate": "unknown",
            "vulnerabilities": [],
            "name": "unknown",
            "confidence": 0.0,
            "reasoning": "JSON parse failed — raw text fallback",
            "variables": [],
            "parameters": [],
            "return_type": "unknown",
            "locals": [],
            "annotated_code": "",
        }

    def _query_openai(self, prompt: str) -> str:
        kwargs = dict(
            model=self.model,
            messages=[
                {"role": "system", "content": "You are an expert binary analyst. Always respond with valid JSON. No markdown fences, no explanations outside the JSON object."},
                {"role": "user", "content": prompt},
            ],
            temperature=self.temperature, max_tokens=self.max_tokens,
        )
        try:
            kwargs["response_format"] = {"type": "json_object"}
            response = self.client.chat.completions.create(**kwargs)
        except Exception:
            kwargs.pop("response_format", None)
            response = self.client.chat.completions.create(**kwargs)
        return response.choices[0].message.content or ""

    def _query_anthropic(self, prompt: str) -> str:
        response = self.client.messages.create(
            model=self.model, max_tokens=self.max_tokens,
            temperature=self.temperature,
            system="You are an expert binary analyst. Always respond with valid JSON. No markdown, no explanations outside the JSON object.",
            messages=[
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": "{"},
            ],
        )
        text = response.content[0].text if response.content else ""
        # Prepend the '{' we used as prefill
        return "{" + text

    def _query_openai_compat(self, prompt: str) -> str:
        messages = [
            {"role": "system", "content": "You are an expert binary analyst. Respond ONLY with a valid JSON object. No markdown, no text outside the JSON."},
            {"role": "user", "content": prompt},
        ]
        # Try response_format first (supported by Ollama, vLLM, etc.)
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=self.temperature, max_tokens=self.max_tokens,
                response_format={"type": "json_object"},
            )
            return response.choices[0].message.content or ""
        except Exception:
            pass
        # Fallback: prefill with '{' so the model continues JSON
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages + [{"role": "assistant", "content": "{"}],
                temperature=self.temperature, max_tokens=self.max_tokens,
            )
            text = response.choices[0].message.content or ""
            return "{" + text
        except Exception:
            # Final fallback: send without prefill
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=self.temperature, max_tokens=self.max_tokens,
            )
            return response.choices[0].message.content or ""

    def _init_client(self):
        if self.provider == "openai":
            if not _OPENAI_AVAILABLE:
                print("[LLMAgent] openai package not installed.")
                return None
            if not self.api_key:
                print("[LLMAgent] No OpenAI API key found. Set OPENAI_API_KEY env var.")
                return None
            return openai.OpenAI(api_key=self.api_key, base_url=self.api_base)
        elif self.provider == "anthropic":
            if not _ANTHROPIC_AVAILABLE:
                print("[LLMAgent] anthropic package not installed.")
                return None
            if not self.api_key:
                print("[LLMAgent] No Anthropic API key found. Set ANTHROPIC_API_KEY env var.")
                return None
            return anthropic.Anthropic(api_key=self.api_key)
        elif self.provider in ("mistral", "local"):
            if not _OPENAI_AVAILABLE:
                print("[LLMAgent] openai package needed for OpenAI-compatible APIs.")
                return None
            base = self.api_base or self._default_api_base()
            return openai.OpenAI(
                api_key=self.api_key or "not-needed",
                base_url=base,
                timeout=60.0,
            )
        else:
            print(f"[LLMAgent] Unknown provider: {self.provider}")
            return None

    def _default_model(self) -> str:
        defaults = {
            "openai": "gpt-4o", "anthropic": "claude-sonnet-4-20250514",
            "mistral": "mistral-large-latest", "local": "default",
        }
        return defaults.get(self.provider, "gpt-4o")

    def _resolve_api_key(self) -> Optional[str]:
        env_keys = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY", "mistral": "MISTRAL_API_KEY"}
        env_var = env_keys.get(self.provider)
        return os.environ.get(env_var) if env_var else None

    def _default_api_base(self) -> str:
        bases = {"mistral": "https://api.mistral.ai/v1", "local": "http://localhost:11434/v1"}
        return bases.get(self.provider, "http://localhost:8000/v1")
