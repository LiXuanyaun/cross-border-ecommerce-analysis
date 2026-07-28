WITH filtered AS (
    SELECT * FROM orders WHERE /* FILTERS */
), combined AS (
    SELECT
        'summary' AS analysis_level,
        '' AS dimension,
        COUNT(DISTINCT order_id) AS orders,
        COUNT(DISTINCT CASE WHEN returned = 1 THEN order_id END) AS returned_orders,
        COALESCE(SUM(COALESCE(gmv_amount_base, total_amount_base, total_amount)), 0.0) AS gmv,
        COALESCE(SUM(CASE WHEN returned = 1 THEN COALESCE(gmv_amount_base, total_amount_base, total_amount) ELSE 0 END), 0.0) AS returned_gmv_exposure
    FROM filtered
    UNION ALL
    SELECT 'category', category, COUNT(DISTINCT order_id),
        COUNT(DISTINCT CASE WHEN returned = 1 THEN order_id END),
        COALESCE(SUM(COALESCE(gmv_amount_base, total_amount_base, total_amount)), 0.0),
        COALESCE(SUM(CASE WHEN returned = 1 THEN COALESCE(gmv_amount_base, total_amount_base, total_amount) ELSE 0 END), 0.0)
    FROM filtered WHERE category IS NOT NULL GROUP BY category
    UNION ALL
    SELECT 'region', /* MARKET */, COUNT(DISTINCT order_id),
        COUNT(DISTINCT CASE WHEN returned = 1 THEN order_id END),
        COALESCE(SUM(COALESCE(gmv_amount_base, total_amount_base, total_amount)), 0.0),
        COALESCE(SUM(CASE WHEN returned = 1 THEN COALESCE(gmv_amount_base, total_amount_base, total_amount) ELSE 0 END), 0.0)
    FROM filtered GROUP BY /* MARKET */
    UNION ALL
    SELECT 'month', strftime('%Y-%m', order_date), COUNT(DISTINCT order_id),
        COUNT(DISTINCT CASE WHEN returned = 1 THEN order_id END),
        COALESCE(SUM(COALESCE(gmv_amount_base, total_amount_base, total_amount)), 0.0),
        COALESCE(SUM(CASE WHEN returned = 1 THEN COALESCE(gmv_amount_base, total_amount_base, total_amount) ELSE 0 END), 0.0)
    FROM filtered GROUP BY strftime('%Y-%m', order_date)
)
SELECT * FROM combined;
