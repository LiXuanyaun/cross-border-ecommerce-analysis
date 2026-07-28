"""AdventureWorksDW adapter for headerless pipe-delimited source exports."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
import hashlib

import pandas as pd

from autoclean.analytics import LoadedDataset


FACT_INTERNET_SALES_COLUMNS = (
    "ProductKey", "OrderDateKey", "DueDateKey", "ShipDateKey", "CustomerKey",
    "PromotionKey", "CurrencyKey", "SalesTerritoryKey", "SalesOrderNumber",
    "SalesOrderLineNumber", "RevisionNumber", "OrderQuantity", "UnitPrice",
    "ExtendedAmount", "UnitPriceDiscountPct", "DiscountAmount", "ProductStandardCost",
    "TotalProductCost", "SalesAmount", "TaxAmt", "Freight", "CarrierTrackingNumber",
    "CustomerPONumber", "OrderDate", "DueDate", "ShipDate",
)
DIM_PRODUCT_COLUMNS = (
    "ProductKey", "ProductAlternateKey", "ProductSubcategoryKey", "WeightUnitMeasureCode",
    "SizeUnitMeasureCode", "EnglishProductName", "SpanishProductName", "FrenchProductName",
    "StandardCost", "FinishedGoodsFlag", "Color", "SafetyStockLevel", "ReorderPoint",
    "ListPrice", "Size", "SizeRange", "Weight", "DaysToManufacture", "ProductLine",
    "DealerPrice", "Class", "Style", "ModelName", "LargePhoto", "EnglishDescription",
    "FrenchDescription", "ChineseDescription", "ArabicDescription", "HebrewDescription",
    "ThaiDescription", "GermanDescription", "JapaneseDescription", "TurkishDescription",
    "StartDate", "EndDate", "Status",
)
DIM_PRODUCT_SUBCATEGORY_COLUMNS = (
    "ProductSubcategoryKey", "ProductSubcategoryAlternateKey", "EnglishProductSubcategoryName",
    "SpanishProductSubcategoryName", "FrenchProductSubcategoryName", "ProductCategoryKey",
)
DIM_PRODUCT_CATEGORY_COLUMNS = (
    "ProductCategoryKey", "ProductCategoryAlternateKey", "EnglishProductCategoryName",
    "SpanishProductCategoryName", "FrenchProductCategoryName",
)
DIM_CUSTOMER_COLUMNS = (
    "CustomerKey", "GeographyKey", "CustomerAlternateKey", "Title", "FirstName", "MiddleName",
    "LastName", "NameStyle", "BirthDate", "MaritalStatus", "Suffix", "Gender", "EmailAddress",
    "YearlyIncome", "TotalChildren", "NumberChildrenAtHome", "EnglishEducation",
    "SpanishEducation", "FrenchEducation", "EnglishOccupation", "SpanishOccupation",
    "FrenchOccupation", "HouseOwnerFlag", "NumberCarsOwned", "AddressLine1", "AddressLine2",
    "Phone", "DateFirstPurchase", "CommuteDistance",
)
DIM_GEOGRAPHY_COLUMNS = (
    "GeographyKey", "City", "StateProvinceCode", "StateProvinceName", "CountryRegionCode",
    "EnglishCountryRegionName", "SpanishCountryRegionName", "FrenchCountryRegionName",
    "PostalCode", "SalesTerritoryKey", "IpAddressLocator",
)
DIM_TERRITORY_COLUMNS = (
    "SalesTerritoryKey", "SalesTerritoryAlternateKey", "SalesTerritoryRegion",
    "SalesTerritoryCountry", "SalesTerritoryGroup", "SalesTerritoryImage",
)
DIM_CURRENCY_COLUMNS = ("CurrencyKey", "CurrencyAlternateKey", "CurrencyName")
FACT_CURRENCY_RATE_COLUMNS = ("CurrencyKey", "DateKey", "AverageRate", "EndOfDayRate", "Date")


SOURCE_SCHEMAS = {
    "FactInternetSales.csv": FACT_INTERNET_SALES_COLUMNS,
    "DimProduct.csv": DIM_PRODUCT_COLUMNS,
    "DimProductSubcategory.csv": DIM_PRODUCT_SUBCATEGORY_COLUMNS,
    "DimProductCategory.csv": DIM_PRODUCT_CATEGORY_COLUMNS,
    "DimCustomer.csv": DIM_CUSTOMER_COLUMNS,
    "DimGeography.csv": DIM_GEOGRAPHY_COLUMNS,
    "DimSalesTerritory.csv": DIM_TERRITORY_COLUMNS,
    "DimCurrency.csv": DIM_CURRENCY_COLUMNS,
    "FactCurrencyRate.csv": FACT_CURRENCY_RATE_COLUMNS,
}


@dataclass(frozen=True)
class AdventureWorksOrderLoad:
    loaded: LoadedDataset
    source_files: tuple[dict, ...]
    dataset_id: str


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_pipe(root: Path, filename: str, usecols: Iterable[str]) -> pd.DataFrame:
    path = root / filename
    if not path.is_file():
        raise FileNotFoundError("AdventureWorks source file is missing: {}".format(path))
    return pd.read_csv(
        path,
        sep="|",
        header=None,
        names=list(SOURCE_SCHEMAS[filename]),
        usecols=list(usecols),
        dtype=str,
        keep_default_na=False,
        na_values=[""],
        encoding="utf-8-sig",
        low_memory=False,
    )


class AdventureWorksAdapter:
    required_files = tuple(SOURCE_SCHEMAS)

    def load_orders(self, directory: str | Path) -> AdventureWorksOrderLoad:
        root = Path(directory)
        sales = _read_pipe(root, "FactInternetSales.csv", FACT_INTERNET_SALES_COLUMNS)
        products = _read_pipe(root, "DimProduct.csv", (
            "ProductKey", "ProductAlternateKey", "ProductSubcategoryKey", "EnglishProductName",
        ))
        subcategories = _read_pipe(root, "DimProductSubcategory.csv", (
            "ProductSubcategoryKey", "EnglishProductSubcategoryName", "ProductCategoryKey",
        ))
        categories = _read_pipe(root, "DimProductCategory.csv", (
            "ProductCategoryKey", "EnglishProductCategoryName",
        ))
        customers = _read_pipe(root, "DimCustomer.csv", (
            "CustomerKey", "GeographyKey", "CustomerAlternateKey", "FirstName", "LastName",
        ))
        geographies = _read_pipe(root, "DimGeography.csv", (
            "GeographyKey", "EnglishCountryRegionName",
        ))
        territories = _read_pipe(root, "DimSalesTerritory.csv", (
            "SalesTerritoryKey", "SalesTerritoryRegion", "SalesTerritoryCountry", "SalesTerritoryGroup",
        ))
        currencies = _read_pipe(root, "DimCurrency.csv", ("CurrencyKey", "CurrencyAlternateKey"))
        rates = _read_pipe(root, "FactCurrencyRate.csv", ("CurrencyKey", "DateKey", "AverageRate"))

        products = products.merge(subcategories, on="ProductSubcategoryKey", how="left").merge(
            categories, on="ProductCategoryKey", how="left"
        )
        customers = customers.merge(geographies, on="GeographyKey", how="left", suffixes=("", "_geo"))
        sales = sales.merge(products, on="ProductKey", how="left", validate="many_to_one")
        sales = sales.merge(customers, on="CustomerKey", how="left", validate="many_to_one")
        sales = sales.merge(
            territories,
            on="SalesTerritoryKey",
            how="left",
            validate="many_to_one",
            suffixes=("", "_territory"),
        )
        sales = sales.merge(currencies, on="CurrencyKey", how="left", validate="many_to_one")
        sales = sales.merge(
            rates.rename(columns={"DateKey": "OrderDateKey"}),
            on=["CurrencyKey", "OrderDateKey"],
            how="left",
            validate="many_to_one",
        )

        numeric = (
            "SalesOrderLineNumber", "OrderQuantity", "UnitPrice", "UnitPriceDiscountPct",
            "ProductStandardCost", "TotalProductCost", "SalesAmount", "Freight", "AverageRate",
        )
        for field in numeric:
            sales[field] = pd.to_numeric(sales[field], errors="coerce")
        if sales["AverageRate"].isna().any():
            missing = int(sales["AverageRate"].isna().sum())
            raise ValueError("FactCurrencyRate is missing for {:,} AdventureWorks order lines".format(missing))

        order_date = pd.to_datetime(sales["OrderDate"], errors="coerce")
        ship_date = pd.to_datetime(sales["ShipDate"], errors="coerce")
        rate = sales["AverageRate"]
        customer_name = (
            sales["FirstName"].fillna("").str.strip() + " " + sales["LastName"].fillna("").str.strip()
        ).str.strip()
        normalized = pd.DataFrame({
            "record_id": "aw:" + sales["SalesOrderNumber"].astype(str) + ":" + sales["SalesOrderLineNumber"].astype("Int64").astype(str),
            "order_id": sales["SalesOrderNumber"].astype(str),
            "sales_order_number": sales["SalesOrderNumber"].astype(str),
            "sales_order_line_number": sales["SalesOrderLineNumber"].astype("Int64"),
            "customer_id": sales["CustomerAlternateKey"].fillna(sales["CustomerKey"]).astype(str),
            "product_id": sales["ProductAlternateKey"].fillna(sales["ProductKey"]).astype(str),
            "product_name": sales["EnglishProductName"],
            "category": sales["EnglishProductCategoryName"].fillna("Uncategorized"),
            "price": sales["UnitPrice"] * rate,
            "discount": sales["UnitPriceDiscountPct"],
            "quantity": sales["OrderQuantity"].astype("Int64"),
            "order_date": order_date,
            "delivery_time_days": (ship_date - order_date).dt.total_seconds().div(86400),
            "country": sales["EnglishCountryRegionName"].fillna(sales["SalesTerritoryCountry"]),
            "region": sales["SalesTerritoryGroup"].fillna(sales["SalesTerritoryRegion"]),
            "returned": False,
            "total_amount": sales["SalesAmount"] * rate,
            "shipping_cost": sales["Freight"] * rate,
            "profit_amount": (sales["SalesAmount"] - sales["TotalProductCost"]) * rate,
            "cost_amount": sales["TotalProductCost"] * rate,
            "customer_gender": pd.NA,
            "currency": "USD",
            "source_product_key": sales["ProductKey"].astype(str),
            "source_customer_key": sales["CustomerKey"].astype(str),
            "source_currency_key": sales["CurrencyKey"].astype(str),
            "source_sales_territory_key": sales["SalesTerritoryKey"].astype(str),
            "source_row_number": pd.Series(range(1, len(sales) + 1), dtype="Int64") + 1,
        })
        normalized["source_file_id"] = "src_{}".format(_sha256(root / "FactInternetSales.csv")[:12])
        normalized["gmv_amount"] = normalized["total_amount"]
        normalized["gmv_amount_base"] = normalized["total_amount"]
        normalized["fx_rate"] = 1.0
        normalized["fx_rate_date"] = normalized["order_date"]
        normalized["fx_source"] = "AdventureWorks FactCurrencyRate.AverageRate to USD"

        source_files = tuple(
            {
                "filename": filename,
                "path": str((root / filename).resolve()),
                "sha256": _sha256(root / filename),
                "delimiter": "|",
                "header": False,
            }
            for filename in self.required_files
        )
        combined_hash = hashlib.sha256(
            "|".join(item["sha256"] for item in source_files).encode("ascii")
        ).hexdigest()
        dataset_id = "adventureworks-{}".format(combined_hash[:16])
        loaded = LoadedDataset(
            data=normalized,
            metadata={
                "filename": "AdventureWorksDW-data/FactInternetSales.csv",
                "source_location": str(root.resolve()),
                "sha256": combined_hash,
                "file_size": sum((root / item).stat().st_size for item in self.required_files),
                "rows": len(normalized),
                "columns": len(normalized.columns),
                "column_names": normalized.columns.tolist(),
                "encoding": "utf-8-sig",
            },
        )
        return AdventureWorksOrderLoad(loaded, source_files, dataset_id)
