# SQLite 数据层说明

## 定位

SQLite 保存 AutoClean 生成的规范化分析视图，为 CrossBorder 的预定义 SQL、Python 业务规则、Dashboard 和报告提供同一份可追溯数据。原始 CSV/XLSX 始终只读，数据库不是源文件的替代品。

默认数据库路径为 `database/ecommerce.db`。数据库文件、WAL 和临时文件属于本地运行产物，不进入 Git。

## 数据流与职责

```text
原始文件（只读）
  -> AutoClean 字段契约与规范分析视图
  -> SQLite 版本化入库
  -> 预定义参数化 SQL 筛选与聚合
  -> Python 指标解释、阈值、分群和建议
  -> Dashboard、报告与证据清单
```

SQL 负责数据集隔离、筛选和聚合；Python 负责利润率、增长率、RFM（客户价值模型）、证据状态和建议规则。Dashboard 和 CLI 默认使用 SQL 后端，数据库失败时不会静默切换到 pandas。

## 表结构

| 表 | 用途 | 关键字段 |
| --- | --- | --- |
| `autoclean_datasets` | 数据集版本登记 | `dataset_id`、契约、源文件哈希、字段映射、语义参数、行数、状态、创建时间 |
| `autoclean_dataset_issues` | 数据质量问题 | `dataset_id`、严重级别、问题代码、字段、影响行数、详情 |
| `autoclean_query_runs` | 命名查询审计 | `dataset_id`、查询名、状态、耗时、错误类型、执行时间 |
| `orders` | 规范化订单分析视图 | `dataset_id`、订单契约字段、基准币种金额、汇率及血缘字段 |

`orders` 以 `(dataset_id, order_id)` 作为联合主键。没有通过订单粒度检查的数据不会写入。CrossBorder 为日期、市场、品类、商品和客户建立以 `dataset_id` 开头的组合索引。

AutoClean 存储层的 `SCHEMA_VERSION` 当前为 1。CrossBorder 在分析元数据中记录数据库模式版本 3：版本 2 兼容增加 `country` 和 `product_name`，版本 3 增加分析运行、指标、质量、异常、诊断、建议、证据和洞察派生表。

## 数据集版本与复用

`dataset_id` 根据以下内容生成：

- 源文件哈希、数据契约和目标表名；
- 字段映射和语义覆盖；
- 源币种、目标币种；
- 规范分析视图的列名、类型和内容。

完全相同的分析视图再次导入时复用原 `dataset_id`，不会重复插入订单。字段映射、币种、规范化结果或数据内容变化时生成新版本。日期、区域和品类筛选只影响查询参数，不产生新的数据集版本。

所有业务查询都自动包含 `dataset_id = :dataset_id`，禁止跨版本混算。商品详情查询在此基础上增加参数化的 `product_id`。

## 事务与故障边界

- 入库使用 `BEGIN IMMEDIATE`，数据集先标记为 `IMPORTING`，订单和质量问题全部写入并校验行数后才改为 `READY` 并提交。
- 任一写入、粒度或行数校验失败都会回滚整个事务，不保留半成品数据集。
- SQLite 启用外键、WAL、忙等待超时和连接级回滚保护。
- 查询成功或失败都会写入 `autoclean_query_runs`；上层同时记录查询耗时和返回行数。
- 核心数据库初始化、入库或查询失败会显式返回 `FATAL` 或 `FAILED`，不会悄悄改用另一套计算结果。

## 命名 SQL 目录

SQL 文件随 Python 包发布在 `crossborder_analytics/sql/`，运行时只允许调用目录中的已知查询。

| 领域 | 查询名 |
| --- | --- |
| 经营总览 | `overview` |
| 销售趋势与贡献 | `monthly_sales`、`sales_contribution` |
| 市场与品类 | `market_analysis`、`market_category_analysis` |
| 商品 | `product_analysis`、`loss_product_analysis` |
| 客户 | `customer_rfm_base` |
| 退货 | `return_analysis` |
| 商品详情 | `product_detail_summary`、`product_detail_monthly`、`product_detail_market`、`product_detail_customers` |

日期、区域、品类和商品值全部使用绑定参数。市场字段只能在 `country` 和 `region` 两个受控表达式之间选择。系统不提供任意 SQL 控制台，未来 Agent 也应优先选择受控查询和指标接口，不能绕过数据集隔离与证据记录。

## 验证

```powershell
python -m pytest tests\test_sqlite.py tests\test_analysis.py
python .\scripts\benchmark_sqlite.py
```

测试覆盖重复导入复用、数据集隔离、失败回滚、查询日志、筛选参数、商品详情，以及 SQL 与 pandas 结果对账。10 万行基准用于记录流水线、最慢查询、市场品类查询和商品详情耗时，不作为跨机器固定性能承诺。

2026-07-19 本机首次入库基线（Windows、Python 3.14、`storage_reused=False`）：

| 项目 | 耗时 |
| --- | ---: |
| 完整流水线 | 14.075 秒 |
| 最慢命名查询 | 1.912 秒 |
| 市场品类查询 | 0.670 秒 |
| 商品详情（4 个查询） | 0.630 秒 |
