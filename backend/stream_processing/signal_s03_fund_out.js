// ============================================================
// Signal S03 — Multiple Fund-Outs After Top-Up (HYBRID)
// 30-minute tumbling window for counting fund_out_transfer
// events, THEN $lookup against user_profiles to verify
// the user had a recent top-up.
//
// Conditions:
//   - 2+ fund_out_transfer events > RM500 within 30 minutes
//   - User had a top-up within 60 minutes of the window end
//     (60-min buffer to account for window boundary timing)
//
// Architecture: HYBRID approach —
//   Window: counts fund-out events per user (aggregation)
//   Lookup: checks user_profiles for recent topup (state)
//
// The topup state is written by topup_state_writer.js which
// updates fraud.lastTopupAt on every top-up event.
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

// Step 2: Filter to qualifying fund-out transfers
let matchFundOuts = {
  $match: {
    name: "fund_out_transfer",
    "properties.amount": { $gt: 500 }
  }
};

// Step 3: Group by user within the window, count and collect details
let groupByUser = {
  $group: {
    _id: "$user_id",
    fundOutCount: { $sum: 1 },
    totalAmount: { $sum: "$properties.amount" },
    windowEnd: { $max: "$timestamp" },
    fundOutDetails: {
      $push: {
        eventId: "$eventId",
        amount: "$properties.amount",
        timestamp: "$timestamp",
        recipient: "$properties.recipient"
      }
    }
  }
};

// Step 4: Only emit when 2+ fund-outs detected in window
let matchMultipleFundOuts = {
  $match: {
    fundOutCount: { $gte: 2 }
  }
};

// Step 5: 30-minute tumbling window wrapping the group + filter
let tumblingWindowStage = {
  $tumblingWindow: {
    interval: { size: 2, unit: "minute" },  // PRODUCTION: 30 minute
    pipeline: [
      groupByUser,
      matchMultipleFundOuts
    ]
  }
};

// ── HOPPING WINDOW ALTERNATIVE ──────────────────────────────
// To switch to hopping windows, replace tumblingWindowStage with:
//
// let hoppingWindowStage = {
//   $hoppingWindow: {
//     interval: { size: 30, unit: "minute" },
//     hopSize:  { size: 10, unit: "minute" },  // window advances every 10 min
//     pipeline: [
//       groupByUser,
//       matchMultipleFundOuts
//     ]
//   }
// };
//
// What this changes:
//   - Tumbling: fund-outs at minute 29 and minute 31 land in DIFFERENT
//     30-min windows and never trigger together.
//   - Hopping (30-min interval, 10-min hop): overlapping windows catch
//     clusters that straddle boundaries. Same events appear in multiple windows.
//
// *** CAUTION — DUPLICATE ALERTS ***
//   This pipeline writes to fraud_alerts WITHOUT a dedup key (no "on" field
//   in $merge). Each window flush creates a NEW alert document. With hopping
//   windows, the same fund-out cluster will generate multiple alerts (one per
//   overlapping window that captures it).
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
//   sp.createStreamProcessor("FuelRetail-signal-s03",
//     [source, matchFundOuts, hoppingWindowStage, lookupUserProfile, unwindProfile,
//      matchRecentTopup, buildAlert, projectAlert, mergeStage]);
// ─────────────────────────────────────────────────────────────

// Step 6: Lookup user_profiles to check for recent topup
let lookupUserProfile = {
  $lookup: {
    from: {
      connectionName: "FuelRetail_cluster",
      db: "FuelRetail_fraud",
      coll: "user_profiles"
    },
    localField: "_id",
    foreignField: "userId",
    as: "userProfile"
  }
};

// Step 7: Unwind the lookup result
let unwindProfile = {
  $unwind: "$userProfile"
};

// Step 8: Check that user has a recent topup (within 60 min of window end)
let matchRecentTopup = {
  $match: {
    "userProfile.fraud.lastTopupAt": { $exists: true },
    $expr: {
      $lte: [
        {
          $dateDiff: {
            startDate: { $toDate: "$userProfile.fraud.lastTopupAt" },
            endDate: { $toDate: "$windowEnd" },
            unit: "minute"
          }
        },
        60
      ]
    }
  }
};

// Step 9: Build the alert document
let buildAlert = {
  $addFields: {
    alertId: { $concat: ["alert-s03-", { $toString: "$_id" }, "-", { $toString: "$$NOW" }] },
    userId: "$_id",
    signal: "S03",
    severity: "high",
    status: "open",
    details: "2+ fund-out transfers > RM500 within 30min after top-up",
    ruleSnapshot: {
      amountThreshold: 500,
      countThreshold: 2,
      windowMinutes: 30
    },
    topupInfo: {
      lastTopupAt: "$userProfile.fraud.lastTopupAt",
      lastTopupAmount: "$userProfile.fraud.lastTopupAmount",
      lastTopupType: "$userProfile.fraud.lastTopupType"
    },
    events: "$fundOutDetails",
    createdAt: "$$NOW"
  }
};

// Step 10: Project only alert fields
let projectAlert = {
  $project: {
    alertId: 1,
    userId: 1,
    signal: 1,
    severity: 1,
    status: 1,
    details: 1,
    ruleSnapshot: 1,
    topupInfo: 1,
    events: 1,
    fundOutCount: 1,
    totalAmount: 1,
    createdAt: 1
  }
};

// Step 11: Write alert to fraud_alerts collection
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
//    sp["FuelRetail-signal-s03"].stop();
//    sp["FuelRetail-signal-s03"].drop();
//
// 2. Create the stream processor:
sp.createStreamProcessor("FuelRetail-signal-s03", [source, matchFundOuts, tumblingWindowStage, lookupUserProfile, unwindProfile, matchRecentTopup, buildAlert, projectAlert, mergeStage]);
//
// 3. Start:
//    sp["FuelRetail-signal-s03"].start();
//
// 4. Verify:
//    sp["FuelRetail-signal-s03"].stats();
