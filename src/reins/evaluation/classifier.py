from __future__ import annotations

from reins.kernel.types import FailureClass


class FailureClassifier:
    def classify(self, eval_result: dict, context: dict) -> FailureClass:
        text = " ".join(str(value).lower() for value in [eval_result, context])
        if eval_result.get("policy_block") or "approval required" in text:
            return FailureClass.policy_block
        if "merge conflict" in text or "conflict" in text:
            return FailureClass.merge_conflict
        if eval_result.get("remote_agent") or "remote agent" in text:
            return FailureClass.remote_agent_failure
        if eval_result.get("skill_id") and ("activate" in text or "missing tool" in text):
            return FailureClass.skill_activation_failure
        if "timeout" in text or "missing executable" in text or context.get("environment_missing"):
            return FailureClass.environment_failure
        if "flaky" in text or eval_result.get("retryable"):
            return FailureClass.flaky_eval
        if "context" in text or "token" in text:
            return FailureClass.context_failure
        if "http" in text or "network" in text or "external" in text:
            return FailureClass.external_effect_failure
        return FailureClass.logic_failure

    def repair_route(self, failure_class: FailureClass) -> str:
        routes = {
            FailureClass.logic_failure: "change_hypothesis",
            FailureClass.context_failure: "recompile_context",
            FailureClass.environment_failure: "reacquire_environment",
            FailureClass.policy_block: "escalate_or_request_human",
            FailureClass.flaky_eval: "isolate_and_retry",
            FailureClass.merge_conflict: "rerun_local_fix",
            FailureClass.external_effect_failure: "escalate_or_request_human",
            FailureClass.remote_agent_failure: "escalate_or_request_human",
            FailureClass.skill_activation_failure: "change_hypothesis",
        }
        return routes[failure_class]

    def retry_allowed(self, failure_class: FailureClass, prior_hypotheses: list[str]) -> bool:
        normalized = [item.strip().lower() for item in prior_hypotheses if item.strip()]
        if failure_class == FailureClass.policy_block:
            return False
        return len(normalized) > 1 and len(normalized) == len(set(normalized))
