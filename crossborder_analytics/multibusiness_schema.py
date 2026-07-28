"""SQLite v4 schema for advertising, returns and logistics facts."""
from __future__ import annotations

from contextlib import closing
from pathlib import Path
import sqlite3


SCHEMA_VERSION = 4


DDL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS import_batches (
    import_batch_id TEXT PRIMARY KEY,
    dataset_id TEXT NOT NULL,
    status TEXT NOT NULL,
    data_origin TEXT NOT NULL,
    scenario_id TEXT NOT NULL,
    generator_version TEXT NOT NULL,
    source_version TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    warning_count INTEGER NOT NULL DEFAULT 0,
    error_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS import_files (
    import_file_id TEXT PRIMARY KEY,
    import_batch_id TEXT NOT NULL,
    dataset_id TEXT NOT NULL,
    filename TEXT NOT NULL,
    file_sha256 TEXT NOT NULL,
    file_type TEXT NOT NULL,
    grain_description TEXT NOT NULL,
    data_origin TEXT NOT NULL,
    scenario_id TEXT NOT NULL,
    generator_version TEXT NOT NULL,
    source_version TEXT NOT NULL,
    source_row_count INTEGER NOT NULL,
    inserted_row_count INTEGER NOT NULL DEFAULT 0,
    duplicate_row_count INTEGER NOT NULL DEFAULT 0,
    imported_at TEXT NOT NULL,
    FOREIGN KEY (import_batch_id) REFERENCES import_batches(import_batch_id),
    UNIQUE (dataset_id, file_sha256, file_type)
);

CREATE TABLE IF NOT EXISTS business_orders (
    dataset_id TEXT NOT NULL,
    sales_order_number TEXT NOT NULL,
    import_batch_id TEXT NOT NULL,
    data_origin TEXT NOT NULL,
    scenario_id TEXT NOT NULL,
    generator_version TEXT NOT NULL,
    PRIMARY KEY (dataset_id, sales_order_number),
    FOREIGN KEY (import_batch_id) REFERENCES import_batches(import_batch_id)
);

CREATE TABLE IF NOT EXISTS business_order_lines (
    dataset_id TEXT NOT NULL,
    sales_order_number TEXT NOT NULL,
    sales_order_line_number INTEGER NOT NULL,
    record_id TEXT NOT NULL,
    import_batch_id TEXT NOT NULL,
    data_origin TEXT NOT NULL,
    scenario_id TEXT NOT NULL,
    generator_version TEXT NOT NULL,
    PRIMARY KEY (dataset_id, sales_order_number, sales_order_line_number),
    FOREIGN KEY (dataset_id, sales_order_number) REFERENCES business_orders(dataset_id, sales_order_number),
    FOREIGN KEY (dataset_id, record_id) REFERENCES orders(dataset_id, record_id),
    FOREIGN KEY (import_batch_id) REFERENCES import_batches(import_batch_id)
);

CREATE TABLE IF NOT EXISTS dim_campaign (
    dataset_id TEXT NOT NULL,
    campaign_id TEXT NOT NULL,
    campaign_name TEXT NOT NULL,
    channel TEXT NOT NULL,
    platform TEXT NOT NULL,
    objective TEXT,
    target_country_code TEXT,
    target_country TEXT,
    sales_territory_key_scope TEXT,
    billing_currency TEXT NOT NULL,
    active_start_date TEXT,
    active_end_date TEXT,
    import_batch_id TEXT NOT NULL,
    data_origin TEXT NOT NULL,
    scenario_id TEXT NOT NULL,
    generator_version TEXT NOT NULL,
    source_campaign_id TEXT NOT NULL,
    synthetic_note TEXT,
    PRIMARY KEY (dataset_id, campaign_id),
    FOREIGN KEY (import_batch_id) REFERENCES import_batches(import_batch_id)
);

CREATE TABLE IF NOT EXISTS dim_carrier (
    dataset_id TEXT NOT NULL,
    carrier_id TEXT NOT NULL,
    carrier_name TEXT NOT NULL,
    service_level TEXT,
    carrier_type TEXT,
    import_batch_id TEXT NOT NULL,
    data_origin TEXT NOT NULL,
    scenario_id TEXT NOT NULL,
    generator_version TEXT NOT NULL,
    source_carrier_id TEXT NOT NULL,
    synthetic_note TEXT,
    PRIMARY KEY (dataset_id, carrier_id),
    FOREIGN KEY (import_batch_id) REFERENCES import_batches(import_batch_id)
);

CREATE TABLE IF NOT EXISTS dim_return_reason (
    dataset_id TEXT NOT NULL,
    return_reason_id TEXT NOT NULL,
    return_reason_code TEXT NOT NULL,
    reason_category TEXT NOT NULL,
    reason_description TEXT,
    import_batch_id TEXT NOT NULL,
    data_origin TEXT NOT NULL,
    scenario_id TEXT NOT NULL,
    generator_version TEXT NOT NULL,
    source_return_reason_id TEXT NOT NULL,
    synthetic_note TEXT,
    PRIMARY KEY (dataset_id, return_reason_id),
    FOREIGN KEY (import_batch_id) REFERENCES import_batches(import_batch_id)
);

CREATE TABLE IF NOT EXISTS fact_ad_performance_daily (
    dataset_id TEXT NOT NULL,
    ad_date TEXT NOT NULL,
    campaign_id TEXT NOT NULL,
    target_country_code TEXT,
    channel TEXT NOT NULL,
    platform TEXT NOT NULL,
    billing_currency TEXT NOT NULL CHECK (billing_currency = 'USD'),
    impressions INTEGER NOT NULL CHECK (impressions >= 0),
    clicks INTEGER NOT NULL CHECK (clicks >= 0 AND clicks <= impressions),
    conversions INTEGER NOT NULL CHECK (conversions >= 0 AND conversions <= clicks),
    spend_usd REAL NOT NULL CHECK (spend_usd >= 0),
    attributed_revenue_usd REAL NOT NULL CHECK (attributed_revenue_usd >= 0),
    import_batch_id TEXT NOT NULL,
    data_origin TEXT NOT NULL,
    scenario_id TEXT NOT NULL,
    generator_version TEXT NOT NULL,
    source_campaign_id TEXT NOT NULL,
    source_ad_date TEXT NOT NULL,
    synthetic_note TEXT,
    PRIMARY KEY (dataset_id, ad_date, campaign_id),
    FOREIGN KEY (dataset_id, campaign_id) REFERENCES dim_campaign(dataset_id, campaign_id),
    FOREIGN KEY (import_batch_id) REFERENCES import_batches(import_batch_id)
);

CREATE TABLE IF NOT EXISTS bridge_order_attribution (
    dataset_id TEXT NOT NULL,
    attribution_id TEXT NOT NULL,
    sales_order_number TEXT NOT NULL,
    customer_key TEXT,
    sales_territory_key TEXT,
    campaign_id TEXT NOT NULL,
    touchpoint_date TEXT,
    conversion_date TEXT,
    attribution_model TEXT NOT NULL,
    attribution_credit REAL NOT NULL CHECK (attribution_credit >= 0 AND attribution_credit <= 1),
    order_currency_key TEXT,
    attributed_revenue_order_currency REAL,
    usd_average_rate REAL,
    attributed_revenue_usd REAL NOT NULL CHECK (attributed_revenue_usd >= 0),
    currency_basis TEXT NOT NULL,
    import_batch_id TEXT NOT NULL,
    data_origin TEXT NOT NULL,
    scenario_id TEXT NOT NULL,
    generator_version TEXT NOT NULL,
    source_attribution_id TEXT NOT NULL,
    source_sales_order_number TEXT NOT NULL,
    synthetic_note TEXT,
    PRIMARY KEY (dataset_id, attribution_id),
    FOREIGN KEY (dataset_id, sales_order_number) REFERENCES business_orders(dataset_id, sales_order_number),
    FOREIGN KEY (dataset_id, campaign_id) REFERENCES dim_campaign(dataset_id, campaign_id),
    FOREIGN KEY (import_batch_id) REFERENCES import_batches(import_batch_id)
);

CREATE TABLE IF NOT EXISTS fact_shipments (
    dataset_id TEXT NOT NULL,
    shipment_id TEXT NOT NULL,
    sales_order_number TEXT NOT NULL,
    customer_key TEXT,
    sales_territory_key TEXT,
    origin_country TEXT NOT NULL,
    destination_country TEXT NOT NULL,
    destination_region TEXT,
    carrier_id TEXT NOT NULL,
    carrier_name TEXT NOT NULL,
    service_level TEXT,
    tracking_number TEXT NOT NULL,
    ship_date TEXT NOT NULL,
    promised_delivery_date TEXT NOT NULL,
    actual_delivery_date TEXT,
    transit_days REAL,
    delay_days REAL NOT NULL,
    on_time_flag INTEGER NOT NULL CHECK (on_time_flag IN (0, 1)),
    cross_border_flag INTEGER NOT NULL CHECK (cross_border_flag IN (0, 1)),
    customs_delay_days REAL NOT NULL,
    shipment_status TEXT NOT NULL,
    order_line_count INTEGER NOT NULL,
    freight_amount REAL,
    import_batch_id TEXT NOT NULL,
    data_origin TEXT NOT NULL,
    scenario_id TEXT NOT NULL,
    generator_version TEXT NOT NULL,
    source_shipment_id TEXT NOT NULL,
    source_sales_order_number TEXT NOT NULL,
    synthetic_note TEXT,
    PRIMARY KEY (dataset_id, shipment_id),
    FOREIGN KEY (dataset_id, sales_order_number) REFERENCES business_orders(dataset_id, sales_order_number),
    FOREIGN KEY (dataset_id, carrier_id) REFERENCES dim_carrier(dataset_id, carrier_id),
    FOREIGN KEY (import_batch_id) REFERENCES import_batches(import_batch_id)
);

CREATE TABLE IF NOT EXISTS fact_returns (
    dataset_id TEXT NOT NULL,
    return_id TEXT NOT NULL,
    sales_order_number TEXT NOT NULL,
    sales_order_line_number INTEGER NOT NULL,
    shipment_id TEXT NOT NULL,
    customer_key TEXT,
    product_key TEXT,
    product_category_key TEXT,
    sales_territory_key TEXT,
    currency_key TEXT,
    return_reason_id TEXT NOT NULL,
    return_request_date TEXT NOT NULL,
    return_received_date TEXT,
    refund_date TEXT,
    original_order_quantity INTEGER NOT NULL,
    return_quantity INTEGER NOT NULL CHECK (return_quantity > 0 AND return_quantity <= original_order_quantity),
    original_line_sales_amount REAL NOT NULL,
    refund_amount REAL NOT NULL CHECK (refund_amount >= 0 AND refund_amount <= original_line_sales_amount),
    resolution TEXT,
    return_status TEXT,
    import_batch_id TEXT NOT NULL,
    data_origin TEXT NOT NULL,
    scenario_id TEXT NOT NULL,
    generator_version TEXT NOT NULL,
    source_return_id TEXT NOT NULL,
    source_sales_order_number TEXT NOT NULL,
    source_sales_order_line_number INTEGER NOT NULL,
    synthetic_note TEXT,
    PRIMARY KEY (dataset_id, return_id),
    FOREIGN KEY (dataset_id, sales_order_number, sales_order_line_number)
        REFERENCES business_order_lines(dataset_id, sales_order_number, sales_order_line_number),
    FOREIGN KEY (dataset_id, shipment_id) REFERENCES fact_shipments(dataset_id, shipment_id),
    FOREIGN KEY (dataset_id, return_reason_id) REFERENCES dim_return_reason(dataset_id, return_reason_id),
    FOREIGN KEY (import_batch_id) REFERENCES import_batches(import_batch_id)
);

CREATE TABLE IF NOT EXISTS fact_tracking_events (
    dataset_id TEXT NOT NULL,
    tracking_event_id TEXT NOT NULL,
    shipment_id TEXT NOT NULL,
    sales_order_number TEXT NOT NULL,
    tracking_number TEXT NOT NULL,
    event_sequence INTEGER NOT NULL CHECK (event_sequence > 0),
    event_code TEXT NOT NULL,
    event_timestamp TEXT NOT NULL,
    event_location TEXT,
    carrier_id TEXT NOT NULL,
    cross_border_flag INTEGER NOT NULL CHECK (cross_border_flag IN (0, 1)),
    exception_flag INTEGER NOT NULL CHECK (exception_flag IN (0, 1)),
    import_batch_id TEXT NOT NULL,
    data_origin TEXT NOT NULL,
    scenario_id TEXT NOT NULL,
    generator_version TEXT NOT NULL,
    source_tracking_event_id TEXT NOT NULL,
    source_shipment_id TEXT NOT NULL,
    synthetic_note TEXT,
    PRIMARY KEY (dataset_id, tracking_event_id),
    UNIQUE (dataset_id, shipment_id, event_sequence),
    FOREIGN KEY (dataset_id, shipment_id) REFERENCES fact_shipments(dataset_id, shipment_id),
    FOREIGN KEY (dataset_id, carrier_id) REFERENCES dim_carrier(dataset_id, carrier_id),
    FOREIGN KEY (import_batch_id) REFERENCES import_batches(import_batch_id)
);

CREATE INDEX IF NOT EXISTS idx_ad_daily_scope ON fact_ad_performance_daily(dataset_id, ad_date, campaign_id);
CREATE INDEX IF NOT EXISTS idx_attribution_order ON bridge_order_attribution(dataset_id, sales_order_number);
CREATE INDEX IF NOT EXISTS idx_returns_scope ON fact_returns(dataset_id, return_request_date, product_category_key);
CREATE INDEX IF NOT EXISTS idx_shipments_scope ON fact_shipments(dataset_id, ship_date, carrier_id, destination_region);
CREATE INDEX IF NOT EXISTS idx_tracking_shipment_time ON fact_tracking_events(dataset_id, shipment_id, event_timestamp);
"""


def migrate_multibusiness_schema(path: str | Path) -> None:
    """Create the v4 tables without changing or deleting existing order facts."""
    database_path = Path(path)
    database_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(str(database_path))) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(DDL)
        connection.execute("PRAGMA user_version = {}".format(SCHEMA_VERSION))
        connection.commit()


def foreign_key_violations(path: str | Path) -> list[tuple]:
    with closing(sqlite3.connect(str(path))) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        return list(connection.execute("PRAGMA foreign_key_check"))
