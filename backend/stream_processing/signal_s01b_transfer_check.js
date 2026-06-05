// ============================================================
// Signal S01 — Stage 2: InstantTransfer Transfer Check
// Windowless. For every InstantTransfer_transfer_out event, does a
// $lookup against user_profiles to check:
//   1. Is fraud.signals.s01.topupBurstDetected == true?
//   2. Is the transfer within 30 minutes of lastBurstAt?
//
// If both conditions match, writes S01 alert to fraud_alerts.
//
// Why no window: Each InstantTransfer transfer is checked individually
// on arrival. The 30-minute condition is a timestamp comparison
// against stored state, not a stream window. This is event
// enrichment, not windowed aggregation.
//
// This is stage 2 of the S01 two-stage detection pattern.
// Stage 1 (signal_s01a_topup_cluster.js) writes the state;
// this pipeline reads it via $lookup.
// ============================================================

// Step 1: Source from Kafka (windowless — no timeField needed)
let source = {
  $source: {
    connectionName: "UtilitymskKafkaConnection",
    topic: "FuelRetail-fraud-events"
  }
};

// Step 2: Filter to InstantTransfer transfer out events only
let matchTransfers = {
  $match: {
    name: "InstantTransfer_transfer_out"
  }
};

// Step 3: Enrich with user profile state via $lookup
let lookupUserProfile = {
  $lookup: {
    from: {
      connectionName: "FuelRetail_cluster",
      db: "FuelRetail_fraud",
      coll: "user_profiles"
    },
    localField: "user_id",
    foreignField: "userId",
    as: "userProfile"
  }
};

// Step 4: Unwind the lookup result (1:1 relationship)
let unwindProfile = {
  $unwind: "$userProfile"
};

// Step 5: Check S01 condition — cluster detected
let matchClusterDetected = {
  $match: {
    "userProfile.fraud.signals.s01.topupBurstDetected": true
  }
};

// Step 6: Check S01 condition — transfer within 30 min of cluster
let matchWithinWindow = {
  $match: {
    $expr: {
      $lte: [
        {
          $dateDiff: {
            startDate: { $toDate: "$userProfile.fraud.signals.s01.lastBurstAt" },
            endDate: { $toDate: "$timestamp" },
            unit: "minute"
          }
        },
        30
      ]
    }
  }
};

// Step 7: Build the alert document
let buildAlert = {
  $addFields: {
    alertId: { $concat: ["alert-s01-", { $toString: "$user_id" }, "-", { $toString: { $toDate: "$_ts" } }] },
    userId: "$user_id",
    signal: "S01",
    severity: "critical",
    status: "open",
    details: "Auto top-up >= RM500 x 2+ within 15min + InstantTransfer transfer out within 30min",
    ruleSnapshot: {
      topupAmountThreshold: 500,
      topupCountThreshold: 2,
      topupWindowMinutes: 15,
      transferWindowMinutes: 30
    },
    events: {
      $concatArrays: [
        "$userProfile.fraud.signals.s01.recentHighTopups",
        [{
          eventId: "$eventId",
          name: "$name",
          amount: "$properties.amount",
          timestamp: "$timestamp",
          properties: "$properties"
        }]
      ]
    },
    createdAt: { $toDate: "$_ts" }
  }
};

// Step 8: Project only alert fields
let projectAlert = {
  $project: {
    alertId: 1,
    userId: 1,
    signal: 1,
    severity: 1,
    status: 1,
    details: 1,
    ruleSnapshot: 1,
    events: 1,
    createdAt: 1
  }
};

// Step 9: Write alert to fraud_alerts collection
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
//    sp["FuelRetail-signal-s01b"].stop();
//    sp["FuelRetail-signal-s01b"].drop();
//
// 2. Create the stream processor:
sp.createStreamProcessor("FuelRetail-signal-s01b", [source, matchTransfers, lookupUserProfile, unwindProfile, matchClusterDetected, matchWithinWindow, buildAlert, projectAlert, mergeStage]);
//
// 3. Start:
//    sp["FuelRetail-signal-s01b"].start();
//
// 4. Verify:
//    sp["FuelRetail-signal-s01b"].stats();
