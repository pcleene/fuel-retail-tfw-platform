// ============================================================
// Event Ingestion Passthrough Stream Processor
// Pipes all raw Kafka events into the FuelRetail_fraud.events
// collection with an _ingestedAt timestamp for dashboard feed.
//
// Windowless — no aggregation, no filtering.
// Every event from the FuelRetail-fraud-events topic is written
// as-is with an ingestion timestamp.
// ============================================================

// Step 1: Source from Kafka (windowless — no timeField needed)
let source = {
  $source: {
    connectionName: "UtilitymskKafkaConnection",
    topic: "FuelRetail-fraud-events"
  }
};

// Step 2: Add ingestion metadata
let addIngestionFields = {
  $addFields: {
    _ingestedAt: { $toDate: "$_ts" }
  }
};

// Step 3: Write to events collection
let mergeStage = {
  $merge: {
    into: {
      connectionName: "FuelRetail_cluster",
      db: "FuelRetail_fraud",
      coll: "asp_ingested_events"
    }
  }
};

// ── Deploy Commands ──────────────────────────────────────────
// Run in mongosh connected to ASP workspace:
// mongosh "mongodb+srv://<user>:<password>@<cluster>.mongodb.net/<db>"
//
// 1. Stop & drop existing processor (if running):
//    sp["FuelRetail-event-ingest"].stop();
//    sp["FuelRetail-event-ingest"].drop();
//
// 2. Create the stream processor:
sp.createStreamProcessor("FuelRetail-event-ingest", [source, addIngestionFields, mergeStage]);
//
// 3. Start:
//    sp["FuelRetail-event-ingest"].start();
//
// 4. Verify:
//    sp["FuelRetail-event-ingest"].stats();
