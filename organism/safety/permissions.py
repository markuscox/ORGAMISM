"""Least-privilege capability matrix and human-approval gating."""

from __future__ import annotations

from enum import Enum

from organism.kernel.contracts import TrustLevel


class Capability(str, Enum):
    READ_INTERNAL_STATE = "read_internal_state"
    COMPUTE_MATH = "compute_math"
    QUERY_MEMORY = "query_memory"
    WRITE_MEMORY_CANDIDATE = "write_memory_candidate"
    CALL_LLM = "call_llm"
    EXTERNAL_ACTION_REQUEST = "external_action_request"
    ARBITRARY_CODE_EXECUTION = "arbitrary_code_execution"
    UNRESTRICTED_SHELL = "unrestricted_shell"
    MODIFY_SECURITY_RULES = "modify_security_rules"


class PermissionPolicy:
    """Enforces non-negotiable least-privilege access across trust levels."""

    ALWAYS_DENIED: set[Capability] = {
        Capability.ARBITRARY_CODE_EXECUTION,
        Capability.UNRESTRICTED_SHELL,
        Capability.MODIFY_SECURITY_RULES,
    }

    REQUIRES_HUMAN_APPROVAL: set[Capability] = {
        Capability.EXTERNAL_ACTION_REQUEST,
    }

    ALLOWED_BY_TRUST: dict[TrustLevel, set[Capability]] = {
        TrustLevel.TRUSTED_OPERATOR: {
            Capability.READ_INTERNAL_STATE,
            Capability.COMPUTE_MATH,
            Capability.QUERY_MEMORY,
            Capability.WRITE_MEMORY_CANDIDATE,
            Capability.CALL_LLM,
            Capability.EXTERNAL_ACTION_REQUEST,
        },
        TrustLevel.INTERNAL_SYSTEM: {
            Capability.READ_INTERNAL_STATE,
            Capability.COMPUTE_MATH,
            Capability.QUERY_MEMORY,
            Capability.WRITE_MEMORY_CANDIDATE,
            Capability.CALL_LLM,
        },
        TrustLevel.UNTRUSTED_EXTERNAL: {
            Capability.READ_INTERNAL_STATE,
            Capability.COMPUTE_MATH,
            Capability.QUERY_MEMORY,
            Capability.WRITE_MEMORY_CANDIDATE,
        },
    }

    @classmethod
    def evaluate(
        cls,
        trust_level: TrustLevel,
        capability: Capability,
        approved_by_human: bool = False,
    ) -> tuple[bool, str]:
        if capability in cls.ALWAYS_DENIED:
            return False, f"Capability '{capability.value}' is permanently prohibited in Stage 1."

        allowed = cls.ALLOWED_BY_TRUST.get(trust_level, set())
        if capability not in allowed:
            return (
                False,
                f"Trust level '{trust_level.value}' lacks permission for '{capability.value}'.",
            )

        if capability in cls.REQUIRES_HUMAN_APPROVAL and not approved_by_human:
            return (
                False,
                f"Capability '{capability.value}' requires explicit human approval.",
            )

        return True, "Permitted"
