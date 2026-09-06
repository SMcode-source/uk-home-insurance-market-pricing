# What the pricing vendors actually deliver

Researched 2026-09-06 against vendor pages, vendor PDFs, ONS and FCA pages, and
trade-press reports of the vendors' own releases. Every claim carries the URL
read and the date shown on it. Where a page carried no date, that is stated and
the read date (2026-09-06) applies. Confidence is marked on every row:

- VERIFIED: read on a vendor, regulator or statistics-office page or PDF.
- INFERRED: implied by a description, a screenshot, a metric name or a number,
  not stated outright.
- UNKNOWN: nothing found. Ask the vendor.
- LOW: trade press, search summaries or secondary pages; use as a hint only.

The headline finding first, because it changes the shape of this document:
**Pearson Ham Group's insurance market pricing business was sold to Defaqto
(Fintel plc) in January 2026 for GBP 11.0m and was rebranded "Defaqto Market
Pricing" on 1-2 June 2026.** Defaqto's "Market Pricing Intelligence" page is that
business. There are two vendors to talk to, not three, and Pearson Ham Group
itself (now "CIL Pearson Ham") no longer advertises an insurance data product.
Sources in section 2.2.

**No actual column names were found for any vendor.** Not one data dictionary,
sample file, API document or table screenshot is public. Every column name in
`src/mktpricing/collect/vendor.py` (`CI_SPEC`, `DEFAQTO_SPEC`) remains a guess
and should be treated as such until a real file lands and `profile_extract()`
has run on it. What was found is the *vocabulary* each vendor uses for its
metrics, which is enough to say which canonical fields are almost certainly
present, which are probably absent, and which questions must be answered in
writing before the first file is accepted.

## 1. Summary table

| Vendor | Product | Granularity | Format | Cadence | PCWs covered | Direct covered | Declines present? | Truncated to top-N? | Underwriter given? | Confidence |
|---|---|---|---|---|---|---|---|---|---|---|
| Consumer Intelligence | Home Insurance Market View (Annual View) | One price per brand per PCW (or direct site) per risk per collection; 3,600 home risks/month, 4 PCWs, 32-34 direct sites, >1.5m home prices/month | Online portal (Viewfinder) with Excel export; PowerPoint reports; "Raw data download" as optional extra; "Excel spreadsheets" of pricing and excess; price-claim files | Monthly or quarterly reports; weekly option | 4 ("the big four") | Yes, 32-34 direct home sites | Quotability is a headline metric, so non-quotes are recorded somewhere; whether they appear as rows in raw data is UNKNOWN | Portal shows "each insurer on the market"; raw file truncation UNKNOWN | Brand level; an Underwriting module exists (home/motor) | Fields VERIFIED at metric level; file layout UNKNOWN |
| Consumer Intelligence | Underwriter View | Winning underwriter per risk per day from the MoneySuperMarket data set; 5,040 risks per 5 weeks, ~550,000 prices per 5 weeks | Power BI portal, daily refresh; "Raw Data access"; "Full metrics export by underwriter and segment" | Daily refresh; 5-week risk cycle | MoneySuperMarket only for the underwriter field | No | UNKNOWN | UNKNOWN | Yes, from MSM ("the only provider who consistently show the underwriter") | VERIFIED |
| Consumer Intelligence | Daily Price Benchmarking / Trading View | 432 risks run daily, each risk run on 3 consecutive days, 5,040 risks per 5-week cycle, ~1.3m prices/week; Trading View rolls up ~2,800 home risks/week | Power BI dashboards; "raw data files"; insight reports; weekly report Monday morning | Daily; weekly | 4 | Not stated for the daily product | Quotability, "Distance to P1", "LOTT" metrics exist | UNKNOWN | No | VERIFIED (numbers), UNKNOWN (file) |
| Consumer Intelligence | Instalment View / Offers and Incentives View | Same risk sets; home O&I sample 2,100 | Portal, Excel | Weekly or monthly | 4 | Instalment: yes; O&I: PCW results-page banners | n/a | n/a | No | VERIFIED |
| Defaqto Market Pricing (ex Pearson Ham) | Market Pricing Intelligence | One price per brand per PCW per risk per day; panel "over 6000 consumers" (Pearson Ham page); each profile "run for a few consecutive days before dropping out of the rotation" | "dashboards, raw data extracts, and daily, weekly and monthly insight reports"; Tableau dashboards and "raw data files" under Pearson Ham | Daily collection; daily/weekly/monthly reports; monthly calls | 4 ("the four major UK price comparison websites") | Not mentioned anywhere. Treat as PCW-only until told otherwise | "quotability" is a stated metric | UNKNOWN; public index is a top-5 average | Not mentioned | Delivery VERIFIED; fields INFERRED from metric names; file layout UNKNOWN |
| Defaqto | General Insurance Price Index (public) | Aggregate: average (2026) or median (2024-25) of the five cheapest quoted premiums, combined buildings and contents; monthly with 9 regions | Press release figures only | Monthly, quarterly summary | 4 | No | n/a | Top-5 by construction | No | VERIFIED |
| Pearson Ham Group | (none since Jan 2026) | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | VERIFIED: business sold; group is now CIL Pearson Ham, a consultancy |

## 2. Vendors

### 2.1 Consumer Intelligence

#### Products

