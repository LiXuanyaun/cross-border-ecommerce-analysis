"use strict";

const fs = require("fs");
const path = require("path");
const crypto = require("crypto");

const ROOT = __dirname;
const SEED = 20260728;
const GENERATOR_VERSION = "1.0.0";
const GENERATED_AT = "2026-07-28T00:00:00.000Z";
const DATA_ORIGIN = "synthetic_extension";
const DAY_MS = 24 * 60 * 60 * 1000;

const SCENARIOS = {
  baseline: "BASELINE",
  advertising: "SCN_AD_DE_SEARCH_EFFICIENCY_DECLINE",
  returns: "SCN_RET_CLOTHING_SIZE_SPIKE",
  logistics: "SCN_LOGISTICS_EU_CUSTOMS_DELAY",
};

const TERRITORIES = {
  1: { code: "US", country: "United States", region: "North America" },
  2: { code: "US", country: "United States", region: "North America" },
  3: { code: "US", country: "United States", region: "North America" },
  4: { code: "US", country: "United States", region: "North America" },
  5: { code: "US", country: "United States", region: "North America" },
  6: { code: "CA", country: "Canada", region: "North America" },
  7: { code: "FR", country: "France", region: "Europe" },
  8: { code: "DE", country: "Germany", region: "Europe" },
  9: { code: "AU", country: "Australia", region: "Pacific" },
  10: { code: "GB", country: "United Kingdom", region: "Europe" },
};

const COUNTRY_TERRITORY_SCOPE = {
  US: "1;2;3;4;5",
  CA: "6",
  FR: "7",
  DE: "8",
  AU: "9",
  GB: "10",
};

const META_HEADERS = [
  "data_origin",
  "generator_version",
  "scenario_id",
  "seed",
  "generated_at",
];

function readPipeRows(fileName) {
  return fs
    .readFileSync(path.join(ROOT, fileName), "utf8")
    .split(/\r?\n/)
    .filter((line) => line.length > 0)
    .map((line) => line.split("|"));
}

