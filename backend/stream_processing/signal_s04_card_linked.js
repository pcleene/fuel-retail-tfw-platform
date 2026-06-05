// ============================================================
// Signal S04 — Rapid Card Linking
// 60-minute tumbling window to detect 3+ card_linked events
// from the same user within 1 hour.
//
// Conditions:
//   - 3+ card_linked events from the same user within 60 min
//
// Simplest signal — pure windowed aggregation with no $lookup.
// No topup correlation needed. Rapid card linking is suspicious
// on its own regardless of other activity.
// ============================================================

// Step 1: Source from Kafka with timeField for windowed processing
let source = {
  $source: {
    connectionName: "UtilitymskKafkaConnection",
    topic: "FuelRetail-fraud-events",
    timeField: { $toDate: "$timestamp" },
    partitionIdleTimeout: { size: 5, unit: "second" }
  }
};

// Step 2: Filter to card_linked events only
let matchCardLinked = {
  $match: {
    name: "card_linked"
  }
};

// Step 3: Group by user within the window, count and collect card details
let groupByUser = {
  $group: {
    _id: "$user_id",
    cardCount: { $sum: 1 },
    cards: {
      $push: {
        eventId: "$eventId",
        name: "$name",
        timestamp: "$timestamp",
        properties: "$properties"
      }
    }
  }
};

// Step 4: Only emit when 3+ cards linked in window
let matchRapidLinking = {
  $match: {
    cardCount: { $gte: 3 }
  }
};

// Step 5: 60-minute tumbling window wrapping the group + filter
let tumblingWindowStage = {
  $tumblingWindow: {
    interval: { size: 2, unit: "minute" },  // PRODUCTION: 60 minute
    pipeline: [
      groupByUser,
      matchRapidLinking
    ]
  }
};

// ── HOPPING WINDOW ALTERNATIVE ──────────────────────────────
// To switch to hopping windows, replace tumblingWindowStage with:
//
// let hoppingWindowStage = {
//   $hoppingWindow: {
//     interval: { size: 60, unit: "minute" },
//     hopSize:  { size: 15, unit: "minute" },  // window advances every 15 min
//     pipeline: [
//       groupByUser,
//       matchRapidLinking
//     ]
//   }
// };
//
// What this changes:
//   - Tumbling: 3 cards linked at minutes 55, 61, 62 — the first lands in
//     window [0-60], the other two in [60-120]. Neither window hits the
//     threshold of 3. The cluster is MISSED.
//   - Hopping (60-min interval, 15-min hop): overlapping windows ensure
//     that cluster is captured by window [15-75]. Fewer missed detections.
//
// *** CAUTION — DUPLICATE ALERTS ***
//   Same issue as S03: this pipeline writes to fraud_alerts with no dedup
//   key. Overlapping windows will produce multiple alert documents for the
//   same card-linking burst.
//
//   To mitigate, either:
//   (a) Add a deterministic alertId and merge with on:"alertId" —
//       let mergeStage = {
//         $merge: {
//           into: { connectionName: "FuelRetail_cluster", db: "FuelRetail_fraud", coll: "fraud_alerts" },
//           on: "alertId",
//           whenMatched: "merge"
//         }
//       };
//   (b) Or dedup downstream in the query/UI layer.
//
// Then update the deploy line to use hoppingWindowStage:
//   sp.createStreamProcessor("FuelRetail-signal-s04",
//     [source, matchCardLinked, hoppingWindowStage, buildAlert, projectAlert, mergeStage]);
// ─────────────────────────────────────────────────────────────

// Step 6: Build the alert document
let buildAlert = {
  $addFields: {
    alertId: { $concat: ["alert-s04-", { $toString: "$_id" }, "-", { $toString: "$$NOW" }] },
    userId: "$_id",
    signal: "S04",
    severity: "medium",
    status: "open",
    details: "3+ cards linked within 1 hour",
    events: "$cards",
    ruleSnapshot: {
      cardCountThreshold: 3,
      velocityWindowMinutes: 60
    },
    createdAt: "$$NOW"
  }
};

// Step 7: Project only alert fields
let projectAlert = {
  $project: {
    alertId: 1,
    userId: 1,
    signal: 1,
    severity: 1,
    status: 1,
    details: 1,
    events: 1,
    ruleSnapshot: 1,
    cardCount: 1,
    createdAt: 1
  }
};

// Step 8: Write alert to fraud_alerts collection
let mergeStage = {
  $merge: {
    into: {
      connectionName: "FuelRetail_cluster",
      db: "FuelRetail_fraud",
      coll: "fraud_alerts"
    }
  }
};

// ── Deploy Commands ──────────────────────────────────────────
// Run in mongosh connected to ASP workspace:
// mongosh "mongodb+srv://<user>:<password>@<cluster>.mongodb.net/<db>"
//
// 1. Stop & drop existing processor (if running):
//    sp["FuelRetail-signal-s04"].stop();
//    sp["FuelRetail-signal-s04"].drop();
//
// 2. Create the stream processor:
sp.createStreamProcessor("FuelRetail-signal-s04", [source, matchCardLinked, tumblingWindowStage, buildAlert, projectAlert, mergeStage]);
//
// 3. Start:
//    sp["FuelRetail-signal-s04"].start();
//
// 4. Verify:
//    sp["FuelRetail-signal-s04"].stats();
