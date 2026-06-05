// ============================================================
// Signal S02 — InstantTransfer Payment After Top-Up
// Windowless. For every qualifying InstantTransfer_payment event,
// does a $lookup against user_profiles to check if the user
// recently topped up (within 30 minutes).
//
// Conditions:
//   - InstantTransfer payment > RM500
//   - Payment type is NOT ewallet (bank transfer InstantTransfer only)
//   - User had a top-up within the last 30 minutes
//     (checked via fraud.lastTopupAt in user_profiles,
//      written by topup_state_writer.js)
//
// Why windowless: Each payment is checked individually on
// arrival. The 30-minute condition is a timestamp comparison
// against the stored lastTopupAt state, not a stream window.
// This avoids the complexity of co-grouping different event
// types in a single window.
// ============================================================

// Step 1: Source from Kafka (windowless — no timeField needed)
let source = {
  $source: {
    connectionName: "UtilitymskKafkaConnection",
    topic: "FuelRetail-fraud-events"
  }
};

// Step 2: Filter to qualifying InstantTransfer payments
let matchPayments = {
  $match: {
    name: "InstantTransfer_payment",
    "properties.amount": { $gt: 500 },
    "properties.type": { $ne: "ewallet" }
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

// Step 4: Unwind the lookup result
let unwindProfile = {
  $unwind: "$userProfile"
};

// Step 5: Check that user has a recent topup (lastTopupAt exists
// and is within 30 minutes of the payment timestamp)
let matchRecentTopup = {
  $match: {
    "userProfile.fraud.lastTopupAt": { $exists: true },
    $expr: {
      $lte: [
        {
          $dateDiff: {
            startDate: { $toDate: "$userProfile.fraud.lastTopupAt" },
            endDate: { $toDate: "$timestamp" },
            unit: "minute"
          }
        },
        30
      ]
    }
  }
};

// Step 6: Build the alert document
let buildAlert = {
  $addFields: {
    alertId: { $concat: ["alert-s02-", { $toString: "$user_id" }, "-", { $toString: { $toDate: "$_ts" } }] },
    userId: "$user_id",
    signal: "S02",
    severity: "high",
    status: "open",
    details: "InstantTransfer payment > RM500 (bank transfer) within 30min after top-up",
    ruleSnapshot: {
      amountThreshold: 500,
      windowMinutes: 30
    },
    topupInfo: {
      lastTopupAt: "$userProfile.fraud.lastTopupAt",
      lastTopupAmount: "$userProfile.fraud.lastTopupAmount",
      lastTopupType: "$userProfile.fraud.lastTopupType"
    },
    events: [
      {
        eventId: "$eventId",
        name: "$name",
        amount: "$properties.amount",
        timestamp: "$timestamp",
        properties: "$properties"
      }
    ],
    createdAt: { $toDate: "$_ts" }
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
    ruleSnapshot: 1,
    topupInfo: 1,
    events: 1,
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
//    sp["FuelRetail-signal-s02"].stop();
//    sp["FuelRetail-signal-s02"].drop();
//
// 2. Create the stream processor:
sp.createStreamProcessor("FuelRetail-signal-s02", [source, matchPayments, lookupUserProfile, unwindProfile, matchRecentTopup, buildAlert, projectAlert, mergeStage]);
//
// 3. Start:
//    sp["FuelRetail-signal-s02"].start();
//
// 4. Verify:
//    sp["FuelRetail-signal-s02"].stats();
