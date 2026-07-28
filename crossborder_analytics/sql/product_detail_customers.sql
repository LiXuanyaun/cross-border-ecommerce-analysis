SELECT
    customer_id,
    COUNT(DISTINCT order_id) AS orders,
    COALESCE(SUM(COALESCE(gmv_amount_base, total_amount_base, total_amount)), 0.0) AS gmv
FROM orders
WHERE /* FILTERS */ AND product_id = :product_id AND customer_id IS NOT NULL
GROUP BY customer_id;
