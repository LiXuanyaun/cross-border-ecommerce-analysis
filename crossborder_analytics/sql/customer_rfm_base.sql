SELECT
    customer_id,
    MAX(order_date) AS last_order,
    COUNT(DISTINCT order_id) AS frequency,
    COALESCE(SUM(COALESCE(gmv_amount_base, total_amount_base, total_amount)), 0.0) AS monetary
FROM orders
WHERE /* FILTERS */
GROUP BY customer_id
ORDER BY monetary DESC;
