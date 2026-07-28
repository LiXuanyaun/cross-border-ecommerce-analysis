SELECT
    product_id,
    MIN(product_name) AS product_name,
    MIN(category) AS category,
    COUNT(DISTINCT category) AS category_count,
    COUNT(DISTINCT order_id) AS orders,
    COUNT(DISTINCT CASE WHEN returned = 1 THEN order_id END) AS returned_orders,
    SUM(quantity) AS units,
    COUNT(DISTINCT customer_id) AS customers,
    COALESCE(SUM(COALESCE(gmv_amount_base, total_amount_base, total_amount)), 0.0) AS gmv,
    SUM(COALESCE(profit_amount_base, profit_amount)) AS profit,
    MIN(order_date) AS first_order,
    MAX(order_date) AS last_order
FROM orders
WHERE /* FILTERS */
GROUP BY product_id
ORDER BY gmv DESC;
