import logging
from datetime import datetime, timezone

from bson import ObjectId
from langgraph.graph import END, StateGraph

from backend.agents.nodes.fraud_analysis import fraud_analysis_node
from backend.agents.nodes.similar_cases import similar_cases_node
from backend.agents.nodes.recommendation import recommendation_node
from backend.agents.state import FraudAgentState
from backend.database import get_fraud_db

logger = logging.getLogger(__name__)


async def persist_investigation(state: FraudAgentState) -> dict:
    """Final node: persist the complete investigation to MongoDB and update user profile."""
    db = get_fraud_db()
    now = datetime.now(timezone.utc)
    investigation_id = f"INV-{now:%Y%m%d}-{ObjectId()}"

    fraud_analysis = state.get("fraud_analysis", {})
    similar_cases = state.get("similar_cases", {})
    recommendation = state.get("recommendation", {})

    investigation_doc = {
        "investigationId": investigation_id,
        "userId": state["user_id"],
        "triggerAlertId": state.get("trigger_alert_id"),
        "fraudAnalysis": fraud_analysis,
        "similarCases": similar_cases,
        "recommendation": recommendation,
        "queriesExecuted": state.get("queries_executed", []),
        "status": "pending_review",
        "createdAt": now,
    }

    await db["fraud_investigations"].insert_one(investigation_doc)
    logger.info("Investigation %s persisted for user %s", investigation_id, state["user_id"])

    # Update user profile with investigation reference
    await db["user_profiles"].update_one(
        {"userId": state["user_id"]},
        {
            "$set": {
                "lastInvestigationId": investigation_id,
                "lastInvestigatedAt": now,
            }
        },
    )

    return {"investigation_id": investigation_id}


def build_fraud_agent_graph():
    """Build the LangGraph sequential pipeline: fraud_analysis -> similar_cases -> recommendation -> persist."""
    graph = StateGraph(FraudAgentState)

    graph.add_node("fraud_analysis", fraud_analysis_node)
    graph.add_node("similar_cases", similar_cases_node)
    graph.add_node("recommendation", recommendation_node)
    graph.add_node("persist", persist_investigation)

    graph.set_entry_point("fraud_analysis")
    graph.add_edge("fraud_analysis", "similar_cases")
    graph.add_edge("similar_cases", "recommendation")
    graph.add_edge("recommendation", "persist")
    graph.add_edge("persist", END)

    return graph.compile()


# Compiled graph — reusable
fraud_agent_pipeline = build_fraud_agent_graph()
