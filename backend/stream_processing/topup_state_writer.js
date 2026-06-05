// ============================================================
// Top-Up State Writer Stream Processor
// Updates user_profiles with the latest top-up information
// on every auto_topup or manual_topup event.
//
// Windowless — each top-up event immediately updates the
// user's fraud.lastTopupAt, fraud.lastTopupAmount, and
// fraud.lastTopupType fields in user_profiles. This state
// is consumed by S01b, S02, and S03 pipelines via $lookup.
// ============================================================

// Step 1: Source from Kafka (windowless — no timeField needed)
let source = {
  $source: {
    connectionName: "UtilitymskKafkaConnection",
    topic: "FuelRetail-fraud-events"
  }
};

// Step 2: Filter to top-up events only
let matchTopups = {
  $match: {
    name: { $in: ["auto_topup", "manual_topup"] }
  }
};

// Step 3: Reshape into user_profiles merge format
// Map user_id -> userId and nest topup info under fraud.*
let reshapeFields = {
  $addFields: {
    userId: "$user_id",
    "fraud.lastTopupAt": { $toDate: "$timestamp" },
    "fraud.lastTopupAmount": "$properties.amount",
    "fraud.lastTopupType": "$name"
  }
};

// Step 4: Project only the fields we want to merge
let projectStage = {
  $project: {
    userId: 1,
    "fraud.lastTopupAt": 1,
    "fraud.lastTopupAmount": 1,
    "fraud.lastTopupType": 1
  }
};

// Step 5: Merge into user_profiles, keyed on userId
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
//    sp["FuelRetail-topup-state-writer"].stop();
//    sp["FuelRetail-topup-state-writer"].drop();
//
// 2. Create the stream processor:
sp.createStreamProcessor("FuelRetail-topup-state-writer", [source, matchTopups, reshapeFields, projectStage, mergeStage]);
//
// 3. Start:
//    sp["FuelRetail-topup-state-writer"].start();
//
// 4. Verify:
//    sp["FuelRetail-topup-state-writer"].stats();
