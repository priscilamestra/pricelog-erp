# Pricelog ERP

Competitive price intelligence and product management system built with **Python, Streamlit, PostgreSQL, API integration, and browser automation**.

Pricelog centralizes product catalog management and automates the process of comparing internal prices against the online market.

The system supports two complementary monitoring strategies:

- **Fast Mode:** retrieves Google Shopping results through SerpAPI for scalable catalog analysis;
- **Detailed Mode:** uses Playwright and a real Chromium browser to collect and validate pricing data directly from e-commerce search results.

The project focuses on the engineering challenges behind reliable automation: **external API integration, product entity matching, noisy-data filtering, browser automation, persistence, state management, error handling, and deployment-ready secret management**.

## Problem

Companies managing large product catalogs need to understand whether their prices are competitive while still protecting healthy margins.

Doing this manually requires repeatedly searching marketplaces, comparing different listings, distinguishing the correct product from accessories or similar models, identifying used products, calculating market references, and comparing those values against internal costs.

The process becomes especially unreliable when search results contain:

- different product variants;
- incorrect storage capacities;
- accessories mixed with the main product;
- used or refurbished products;
- unrelated listings;
- extreme price outliers;
- inconsistent product naming.

At scale, manual monitoring becomes slow, repetitive, and difficult to standardize.

## Solution

I built Pricelog as an automated price intelligence workflow that combines ERP functionality with external market data collection.

The system:

1. manages a structured product catalog in PostgreSQL;
2. imports products individually or in bulk through CSV;
3. retrieves competitive pricing through APIs or browser automation;
4. normalizes product names before comparison;
5. performs structural product matching instead of trusting search results directly;
6. rejects incompatible variants, capacities, accessories, and non-new products;
7. removes statistical price outliers;
8. calculates a market reference price;
9. compares market price, internal price, cost, and margin;
10. stores analysis history for later review.

The architecture separates **interface, persistence, market-data collection, matching logic, and analysis processing**, making the system easier to maintain and extend.


<!-- Add image: main Pricelog dashboard overview -->

***Figure 1.*** *Pricelog ERP dashboard showing product management and competitive price monitoring workflows.*

## Architecture

```text
                         Pricelog ERP
                              |
                              v
                       Streamlit UI
                          app.py
                              |
              +---------------+---------------+
              |                               |
              v                               v
       Product Management              Price Monitoring
              |                               |
              v                      +--------+--------+
         PostgreSQL                  |                 |
       database.py                   v                 v
                              Fast Analysis      Detailed Analysis
                                   |                  |
                                   v                  v
                               SerpAPI            Playwright
                            Google Shopping        Chromium
                                   |                  |
                                   +--------+---------+
                                            |
                                            v
                                  Product Matching Engine
                                   rpa_monitor.py
                                            |
                      +---------------------+--------------------+
                      |                     |                    |
                      v                     v                    v
               Text normalization      Variant checks      Condition checks
               Brand / model IDs       Capacity match      New vs used
                      |                     |                    |
                      +---------------------+--------------------+
                                            |
                                            v
                                   Relevant Price Set
                                            |
                                            v
                                      IQR Filtering
                                            |
                                            v
                                    Market Median Price
                                            |
                                            v
                             Price + Margin Classification
                                            |
                                            v
                                      PostgreSQL History
```

## How It Works

### 1. Product catalog management

Products are stored in PostgreSQL and can be created manually or imported in bulk using CSV files.

Each product contains structured business information such as:

- product code;
- brand;
- type;
- model;
- category;
- selling price;
- acquisition cost;
- observations.

Product codes are unique and duplicate registrations are rejected automatically.

The management interface supports:

- complete product listing;
- search across product fields;
- product selection by ID or product code;
- editing existing records;
- individual deletion;
- CSV batch import.

PostgreSQL acts as the persistent state layer used by both the ERP interface and the price-monitoring workflows.


<!-- Add image: product catalog / management screen -->

***Figure 2.*** *Product catalog management interface with structured PostgreSQL-backed records, search, editing, and CSV import.*

### 2. Fast market analysis — SerpAPI

Fast Mode is designed for broader catalog analysis.

For each selected product, the system builds a search query and sends a request to Google Shopping through SerpAPI.

The raw API response is not immediately treated as valid market data.

Search engines frequently return similar but incompatible products, so each result passes through the product-matching pipeline before its price can be used.

The process follows:

