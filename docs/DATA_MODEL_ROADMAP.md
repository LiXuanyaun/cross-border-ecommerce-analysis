# Data Model Roadmap

## Current v4.0 Model

The compatible normalized `orders` stream continues to power existing order analysis. v4 adds independent business grains for AdventureWorks-linked advertising, returns and logistics; it does not overload the order fact.

SQLite stores:

- normalized order rows and dataset metadata;
- metric snapshots;
- anomalies, diagnoses, recommendations and insights;
- evidence bundles;
- opportunities, action items and work item state;
- report and topic-detail supporting artifacts.
- `business_orders` and `business_order_lines` retain `SalesOrderNumber` and `SalesOrderLineNumber` links.
- `dim_campaign`, `dim_carrier`, `dim_return_reason` hold reusable advertising, carrier and return-reason dimensions.
- `fact_ad_performance_daily`, `bridge_order_attribution`, `fact_returns`, `fact_shipments` and `fact_tracking_events` hold their respective grains.
- `import_batches` and `import_files` preserve source version, SHA-256 hash, batch status and row-level import results.

All v4 business tables carry `dataset_id`, `import_batch_id`, `data_origin`, `scenario_id`, `generator_version` and raw source linkage keys. Foreign keys enforce valid order, campaign, carrier, return-reason and shipment relationships.

## Import And Quality Controls

Implemented controls:

- recognize order, dimension, advertising performance, attribution, return, shipment and tracking files;
- show field preview, grain, association rates, source origin and simulated-data disclosure before commit;
- reject missing associations, attribution credit above one, invalid click/conversion funnels, refund caps, invalid event sequence/timestamps and domestic customs events;
- use file SHA-256 plus natural business keys to make re-import idempotent.

## Future Scope

Inventory, store and marketplace connector facts remain out of v4.0. Any future source must retain the same provenance columns, respect dataset isolation and register metrics/evidence before it can appear in Dashboard, reports or Agent context.