- **Market View** is the umbrella "insurance market pricing benchmarking toolkit", made of **Annual View** (all six sectors) and **Instalment View** (home and motor). https://www.consumerintelligence.com/market-view and https://www.consumerintelligence.com/market-view-solution (no date on page; read 2026-09-06). Sector table on those pages: Home 3,600 risks, 4 PCWs, 32 direct sites (solution page) or 34 (market-view page), "Over 1.5m" prices per month; all sectors "just under 4 million prices for over 10,000 risks each month". Modules: Market (headlines, competitive brands, price moves, trended changes), Brand (market position, pricing opportunities, quotability opportunities), Group (brand stacking, positioning, channel footprint), Underwriting (panel competitiveness, brand/underwriter rankings, variances; home and motor only). Reporting monthly or quarterly with optional weekly insight; PowerPoint delivery; "Raw data download available (optional extra)"; history "6 months standard; >6 months available as optional extra"; a "Download access centre".
- **Home Insurance Market View** is the home cut. Stated content: "annual price and, where relevant, compulsory and voluntary excess values for each insurer on the market", competitive ranking, underwriting performance, average premiums, and "Price Claim Messages" files "that comply with ASA and FCA standards". Raw data: "Excel spreadsheets". Delivered "weekly or monthly". https://www.consumerintelligence.com/home-insurance-market-view (no date; read 2026-09-06).
- **Underwriter View**: "5040 unique risks across the PCW's, every 5 weeks", "in the region of 550,000 prices back every 5 weeks", "Scraping all the underlying insurer details from MoneySuperMarket", described as "the only provider who consistently show the underwriter". Power BI, web-based, "Daily fresh data". Dashboards: Broker Headlines, Underwriter Headlines, Price Changes, Optimal Panel Composition. Motor and home. https://www.consumerintelligence.com/underwriter-view (no date; read 2026-09-06). The BIBA slide deck "Underwriter & Panel" (PDF metadata: created 2 May 2025; copyright 2025) adds: "We identify the winning underwriter for every risk daily using the MSM pricing data-set"; "% Best Price"; "Broker Panel Performance: Full metrics export by underwriter and segment"; "Underwriter Panel Performance: Detailed data export by broker and segment"; deliverables "On-line Power BI portal access updated daily", "Raw Data access". https://www.consumerintelligence.com/hubfs/Underwriter%20and%20Panel.pdf
- **Daily Price Benchmarking**: "432 risks run daily", "Each risk run on 3 consecutive days", "5040" risks per cycle, "5 weekly run cycle", "No dark collection days", 12 risk baskets, 4 PCWs, "Circa 1.3m prices per week in the database". Views: Daily, Weekly, Biggest mover, Top performers, Segmented views, "Distance to P1 analysis segmented", "New footprint opportunities", "Quotability", "LOTT", "Offers and incentives". Delivery: "Online dashboards, raw data files, and insight reports". Subscriptions 3, 6 or 12 months. Home and motor only. https://www.consumerintelligence.com/daily-price-benchmarking-solution and https://www.consumerintelligence.com/daily-insurance-price-benchmarking (no date; read 2026-09-06).
- **Trading View**: weekly Power BI report built on Daily Price Benchmarking, "3,024" motor and "2,772" home risks per week on the product page; "nearly 2,800 Home risks" in the 30 July 2026 upgrade article. Refreshed Monday morning for a Monday-Sunday window. Metrics: footprint, price changes "broken down by channel", positioning, price indices including a "Machine Learning-based rating index", win/lose frequency against each competitor "and the average price difference when they do", segment tables. 12-month subscription. https://www.consumerintelligence.com/trading-view (video dated 23 May 2024) and https://www.consumerintelligence.com/articles/introducing-the-latest-upgrades-to-trading-view-our-weekly-market-compass (30/07/2026).
- **Instalment View / premium finance**: monthly instalment, deposit, APR, Total Instalment Cost (TIC), annual price. Motor and home. https://www.consumerintelligence.com/insurance-premium-finance-insights (read 2026-09-06; refers to an April report and FCA MS24/2.1).
- **Offers and Incentives View**: "Offers collected are those displayed by providers in the form of banners on the results pages of the four main PCWs"; home sample 2,100; weekly and monthly; portal, Excel. https://www.consumerintelligence.com/offers-and-incentives-view (no date; read 2026-09-06). This is the only vendor product found that captures cashback-type incentives, and it captures them as PCW banners, not as a per-quote cashback amount.
- **Question Set Monitor**: records "exact question wording and ordering, along with the drop down options and available selections" on the big four PCWs, car and home. https://www.consumerintelligence.com/question-set-monitor (read 2026-09-06). Relevant because it shows CI stores risk attributes as PCW question answers, not as a normalised schema.
- **Home Insurance Price Index** (free, gated): "For each risk, common to consecutive months, the variation is calculated from the average of the five cheapest premiums returned on each PCW in the previous month to the average of the Top 5 in the current month"; averaged across risks and PCWs; chained from 100. https://www.consumerintelligence.com/home-insurance-price-index-download (copyright 2026; read 2026-09-06).
- **Inflation tracking** (for investors): "raw data to fuel internal modelling", "four leading price comparison websites and direct market leaders", database "extends back over a decade". https://www.consumerintelligence.com/inflation-tracking (no date; read 2026-09-06).

#### Collection method