```text
Product
   |
   v
Search Query
   |
   v
SerpAPI / Google Shopping
   |
   v
Raw Product Results
   |
   v
Normalization
   |
   v
Structural Matching
   |
   v
Condition Filtering
   |
   v
Relevant Prices
   |
   v
Outlier Filtering
   |
   v
Median Market Price
```

The request layer also includes timeout handling and explicit behavior for cases where no compatible result is found.

Instead of silently falling back to unrelated products, the analysis returns a controlled **Not Found** state.

### 3. Product matching and normalization

One of the main engineering challenges in this project is determining whether a marketplace result represents the same product as the catalog query.

Exact string comparison is not enough.

For example:

```text
Dell Teclado sem fio KB500
```

and:

```text
Dell KB500 Wireless Keyboard
```

describe the same product even though their text differs significantly.

Before comparison, product names are normalized.

The normalization layer handles differences such as:

```text
sem fio  -> wireless
com fio  -> wired
wi fi    -> wifi

256 GB   -> 256gb
1 TB     -> 1tb
```

Accents, punctuation, casing, and unnecessary text differences are also normalized.

The matching engine combines textual similarity with structural validation.

Important identifiers found in the query must also exist in the marketplace result.

This prevents a generic similarity score from incorrectly accepting related but different products.

### 4. Variant-aware matching

Product variants are treated as meaningful identifiers.

The system recognizes terms such as:

```text
Pro
Pro Max
Max
Plus
Ultra
Mini
Air
Lite
FE
```

A query for:

```text
iPhone 16 Pro Max
```

must not accept:

```text
iPhone 16
iPhone 16 Pro
```

even when the titles have high textual similarity.

This provides an additional deterministic validation layer before price aggregation.

### 5. Storage-capacity validation

Storage capacity is also validated structurally.

If the catalog query contains:

```text
128GB
```

the system rejects results representing:

```text
256GB
512GB
1TB
```

as well as listings that ambiguously combine multiple storage variants.

Capacity detection distinguishes probable storage values from smaller values that may represent RAM.

This prevents prices from different product configurations from contaminating the market reference.

### 6. Product-condition filtering

Competitive pricing should compare equivalent product conditions.

Listings containing signals such as:

```text
used
seminovo
refurbished
renewed
open box
caixa aberta
como novo
vitrine
```

are excluded from the price set.

Listings containing indicators such as battery-health percentages can also be rejected when they indicate a second-hand device.

This prevents artificially low used-product prices from distorting the reference price for a new product.

### 7. Statistical price filtering

After product relevance has been validated, the remaining prices are processed statistically.

Pricelog uses **Interquartile Range (IQR)** filtering to reduce the influence of extreme values.

The pipeline follows:

```text
Validated Product Prices
          |
          v
      Q1 and Q3
          |
          v
          IQR
          |
          v
Remove Statistical Outliers
          |
          v
   Median Market Price
```

The median is used instead of the arithmetic mean because it is more resistant to isolated extreme prices, temporary promotions, incorrect listings, or stale inventory.

### 8. Price and margin classification

Once a market reference is available, Pricelog compares it with the company's selling price and acquisition cost.

Each analyzed product receives an operational status.

| Status | Meaning |
|---|---|
| ✅ OK | Price and margin remain within the configured healthy range |
| ⚠️ Moderate | Price difference or margin requires attention |
| 🔴 Critical | Margin or market-price difference exceeds critical thresholds |
| ⚪ No reference | No compatible market product was found |
| 🚫 Error | Market data could not be collected successfully |

The minimum acceptable margin can be configured before analysis.

Results are persisted in PostgreSQL together with analysis metadata and expiration information.


<!-- Add image: Fast Mode analysis results -->

***Figure 3.*** *Fast competitive analysis using Google Shopping data, structural product matching, market-price estimation, and margin classification.*

### 9. Detailed browser automation — Playwright

Detailed Mode provides an alternative collection strategy using Playwright.

Instead of relying exclusively on an external API, the system launches Chromium and navigates e-commerce search pages.

The browser automation layer includes:

- controlled page navigation;
- variable waiting intervals;
- incremental scrolling;
- mouse movement simulation;
- product-card extraction;
- blocking and captcha detection;
- multiple extraction fallbacks.

The extraction pipeline attempts structured approaches before progressively falling back:

```text
Browser Page
     |
     v
JavaScript Product Extraction
     |
     | failed
     v
CSS Selector Extraction
     |
     | failed
     v
HTML / Regex Fallback
```

Extracted product titles and prices still pass through the same relevance and price-filtering logic used by the rest of the system.

