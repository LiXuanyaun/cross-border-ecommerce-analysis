import sqlite3

from crossborder_analytics.multibusiness_schema import (
    SCHEMA_VERSION,
    foreign_key_violations,
    migrate_multibusiness_schema,
)


BUSINESS_TABLES = {
    "dim_campaign",
    "dim_carrier",
    "dim_return_reason",
    "fact_ad_performance_daily",
    "bridge_order_attribution",
    "fact_returns",
    "fact_shipments",
    "fact_tracking_events",
}


def test_v4_migration_creates_independent_business_tables_and_provenance(tmp_path):
    path = tmp_path / "v4.db"
    migrate_multibusiness_schema(path)

    with sqlite3.connect(path) as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert BUSINESS_TABLES <= tables
        assert {"import_batches", "import_files", "business_orders", "business_order_lines"} <= tables
        assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        for table in BUSINESS_TABLES:
            columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
            assert {
                "dataset_id",
                "import_batch_id",
                "data_origin",
                "scenario_id",
                "generator_version",
            } <= columns


def test_v4_schema_registers_foreign_keys_and_is_repeatable(tmp_path):
    path = tmp_path / "v4.db"
    migrate_multibusiness_schema(path)
    migrate_multibusiness_schema(path)

    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA foreign_key_list(fact_returns)").fetchall()
        assert connection.execute("PRAGMA foreign_key_list(fact_tracking_events)").fetchall()
        assert connection.execute("PRAGMA foreign_key_list(bridge_order_attribution)").fetchall()
    assert foreign_key_violations(path) == []