- Consented panel. Viewsbank members "offer their details for pricing research"; opting into the "Unique Quote Research Project" pays GBP 5 "when they select your details"; quotes are "anonymised". Search summary of https://www.consumerintelligence.com/viewsbank-consumer-survey-panel (page fetch returned 404 on 2026-09-06; LOW for the exact wording).
- "around 90,000 active consumer risk profiles"; quotes "across the UK's four major price comparison websites on the same day, alongside extensive direct insurer coverage"; baskets reflect "age, geography, claims history, vehicle and property characteristics, occupation and payment preference" and are "reviewed, refreshed and refined regularly"; automated QA flags "unexpected premium movements, significant changes in quotability, inconsistencies between channels". https://www.consumerintelligence.com/articles/behind-the-data-how-trusted-market-intelligence-is-built (29/06/26). VERIFIED.
- Mechanics, from CI's own 2020 methodology note: "The data collection process is almost entirely automated and constantly monitored for website changes"; "We use various techniques to avoid detection by provider websites. In addition, we vary elements within each profile to minimise detection"; "The provider sets its own compulsory excess but we set the voluntary excess within each profile"; "In each individual profile we specify the benefits we require. We accept the best price that gives at least this cover"; "we monitor, at all times, companies that account for over 80% of all the General Insurance sold"; minimum "50 market tests" per claim; extreme prices are "clipped". https://www.consumerintelligence.com/hubfs/Marketing%20Messages%20-%20Methodology%20and%20Guidelines%202020.pdf (July 2020). VERIFIED, but six years old.
- ONS: the CPIH QA page (revised 26 March 2025) says the data "are scraped from supplier websites". https://www.ons.gov.uk/economy/inflationandpriceindices/methodologies/qualityassuranceofadministrativedatausedincpih . The 2019 CPI Technical Manual section 9.5.10 (home contents): "Each index is constructed from actual insurance price quotes provided by a third-party company. These quotes are returned for a database of customer profiles. The customers in question cover a wide range of regions, the material used for the construction of their house or flat, the number of rooms, the number of occupants and many other attributes. The database of profiles is fully rotated every three months". Per-insurer indices weighted by expenditure with PPS selection of insurers. https://www.ons.gov.uk/economy/inflationandpriceindices/methodologies/consumerpricesindicestechnicalmanual2019/pdf . ONS confirmed the supplier is "Consumer Intelligence Ltd" in an FOI response of 18 September 2020 and refused field-level detail under s43 FOIA. https://www.ons.gov.uk/aboutus/transparencyandgovernance/freedomofinformationfoi/carinsurancesubindices . A second FOI (FOI/2021/3044) refused quote counts, matched-pair counts and insurer names on the same ground. https://cy.ons.gov.uk/aboutus/transparencyandgovernance/freedomofinformationfoi/carinsurancedata . ONS to the Treasury Committee, 16 June 2023: the ONS quotes are for "new policies". https://uksa.statisticsauthority.gov.uk/submission/office-for-national-statistics-correspondence-to-the-treasury-select-committee-on-insurance-industry-inflation . So the ONS feed is per-insurer quotes for a rotating profile database; ONS publishes nothing about its columns.
- CI's own case studies show quote *inputs* are stored alongside outputs: a data-mapping diagnostic compared Confused.com and MoneySuperMarket for the same risks and found "an average difference of GBP 206 on otherwise identical risks", "huge, unexplained differences" in compulsory excess, misaligned NCD capping, employment status and home claims mapping ("Escape of water" mis-mapped "nearly 70% of the time"; theft claims "100%" missed). https://www.consumerintelligence.com/how-a-major-uk-insurer-uncovered-critical-data-mismatches-to-optimise-pcw-performance (no date; read 2026-09-06). INFERRED: per-PCW, per-risk rows with the declared claims history and excess attached.
- Another case study (30/07/2026) models "which brands appeared in the cheapest ten quotes, and in what order" (P1 to P10) and segments home by "property age, rebuild value, property type". https://www.consumerintelligence.com/articles/case-study-separating-self-competition-from-real-competition . INFERRED: rank, property type, year built and buildings sum insured are available at risk level.
- PCW case study: "weekly benchmark of offers & relative competitive positioning for Home and Motor insurance"; "top 5 prevalence and frequency of position"; quotability and pricing metrics across PCWs. https://www.consumerintelligence.com/market-insight-to-empower-pcw-commercial-team-case-study and https://www.consumerintelligence.com/understanding-pcw-trade-performance (no dates; read 2026-09-06).

#### Delivery

- Portal: "Viewfinder" login, Power BI for Underwriter View, Daily Price Benchmarking and Trading View. Excel export from the portal. PowerPoint for Market View reports. "Raw data download available (optional extra)" and "6 months standard; >6 months available as optional extra" for history (market-view page). "Raw Data: Excel spreadsheets" (home market view page). "Raw Data access" (BIBA deck). No API, SFTP, Parquet or CSV mentioned anywhere. UNKNOWN whether the raw download is one flat file or one workbook per PCW.

#### Field inventory (metric-level; no column names exist in public)

| Field | Meaning as CI describes it | Confidence | Source |
|---|---|---|---|
| Annual price | "annual price ... for each insurer on the market" | VERIFIED as a metric; IPT treatment UNKNOWN | home-insurance-market-view |
| Compulsory excess | "compulsory and voluntary excess values"; "The provider sets its own compulsory excess" | VERIFIED | home-insurance-market-view; 2020 methodology PDF |
| Voluntary excess | set by CI per profile, so a risk attribute, not a quote attribute | VERIFIED | 2020 methodology PDF |
| Rank / position | "competitive ranking"; "Distance to P1"; "P1 to P10"; "top 5 prevalence and frequency of position" | VERIFIED as metrics | home-insurance-market-view; daily-insurance-price-benchmarking; self-competition case study; understanding-pcw-trade-performance |
| Brand | "brand-visible"; Brand module | VERIFIED | market-view-solution |
| Group | "brand stacking", Group module | VERIFIED | market-view-solution |
| Underwriter | from MoneySuperMarket only; "winning underwriter for every risk daily" | VERIFIED, MSM-only | underwriter-view; BIBA PDF |
| Channel / PCW | "four major price comparison websites on the same day, alongside extensive direct insurer coverage"; price changes "broken down by channel" | VERIFIED | behind-the-data; trading-view upgrade |
| Quotability | headline metric; "significant changes in quotability" flagged in QA | VERIFIED as metric; row representation UNKNOWN | market-view-solution; behind-the-data |
| Collection date | "same day" across PCWs; daily runs; 3 consecutive days per risk | VERIFIED | behind-the-data; daily-price-benchmarking-solution |
| Risk identifier | "For each risk, common to consecutive months" implies a stable risk key across months | INFERRED | price index method |
| Postcode / region | "geography"; regional index cuts | INFERRED (postcode vs region UNKNOWN) | behind-the-data |
| Property type, property age, rebuild value | used as segments | INFERRED | self-competition case study |
| Construction, rooms, occupants | in the ONS description of the profile database | INFERRED for licensed products | ONS technical manual 9.5.10 |
| Claims history | "claims history" in basket design; "Escape of water", theft claims compared across PCWs | INFERRED | behind-the-data; data-mismatch case study |
| Cover level / add-ons | "we specify the benefits we require. We accept the best price that gives at least this cover" | VERIFIED for method; per-quote add-on flags UNKNOWN | 2020 methodology PDF |
| Payment preference | "payment preference" in basket design; Instalment View monthly, deposit, APR, TIC | VERIFIED | behind-the-data; premium finance page |
| Offers / incentives | PCW results-page banners, separate product | VERIFIED | offers-and-incentives-view |
| Question-set answers | "exact question wording ... drop down options" per PCW | VERIFIED (separate product) | question-set-monitor |

