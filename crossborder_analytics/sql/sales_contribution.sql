SELECT
    strftime('%Y-%m', order_date) AS month,
    category,
    /* MARKET */ AS region,
    COALESCE(SUM(COALESCE(gmv_amount_base, total_amount_base, total_amount)), 0.0) AS gmv
FROM orders
WHERE /* FILTERS */
GROUP BY strftime('%Y-%m', order_date), category, /* MARKET */;
