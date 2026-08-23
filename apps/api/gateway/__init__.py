"""The PRAMAN gateway: S1 mandate verification, S2 faithfulness, S3
behaviour, S4 policy fusion, orchestrated end to end by pipeline.py (see
PRAMAN_BUILD.md §9, Phases 4-6)."""

from apps.api.gateway.behaviour_events import (
    AgentEvent,
    cart_signature,
    get_recent_events,
    record_agent_event,
)
from apps.api.gateway.pipeline import (
    AuthorizationResult,
    ConfirmStepUpResult,
    PipelineThresholds,
    authorize,
    confirm_step_up,
    quote_to_cart,
)
from apps.api.gateway.policy import PolicyResult, fuse_decision
from apps.api.gateway.replay_guard import check_and_mark_seen
from apps.api.gateway.stage_behaviour import BehaviourResult, evaluate_behaviour
from apps.api.gateway.stage_faithfulness import FaithfulnessResult, evaluate_faithfulness
from apps.api.gateway.stage_mandate import MandateStageResult, evaluate_mandate
from apps.api.gateway.step_up import issue_step_up_token, redeem_step_up_token

__all__ = [
    "AgentEvent",
    "AuthorizationResult",
    "BehaviourResult",
    "ConfirmStepUpResult",
    "FaithfulnessResult",
    "MandateStageResult",
    "PipelineThresholds",
    "PolicyResult",
    "authorize",
    "cart_signature",
    "check_and_mark_seen",
    "confirm_step_up",
    "evaluate_behaviour",
    "evaluate_faithfulness",
    "evaluate_mandate",
    "fuse_decision",
    "get_recent_events",
    "issue_step_up_token",
    "quote_to_cart",
    "record_agent_event",
    "redeem_step_up_token",
]