function hash32(value) {
  let hash = 2166136261 ^ SEED;
  const text = String(value);
  for (let i = 0; i < text.length; i += 1) {
    hash ^= text.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

function random01(value) {
  return hash32(value) / 4294967296;
}

function pick(values, key) {
  return values[hash32(key) % values.length];
}

function round(value, digits = 2) {
  return Number(value.toFixed(digits));
}

function parseDate(value) {
  return new Date(`${value.slice(0, 10)}T00:00:00.000Z`);
}

function isoDate(value) {
  return new Date(value).toISOString().slice(0, 10);
}

function isoTimestamp(value) {
  return new Date(value).toISOString();
}

function addDays(value, days) {
  return new Date(new Date(value).getTime() + days * DAY_MS);
}

function dayDiff(later, earlier) {
  return Math.round((new Date(later).getTime() - new Date(earlier).getTime()) / DAY_MS);
}

function interpolateTime(start, end, fraction) {
  return new Date(start.getTime() + (end.getTime() - start.getTime()) * fraction);
}

function metadata(scenarioId = SCENARIOS.baseline) {
  return {
    data_origin: DATA_ORIGIN,
    generator_version: GENERATOR_VERSION,
    scenario_id: scenarioId,
    seed: SEED,
    generated_at: GENERATED_AT,
  };
}

function withMetadata(row, scenarioId) {
  return { ...row, ...metadata(scenarioId) };
}

function csvCell(value) {
  if (value === null || value === undefined) return "";
  const text = String(value);
  if (/[",\r\n]/.test(text)) return `"${text.replace(/"/g, '""')}"`;
  return text;
}

function writeCsv(fileName, headers, rows) {
  const output = [
    headers.join(","),
    ...rows.map((row) => headers.map((header) => csvCell(row[header])).join(",")),
  ].join("\n");
  fs.writeFileSync(path.join(ROOT, fileName), `${output}\n`, "utf8");
}

function sha256(fileName) {
  return crypto
    .createHash("sha256")
    .update(fs.readFileSync(path.join(ROOT, fileName)))
    .digest("hex");
}

function assert(condition, message) {
  if (!condition) throw new Error(`Validation failed: ${message}`);
}

function loadSourceData() {
  const usdRateByCurrencyDate = new Map(
    readPipeRows("FactCurrencyRate.csv").map((row) => [
      `${Number(row[0])}:${Number(row[1])}`,
      Number(row[2]),
    ]),
  );
  const subcategoryToCategory = new Map(
    readPipeRows("DimProductSubcategory.csv").map((row) => [Number(row[0]), Number(row[5])]),
  );
  const productCategory = new Map();
  for (const row of readPipeRows("DimProduct.csv")) {
    const productKey = Number(row[0]);
    const subcategoryKey = Number(row[2] || 0);
    productCategory.set(productKey, subcategoryToCategory.get(subcategoryKey) || 0);
  }

  const salesLines = readPipeRows("FactInternetSales.csv").map((row) => {
    const currencyKey = Number(row[6]);
    const orderDateKey = Number(row[1]);
    const usdAverageRate = usdRateByCurrencyDate.get(`${currencyKey}:${orderDateKey}`);
    assert(usdAverageRate, `missing USD average rate for currency ${currencyKey} on ${orderDateKey}`);
    return {
    productKey: Number(row[0]),
    orderDateKey,
    dueDateKey: Number(row[2]),
    shipDateKey: Number(row[3]),
    customerKey: Number(row[4]),
    promotionKey: Number(row[5]),
    currencyKey,
    salesTerritoryKey: Number(row[7]),
    salesOrderNumber: row[8],
    salesOrderLineNumber: Number(row[9]),
    orderQuantity: Number(row[11]),
    salesAmount: Number(row[18]),
    freight: Number(row[20]),
    orderDate: parseDate(row[23]),
    dueDate: parseDate(row[24]),
    shipDate: parseDate(row[25]),
    productCategoryKey: productCategory.get(Number(row[0])) || 0,
    usdAverageRate,
  };
  });

  const orders = new Map();
  for (const line of salesLines) {
    if (!orders.has(line.salesOrderNumber)) {
      orders.set(line.salesOrderNumber, {
        salesOrderNumber: line.salesOrderNumber,
        customerKey: line.customerKey,
        currencyKey: line.currencyKey,
        salesTerritoryKey: line.salesTerritoryKey,
        orderDate: line.orderDate,
        dueDate: line.dueDate,
        shipDate: line.shipDate,
        orderSalesAmount: 0,
        orderSalesAmountUsd: 0,
        usdAverageRate: line.usdAverageRate,
        freightAmount: 0,
        lineCount: 0,
      });
    }
    const order = orders.get(line.salesOrderNumber);
    order.orderSalesAmount += line.salesAmount;
    order.orderSalesAmountUsd += line.salesAmount * line.usdAverageRate;
    order.freightAmount += line.freight;
    order.lineCount += 1;
  }

  const orderList = [...orders.values()].sort((a, b) =>
    a.salesOrderNumber.localeCompare(b.salesOrderNumber),
  );
  const minDate = new Date(Math.min(...orderList.map((order) => order.orderDate.getTime())));
  const maxDate = new Date(Math.max(...orderList.map((order) => order.orderDate.getTime())));
  return { salesLines, orderList, minDate, maxDate };
}

function buildDimensions(minDate, maxDate) {
  const channels = [
    { suffix: "SEARCH", channel: "Paid Search", platform: "Google Ads", objective: "Conversion" },
    { suffix: "SOCIAL", channel: "Paid Social", platform: "Meta Ads", objective: "Prospecting" },
    { suffix: "SHOPPING", channel: "Shopping", platform: "Google Merchant Center", objective: "Sales" },
  ];
  const countries = ["US", "CA", "FR", "DE", "AU", "GB"];
  const countryDetails = Object.values(TERRITORIES).reduce((map, territory) => {
    map.set(territory.code, territory);
    return map;
  }, new Map());

  const campaigns = [];
  for (const countryCode of countries) {
    const detail = countryDetails.get(countryCode);
    for (const channel of channels) {
      const isGermanSearch = countryCode === "DE" && channel.suffix === "SEARCH";
      const campaignId = isGermanSearch
        ? "CMP-DE-SEARCH-GENERIC"
        : `CMP-${countryCode}-${channel.suffix}`;
      campaigns.push(
        withMetadata(
          {
            campaign_id: campaignId,
            campaign_name: isGermanSearch
              ? "Germany Generic Search"
              : `${detail.country} ${channel.channel}`,
            channel: channel.channel,
            platform: channel.platform,
            objective: channel.objective,
            target_country_code: countryCode,
            target_country: detail.country,
            sales_territory_key_scope: COUNTRY_TERRITORY_SCOPE[countryCode],
            billing_currency: "USD",
            active_start_date: isoDate(minDate),
            active_end_date: isoDate(maxDate),
            synthetic_note: "SIMULATED campaign; not an original AdventureWorks fact",
          },
          isGermanSearch ? SCENARIOS.advertising : SCENARIOS.baseline,
        ),
      );
    }
  }

  const carriers = [
    { carrier_id: "CAR-001", carrier_name: "NorthStar Express", service_level: "Standard" },
    { carrier_id: "CAR-002", carrier_name: "ParcelBridge", service_level: "Economy" },
    { carrier_id: "CAR-003", carrier_name: "GlobalPost", service_level: "International Priority" },
    { carrier_id: "CAR-004", carrier_name: "EuroFreight", service_level: "International Economy" },
  ].map((carrier) =>
    withMetadata(
      {
        ...carrier,
        carrier_type: "fictional_synthetic_carrier",
        synthetic_note: "SIMULATED carrier; not an original AdventureWorks entity",
      },
      carrier.carrier_id === "CAR-003" ? SCENARIOS.logistics : SCENARIOS.baseline,
    ),
  );

  const returnReasons = [
    ["RR-001", "SIZE_TOO_SMALL", "Size / fit", "Customer reported item too small"],
    ["RR-002", "SIZE_TOO_LARGE", "Size / fit", "Customer reported item too large"],
    ["RR-003", "DAMAGED_IN_TRANSIT", "Logistics", "Item damaged during transport"],
    ["RR-004", "PRODUCT_DEFECT", "Quality", "Product defect reported"],
    ["RR-005", "NOT_AS_DESCRIBED", "Expectation", "Item did not match expectations"],
    ["RR-006", "CHANGED_MIND", "Customer preference", "Customer changed purchase decision"],
  ].map(([return_reason_id, return_reason_code, reason_category, reason_description]) =>
    withMetadata(
      {
        return_reason_id,
        return_reason_code,
        reason_category,
        reason_description,
        synthetic_note: "SIMULATED reason dimension",
      },
      return_reason_code.startsWith("SIZE_") ? SCENARIOS.returns : SCENARIOS.baseline,
    ),
  );

  return { campaigns, carriers, returnReasons };
}

function buildShipments(orderList, carriers, scenarioStart) {
  const shipments = [];
  const trackingEvents = [];
  const shipmentByOrder = new Map();
  const carrierById = new Map(carriers.map((carrier) => [carrier.carrier_id, carrier]));

  for (let index = 0; index < orderList.length; index += 1) {
    const order = orderList[index];
    const territory = TERRITORIES[order.salesTerritoryKey];
    assert(territory, `unknown SalesTerritoryKey ${order.salesTerritoryKey}`);
    const crossBorder = territory.country !== "United States";
    const europe = territory.region === "Europe";
    let carrierId;
    if (europe && random01(`eu-carrier:${order.salesOrderNumber}`) < 0.48) {
      carrierId = "CAR-003";
    } else if (crossBorder) {
      carrierId = pick(["CAR-002", "CAR-003", "CAR-004"], `intl:${order.salesOrderNumber}`);
    } else {
      carrierId = pick(["CAR-001", "CAR-002"], `dom:${order.salesOrderNumber}`);
    }
    const carrier = carrierById.get(carrierId);
    const isScenario =
      europe && carrierId === "CAR-003" && order.shipDate.getTime() >= scenarioStart.getTime();
    const scenarioId = isScenario ? SCENARIOS.logistics : SCENARIOS.baseline;
    const baseTransit = crossBorder ? 4 : 2;
    const variability = hash32(`transit:${order.salesOrderNumber}`) % (crossBorder ? 4 : 3);
    const customsDelay = isScenario ? 6 + (hash32(`customs:${order.salesOrderNumber}`) % 4) : 0;
    const actualDelivery = addDays(order.shipDate, baseTransit + variability + customsDelay);
    actualDelivery.setUTCHours(16, 0, 0, 0);
    const promisedDelivery = new Date(order.dueDate);
    promisedDelivery.setUTCHours(18, 0, 0, 0);
    const transitDays = dayDiff(actualDelivery, order.shipDate);
    const delayDays = Math.max(0, dayDiff(actualDelivery, promisedDelivery));
    const shipmentId = `SHP-${String(index + 1).padStart(6, "0")}`;
    const shipment = withMetadata(
      {
        shipment_id: shipmentId,
        sales_order_number: order.salesOrderNumber,
        customer_key: order.customerKey,
        sales_territory_key: order.salesTerritoryKey,
        origin_country: "United States",
        destination_country: territory.country,
        destination_region: territory.region,
        carrier_id: carrierId,
        carrier_name: carrier.carrier_name,
        service_level: carrier.service_level,
        tracking_number: `SYN-${carrierId.slice(-3)}-${order.salesOrderNumber.slice(2)}`,
        ship_date: isoDate(order.shipDate),
        promised_delivery_date: isoDate(promisedDelivery),
        actual_delivery_date: isoDate(actualDelivery),
        transit_days: transitDays,
        delay_days: delayDays,
        on_time_flag: actualDelivery.getTime() <= promisedDelivery.getTime() ? 1 : 0,
        cross_border_flag: crossBorder ? 1 : 0,
        customs_delay_days: customsDelay,
        shipment_status: "DELIVERED",
        order_line_count: order.lineCount,
        freight_amount: round(order.freightAmount),
        synthetic_note: "SIMULATED shipment linked to AdventureWorks SalesOrderNumber",
      },
      scenarioId,
    );
    shipments.push(shipment);
    shipmentByOrder.set(order.salesOrderNumber, shipment);

    const pickup = new Date(order.shipDate);
    pickup.setUTCHours(8, 0, 0, 0);
    const labelCreated = new Date(Math.min(addDays(pickup, -0.25).getTime(), addDays(order.orderDate, 0.5).getTime()));
    const eventDefinitions = crossBorder
      ? isScenario
        ? [
            ["LABEL_CREATED", "Origin fulfillment center", labelCreated],
            ["PICKED_UP", "Origin fulfillment center", pickup],
            ["DEPARTED_ORIGIN", "Origin export hub", interpolateTime(pickup, actualDelivery, 0.12)],
            ["EXPORT_CLEARED", "Origin customs", interpolateTime(pickup, actualDelivery, 0.24)],
            ["ARRIVED_DESTINATION", `${territory.country} import hub`, interpolateTime(pickup, actualDelivery, 0.43)],
            ["CUSTOMS_HELD", `${territory.country} customs`, interpolateTime(pickup, actualDelivery, 0.48)],
            ["CUSTOMS_RELEASED", `${territory.country} customs`, interpolateTime(pickup, actualDelivery, 0.82)],
            ["OUT_FOR_DELIVERY", `${territory.country} local depot`, interpolateTime(pickup, actualDelivery, 0.92)],
            ["DELIVERED", territory.country, actualDelivery],
          ]
        : [
            ["LABEL_CREATED", "Origin fulfillment center", labelCreated],
            ["PICKED_UP", "Origin fulfillment center", pickup],
            ["DEPARTED_ORIGIN", "Origin export hub", interpolateTime(pickup, actualDelivery, 0.14)],
            ["EXPORT_CLEARED", "Origin customs", interpolateTime(pickup, actualDelivery, 0.28)],
            ["ARRIVED_DESTINATION", `${territory.country} import hub`, interpolateTime(pickup, actualDelivery, 0.54)],
            ["CUSTOMS_CLEARED", `${territory.country} customs`, interpolateTime(pickup, actualDelivery, 0.67)],
            ["OUT_FOR_DELIVERY", `${territory.country} local depot`, interpolateTime(pickup, actualDelivery, 0.88)],
            ["DELIVERED", territory.country, actualDelivery],
          ]
      : [
          ["LABEL_CREATED", "Origin fulfillment center", labelCreated],
          ["PICKED_UP", "Origin fulfillment center", pickup],
          ["DEPARTED_ORIGIN", "Regional sorting center", interpolateTime(pickup, actualDelivery, 0.22)],
          ["ARRIVED_AT_HUB", "Destination sorting center", interpolateTime(pickup, actualDelivery, 0.58)],
          ["OUT_FOR_DELIVERY", "Local delivery depot", interpolateTime(pickup, actualDelivery, 0.86)],
          ["DELIVERED", territory.country, actualDelivery],
        ];

    eventDefinitions.forEach(([eventCode, eventLocation, eventTime], eventIndex) => {
      trackingEvents.push(
        withMetadata(
          {
            tracking_event_id: `${shipmentId}-E${String(eventIndex + 1).padStart(2, "0")}`,
            shipment_id: shipmentId,
            sales_order_number: order.salesOrderNumber,
            tracking_number: shipment.tracking_number,
            event_sequence: eventIndex + 1,
            event_code: eventCode,
            event_timestamp: isoTimestamp(eventTime),
            event_location: eventLocation,
            carrier_id: carrierId,
            cross_border_flag: crossBorder ? 1 : 0,
            exception_flag: eventCode === "CUSTOMS_HELD" ? 1 : 0,
            synthetic_note: "SIMULATED tracking event",
          },
          scenarioId,
        ),
      );
    });
  }

  return { shipments, trackingEvents, shipmentByOrder };
}

function buildReturns(salesLines, shipmentByOrder, scenarioStart) {
  const returns = [];
  const clothingReasons = ["RR-001", "RR-002"];
  const otherReasons = ["RR-003", "RR-004", "RR-005", "RR-006"];

  for (const line of salesLines) {
    const shipment = shipmentByOrder.get(line.salesOrderNumber);
    const delivered = parseDate(shipment.actual_delivery_date);
    const isClothing = line.productCategoryKey === 3;
    const inScenarioWindow = line.orderDate.getTime() >= scenarioStart.getTime();
    const isScenarioEligible = isClothing && inScenarioWindow;
    const returnProbability = isScenarioEligible ? 0.24 : isClothing ? 0.085 : 0.032;
    const lineKey = `${line.salesOrderNumber}:${line.salesOrderLineNumber}`;
    if (random01(`return:${lineKey}`) >= returnProbability) continue;

    const sizeReasonProbability = isScenarioEligible ? 0.86 : isClothing ? 0.52 : 0;
    const isSizeReason = random01(`reason-type:${lineKey}`) < sizeReasonProbability;
    const reasonId = isSizeReason
      ? pick(clothingReasons, `size:${lineKey}`)
      : pick(otherReasons, `other:${lineKey}`);
    const isScenario = isScenarioEligible && isSizeReason;
    const scenarioId = isScenario ? SCENARIOS.returns : SCENARIOS.baseline;
    const requestDate = addDays(delivered, 3 + (hash32(`request:${lineKey}`) % 18));
    const receivedDate = addDays(requestDate, 3 + (hash32(`received:${lineKey}`) % 8));
    const refundDate = addDays(receivedDate, 1 + (hash32(`refund:${lineKey}`) % 4));
    const returnQuantity = 1 + (hash32(`qty:${lineKey}`) % Math.max(1, line.orderQuantity));
    const refundRatio = returnQuantity / line.orderQuantity;
    const refundAmount = Math.min(line.salesAmount, round(line.salesAmount * refundRatio * 0.97, 2));

    returns.push(
      withMetadata(
        {
          return_id: `RET-${String(returns.length + 1).padStart(6, "0")}`,
          sales_order_number: line.salesOrderNumber,
          sales_order_line_number: line.salesOrderLineNumber,
          shipment_id: shipment.shipment_id,
          customer_key: line.customerKey,
          product_key: line.productKey,
          product_category_key: line.productCategoryKey,
          sales_territory_key: line.salesTerritoryKey,
          currency_key: line.currencyKey,
          return_reason_id: reasonId,
          return_request_date: isoDate(requestDate),
          return_received_date: isoDate(receivedDate),
          refund_date: isoDate(refundDate),
          original_order_quantity: line.orderQuantity,
          return_quantity: returnQuantity,
          original_line_sales_amount: round(line.salesAmount, 2),
          refund_amount: refundAmount,
          resolution: "REFUND",
          return_status: "REFUNDED",
          synthetic_note: "SIMULATED return linked to an AdventureWorks order line",
        },
        scenarioId,
      ),
    );
  }
  return returns;
}

function campaignChoices(countryCode) {
  return [
    countryCode === "DE" ? "CMP-DE-SEARCH-GENERIC" : `CMP-${countryCode}-SEARCH`,
    `CMP-${countryCode}-SOCIAL`,
    `CMP-${countryCode}-SHOPPING`,
  ];
}

function buildAdvertising(orderList, campaigns, minDate, maxDate, scenarioStart) {
  const attribution = [];
  const dailyConversions = new Map();

  for (const order of orderList) {
    if (random01(`paid:${order.salesOrderNumber}`) >= 0.52) continue;
    const territory = TERRITORIES[order.salesTerritoryKey];
    const choices = campaignChoices(territory.code);
    let campaignId;
    if (territory.code === "DE" && random01(`de-search:${order.salesOrderNumber}`) < 0.62) {
      campaignId = "CMP-DE-SEARCH-GENERIC";
    } else {
      campaignId = pick(choices, `campaign:${order.salesOrderNumber}`);
    }
    const isScenario =
      campaignId === "CMP-DE-SEARCH-GENERIC" &&
      order.orderDate.getTime() >= scenarioStart.getTime();
    const scenarioId = isScenario ? SCENARIOS.advertising : SCENARIOS.baseline;
    const adDate = isoDate(order.orderDate);
    const dailyKey = `${adDate}|${campaignId}`;
    if (!dailyConversions.has(dailyKey)) {
      dailyConversions.set(dailyKey, { conversions: 0, revenueUsd: 0 });
    }
    const daily = dailyConversions.get(dailyKey);
    daily.conversions += 1;
    daily.revenueUsd += order.orderSalesAmountUsd;
    attribution.push(
      withMetadata(
        {
          attribution_id: `ATT-${String(attribution.length + 1).padStart(6, "0")}`,
          sales_order_number: order.salesOrderNumber,
          customer_key: order.customerKey,
          sales_territory_key: order.salesTerritoryKey,
          campaign_id: campaignId,
          touchpoint_date: adDate,
          conversion_date: isoDate(order.orderDate),
          attribution_model: "LAST_CLICK",
          attribution_credit: 1,
          order_currency_key: order.currencyKey,
          attributed_revenue_order_currency: round(order.orderSalesAmount, 2),
          usd_average_rate: round(order.usdAverageRate, 8),
          attributed_revenue_usd: round(order.orderSalesAmountUsd, 2),
          currency_basis: "FactCurrencyRate.AverageRate on conversion date",
          synthetic_note: "SIMULATED last-click attribution linked to AdventureWorks order",
        },
        scenarioId,
      ),
    );
  }

  const adPerformance = [];
  const start = new Date(minDate);
  const end = new Date(maxDate);
  for (const campaign of campaigns) {
    for (let date = new Date(start); date.getTime() <= end.getTime(); date = addDays(date, 1)) {
      const adDate = isoDate(date);
      const daily = dailyConversions.get(`${adDate}|${campaign.campaign_id}`) || {
        conversions: 0,
        revenueUsd: 0,
      };
      const isScenario =
        campaign.campaign_id === "CMP-DE-SEARCH-GENERIC" &&
        date.getTime() >= scenarioStart.getTime();
      const scenarioId = isScenario ? SCENARIOS.advertising : SCENARIOS.baseline;
      const noise = random01(`ad:${campaign.campaign_id}:${adDate}`);
      let impressions;
      let clicks;
      let cpc;
      if (campaign.campaign_id === "CMP-DE-SEARCH-GENERIC") {
        if (isScenario) {
          impressions = Math.round(5200 + noise * 1800 + daily.conversions * 150);
          clicks = Math.max(daily.conversions, Math.round(150 + noise * 45 + daily.conversions * 5));
          cpc = 2.05 + noise * 0.35;
        } else {
          impressions = Math.round(1700 + noise * 650 + daily.conversions * 100);
          clicks = Math.max(daily.conversions, Math.round(52 + noise * 18 + daily.conversions * 4));
          cpc = 0.95 + noise * 0.25;
        }
      } else {
        impressions = Math.round(650 + noise * 850 + daily.conversions * 110);
        const ctr = 0.022 + random01(`ctr:${campaign.campaign_id}:${adDate}`) * 0.025;
        clicks = Math.max(daily.conversions, Math.round(impressions * ctr));
        cpc = 0.65 + random01(`cpc:${campaign.campaign_id}:${adDate}`) * 1.15;
      }
      clicks = Math.min(clicks, impressions);
      const spend = round(clicks * cpc, 2);
      const conversions = daily.conversions;
      const attributedRevenueUsd = round(daily.revenueUsd, 2);
      adPerformance.push(
        withMetadata(
          {
            ad_date: adDate,
            campaign_id: campaign.campaign_id,
            target_country_code: campaign.target_country_code,
            channel: campaign.channel,
            platform: campaign.platform,
            billing_currency: "USD",
            impressions,
            clicks,
            conversions,
            spend,
            attributed_revenue_usd: attributedRevenueUsd,
            ctr: round(clicks / impressions, 6),
            conversion_rate: clicks === 0 ? 0 : round(conversions / clicks, 6),
            cost_per_click: clicks === 0 ? 0 : round(spend / clicks, 4),
            cost_per_acquisition: conversions === 0 ? 0 : round(spend / conversions, 4),
            roas: spend === 0 ? 0 : round(attributedRevenueUsd / spend, 4),
            synthetic_note: "SIMULATED daily advertising performance",
          },
          scenarioId,
        ),
      );
    }
  }

  return { attribution, adPerformance };
}

function validate(data, source, scenarioStart) {
  const orderNumbers = new Set(source.orderList.map((order) => order.salesOrderNumber));
  const orderLines = new Map(
    source.salesLines.map((line) => [
      `${line.salesOrderNumber}:${line.salesOrderLineNumber}`,
      line,
    ]),
  );
  const shipmentById = new Map(data.shipments.map((shipment) => [shipment.shipment_id, shipment]));

  assert(data.shipments.length === source.orderList.length, "each order must have one shipment");
  assert(new Set(data.shipments.map((row) => row.sales_order_number)).size === data.shipments.length,
    "shipment SalesOrderNumber must be unique");

  const attributionCredit = new Map();
  for (const row of data.attribution) {
    assert(orderNumbers.has(row.sales_order_number), `attribution FK ${row.sales_order_number}`);
    attributionCredit.set(
      row.sales_order_number,
      (attributionCredit.get(row.sales_order_number) || 0) + Number(row.attribution_credit),
    );
  }
  for (const [orderNumber, credit] of attributionCredit) {
    assert(credit <= 1 + Number.EPSILON, `attribution credit exceeds 1 for ${orderNumber}`);
  }

  for (const row of data.adPerformance) {
    assert(row.clicks <= row.impressions, `clicks exceed impressions for ${row.campaign_id}`);
    assert(row.conversions <= row.clicks, `conversions exceed clicks for ${row.campaign_id}`);
  }

  for (const row of data.returns) {
    const key = `${row.sales_order_number}:${row.sales_order_line_number}`;
    const sourceLine = orderLines.get(key);
    assert(sourceLine, `return line FK ${key}`);
    assert(row.refund_amount <= sourceLine.salesAmount + 0.001, `refund exceeds sales amount for ${key}`);
    assert(row.return_quantity <= sourceLine.orderQuantity, `return quantity exceeds sold quantity for ${key}`);
    const shipment = shipmentById.get(row.shipment_id);
    assert(shipment, `return shipment FK ${row.shipment_id}`);
    assert(
      parseDate(row.return_request_date).getTime() > parseDate(shipment.actual_delivery_date).getTime(),
      `return request must be after delivery for ${row.return_id}`,
    );
  }

  const eventsByShipment = new Map();
  for (const event of data.trackingEvents) {
    if (!eventsByShipment.has(event.shipment_id)) eventsByShipment.set(event.shipment_id, []);
    eventsByShipment.get(event.shipment_id).push(event);
    if (event.event_code.startsWith("CUSTOMS_")) {
      assert(event.cross_border_flag === 1, `customs event on domestic shipment ${event.shipment_id}`);
    }
  }
  for (const [shipmentId, events] of eventsByShipment) {
    events.sort((a, b) => a.event_sequence - b.event_sequence);
    for (let index = 1; index < events.length; index += 1) {
      assert(
        new Date(events[index].event_timestamp).getTime() >
          new Date(events[index - 1].event_timestamp).getTime(),
        `tracking events not chronological for ${shipmentId}`,
      );
    }
  }

  const germanSearch = data.adPerformance.filter(
    (row) => row.campaign_id === "CMP-DE-SEARCH-GENERIC",
  );
  const scenarioAds = germanSearch.filter((row) => row.scenario_id === SCENARIOS.advertising);
  const baselineAds = germanSearch.filter(
    (row) =>
      row.scenario_id === SCENARIOS.baseline &&
      parseDate(row.ad_date).getTime() >= addDays(scenarioStart, -120).getTime(),
  );
  const adSummary = (rows) => ({
    spendPerDay: rows.reduce((sum, row) => sum + row.spend, 0) / rows.length,
    cvr:
      rows.reduce((sum, row) => sum + row.conversions, 0) /
      rows.reduce((sum, row) => sum + row.clicks, 0),
  });
  const before = adSummary(baselineAds);
  const after = adSummary(scenarioAds);
  assert(after.spendPerDay > before.spendPerDay * 2, "German search spend spike not detectable");
  assert(after.cvr < before.cvr, "German search conversion efficiency decline not detectable");

  const scenarioReturns = data.returns.filter((row) => row.scenario_id === SCENARIOS.returns);
  assert(scenarioReturns.length >= 10, "clothing size-return scenario has too few rows");
  const priorStart = addDays(scenarioStart, -120);
  const isPriorWindow = (date) =>
    date.getTime() >= priorStart.getTime() && date.getTime() < scenarioStart.getTime();
  const isScenarioWindow = (date) => date.getTime() >= scenarioStart.getTime();
  const clothingPriorLines = source.salesLines.filter(
    (line) => line.productCategoryKey === 3 && isPriorWindow(line.orderDate),
  ).length;
  const clothingScenarioLines = source.salesLines.filter(
    (line) => line.productCategoryKey === 3 && isScenarioWindow(line.orderDate),
  ).length;
  const sizeReasonIds = new Set(["RR-001", "RR-002"]);
  const clothingSizePriorReturns = data.returns.filter((row) => {
    const line = orderLines.get(`${row.sales_order_number}:${row.sales_order_line_number}`);
    return line.productCategoryKey === 3 && sizeReasonIds.has(row.return_reason_id) && isPriorWindow(line.orderDate);
  }).length;
  const clothingSizeScenarioReturns = data.returns.filter((row) => {
    const line = orderLines.get(`${row.sales_order_number}:${row.sales_order_line_number}`);
    return line.productCategoryKey === 3 && sizeReasonIds.has(row.return_reason_id) && isScenarioWindow(line.orderDate);
  }).length;
  const priorSizeReturnRate = clothingSizePriorReturns / clothingPriorLines;
  const scenarioSizeReturnRate = clothingSizeScenarioReturns / clothingScenarioLines;
  assert(
    scenarioSizeReturnRate > priorSizeReturnRate * 2,
    "clothing size-return rate spike not detectable",
  );

  const scenarioShipments = data.shipments.filter((row) => row.scenario_id === SCENARIOS.logistics);
  assert(scenarioShipments.length >= 10, "European customs-delay scenario has too few rows");
  const priorComparableShipments = data.shipments.filter(
    (row) =>
      row.carrier_id === "CAR-003" &&
      row.destination_region === "Europe" &&
      isPriorWindow(parseDate(row.ship_date)),
  );
  const priorDelayDays =
    priorComparableShipments.reduce((sum, row) => sum + row.delay_days, 0) /
    priorComparableShipments.length;
  const scenarioDelayDays =
    scenarioShipments.reduce((sum, row) => sum + row.delay_days, 0) / scenarioShipments.length;
  assert(scenarioDelayDays >= 5, "European customs-delay scenario is not detectable");
  assert(
    scenarioDelayDays > priorDelayDays * 3,
    "European customs delay is not materially above the prior period",
  );

  const allRows = [
    ...data.campaigns,
    ...data.carriers,
    ...data.returnReasons,
    ...data.shipments,
    ...data.trackingEvents,
    ...data.returns,
    ...data.attribution,
    ...data.adPerformance,
  ];
  for (const row of allRows) {
    for (const header of META_HEADERS) {
      assert(row[header] !== undefined && row[header] !== "", `missing ${header}`);
    }
    assert(row.data_origin === DATA_ORIGIN, "invalid data_origin marker");
  }

  return {
    advertising: {
      prior_120d_average_daily_spend: round(before.spendPerDay, 2),
      scenario_120d_average_daily_spend: round(after.spendPerDay, 2),
      spend_change_pct: round((after.spendPerDay / before.spendPerDay - 1) * 100, 2),
      prior_120d_conversion_rate: round(before.cvr, 6),
      scenario_120d_conversion_rate: round(after.cvr, 6),
      conversion_rate_change_pct: round((after.cvr / before.cvr - 1) * 100, 2),
    },
    returns: {
      prior_120d_clothing_line_count: clothingPriorLines,
      prior_120d_size_return_count: clothingSizePriorReturns,
      prior_120d_size_return_rate: round(priorSizeReturnRate, 6),
      scenario_120d_clothing_line_count: clothingScenarioLines,
      scenario_120d_size_return_count: clothingSizeScenarioReturns,
      scenario_120d_size_return_rate: round(scenarioSizeReturnRate, 6),
      size_return_rate_change_pct: round(
        (scenarioSizeReturnRate / priorSizeReturnRate - 1) * 100,
        2,
      ),
    },
    logistics: {
      prior_120d_comparable_shipment_count: priorComparableShipments.length,
      prior_120d_average_delay_days: round(priorDelayDays, 2),
      scenario_120d_shipment_count: scenarioShipments.length,
      scenario_120d_average_delay_days: round(scenarioDelayDays, 2),
      average_delay_days_change_pct: round((scenarioDelayDays / priorDelayDays - 1) * 100, 2),
    },
  };
}

function main() {
  const source = loadSourceData();
  const scenarioStart = addDays(source.maxDate, -119);
  const dimensions = buildDimensions(source.minDate, source.maxDate);
  const logistics = buildShipments(source.orderList, dimensions.carriers, scenarioStart);
  const returns = buildReturns(source.salesLines, logistics.shipmentByOrder, scenarioStart);
  const advertising = buildAdvertising(
    source.orderList,
    dimensions.campaigns,
    source.minDate,
    source.maxDate,
    scenarioStart,
  );

  const data = {
    ...dimensions,
    ...logistics,
    returns,
    ...advertising,
  };
  const observedMetrics = validate(data, source, scenarioStart);

  const files = [
    {
      name: "dim_campaign.csv",
      headers: [
        "campaign_id", "campaign_name", "channel", "platform", "objective",
        "target_country_code", "target_country", "sales_territory_key_scope",
        "billing_currency", "active_start_date", "active_end_date", "synthetic_note", ...META_HEADERS,
      ],
      rows: data.campaigns,
    },
    {
      name: "dim_carrier.csv",
      headers: [
        "carrier_id", "carrier_name", "service_level", "carrier_type", "synthetic_note", ...META_HEADERS,
      ],
      rows: data.carriers,
    },
    {
      name: "dim_return_reason.csv",
      headers: [
        "return_reason_id", "return_reason_code", "reason_category", "reason_description",
        "synthetic_note", ...META_HEADERS,
      ],
      rows: data.returnReasons,
    },
    {
      name: "fact_ad_performance_daily.csv",
      headers: [
        "ad_date", "campaign_id", "target_country_code", "channel", "platform", "billing_currency",
        "impressions", "clicks", "conversions", "spend", "attributed_revenue_usd", "ctr",
        "conversion_rate", "cost_per_click", "cost_per_acquisition", "roas", "synthetic_note", ...META_HEADERS,
      ],
      rows: data.adPerformance,
    },
    {
      name: "bridge_order_attribution.csv",
      headers: [
        "attribution_id", "sales_order_number", "customer_key", "sales_territory_key", "campaign_id",
        "touchpoint_date", "conversion_date", "attribution_model", "attribution_credit",
        "order_currency_key", "attributed_revenue_order_currency", "usd_average_rate",
        "attributed_revenue_usd", "currency_basis", "synthetic_note", ...META_HEADERS,
      ],
      rows: data.attribution,
    },
    {
      name: "fact_returns.csv",
      headers: [
        "return_id", "sales_order_number", "sales_order_line_number", "shipment_id", "customer_key",
        "product_key", "product_category_key", "sales_territory_key", "currency_key", "return_reason_id",
        "return_request_date", "return_received_date", "refund_date", "original_order_quantity",
        "return_quantity", "original_line_sales_amount", "refund_amount", "resolution", "return_status",
        "synthetic_note", ...META_HEADERS,
      ],
      rows: data.returns,
    },
    {
      name: "fact_shipments.csv",
      headers: [
        "shipment_id", "sales_order_number", "customer_key", "sales_territory_key", "origin_country",
        "destination_country", "destination_region", "carrier_id", "carrier_name", "service_level",
        "tracking_number", "ship_date", "promised_delivery_date", "actual_delivery_date", "transit_days",
        "delay_days", "on_time_flag", "cross_border_flag", "customs_delay_days", "shipment_status",
        "order_line_count", "freight_amount", "synthetic_note", ...META_HEADERS,
      ],
      rows: data.shipments,
    },
    {
      name: "fact_tracking_events.csv",
      headers: [
        "tracking_event_id", "shipment_id", "sales_order_number", "tracking_number", "event_sequence",
        "event_code", "event_timestamp", "event_location", "carrier_id", "cross_border_flag",
        "exception_flag", "synthetic_note", ...META_HEADERS,
      ],
      rows: data.trackingEvents,
    },
  ];

  for (const file of files) writeCsv(file.name, file.headers, file.rows);

  const manifest = {
    title: "AdventureWorksDW synthetic business data extension",
    warning: "SIMULATED DATA. These files are not original AdventureWorks facts and must not be presented as real business records.",
    data_origin: DATA_ORIGIN,
    generator_version: GENERATOR_VERSION,
    seed: SEED,
    generated_at: GENERATED_AT,
    source: {
      sales_file: "FactInternetSales.csv",
      source_sales_line_count: source.salesLines.length,
      source_order_count: source.orderList.length,
      min_order_date: isoDate(source.minDate),
      max_order_date: isoDate(source.maxDate),
    },
    scenario_window: {
      start_date: isoDate(scenarioStart),
      end_date: isoDate(source.maxDate),
    },
    scenarios: [
      {
        scenario_id: SCENARIOS.advertising,
        description: "German generic-search spend rises while conversion efficiency falls.",
        ground_truth_filter: "campaign_id = CMP-DE-SEARCH-GENERIC and ad_date in scenario window",
        expected_signal: "daily spend > 2x prior 120-day average and conversion rate declines",
      },
      {
        scenario_id: SCENARIOS.returns,
        description: "Clothing size-related returns increase.",
        ground_truth_filter: "product_category_key = 3 and order date in scenario window and reason is size-related",
        expected_signal: "size/fit returns rise relative to the earlier period",
      },
      {
        scenario_id: SCENARIOS.logistics,
        description: "GlobalPost European shipments experience customs delays.",
        ground_truth_filter: "carrier_id = CAR-003, destination_region = Europe, ship_date in scenario window",
        expected_signal: "customs holds and delivery delay days rise",
      },
    ],
    observed_metrics: observedMetrics,
    outputs: files.map((file) => ({
      file: file.name,
      row_count: file.rows.length,
      sha256: sha256(file.name),
    })),
    validation: {
      status: "passed",
      checks: [
        "all attribution orders exist in FactInternetSales",
        "clicks <= impressions and conversions <= clicks",
        "attribution credit per order <= 1",
        "returns link to existing order lines",
        "refund amount <= original line sales amount",
        "return request date > actual delivery date",
        "one shipment per order",
        "tracking events are chronological",
        "customs events occur only on cross-border shipments",
        "all rows carry synthetic provenance metadata",
        "all three planted scenarios pass detectability thresholds",
      ],
    },
  };
  fs.writeFileSync(
    path.join(ROOT, "synthetic_scenario_manifest.json"),
    `${JSON.stringify(manifest, null, 2)}\n`,
    "utf8",
  );

  console.log(`Generated ${files.length} CSV files.`);
  for (const file of files) console.log(`${file.name}: ${file.rows.length} rows`);
  console.log("Validation: PASSED");
}

main();
