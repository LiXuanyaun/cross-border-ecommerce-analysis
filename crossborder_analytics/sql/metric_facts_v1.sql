SELECT
    date(order_date) AS order_day,
    /* MARKET */ AS market,
    COALESCE(NULLIF(TRIM(category), ''), '未标注品类') AS category,
    COALESCE(NULLIF(TRIM(product_id), ''), '未标注SKU') AS sku,
    order_id,
    customer_id,
    1 AS orders,
    COALESCE(total_amount_base, total_amount, 0.0) AS gmv,
    quantity AS units,
    COALESCE(profit_amount_base, profit_amount) AS profit,
    CASE WHEN returned = 1 THEN 1 ELSE 0 END AS returned_orders,
    CASE WHEN returned = 1 THEN COALESCE(total_amount_base, total_amount, 0.0) ELSE 0 END AS returned_gmv
FROM orders
WHERE /* FILTERS */
ORDER BY order_day, market, category, sku, customer_id, order_id;
