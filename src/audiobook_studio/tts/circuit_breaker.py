"""Circuit Breaker for TTS provider failure isolation.

Thin re-export of the LLM circuit breaker for TTS usage.
Three-state machine: CLOSED (normal) → OPEN (blocked) → HALF_OPEN (testing)
- CLOSED: Normal operation, counting failures
- OPEN: Provider blocked, skipping all calls
- HALF_OPEN: Testing with limited calls, promoting back to CLOSED on success
"""

from ..llm.circuit_breaker import CircuitBreaker

__all__ = ["CircuitBreaker"]