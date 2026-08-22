"""The PRAMAN gateway: S1 mandate verification, S2 faithfulness, S3 behaviour,
S4 policy fusion (see PRAMAN_BUILD.md §9, Phases 4-6)."""

from apps.api.gateway.behaviour_events import (
    AgentEvent,
    cart_signature,
    get_recent_events,
    record_agent_event,
)
from apps.api.gateway.replay_guard import check_and_mark_seen
from apps.api.gateway.stage_behaviour import BehaviourResult, evaluate_behaviour
from apps.api.gateway.stage_mandate import MandateStageResult, evaluate_mandate

__all__ = [
    "AgentEvent",
    "BehaviourResult",
    "MandateStageResult",
    "cart_signature",
    "check_and_mark_seen",
    "evaluate_behaviour",
    "evaluate_mandate",
    "get_recent_events",
    "record_agent_event",
]
