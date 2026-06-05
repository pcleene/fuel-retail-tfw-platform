// ============================================================
// Signal S01 — Stage 1: Top-Up Cluster Detection
// Detects 2+ auto top-ups >= RM500 within a 15-minute window.
//
// When detected, writes intermediate state to the user's
// fraud.signals.s01 sub-document in user_profiles. This state
// is then read by Pipeline S01b (signal_s01b_transfer_check.js)
// via $lookup to complete the S01 two-stage detection.
//
// What gets written to user_profiles:
//   fraud.signals.s01.topupBurstDetected: true
//   fraud.signals.s01.lastBurstAt: timestamp of last topup
//   fraud.signals.s01.topupCount: number of qualifying topups
//   fraud.signals.s01.intervalSeconds: time between first/last
//   fraud.signals.s01.recentHighTopups[]: qualifying events
//
// This is the showcase — genuine multi-window detection
// that KSQL cannot do cleanly.
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

// Step 2: Filter to auto_topup events >= RM500
let matchHighTopups = {
  $match: {
    name: "auto_topup",
    "properties.amount": { $gte: 500 }
  }
};

// Step 3: Group by user within 15-minute tumbling window
let groupByUser = {
  $group: {
    _id: "$user_id",
    topupCount: { $sum: 1 },
    firstTopupAt: { $min: "$timestamp" },
    lastTopupAt: { $max: "$timestamp" },
    recentHighTopups: {
      $push: {
        eventId: "$eventId",
        amount: "$properties.amount",
        timestamp: "$timestamp",
        source: "$properties.source"
      }
    }
  }
};

// Step 4: Only emit when 2+ topups detected in window
let matchCluster = {
  $match: {
    topupCount: { $gte: 2 }
  }
};

// Step 5: Compute interval between first and last topup
let computeInterval = {
  $addFields: {
    intervalSeconds: {
      $dateDiff: {
        startDate: { $toDate: "$firstTopupAt" },
        endDate: { $toDate: "$lastTopupAt" },
        unit: "second"
      }
    }
  }
};

// Step 6: 15-minute tumbling window wrapping the group + filter
let tumblingWindowStage = {
  $tumblingWindow: {
    interval: { size: 1, unit: "minute" },  // PRODUCTION: 15 minute
    pipeline: [
      groupByUser,
      matchCluster,
      computeInterval
    ]
  }
};

// ── HOPPING WINDOW ALTERNATIVE ──────────────────────────────
// To switch to hopping windows, replace tumblingWindowStage with:
//
// let hoppingWindowStage = {
//   $hoppingWindow: {
//     interval: { size: 15, unit: "minute" },
//     hopSize:  { size: 5,  unit: "minute" },  // window advances every 5 min
//     pipeline: [
//       groupByUser,
//       matchCluster,
//       computeInterval
//     ]
//   }
// };
//
// What this changes:
//   - Tumbling: one 15-min window fires, then the next starts at minute 15.
//     An event at minute 14 and one at minute 16 land in DIFFERENT windows.
//   - Hopping (15-min interval, 5-min hop): a new 15-min window opens every
//     5 minutes. An event at minute 14 appears in windows [0-15], [5-20],
//     and [10-25]. This catches clusters that straddle tumbling boundaries.
//
// Impact on THIS pipeline: LOW RISK
//   The $merge uses on:"userId" + whenMatched:"merge", so overlapping
//   windows just overwrite the same user_profiles document with the
//   latest state. Last write wins — no duplicate documents created.
//   Actually slightly beneficial: burst state stays fresher.
//
// Then update the deploy line to use hoppingWindowStage:
//   sp.createStreamProcessor("FuelRetail-signal-s01a",
//     [source, matchHighTopups, hoppingWindowStage, projectForMerge, mergeStage]);
// ─────────────────────────────────────────────────────────────

// Step 7: Reshape for user_profiles merge
// Write intermediate state to fraud.signals.s01
let projectForMerge = {
  $project: {
    userId: "$_id",
    "fraud.signals.s01.topupBurstDetected": { $literal: true },
    "fraud.signals.s01.lastBurstAt": "$lastTopupAt",
    "fraud.signals.s01.topupCount": "$topupCount",
    "fraud.signals.s01.intervalSeconds": "$intervalSeconds",
    "fraud.signals.s01.recentHighTopups": "$recentHighTopups"
  }
};

// Step 8: Merge into user_profiles
let mergeStage = {
  $merge: {
    into: {
      connectionName: "FuelRetail_cluster",
      db: "FuelRetail_fraud",
      coll: "user_profiles"
    },
    on: "userId",
    whenMatched: "merge"
  }
};

// ── Deploy Commands ──────────────────────────────────────────
// Run in mongosh connected to ASP workspace:
// mongosh "mongodb+srv://<user>:<password>@<cluster>.mongodb.net/<db>"
//
// 1. Stop & drop existing processor (if running):
//    sp["FuelRetail-signal-s01a"].stop();
//    sp["FuelRetail-signal-s01a"].drop();
//
// 2. Create the stream processor:
sp.createStreamProcessor("FuelRetail-signal-s01a", [source, matchHighTopups, tumblingWindowStage, projectForMerge, mergeStage]);
//
// 3. Start:
//    sp["FuelRetail-signal-s01a"].start();
//
// 4. Verify:
//    sp["FuelRetail-signal-s01a"].stats();