#### Gaps

- No column names, no sample file, no data dictionary, no API doc.
- Whether declines are rows in the raw extract or only feed a quotability percentage.
- IPT and premium basis: never stated. "Annual price" is the stated basis for Annual View; Instalment View is a separate product, so the two are unlikely to be mixed in one file.
- Whether the raw download is the full panel or the top-N shown in the portal.
- Which "32-34 direct sites" are covered for home; not listed, and the two pages disagree on the count.
- Panel rotation: the daily product rotates on a 5-week cycle with 3-day runs; monthly Market View overlap between months is only implied by the "common risks" index method; ONS says its profiles rotate fully every three months. The rotation rule for the licensed monthly file is UNKNOWN.
- CI's own 2020 wording ("avoid detection by provider websites") sits awkwardly with the 2026 wording ("explicitly consented"). The consent is the panellist's; the PCW relationship is not described on CI pages. Ask.

### 2.2 Pearson Ham Group (now Defaqto Market Pricing)

#### Corporate position

- Fintel plc, via Defaqto, acquired "Pearson Ham Group's market pricing business" for GBP 11.0m: GBP 7.5m initial, GBP 2.0m April 2026, GBP 1.5m July 2026; expected 2026 revenue GBP 2.6m and EBITDA GBP 0.9m; described as "a leading provider of proprietary pricing data to the UK insurance industry" with a "historic data set". https://www.wearefintel.com/newsroom/fintel-completes-acquisition-of-pearson-ham-groups-insurance-pricing-data-business/ (19 January 2026). Defaqto's own release: motor, home, travel and pet; "real consumer panels"; "daily insights on competitor and market price movements at individual segment levels"; to "initially operate as a standalone entity before integration into Defaqto during 2026"; Stephen Kennedy named. https://www.defaqto.com/resources/defaqto-acquires-leading-market-pricing-business-strengthen-financial-services-and-insurance-insight (January 2026). Hill Dickinson (sell-side): "The existing leadership will remain with the business". https://www.hilldickinson.com/our-view/deals/pearson-hams-insurance-pricing-data-business-acquired-by-fintel/ (20 January 2026).
- Rebrand: "Defaqto Market Pricing", Stephen Kennedy Managing Director, "Our clients will continue working with the same expert team". https://www.insurancetimes.co.uk/news/defaqto-launches-rebranded-market-pricing-business/1458697.article (1 June 2026); https://insurance-edge.net/2026/06/02/defaqto-launches-new-branding-for-its-market-pricing-business/ (2 June 2026). The "live website" the releases refer to is https://www.defaqto.com/solutions/market-pricing-intelligence ; https://www.defaqto.com/market-pricing is a 404.
- What is left of Pearson Ham: pearsonhamgroup.com/how-we-can-help/insurance-insights/ now 301-redirects to https://pearsonham.cil.com/ , which says "Pearson Ham has joined CIL. We now operate as CIL Pearson Ham" and lists pricing consultancy only. No insurance data product. The old microsite https://insuranceinsights.pearsonham.com/ is still up with 2021 webinar dates and a brochure link that returns HTTP 500.

#### What the business delivered, as Pearson Ham described it (pre-sale pages)

- "Daily pricing movements across the top 4 comparison sights, using our panel of over 6000 consumers"; home, motor, pet. https://www.pearsonhamgroup.com/how-we-can-help/insights/ (no date; read 2026-09-06). VERIFIED.
- "Data is published on Tableau dashboards, raw data files, and daily, weekly and monthly insights reports"; "fully automated with minimal human intervention"; "regularly compare our risk cohorts against recent quote mix data supplied by PCW partners and use that to drive future recruitment of new individuals". Search-engine summary of https://www.pearsonhamgroup.com/insurance-insights/ , which returned 404 then 301 on 2026-09-06. LOW for exact wording; the same "quote mix" sentence now appears verbatim on the Defaqto page (VERIFIED there).
- Microsite (2021 era): "Consumer Panel Solution"; "genuine people with real risks who receive live quotes every day"; report types "Daily View", "Competitor Pricing Activity", "Biggest Movers", "Segmented Views", "Weekly Top Positions", "Top Performers", "Price Tracking", "Features and Ticks"; metrics top 1, 3, 5 positions, quotability, "Left on the table", "Beaten by"; "excess levels, add-ons"; "comparison of PCW specific promotional activity"; "Removal of outliers". https://insuranceinsights.pearsonham.com/ (webinar dates 2021-2022; read 2026-09-06). VERIFIED as the 2021 offer; INFERRED that it persists.
- Public index: "median average top-five price for home insurance" GBP 227 (Nov 2024), GBP 196 (Aug 2025); regional cuts for 9 regions. https://insurance-edge.net/2024/12/09/regional-home-and-motor-premiums-data-from-pearson-ham/ (9 Dec 2024); https://insurance-edge.net/2025/09/15/latest-pearson-ham-premium-data-home-motor-still-falling/ (15 Sep 2025). LOW (trade press quoting the release).

