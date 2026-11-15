"""Reasoning organ: deterministic AST math & symbolic logic first, budgeted LLM only when needed."""

from __future__ import annotations

import ast
import math
import operator
import time
from typing import Any

from organism.kernel.contracts import EpistemicType, OrganContract, OrganReport, StepStatus
from organism.models.context_compiler import ContextCompiler
from organism.models.provider import (
    MissingCredentialsError,
    ModelProvider,
    ModelRequest,
    ProviderError,
    QuotaExhaustedError,
)
from organism.models.usage_budget import UsageBudgetManager


class SafeMathEvaluator:
    """Exact Python AST math evaluator (never executes arbitrary code or calls LLM for math)."""

    BINARY_OPS = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv,
        ast.Mod: operator.mod,
        ast.Pow: operator.pow,
    }
    UNARY_OPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}
    ALLOWED_FUNCS = {
        "sqrt": math.sqrt,
        "sin": math.sin,
        "cos": math.cos,
        "tan": math.tan,
        "log": math.log,
        "log10": math.log10,
        "abs": abs,
        "round": round,
        "min": min,
        "max": max,
    }
    ALLOWED_CONSTS = {"pi": math.pi, "e": math.e}

    @classmethod
    def evaluate(cls, expression: str) -> float | int:
        if len(expression) > 200:
            raise ValueError("Expression exceeds maximum length (200 chars)")
        tree = ast.parse(expression.strip(), mode="eval")
        result = cls._eval_node(tree.body)
        if isinstance(result, float) and result.is_integer():
            return int(result)
        return round(result, 8) if isinstance(result, float) else result

    @classmethod
    def _eval_node(cls, node: ast.AST) -> float | int:
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return node.value
        if isinstance(node, ast.Name) and node.id in cls.ALLOWED_CONSTS:
            return cls.ALLOWED_CONSTS[node.id]
        if isinstance(node, ast.UnaryOp) and type(node.op) in cls.UNARY_OPS:
            return cls.UNARY_OPS[type(node.op)](cls._eval_node(node.operand))
        if isinstance(node, ast.BinOp) and type(node.op) in cls.BINARY_OPS:
            left = cls._eval_node(node.left)
            right = cls._eval_node(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > 1000:
                raise ValueError("Exponent exceeds safe limit")
            return cls.BINARY_OPS[type(node.op)](left, right)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in cls.ALLOWED_FUNCS:
            if node.keywords:
                raise ValueError("Keyword arguments are prohibited")
            args = [cls._eval_node(arg) for arg in node.args]
            return cls.ALLOWED_FUNCS[node.func.id](*args)
        raise ValueError(f"Unsupported or unsafe expression element: {type(node).__name__}")


class ReasoningOrgan(OrganContract):
    name = "reasoning"
    critical = True

    def __init__(
        self,
        provider: ModelProvider,
        budget: UsageBudgetManager,
        compiler: ContextCompiler,
    ) -> None:
        self._provider = provider
        self._budget = budget
        self._compiler = compiler

    def execute(self, context: dict[str, Any]) -> OrganReport:
        t0 = time.perf_counter()
        perception = context.get("perception", {})
        memories = context.get("retrieved_memories", [])
        workspace_items = context.get("workspace_items", [])
        goal = str(context.get("active_goal", ""))
        mode = str(context.get("mode", "auto"))

        intent = perception.get("detected_intent", "analysis")
        text = str(perception.get("normalized_text", ""))
        is_untrusted = bool(perception.get("is_untrusted_data", False))

        # 1. Exact deterministic mathematical computation
        if intent == "math_computation" and perception.get("math_expression"):
            expr = str(perception["math_expression"])
            try:
                value = SafeMathEvaluator.evaluate(expr)
                self._budget.record_deterministic_resolution()
                return OrganReport(
                    organ_name=self.name,
                    status=StepStatus.OK,
                    payload={
                        "resolution_type": "deterministic_math",
                        "epistemic_type": EpistemicType.FACT.value,
                        "answer": f"{expr} = {value}",
                        "computed_value": value,
                        "evidence": ["Exact Python AST evaluation"],
                    },
                    confidence=1.0,
                    tokens_used=0,
                    deterministic=True,
                    duration_ms=round((time.perf_counter() - t0) * 1000, 3),
                )
            except Exception as exc:
                return OrganReport(
                    organ_name=self.name,
                    status=StepStatus.DEGRADED,
                    payload={
                        "resolution_type": "math_parse_error",
                        "epistemic_type": EpistemicType.UNKNOWN.value,
                        "answer": f"Unable to evaluate mathematical expression safely: {exc}",
                    },
                    confidence=0.2,
                    tokens_used=0,
                    deterministic=True,
                    error=str(exc),
                    duration_ms=round((time.perf_counter() - t0) * 1000, 3),
                )

        # 2. Deterministic knowledge assertion & evidence staging
        if intent == "knowledge_assertion" and perception.get("extracted_triple"):
            triple = perception["extracted_triple"]
            ep_type = perception.get("epistemic_hint", EpistemicType.HYPOTHESIS.value)
            contradictions = [
                m["summary"]
                for m in memories
                if m.get("layer") == "semantic"
                and triple["subject"].lower() in m["summary"].lower()
                and triple["object_value"].lower() not in m["summary"].lower()
            ]
            # Stage 2: single observation enters as candidate unless corroborated
            conf = 0.6 if not is_untrusted else 0.35
            self._budget.record_deterministic_resolution()
            return OrganReport(
                organ_name=self.name,
                status=StepStatus.OK,
                payload={
                    "resolution_type": "symbolic_assertion",
                    "epistemic_type": ep_type,
                    "triple": triple,
                    "contradictions": contradictions,
                    "answer": (
                        f"Staged {ep_type} candidate: {triple['subject']} {triple['predicate']} {triple['object_value']}"
                        + (f" (conflicts with {len(contradictions)} prior record(s))" if contradictions else "")
                    ),
                },
                confidence=conf,
                tokens_used=0,
                deterministic=True,
                duration_ms=round((time.perf_counter() - t0) * 1000, 3),
            )

        # 3. Deterministic hypothesis framing (never promote unverified hypothesis to fact)
        if intent == "hypothesis_evaluation":
            self._budget.record_deterministic_resolution()
            return OrganReport(
                organ_name=self.name,
                status=StepStatus.OK,
                payload={
                    "resolution_type": "epistemic_classification",
                    "epistemic_type": EpistemicType.HYPOTHESIS.value,
                    "answer": f"Classified as unverified hypothesis (requires corroborating evidence): {text}",
                    "evidence": [m["summary"] for m in memories[:3]],
                },
                confidence=0.45,
                tokens_used=0,
                deterministic=True,
                duration_ms=round((time.perf_counter() - t0) * 1000, 3),
            )

        # 4. Deterministic memory recall query (filter confidence & lifecycle status)
        if intent == "memory_query":
            self._budget.record_deterministic_resolution()
            if memories:
                summary_lines = "; ".join(
                    f"[{m.get('status', 'active')}/{m['epistemic_type']}] {m['summary']}"
                    for m in memories[:3]
                )
                top_conf = float(memories[0].get("confidence", 0.7))
                answer = f"Retrieved {len(memories)} relevant record(s): {summary_lines}"
                conf = round(min(0.95, max(0.45, top_conf)), 4)
                ep = memories[0].get("epistemic_type", EpistemicType.FACT.value)
            else:
                answer = "Refrained / Unknown: no supporting records exist in persistent memory yet."
                conf = 0.25
                ep = EpistemicType.UNKNOWN.value
            return OrganReport(
                organ_name=self.name,
                status=StepStatus.OK,
                payload={
                    "resolution_type": "deterministic_memory_recall",
                    "epistemic_type": ep,
                    "answer": answer,
                    "evidence": [m["summary"] for m in memories[:3]],
                },
                confidence=conf,
                tokens_used=0,
                deterministic=True,
                duration_ms=round((time.perf_counter() - t0) * 1000, 3),
            )

        # 5. Deterministic-only mode refrains from speculative synthesis
        if mode == "deterministic_only":
            self._budget.record_deterministic_resolution()
            return OrganReport(
                organ_name=self.name,
                status=StepStatus.OK,
                payload={
                    "resolution_type": "deterministic_abstention" if not memories else "deterministic_symbolic_fallback",
                    "epistemic_type": EpistemicType.UNKNOWN.value,
                    "answer": (
                        "Refrained from concluding: insufficient deterministic evidence for open synthesis."
                        if not memories
                        else f"Matched {len(memories)} memory item(s) deterministically; open synthesis remains unknown."
                    ),
                    "evidence": [m["summary"] for m in memories[:3]],
                },
                confidence=0.3 if not memories else 0.48,
                tokens_used=0,
                deterministic=True,
                duration_ms=round((time.perf_counter() - t0) * 1000, 3),
            )

        # 6. Budgeted Gemini synthesis when natural-language reasoning is needed
        system_inst, compiled_prompt = self._compiler.compile(
            goal=goal,
            trust_level=str(perception.get("trust_level", "unknown")),
            event_text=text,
            workspace_items=workspace_items,
            retrieved_memories=memories,
        )
        est_tokens = self._compiler.estimate_tokens(system_inst + compiled_prompt) + 256
        allowed, reason = self._budget.can_spend(est_tokens)
        if not allowed:
            self._budget.record_deferred()
            return OrganReport(
                organ_name=self.name,
                status=StepStatus.BLOCKED,
                payload={"resolution_type": "budget_exhausted", "reason": reason},
                confidence=0.0,
                tokens_used=0,
                deterministic=True,
                error=reason,
                duration_ms=round((time.perf_counter() - t0) * 1000, 3),
            )

        if not self._provider.is_configured():
            self._budget.record_deterministic_resolution()
            return OrganReport(
                organ_name=self.name,
                status=StepStatus.DEGRADED,
                payload={
                    "resolution_type": "offline_deterministic_fallback",
                    "epistemic_type": EpistemicType.UNKNOWN.value,
                    "answer": (
                        "Model credentials unavailable; refrained from unverified synthesis. "
                        f"Retrieved {len(memories)} memory item(s)."
                    ),
                    "evidence": [m["summary"] for m in memories[:3]],
                },
                confidence=0.35,
                tokens_used=0,
                deterministic=True,
                error="GEMINI_API_KEY not configured; fell back to deterministic mode.",
                duration_ms=round((time.perf_counter() - t0) * 1000, 3),
            )

        try:
            resp = self._provider.generate(
                ModelRequest(
                    system_instruction=system_inst,
                    prompt=compiled_prompt,
                    max_output_tokens=320,
                )
            )
            self._budget.record_model_call(
                provider=resp.provider,
                model_name=resp.model_name,
                prompt_tokens=resp.prompt_tokens,
                completion_tokens=resp.completion_tokens,
            )
            return OrganReport(
                organ_name=self.name,
                status=StepStatus.OK,
                payload={
                    "resolution_type": "llm_synthesis",
                    "model_name": resp.model_name,
                    "epistemic_type": EpistemicType.HYPOTHESIS.value,
                    "answer": resp.text,
                    "prompt_tokens": resp.prompt_tokens,
                    "completion_tokens": resp.completion_tokens,
                },
                confidence=0.68,
                tokens_used=resp.total_tokens,
                deterministic=False,
                duration_ms=round((time.perf_counter() - t0) * 1000, 3),
            )
        except QuotaExhaustedError as exc:
            self._budget.record_deferred()
            return OrganReport(
                organ_name=self.name,
                status=StepStatus.BLOCKED,
                payload={"resolution_type": "quota_exhausted", "reason": str(exc)},
                confidence=0.0,
                tokens_used=0,
                deterministic=True,
                error=str(exc),
                duration_ms=round((time.perf_counter() - t0) * 1000, 3),
            )
        except (MissingCredentialsError, ProviderError) as exc:
            self._budget.record_deterministic_resolution()
            return OrganReport(
                organ_name=self.name,
                status=StepStatus.DEGRADED,
                payload={
                    "resolution_type": "provider_error_fallback",
                    "epistemic_type": EpistemicType.UNKNOWN.value,
                    "answer": f"Model provider unavailable ({exc}); refrained safely.",
                },
                confidence=0.3,
                tokens_used=0,
                deterministic=True,
                error=str(exc),
                duration_ms=round((time.perf_counter() - t0) * 1000, 3),
            )
