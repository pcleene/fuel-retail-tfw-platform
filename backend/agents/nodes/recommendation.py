import json
import logging

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage

from backend.agents.prompts import RECOMMENDATION_SYSTEM_PROMPT
from backend.agents.state import FraudAgentState
from backend.config import settings

logger = logging.getLogger(__name__)


async def recommendation_node(state: FraudAgentState) -> dict:
    """Agent 3: Synthesize fraud analysis + similar cases into actionable recommendation."""
    fraud_analysis = state.get("fraud_analysis", {})
    similar_cases = state.get("similar_cases", {})
    queries = list(state.get("queries_executed", []))

    context = f"""User ID: {state.get('user_id', 'Unknown')}

=== FRAUD ANALYSIS REPORT ===
Fraud pattern: {fraud_analysis.get('fraud_pattern', 'Unknown')}
Confidence: {fraud_analysis.get('confidence', 0)}
False positive likelihood: {fraud_analysis.get('false_positive_likelihood', 'Unknown')}
Affected amount: RM {fraud_analysis.get('affected_amount_myr', 0):,.2f}
Timeline:
{json.dumps(fraud_analysis.get('timeline_analysis', []), indent=2, default=str)}
Key indicators:
{json.dumps(fraud_analysis.get('key_indicators', []), indent=2, default=str)}

=== SIMILAR CASES ANALYSIS ===
Ring analysis: {json.dumps(similar_cases.get('ring_analysis', {}), indent=2, default=str)}
Pattern frequency: {json.dumps(similar_cases.get('pattern_frequency', {}), indent=2, default=str)}
Typical resolution: {json.dumps(similar_cases.get('typical_resolution', {}), indent=2, default=str)}
Similar profiles:
{json.dumps(similar_cases.get('similar_profiles', []), indent=2, default=str)}
"""

    llm = ChatAnthropic(
        model="claude-sonnet-4-20250514",
        api_key=settings.anthropic_api_key,
        max_tokens=1500,
        temperature=0,
    )
    response = await llm.ainvoke([
        SystemMessage(content=RECOMMENDATION_SYSTEM_PROMPT),
        HumanMessage(content=context),
    ])

    try:
        recommendation = json.loads(response.content)
    except json.JSONDecodeError:
        text = response.content
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            recommendation = json.loads(text[start:end])
        else:
            recommendation = {
                "risk_level": "high",
                "recommended_action": "restrict_transactions",
                "immediate_actions": [
                    "Temporarily restrict outbound transfers",
                    "Flag account for manual review",
                    "Notify fraud operations team",
                ],
                "investigation_steps": [
                    "Review full transaction history",
                    "Check linked device and IP patterns",
                    "Cross-reference with known fraud rings",
                ],
                "estimated_exposure_myr": 0.0,
                "regulatory_implications": {
                    "bnm_str_required": False,
                    "aml_review_needed": False,
                    "timeline_days": 14,
                    "reporting_obligations": [],
                },
                "executive_summary": "Investigation requires further review.",
            }

    return {"recommendation": recommendation, "queries_executed": queries}