#### Gaps

- Everything file-level. No column names, no sample, no dictionary.
- Direct insurers: never mentioned by Pearson Ham or Defaqto. Assume PCW-only.
- Whether "raw data files" are CSV, Excel or a Tableau extract; whether history transferred intact to Defaqto.
- Whether any client contract signed with Pearson Ham Group novated to Defaqto, and on what terms. Not our problem, but it tells you whether the historic data set is licensable.

### 2.3 Defaqto

#### Products

- **Market Pricing Intelligence** (the ex-Pearson Ham business). Stated on https://www.defaqto.com/solutions/market-pricing-intelligence (no date; read 2026-09-06; the page carries Stephen Kennedy's bio "as a consultant with Pearson Ham, and now Defaqto"):
  - "Prices are collected from the four major UK price comparison websites (PCWs)."
  - "Each profile is run for a few consecutive days before dropping out of the rotation".
  - "We regularly compare our risk cohorts against recent quote mix data supplied by PCW partners".
  - "We only collect prices where we have explicit permission and agreements to do so."
  - "Data is delivered via dashboards, raw data extracts, and daily, weekly and monthly insight reports." Plus monthly catch-up calls.
  - "benchmarking covers premium finance, compulsory excess and ancillary pricing"; "Excess levels, add-ons and premium finance all play a role."
  - "daily insights into your performance and quotability against key competitors"; position "against key rivals"; "8 of the top 10 brands appearing in the most competitive 3 positions".
  - Products: motor, home, pet, travel, van. "Trusted by 80% of leading insurance brands"; client logos listed on the first read: AXA, Aviva, Admiral, Ageas, AA, Co-op, Covea, Marshmallow, Policy Expert, Markerstudy.
  - No PDFs, brochures, case studies or webinars linked. No sub-pages.
- **General Insurance Price Index** (public): "average of the five most competitive quoted premiums for combined buildings and contents insurance"; Q2 2026 -0.7% (Apr -0.4%, May -1.2%, Jun +1.0%). https://www.insuranceage.co.uk/insight/7958626/defaqto-sees-first-signs-of-a-turn-in-home-insurance-pricing (15 Jul 2026). Q1 2026 home -0.7% quarter, -9.9% year. https://claimsmag.co.uk/2026/04/motor-insurance-premiums-return-to-growth-as-home-prices-stabilise-in-q1-2026-defaqto-data-shows/ (7 April 2026). LOW (trade press).
- **Matrix 360 / Compare / Data Services**: product feature and rating data, not prices. Defaqto told the CMA in 2016 that its data to MoneySupermarket, GoCompare, Comparethemarket, Confused and money.co.uk "focuses on product features and benefits". https://assets.publishing.service.gov.uk/media/583858a3e5274a130700000e/Defaqto.pdf (CMA DCT market study response, 2016). Irrelevant to pricing; recorded so nobody mistakes Matrix data for a quote feed.
- Defaqto's own conference page (16 September 2026) lists no Market Pricing session. https://www.defaqto.com/defaqto-provider-conference-2026 .

#### Collection method

