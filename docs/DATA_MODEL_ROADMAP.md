# Data Model Roadmap

## Current v3.1 Model

The current model keeps the original MVP assumption: one normalized order fact stream is enough to power the current operating review, evidence chain, reports and Agent context.

SQLite stores:

- normalized order rows and dataset metadata;
- metric snapshots;
- anomalies, diagnoses, recommendations and insights;
- evidence bundles;
- opportunities, action items and work item state;
- report and topic-detail supporting artifacts.

No schema migration is required for the v3.1.1 architecture refactor.

## v3.2 Import Intelligence

The next step is smarter import confirmation, not a new commercial model.

Planned additions:

- detect order vs. order-item grain;
- recommend amount semantics in business language;
- hide technical options by default;
- ask business-language confirmation when confidence is low.

## v4.0 Multi-Source Commercial Model

v4.0 should introduce separate domain tables when the product is ready to analyze channels, campaigns, inventory, refunds, logistics and store operations as first-class facts.

Candidate tables:

- orders and order lines;
- ad campaign spend;
- inventory snapshots;
- refunds;
- logistics fulfillment;
- channels, stores, products and other dimensions.

This change should be designed as a migration with explicit compatibility tests and is outside the v3.1.1 architecture refactor.