This keeps collection and validation separate: **finding a price is not enough — the product must first be proven relevant to the query.**

### 10. Analysis history

Completed analyses are stored in PostgreSQL.

The system maintains:

- analysis creation date;
- monitoring mode;
- source;
- number of analyzed products;
- number of alerts;
- individual product results;
- market price;
- internal price;
- margin;
- classification status.

Previous analyses can be reused to focus new monitoring sessions on Moderate and Critical products.

Analysis records use an expiration lifecycle to prevent indefinite accumulation of temporary monitoring data.


<!-- Add image: analysis history / Detailed Mode -->

***Figure 4.*** *Stored price-monitoring results and historical analysis used to identify products that require further review.*

## Reliability and Engineering Decisions

### Search results are treated as untrusted data

Marketplace and search-engine results are noisy.

Pricelog does not assume that a returned listing is correct merely because the search provider returned it.

Every candidate passes through additional validation before its price contributes to the market calculation.

### Structural validation before fuzzy similarity

Text similarity is useful for ranking candidates, but similarity alone can accept the wrong product.

The matching system therefore combines fuzzy similarity with deterministic checks for product identifiers, variants, and capacities.

This reduces false positives while still handling different marketplace naming conventions.

### Explicit failure instead of unsafe fallback

If no compatible result survives filtering, the API workflow returns:

```text
Not Found
```

instead of calculating a market price from unrelated search results.

This is an intentional reliability decision: missing information is safer than confidently returning incorrect information.

### Separation between collection and validation

SerpAPI and Playwright are responsible for collecting candidate market data.

The matching and filtering pipeline decides whether that data is usable.

This separation allows additional providers to be integrated without rewriting the core product-validation logic.

### Multiple acquisition strategies

The project supports both:

```text
API-based collection
```

and:

```text
Browser-based collection
```

This reduces dependency on a single collection method and demonstrates two different automation approaches inside the same system.

### Defensive handling of marketplace noise

The price engine explicitly handles:

- different model variants;
- incorrect capacities;
- used and refurbished products;
- irrelevant accessories;
- unrelated search results;
- statistical price outliers;
- unavailable products;
- blocked requests.

### Persistent operational state

PostgreSQL is used not only as product storage but also as the operational state layer for analysis history and individual monitoring results.

### Secret isolation

Database credentials, API keys, and application login credentials are loaded through Streamlit secrets.

The local file:

```text
.streamlit/secrets.toml
```

is excluded from version control.

No production credential should be committed to the repository.

### Local-only administration

Development diagnostics are separated from the public application.

The local administration module can:

- verify whether the SerpAPI credential is loaded;
- execute a real API test request;
- inspect the API response;
- reset the development database.

The module is intentionally excluded from Git version control and is loaded only when the local file exists.

This keeps development tooling available without exposing destructive administrative actions in the deployed application.

## Data Model

Pricelog uses three main PostgreSQL tables.

```sql
-- Product catalog

produtos (
    id SERIAL PRIMARY KEY,
    codigo VARCHAR(50) UNIQUE NOT NULL,
    marca VARCHAR(100),
    tipo VARCHAR(100),
    modelo VARCHAR(200),
    categoria VARCHAR(100),
    preco_unitario NUMERIC(10,2),
    custo NUMERIC(10,2),
    obs TEXT
)
```

```sql
-- Analysis metadata

analises (
    id SERIAL PRIMARY KEY,
    data_criacao TIMESTAMP DEFAULT NOW(),
    total_produtos INTEGER,
    total_alertas INTEGER,
    expira_em DATE,
    modo VARCHAR(20),
    fonte VARCHAR(50)
)
```

```sql
-- Individual analysis results

itens_analise (
    id SERIAL PRIMARY KEY,
    analise_id INTEGER REFERENCES analises(id) ON DELETE CASCADE,
    codigo_produto VARCHAR(50),
    nome_produto VARCHAR(200),
    seu_preco NUMERIC(10,2),
    preco_mercado NUMERIC(10,2),
    diferenca_percent NUMERIC(6,2),
    margem_percent NUMERIC(6,2),
    status VARCHAR(30)
)
```

The schema is initialized automatically by the application.

## Tech Stack

