SELECT
    product_id,
    MIN(product_name) AS product_name,
    MIN(category) AS category,
    COUNT(DISTINCT category) AS category_count,
    COUNT(*) AS orders,
    SUM(CASE WHEN returned = 1 THEN 1 ELSE 0 END) AS returned_orders,
    SUM(quantity) AS units,
    COUNT(DISTINCT customer_id) AS customers,
    COALESCE(SUM(COALESCE(total_amount_base, total_amount)), 0.0) AS gmv,
    SUM(COALESCE(profit_amount_base, profit_amount)) AS profit,
    MIN(order_date) AS first_order,
    MAX(order_date) AS last_order
FROM orders
WHERE /* FILTERS */
GROUP BY product_id
ORDER BY gmv DESC;
