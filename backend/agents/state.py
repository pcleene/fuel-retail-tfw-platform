from typing import TypedDict


class QueryRecord(TypedDict):
    agent: str
    collection: str
    operation: str
    pipeline: list | dict | None
    execution_time_ms: float
    docs_returned: int
    mongodb_features: list[str]


class FraudAgentState(TypedDict, total=False):
    # Input
    user_id: str
    trigger_alert_id: str | None

    # Agent 1: Fraud analysis output
    fraud_analysis: dict | None

    # Agent 2: Similar cases output
    similar_cases: dict | None

    # Agent 3: Recommendation output
    recommendation: dict | None

    # All MongoDB queries executed (for UI visualization)
    queries_executed: list[QueryRecord]

    # Final investigation ID
    investigation_id: str | None
