SELECT
    COALESCE(SUM(COALESCE(gmv_amount_base, total_amount_base, total_amount)), 0.0) AS gmv,
    COUNT(DISTINCT order_id) AS orders,
    COUNT(DISTINCT customer_id) AS customers,
    COALESCE(SUM(quantity), 0) AS units,
    COALESCE(SUM(COALESCE(profit_amount_base, profit_amount)), 0.0) AS profit_amount,
    COUNT(DISTINCT CASE WHEN returned = 1 THEN order_id END) AS returned_orders
FROM orders
WHERE /* FILTERS */;