- Real consumer panel (Pearson Ham's "over 6000 consumers"), quoted daily on the four PCWs, profiles run "a few consecutive days" then rotated out, cohort mix benchmarked against PCW quote-mix data, outliers removed. PCW consent stated. Direct insurers not mentioned. VERIFIED (Defaqto page) plus VERIFIED (Pearson Ham insights page) for the panel size.

#### Field inventory (metric-level; no column names in public)

| Field | Meaning as stated | Confidence | Source |
|---|---|---|---|
| Premium ("core premium pricing") | daily competitor price | VERIFIED as metric; annual vs monthly and IPT UNKNOWN | market-pricing-intelligence |
| Compulsory excess | "benchmarking covers ... compulsory excess" | VERIFIED | market-pricing-intelligence |
| Voluntary excess | not mentioned; likely a fixed profile input as at CI | UNKNOWN | |
| Add-ons / ancillary pricing | "ancillary pricing", "add-ons" | VERIFIED as metric; per-add-on columns UNKNOWN | market-pricing-intelligence |
| Premium finance | "premium finance options" | VERIFIED | market-pricing-intelligence |
| Position / rank | "position", "most competitive 3 positions", "Weekly Top Positions", top 1/3/5 | VERIFIED as metric | market-pricing-intelligence; insuranceinsights.pearsonham.com |
| Quotability | "performance and quotability" | VERIFIED as metric; row representation UNKNOWN | market-pricing-intelligence |
| "Left on the table", "Beaten by" | gap-to-winner metrics | VERIFIED (2021 microsite) | insuranceinsights.pearsonham.com |
| Brand | competitor names | INFERRED | |
| Underwriter | not mentioned | UNKNOWN, probably absent | |
| Channel / PCW | four PCWs; "PCW specific promotional activity" | VERIFIED | both |
| Collection date | daily | VERIFIED | market-pricing-intelligence |
| Risk identifier | profile runs a few consecutive days, so a profile key must exist | INFERRED | market-pricing-intelligence |
| Risk attributes | "individual segment levels"; segmentation "by pricing factors" | INFERRED; which factors UNKNOWN | Defaqto release; insuranceinsights.pearsonham.com |
| Region | 9-region index cuts | VERIFIED for the index; postcode level UNKNOWN | trade press |
| Offers / incentives | "PCW specific promotional activity" | VERIFIED (2021) | insuranceinsights.pearsonham.com |

#### Gaps

- Same as Pearson Ham: no file-level information at all.
- Direct channel absent.
- A rotating panel by design ("a few consecutive days before dropping out") means their raw extract cannot be indexed week on week without their own matching method, which is not described.

## 3. Mapping notes

The names below are **not** column names. They are the vendor's public
vocabulary, listed so the first `profile_extract()` run has something to match
against. Every arrow is a guess until a file is seen.

### 3.1 Consumer Intelligence (Market View raw data / Underwriter View raw data)

| Canonical | Likely vendor concept | Status |
|---|---|---|
| `risk_id` | a risk or profile key; the index method needs one that persists month to month | guess; confirm it is a risk key, not a quote reference |
| `brand` | brand as shown on the PCW; Group module implies a separate group column | guess |
| `underwriter` | present only in Underwriter View, sourced from MoneySuperMarket | VERIFIED source; column name guess |
| `channel` | PCW name or direct site; "channel" is CI's own word | guess; value map for four PCWs plus each direct site |
| `collected_on` | collection date; daily product has per-day dates, monthly product a collection or cycle date | guess; date semantics to confirm |
| `quoted` | derived from quotability; may be a status word or may be the absence of a row | UNKNOWN; must ask |
| `premium` | "annual price" | basis VERIFIED as annual for Annual View; IPT UNKNOWN |
| `compulsory_excess` | "compulsory excess" | VERIFIED concept |
| `voluntary_excess` | set by CI per profile | VERIFIED concept; lives on the risk, not the quote |
| `accidental_damage` | part of "benefits we require" per profile; per-quote flag UNKNOWN | guess |
| `rank_on_page` | "position", "P1..P10", "rank 1-5" | VERIFIED concept |
| `cashback` | not in pricing products; Offers and Incentives View captures banners, not amounts | probably absent |
| `postcode` | "geography"; postcode vs region UNKNOWN | guess |
| `policy_type` | buildings, contents, combined; the index is quoted for home generally | guess |
| `building_type` | "property type" used as a segment | INFERRED present |
| `construction` | ONS feed includes "material used for the construction"; CI product pages do not say | INFERRED present |
| `occupancy` | not mentioned | UNKNOWN |
| `year_built` | "property age" segment | INFERRED present |
| `bedrooms` | ONS: "number of rooms" | INFERRED present |
| `buildings_sum_insured` | "rebuild value" segment | INFERRED present |
| `contents_sum_insured` | not mentioned | UNKNOWN |
| `claims_last_5y` | "claims history" in baskets; claim types compared across PCWs | INFERRED present, possibly as claim-type rows rather than a count |
| `flood_history`, `subsidence_history` | not mentioned | UNKNOWN |

Set on the spec once confirmed: `premium_basis="annual"` (stated), `premium_includes_ipt` (ask), `declines_included` (ask), `truncated_to_top_n` (ask; portal language "each insurer on the market" suggests full panel).

### 3.2 Defaqto Market Pricing (ex Pearson Ham) raw data extract

| Canonical | Likely vendor concept | Status |
|---|---|---|
| `risk_id` | profile key; profiles run a few consecutive days | guess |
| `brand` | competitor brand on PCW | guess |
| `underwriter` | not mentioned | probably absent |
| `channel` | one of four PCWs; no direct | VERIFIED scope; column name guess. Expect a PCW column, not a single-channel file |
| `collected_on` | daily collection date | VERIFIED daily; column guess |
| `quoted` | from "quotability" | UNKNOWN representation |
| `premium` | "core premium" | basis UNKNOWN; public index uses quoted premiums, presumably annual |
| `compulsory_excess` | "compulsory excess" | VERIFIED concept |
| `voluntary_excess` | not mentioned | UNKNOWN |
| `accidental_damage` | one of the "add-ons" or "ancillary" items | guess |
| `rank_on_page` | "position" | VERIFIED concept |
| `cashback` | "promotional activity" tracked at PCW level | probably not per quote |
| risk attributes | "individual segment levels"; nothing named | UNKNOWN; this is the gate question |

Set on the spec once confirmed: `premium_basis` (ask), `premium_includes_ipt` (ask), `declines_included` (ask), `truncated_to_top_n` (ask; their public index is a top-5 average, so a top-5 extract is a real possibility).

### 3.3 Repo consequences

- `Source.vendor_dfq` should be understood as "Defaqto Market Pricing, formerly Pearson Ham". `Source.vendor_ph` and the `pearson_ham` spec are kept only for historic pre-2026 raw files a licensee might receive as history, whose layout may differ from the current one; a current delivery is `defaqto`.
- The specs live as YAML under `config/vendor_specs/` (`ci.yml`, `defaqto.yml`, `pearson_ham.yml`). The first real file is profiled with `python scripts/inspect_vendor.py <file-or-folder>`, the draft saved with `--draft-spec`, corrected against whatever data dictionary the vendor supplies, then loaded with `--spec <file> --write`. `scripts/market_price.py` computes the best price, top-5 and spread from the loaded quotes, or straight from the vendor files with `--spec`.
- CI's raw data is stated to be Excel spreadsheets: expect to set `sheet` and `header_row` on the spec. Defaqto's is "raw data extracts", format unknown; the reader handles CSV in any delimiter, gzip or zip, Excel, Parquet and JSON, and a folder of daily files.
- Both vendors rotate risks (CI: 3 consecutive days per risk on a 5-week cycle for the daily product, "common risks" month to month for the monthly product; Defaqto: a few consecutive days). `audit_extract()`'s `rotating_panel` check will fire on any daily extract from either vendor. That is expected; index off matched risks only.
- Only CI offers a direct channel and an underwriter field. If `Risk.channel="direct"` rows matter to the model, only CI can supply them.
- CI's voluntary excess is a profile input, not a quoted value. Map it to `Risk.voluntary_excess`, and expect it to be constant per risk.

## 4. Questions to ask each vendor before the first file

### 4.1 Both vendors

1. Premium basis: is the price the annual premium for annual payment? Is IPT included? Are any fees (PCW admin, broker fee) included?
2. Declines: when a brand returns no quote, is there a row (with a status or reason code), or is the row absent? Are "refer" and "decline" distinguished? Are PCW-side exclusions (brand not on panel for that risk) distinguished from underwriting declines?
3. Truncation: does the raw extract contain every brand returned on the results page, or only the top N? If top N, what is N, and is it per PCW per risk?
4. Risk identity: what key identifies a risk profile across days, weeks and months? Is it stable when the panellist's details are refreshed? Is it a risk key or a quote reference?
5. Panel rotation: how many days is each profile quoted, how often is the panel refreshed, and what fraction of risks is common between two consecutive months? Is a fixed-basket subset available for indexing?
6. Channel: how are the four PCWs identified (codes, names)? Is the same risk quoted on all four on the same day?
7. Brand vs underwriter: is the displayed brand name captured as shown, or normalised? Is a product tier (e.g. Essentials, Standard, Premium) a separate brand row? Is the underwriter given, and from which source?
8. Excess: is compulsory excess per peril (escape of water, subsidence) or a single figure? Is voluntary excess a profile input, and if so, what values are used?
9. Add-ons: is the quoted price the base product only? Is accidental damage in or out? Are add-on prices separate columns or separate rows?
10. Date semantics: is the date the quote date, the cover start date entered, or the file date? What cover start date offset is used?
11. Cashback and incentives: are PCW cashback or voucher offers captured per quote, and how?
12. Risk attributes: the full list of profile fields supplied with the extract, as PCW question answers or as a normalised schema. Specifically: postcode granularity, policy type, property type, construction, occupancy, year built, bedrooms, buildings and contents sums insured, claims in last 5 years, flood and subsidence history.
13. Format and delivery: file type (CSV, XLSX, Parquet), one file or per PCW, delimiter, encoding, date format, delivery method (portal download, SFTP, API), and a data dictionary.
14. History: how far back, at what granularity, and at what price.
15. Licence: what may be published (aggregate indices, brand-level charts), whether derived models may be used commercially, whether outputs must credit the vendor, retention and deletion terms, and whether the licence covers redistribution of derived per-brand estimates.
16. Sample: a redacted sample extract of at least one full collection day before signing.

### 4.2 Consumer Intelligence specifically

1. Which of Market View raw data, Daily Price Benchmarking raw data files, and Underwriter View raw data are on offer, and do they share one schema?
2. Which 32-34 direct home sites are quoted, and are direct quotes for the same risk on the same day as the PCW quotes?
3. Is the underwriter field (MoneySuperMarket only) joinable to the other three PCWs' rows for the same risk and brand?
4. Is the monthly Market View collection one run per month or several? The >1.5m home prices per month against 3,600 risks implies several.
5. Reconcile "explicitly consented" panel with the ONS description "scraped from supplier websites" and CI's 2020 "avoid detection" wording: what agreements exist with the PCWs today?
6. Is the raw download the same rows the portal shows ("each insurer on the market") or a cut?

### 4.3 Defaqto Market Pricing specifically

1. Is any direct-insurer channel collected at all?
2. Is the historic Pearson Ham data set (pre-January 2026) available under a Defaqto licence, and is the schema unchanged across the transfer?
3. What is the panel size for home specifically (the "over 6000" figure was for all products)?
4. Which risk attributes are stored per profile, and are they the PCW question answers or a normalised set?
5. Is the extract the full results page or the top-N behind the public top-5 index?
6. Which "PCW partners" supply quote-mix data, and does that agreement restrict what a licensee may publish?

## 5. Unverified / could not confirm

- Any column name, for any vendor. None found.
- CI raw file format beyond "Excel spreadsheets" and "raw data files". API, SFTP, CSV never mentioned.
- CI IPT treatment and whether declines are rows.
- CI Viewsbank page text (404 on fetch; wording taken from a search summary).
- Whether CI's 32 or 34 direct home sites figure is current (two pages disagree).
- Pearson Ham /insurance-insights/ wording on Tableau and raw data files (page now redirects; wording from a search summary, and partly repeated verbatim on the Defaqto page).
- Pearson Ham 2020 panel brochure PDF (HTTP 500).
- Defaqto client list on the Market Pricing page (read once via fetch summary; not re-checked).
- Defaqto direct-channel coverage (never mentioned; absence assumed).
- Whether ONS's "fully rotated every three months" describes CI's licensed products or only the ONS feed.
- FCA MS18/1 annexes: checked Annex 3 (final report, Sept 2020); it uses firm transaction data, survey data and Financial Lives, not vendor quote data. EP19/1 Annex 4 is CI consumer research, not pricing. EP25/2 uses firm policy data. No regulator document describing a vendor quote file was found.
- No academic paper describing any of these datasets at field level was found.
- No job advert or LinkedIn post leaking table structure was found in the searches run.

## 6. Sources

Consumer Intelligence
- https://www.consumerintelligence.com/home-insurance-market-view (no date; read 2026-09-06)
- https://www.consumerintelligence.com/market-view (no date; read 2026-09-06)
- https://www.consumerintelligence.com/market-view-solution (no date; read 2026-09-06)
- https://www.consumerintelligence.com/underwriter-view (no date; read 2026-09-06)
- https://www.consumerintelligence.com/hubfs/Underwriter%20and%20Panel.pdf (PDF created 2 May 2025; copyright 2025)
- https://www.consumerintelligence.com/hubfs/Marketing%20Messages%20-%20Methodology%20and%20Guidelines%202020.pdf (July 2020)
- https://www.consumerintelligence.com/daily-price-benchmarking-solution (no date; read 2026-09-06)
- https://www.consumerintelligence.com/daily-insurance-price-benchmarking (no date; read 2026-09-06)
- https://www.consumerintelligence.com/trading-view (video 23 May 2024)
- https://www.consumerintelligence.com/articles/introducing-the-latest-upgrades-to-trading-view-our-weekly-market-compass (30/07/2026)
- https://www.consumerintelligence.com/offers-and-incentives-view (no date; read 2026-09-06)
- https://www.consumerintelligence.com/insurance-premium-finance-insights (read 2026-09-06)
- https://www.consumerintelligence.com/instalment-view (404)
- https://www.consumerintelligence.com/question-set-monitor (read 2026-09-06)
- https://www.consumerintelligence.com/home-insurance-price-index-download (copyright 2026; read 2026-09-06)
- https://www.consumerintelligence.com/inflation-tracking (no date; read 2026-09-06)
- https://www.consumerintelligence.com/articles/behind-the-data-how-trusted-market-intelligence-is-built (29/06/26)
- https://www.consumerintelligence.com/how-a-major-uk-insurer-uncovered-critical-data-mismatches-to-optimise-pcw-performance (no date; read 2026-09-06)
- https://www.consumerintelligence.com/articles/case-study-separating-self-competition-from-real-competition (30/07/2026)
- https://www.consumerintelligence.com/market-insight-to-empower-pcw-commercial-team-case-study (no date; read 2026-09-06)
- https://www.consumerintelligence.com/understanding-pcw-trade-performance (no date; read 2026-09-06)
- https://www.consumerintelligence.com/insurance-market-benchmarking (no date; read 2026-09-06)
- https://www.consumerintelligence.com/home-insurance-market (no date; read 2026-09-06)
- https://www.consumerintelligence.com/articles/insurance-quote-journeys-insights-from-the-market (30/05/24)
- https://www.consumerintelligence.com/articles/why-some-of-the-biggest-pcw-performance-issues-never-show-up-in-insurer-data (20/01/26)
- https://www.consumerintelligence.com/viewsbank-consumer-survey-panel (404 on fetch; search summary only)
- https://insurance-edge.net/2024/05/14/consumer-intelligence-launches-new-market-data-tool/ (14 May 2024; secondary)

Pearson Ham Group / Defaqto Market Pricing
- https://www.pearsonhamgroup.com/how-we-can-help/insights/ (no date; read 2026-09-06)
- https://www.pearsonhamgroup.com/insurance-insights/ (404 / 301 to pearsonham.cil.com)
- https://www.pearsonhamgroup.com/how-we-can-help/insurance-insights/ (301 to https://pearsonham.cil.com/ )
- https://pearsonham.cil.com/ (no date; read 2026-09-06)
- https://insuranceinsights.pearsonham.com/ (webinar dates 2021-2022; read 2026-09-06)
- https://insuranceinsights.pearsonham.com/wp-content/uploads/2021/01/2020-PH-Panel-Insurance-Brochure_Q4.pdf (HTTP 500)
- https://www.pearsonham.com/motor-and-home-insurance-pricing-unstable-until-2023/ (TLS certificate mismatch; not read)
- https://www.wearefintel.com/newsroom/fintel-completes-acquisition-of-pearson-ham-groups-insurance-pricing-data-business/ (19 January 2026)
- https://www.defaqto.com/resources/defaqto-acquires-leading-market-pricing-business-strengthen-financial-services-and-insurance-insight (January 2026)
- https://www.hilldickinson.com/our-view/deals/pearson-hams-insurance-pricing-data-business-acquired-by-fintel/ (20 January 2026)
- https://www.insuranceage.co.uk/insight/7957859/defaqto-spends-ps11m-snapping-up-pricing-business (20 January 2026; paywalled)
- https://www.insurancetimes.co.uk/news/defaqto-launches-rebranded-market-pricing-business/1458697.article (1 June 2026)
- https://insurance-edge.net/2026/06/02/defaqto-launches-new-branding-for-its-market-pricing-business/ (2 June 2026)
- https://insurance-edge.net/2024/12/09/regional-home-and-motor-premiums-data-from-pearson-ham/ (9 December 2024)
- https://insurance-edge.net/2025/09/15/latest-pearson-ham-premium-data-home-motor-still-falling/ (15 September 2025)

Defaqto
- https://www.defaqto.com/solutions/market-pricing-intelligence (no date; read 2026-09-06, twice)
- https://www.defaqto.com/solutions/insurers (read 2026-09-06)
- https://www.defaqto.com/solutions/comparison-websites (read 2026-09-06)
- https://www.defaqto.com/defaqto-provider-conference-2026 (event 16 September 2026)
- https://www.defaqto.com/market-pricing (404)
- https://claimsmag.co.uk/2026/04/motor-insurance-premiums-return-to-growth-as-home-prices-stabilise-in-q1-2026-defaqto-data-shows/ (7 April 2026)
- https://www.insuranceage.co.uk/insight/7958626/defaqto-sees-first-signs-of-a-turn-in-home-insurance-pricing (15 July 2026)
- https://assets.publishing.service.gov.uk/media/583858a3e5274a130700000e/Defaqto.pdf (CMA DCT market study response, 2016)

ONS, UKSA, FCA
- https://www.ons.gov.uk/economy/inflationandpriceindices/methodologies/qualityassuranceofadministrativedatausedincpih (revised 26 March 2025)
- https://www.ons.gov.uk/economy/inflationandpriceindices/methodologies/consumerpricesindicestechnicalmanual2019/pdf (2019 edition; sections 9.5.9 and 9.5.10)
- https://www.ons.gov.uk/aboutus/transparencyandgovernance/freedomofinformationfoi/carinsurancesubindices (18 September 2020)
- https://cy.ons.gov.uk/aboutus/transparencyandgovernance/freedomofinformationfoi/carinsurancedata (FOI/2021/3044)
- https://uksa.statisticsauthority.gov.uk/submission/office-for-national-statistics-correspondence-to-the-treasury-select-committee-on-insurance-industry-inflation (16 June 2023)
- https://www.fca.org.uk/publication/market-studies/ms18-1-3-annex-3.pdf (September 2020; no vendor quote data used)
- https://www.fca.org.uk/publication/corporate/ep19-1-annex-4.pdf (CI consumer research for FCA; not pricing; not read in full)
