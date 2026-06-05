"""Change stream watcher — monitors fraud_alerts for new inserts and triggers LangGraph investigations.

Uses Motor's watch() method for async change stream iteration.
Broadcasts real-time events to connected SSE clients.
Includes debouncing to avoid duplicate investigations for the same user.
"""

import asyncio
import logging
from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorDatabase

logger = logging.getLogger(__name__)


class FraudAlertWatcher:
    """Watches fraud_alerts for new inserts, triggers investigations, broadcasts via SSE."""

    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db
        self._task: asyncio.Task | None = None
        self._subscribers: list[asyncio.Queue] = []
        self._active_investigations: set[str] = set()
        self._recent_investigations: dict[str, datetime] = {}
        self._cooldown_seconds: int = 120

    def subscribe(self) -> asyncio.Queue:
        """Create a new SSE subscriber queue."""
        queue: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._subscribers.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue):
        """Remove an SSE subscriber queue."""
        if queue in self._subscribers:
            self._subscribers.remove(queue)

    async def _broadcast(self, event_type: str, data: dict):
        """Broadcast an SSE event to all subscribers."""
        message = {"event": event_type, "data": data}
        dead_queues = []
        for queue in self._subscribers:
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                dead_queues.append(queue)
        for q in dead_queues:
            self._subscribers.remove(q)

    def _should_investigate(self, user_id: str) -> bool:
        """Check if investigation should proceed (debounce logic)."""
        if user_id in self._active_investigations:
            logger.info("Skipping investigation for %s — already in progress", user_id)
            return False
        last = self._recent_investigations.get(user_id)
        if last:
            elapsed = (datetime.now(timezone.utc) - last).total_seconds()
            if elapsed < self._cooldown_seconds:
                logger.info("Skipping investigation for %s — cooldown (%ds remaining)",
                            user_id, int(self._cooldown_seconds - elapsed))
                return False
        return True

    async def run_investigation(self, user_id: str, alert_id: str | None):
        """Run the LangGraph agent and broadcast progress via SSE."""
        self._active_investigations.add(user_id)
        try:
            await self._broadcast("investigation_status", {
                "userId": user_id,
                "alertId": alert_id,
                "status": "started",
                "stage": "fraud_analysis",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

            from backend.agents.graph import fraud_agent_pipeline
            from backend.agents.state import FraudAgentState

            initial_state: FraudAgentState = {
                "user_id": user_id,
                "trigger_alert_id": alert_id,
                "queries_executed": [],
            }

            result = None
            stage_order = ["fraud_analysis", "similar_cases", "recommendation", "persist"]

            try:
                async for event in fraud_agent_pipeline.astream_events(
                    initial_state, version="v2"
                ):
                    if event["event"] == "on_chain_start" and event.get("name") in stage_order:
                        current_stage = event["name"]
                        await self._broadcast("investigation_status", {
                            "userId": user_id,
                            "alertId": alert_id,
                            "status": "in_progress",
                            "stage": current_stage,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        })
                    if event["event"] == "on_chain_end" and event.get("name") == "persist":
                        result = event.get("data", {}).get("output", {})
            except Exception:
                logger.info("astream_events not available, falling back to ainvoke")
                result = None

            if result is None:
                result = await fraud_agent_pipeline.ainvoke(initial_state)

            investigation_result = {
                "userId": user_id,
                "alertId": alert_id,
                "status": "completed",
                "investigationId": result.get("investigation_id"),
                "fraudAnalysis": result.get("fraud_analysis"),
                "similarCases": result.get("similar_cases"),
                "recommendation": result.get("recommendation"),
                "queriesExecuted": result.get("queries_executed", []),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            await self._broadcast("investigation_complete", investigation_result)

            self._recent_investigations[user_id] = datetime.now(timezone.utc)
            logger.info("Investigation completed for user %s: %s",
                        user_id, result.get("investigation_id"))

        except Exception as e:
            logger.exception("Investigation failed for user %s", user_id)
            await self._broadcast("investigation_status", {
                "userId": user_id,
                "alertId": alert_id,
                "status": "error",
                "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
        finally:
            self._active_investigations.discard(user_id)

    async def _watch_loop(self):
        """Main loop: watch fraud_alerts for inserts and trigger investigations."""
        logger.info("Change stream watcher started on fraud_alerts")
        while True:
            try:
                pipeline = [{"$match": {"operationType": "insert"}}]
                async with self.db["fraud_alerts"].watch(
                    pipeline, full_document="updateLookup"
                ) as stream:
                    async for change in stream:
                        doc = change.get("fullDocument", {})
                        user_id = doc.get("userId")
                        alert_id = doc.get("alertId")
                        signal = doc.get("signal", "?")

                        if not user_id:
                            continue

                        logger.info("Change stream: new fraud alert signal=%s user=%s alert=%s",
                                    signal, user_id, alert_id)

                        # Broadcast the new alert immediately
                        alert_data = {k: v for k, v in doc.items() if k != "_id"}
                        for k, v in alert_data.items():
                            if hasattr(v, "isoformat"):
                                alert_data[k] = v.isoformat()
                        await self._broadcast("new_alert", alert_data)

                        if self._should_investigate(user_id):
                            asyncio.create_task(
                                self.run_investigation(user_id, alert_id)
                            )

            except Exception as e:
                logger.error("Change stream error (will retry in 5s): %s", e)
                await asyncio.sleep(5)

    def start(self):
        """Start the watcher as a background asyncio task."""
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._watch_loop())
            logger.info("FraudAlertWatcher background task created")

    async def stop(self):
        """Stop the watcher."""
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            logger.info("FraudAlertWatcher stopped")


# Module-level singleton
_watcher: FraudAlertWatcher | None = None


def get_watcher() -> FraudAlertWatcher:
    assert _watcher is not None, "Watcher not initialised — call init_watcher() first"
    return _watcher


def init_watcher(db: AsyncIOMotorDatabase) -> FraudAlertWatcher:
    global _watcher
    _watcher = FraudAlertWatcher(db)
    return _watcher
