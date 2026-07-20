SELECT
    product_id,
    MIN(product_name) AS product_name,
    MIN(category) AS category,
    COUNT(DISTINCT category) AS category_count,
    COUNT(*) AS orders,
    COALESCE(SUM(quantity), 0) AS units,
    COUNT(DISTINCT customer_id) AS customers,
    COALESCE(SUM(COALESCE(total_amount_base, total_amount)), 0.0) AS gmv,
    SUM(COALESCE(profit_amount_base, profit_amount)) AS profit,
    SUM(CASE WHEN returned = 1 THEN 1 ELSE 0 END) AS returned_orders,
    MIN(order_date) AS first_order,
    MAX(order_date) AS last_order
FROM orders
WHERE /* FILTERS */ AND product_id = :product_id;