| Layer | Technology |
|---|---|
| Application | Python |
| Web interface | Streamlit |
| Relational database | PostgreSQL |
| PostgreSQL integration | psycopg2 |
| Market search API | SerpAPI / Google Shopping |
| Browser automation | Playwright + Chromium |
| Data processing | pandas |
| HTML processing | BeautifulSoup4 + regex |
| Product matching | Python normalization + `difflib.SequenceMatcher` + structural rules |
| Statistical filtering | IQR + median |
| Secret management | Streamlit Secrets |
| Dependency management | uv |
| Version control | Git + GitHub |

## Repository Structure

```text
pricelog-erp/
├── app.py
├── database.py
├── rpa_monitor.py
├── pyproject.toml
├── uv.lock
├── README.md
├── .gitignore
└── .streamlit/
    └── secrets.toml        # Local credentials — not versioned
```

The development-only `local_admin.py` module is intentionally ignored by Git and is not included in the public repository.

## CSV Import Format

Pricelog supports batch product creation through CSV.

```csv
codigo,marca,tipo,modelo,categoria,preco_unitario,custo,obs
MOL000251,Logitech,Mouse,MX Master 3S,Periféricos,349.90,210.00,
MOL000192,Logitech,Mouse,M330 Silent Plus,Periféricos,189.90,110.00,Silent product
```

Required rules:

- `codigo` must be unique;
- `obs` may be empty;
- separator: comma;
- encoding: UTF-8.

## Quick Setup

### 1. Clone the repository

```bash
git clone https://github.com/priscilamestra/pricelog-erp.git
cd pricelog-erp
```

### 2. Install dependencies

```bash
uv sync
```

### 3. Install Chromium for Playwright

```bash
uv run playwright install chromium
```

### 4. Configure local secrets

Create:

```text
.streamlit/secrets.toml
```

Use placeholders for your own credentials:

```toml
[postgres]
host = "localhost"
database = "your_database"
user = "your_postgres_user"
password = "your_postgres_password"
port = "5432"

[login_sistema]
email_admin = "your_demo_email"
senha_admin = "your_demo_password"

[serpapi]
api_key = "your_serpapi_key"
```

The secrets file must remain outside version control.

### 5. Run the application

```bash
uv run streamlit run app.py
```

The local application will normally be available at:

```text
http://localhost:8501
```

## Deployment

The application can be deployed to Streamlit Community Cloud or another Python hosting environment.

For cloud deployment, the PostgreSQL instance must be reachable from the deployment environment.

A local configuration such as:

```toml
host = "localhost"
```

works only when Streamlit and PostgreSQL are running on the same machine.

A remote deployment therefore requires a network-accessible PostgreSQL instance or an environment where PostgreSQL is deployed alongside the application.

Secrets must be configured through the hosting platform and must never be committed to GitHub.

Browser-based Detailed Mode may require deployment-specific Playwright and Chromium configuration depending on the hosting environment.

## Extensibility

The collection and matching layers were intentionally kept separate.

Additional price-data providers can be added while reusing the existing validation pipeline.

A new provider only needs to produce candidate information equivalent to:

```python
[
    {
        "title": "Product title",
        "price": 999.90,
    }
]
```

The existing pipeline can then apply:

```text
Normalization
      ->
Structural Validation
      ->
Variant Validation
      ->
Capacity Validation
      ->
Condition Filtering
      ->
Outlier Filtering
      ->
Market Price
```

This makes the system adaptable to other marketplaces, APIs, scraping providers, or internal pricing sources.

## What This Project Demonstrates

Pricelog was designed as more than a CRUD interface connected to a price API.

It demonstrates:

- Python application architecture;
- intelligent automation design;
- external API integration;
- browser automation with Playwright;
- PostgreSQL data modeling and persistence;
- deterministic product entity matching;
- fuzzy text matching combined with business rules;
- normalization of noisy external data;
- variant and capacity validation;
- data-quality filtering;
- statistical outlier handling;
- defensive API behavior;
- multi-source data acquisition;
- state and history management;
- CSV ingestion;
- secret management;
- modular system design;
- deployment-aware engineering;
- Git-based development workflow.

The project also demonstrates an important part of **AI and automation engineering beyond model calls**: building reliable systems around imperfect external data.

In production AI systems, model quality alone is not enough. Data must be collected, normalized, validated, persisted, monitored, and handled safely when external services fail or return ambiguous information.

Pricelog applies those same engineering principles to a deterministic price-intelligence system.

## License

MIT License

Copyright (c) 2026

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files, to deal in the Software
without restriction, including without limitation the rights to use, copy,
modify, merge, publish, distribute, sublicense, and/or sell copies of the
Software, and to permit persons to whom the Software is furnished to do so,
subject to the conditions of the MIT License.
