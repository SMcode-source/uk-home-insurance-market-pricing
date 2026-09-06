# Where home insurance price data can actually come from

Researched 2026-09-06 against primary pages (insurer, PCW, regulator, vendor).
Every claim below carries the URL that was read and the date shown on it. Where
a page could not be reached or did not say, that is stated rather than guessed.
Scope is the first ten brands in `config/providers.yml`: Aviva, AXA, Direct Line,
Churchill, Privilege, Darwin, Admiral, More Than, LV=, Ageas.

The framing from `COLLECTION.md` holds: this is a list of legitimate routes.
Nothing here is a scraping plan.

## 1. Summary table

| Source | What it contains | Per brand? | Per quote? | Format | Cost | Ingestible by script? | Licence / terms |
|---|---|---|---|---|---|---|---|
| Insurer direct quote journeys (9 of 10 brands) | One real quote for one real risk | Yes | Yes | Web form | Free, manual | No. Manual only | Consumer use of a public site |
| PCW results pages (CTM, MSM, Confused, GoCompare) | 20-40 brand quotes per journey | Yes | Yes | Web page | Free, manual | No. Terms forbid automation (section 5) | CTM, MSM, Confused terms each bar robots/scrapers or bulk use |
| Own renewal notice (ICOBS 6.5.1R) | This year's and last year's premium, known cover | Yes (one) | Yes (one) | Paper / PDF | Free | No, but trivial to key in | Your own document |
| Consumer Intelligence: Home Insurance Price Index | Monthly index, avg of 5 cheapest per PCW per risk | No | No | Web article; report behind a form | Free (gated) | No file found | CI terms |
| Consumer Intelligence: Market View / Underwriter View | Brand-visible prices, excesses, rank, underwriter behind PCW brand | Yes | Yes | Portal, Excel extracts, Power BI | Licence, price on request | Yes (Excel) under licence | Vendor contract |
| Pearson Ham: General Insurance Price Index | Sold to Defaqto Jan 2026; now Defaqto Market Pricing (next row). Monthly top-5 index, panel of 6,000+ | Aggregate public; brand-level licensed | Licensed | Press figures; Tableau + raw files for clients (pre-sale) | Free summary; licence for data | Yes (raw files) under licence, via Defaqto | Vendor contract |
| Defaqto: Market Pricing Intelligence | Daily PCW-level quotes, four PCWs, rotated real profiles | Yes | Yes | Dashboards, raw extracts, reports | Licence, price on request | Yes (extracts) under licence | Vendor contract; Defaqto states PCW permission |
| Insurance DataLab | Firm performance (complaints, claims, CX), not prices | Firm level | No | Data hub | Licence (third-party listing: GBP 6k-18k) | Not price data | Vendor contract |
| WTW / Confused.com Price Index | Car only. No home index | n/a | n/a | PDF | Free | n/a | n/a |
| ABI Property Insurance Premium Tracker | Quarterly avg premium paid (combined, buildings, contents) | No | No | Figures in news posts | Free | No file. Hand-key three numbers a quarter | ABI site terms |
| FCA GI Value Measures 2025 | Per-firm banded claims metrics for home; aggregate premiums written | Firm level (underwriter, not brand) | No | XLSX | Free | Yes | Open (FCA publication; also on data.gov.uk) |
| FCA EP25/2 (GIPP evaluation) | Analysis of 16 home firms' policy-level data | No | No | PDF + technical annex | Free | No dataset published | n/a |
| ONS CPI 12.5.2 (D7F2, D7JE, D7MS) | Monthly index of house contents insurance | No | No | CSV / XLS | Free | Yes | Open Government Licence |
| data.gov.uk | Mirrors FCA VM 2023 and 2024; HMRC IPT bulletin | Firm level (FCA) | No | XLSX / CSV | Free | Yes | OGL |
| Insurer B2B (Aviva developer portal, Polaris imarket) | Broker/partner APIs and EDI; commercial lines or partner-only | n/a | n/a | API behind partner login | Partner only | Not without a partner agreement | Partner contract |

Nothing legitimate gives a consumer or a small research project a programmatic
home quote for any of the ten brands. Per-brand, per-quote data at scale exists
only under vendor licence.

## 2. Brands

Ownership as of 2026-09-06. FCA VM rows are for calendar 2025, product "Home -
(buildings and contents combined)", from the FCA spreadsheet (section 3.7).

### 2.1 Aviva

- Direct online quote: yes. https://www.aviva.co.uk/insurance/home-products/home-insurance/ ("Get a quote in minutes", Aviva Signature home). Read 2026-09-06; no page date.
- PCWs: named on Compare the Market's providers page (read 2026-09-06) and Confused.com's providers page ("Correct as of July 2026"). MoneySuperMarket has a provider page at /home-insurance/providers/aviva/ (HTTP 200, 2026-09-06). GoCompare: not verifiable (section 5).
- Owner: Aviva plc. Completed acquisition of Direct Line Insurance Group plc; scheme effective 1 July 2025. Aviva release https://www.aviva.com/newsroom/news-releases/2025/07/aviva-completes-acquisition-of-direct-line/ ; RNS 2 July 2025 https://www.investegate.co.uk/announcement/rns/direct-line-insurance-group--dlg/aviva-completes-acquisition-of-direct-line/8958714 (0.2867 new Aviva shares plus 129.7p cash per DLG share).
- APIs: https://developer.aviva.co.uk/ exists but returned 403 "not available from your current network location" (2026-09-06). Secondary sources describe it as partner-login only, with broker claims and SME APIs; no consumer quote API. Aviva trades personal lines with brokers over Polaris standards. Nothing public for home pricing.
- FCA VM 2025, Aviva Insurance Limited: claims frequency 5-10%, acceptance 70-75%, average payout GBP 5,000-5,500, complaints 10-15% of claims.

### 2.2 AXA

- Direct online quote: yes. https://www.axa.co.uk/home-insurance/ links to https://customer.axa.co.uk/home/get-quote/. Underwriter in footer: AXA Insurance UK plc. Page cites claims data Jan-Dec 2025 and pricing data 1 May-31 Jul 2026.
- PCWs: Compare the Market yes (2026-09-06); Confused.com yes (July 2026); MoneySuperMarket provider page 200. GoCompare search snippet names AXA; page not verifiable.
- Owner: AXA Insurance UK plc (AXA Group). No 2024-2026 ownership change found.
- APIs: none public found.
- FCA VM 2025, AXA Insurance UK Plc: 0-5%, 75-80%, GBP 8,000-8,500, 20-25%. A second entity, AXA Insurance dac, also reports home.

### 2.3 Direct Line

- Direct online quote: yes. https://www.directline.com/home-cover ("quote in under 10 minutes", /home/quote-policy/). Underwriter: U K Insurance Limited (UKIL). Page carries a notice: "We're proposing to transfer insurance business from U K Insurance Limited (UKIL) to Aviva Insurance Limited (AIL)." FAQs reference policies bought "pre-15th August 2026".
- PCWs: new. Aviva release, published 3 Sep 2026: Direct Line home insurance "launch on price comparison websites (PCWs) for the first time, beginning with Confused.com and expanding to other major comparison sites from late September." Three PCW-specific tiers: Essentials, Standard, Premium. https://www.aviva.com/newsroom/news-and-research-overview/news-releases/2026/09/direct-line-home-insurance-launches-on-price-comparison-websites-for-the-first-time/ . Confused.com's providers list already names Direct Line (page footnote says July 2026; treat the footnote as stale). Not named on Compare the Market's providers page on 2026-09-06; MoneySuperMarket /providers/direct-line/ returns 404. Direct Line car went on PCWs in 2024 (DLG release 10 Jul 2024, now redirects to aviva.com).
- Owner: Aviva plc since 1 July 2025 (see 2.1). Legal underwriter still UKIL, with a Part VII transfer to Aviva Insurance Limited proposed.
- APIs: none public.
- FCA VM 2025, U K Insurance Limited: 0-5%, 70-75%, GBP 6,000-6,500, 15-20%. UKIL is one reporting firm behind Direct Line, Churchill, Privilege and Darwin, so the FCA row is a group number, not a brand number.

### 2.4 Churchill

- Direct online quote: yes. https://www.churchill.com/home-insurance ("Get a home quote", /home/quote-policy). Underwriter UKIL.
- PCWs: Compare the Market yes; MoneySuperMarket featured on its providers page ("Reviewed on 3 Sep 2026"); Confused.com yes.
- Owner: Aviva plc (via DLG, 1 July 2025). Same UKIL row as 2.3.

### 2.5 Privilege

- Direct online quote: yes. https://www.privilege.com/home-insurance ("Get a home insurance quote", /home/quote-policy). Underwriter UKIL; footer "1999-2026". `providers.yml` lists Privilege as PCW-only; that is wrong.
- PCWs: Compare the Market yes; MoneySuperMarket featured; Confused.com yes.
- Owner: Aviva plc (via DLG). Same UKIL row.

### 2.6 Darwin

- Darwin sells car insurance only. https://www.darwin-insurance.com/ shows four motor tiers and no home product; "Darwin insurance policies are underwritten by U K Insurance Limited", with the same UKIL-to-AIL transfer notice. It has its own quote journey (quote.darwin-insurance.com) as well as PCW distribution. The old DLG brand page (directlinegroup.co.uk/en/brands/darwin.html) now redirects to aviva.com.
- Not on any PCW home provider list checked (CTM, MSM, Confused).
- Owner: Aviva plc (via DLG).
- Action for the repo: Darwin has no home price to collect. Drop it from the home panel or mark it not applicable.

### 2.7 Admiral

- Direct online quote: yes. https://www.admiral.com/home-insurance ("get a quote", quote.admiral.com). "Admiral is a trading name of EUI Limited"; EUI acts for other regulated insurers in the group. Page cites "2,193,954 active policies sold as of 10 March 2026".
- PCWs: Compare the Market yes; MoneySuperMarket featured; Confused.com yes. GoCompare snippet names Admiral; page not verifiable.
- Owner: Admiral Group plc. Bought RSA's UK direct home and pet operations: sale announced 7 Dec 2023 (Intact Financial release https://www.intactfc.com/press-releases/1/intact-financial-corporation-and-rsa-announce-sale-of-uk-direct-personal-lines-operations-to-admiral-group-plc ); completion announced 2 April 2024 for GBP 82.5m plus up to GBP 32.5m, including the MORE THAN brand, renewal rights and c.300 staff, with policies renewing to Admiral from Q3 2024. Admiral's own release page (admiralgroup.co.uk) returned 403 to us; text confirmed from a syndicated copy https://insurancenewsnet.com/oarticle/admiral-completes-the-acquisition-of-rsa-direct-home-and-pet-insurance-renewal-rights-for-82-5-million and the Admiral announcement URL https://www.admiralgroup.co.uk/news-releases/news-release-details/admiral-completes-acquisition-rsa-direct-home-and-pet-insurance .
- APIs: none public.
- FCA VM 2025, EUI Limited: 0-5%, 65-70%, GBP 4,000-4,500, 10-15%. EUI is the reporting firm for Admiral and More Than home.

### 2.8 More Than

- Direct online quote: no. https://www.morethan.com/home-insurance/ states "Right now, we're only selling home insurance policies through price comparison websites." Footer: "More Th>n is a trading name of EUI Limited. EUI Limited is a subsidiary of Admiral Group plc". `providers.yml` lists More Than as direct + PCW; the direct channel is closed.
- PCWs: Confused.com yes (July 2026); MoneySuperMarket provider page /providers/more-than/ 200; not named on Compare the Market's providers page on 2026-09-06.
- Owner: Admiral Group plc (see 2.7). `providers.yml` underwriter "Admiral" is right; the FCA reporting firm is EUI Limited.

### 2.9 LV=

- Direct online quote: yes. https://www.lv.com/home-insurance ("Online Quotes from just GBP 119"). Underwriter: Liverpool Victoria Insurance Company Limited (LVIC). Page notice: "we plan to transfer the insurance business of Liverpool Victoria Insurance Company Limited to Allianz Insurance plc. Subject to court approval, from 1 January 2027 this policy will be underwritten by Allianz Insurance plc".
- PCWs: Confused.com yes; MoneySuperMarket provider page /providers/lv/ 200; not named on Compare the Market's providers page on 2026-09-06.
- Owner: the LV= general insurance business has been Allianz's since 2019; the LV= brand belongs to the mutual (Liverpool Victoria Financial Services). Allianz UK release 24 April 2026: new multi-year partnership to keep distributing home, car and pet under the LV= brand. https://www.allianz.co.uk/news-and-insight/news/allianz-and-lv-long-term-partnership.html . `providers.yml` underwriter "LV= General Insurance" should read Allianz (LVIC until the Part VII transfer, then Allianz Insurance plc).
- FCA VM 2025, Liverpool Victoria Insurance Company Limited: 0-5%, 60-65%, GBP 3,000-3,500, 5-10%.

### 2.10 Ageas

- Direct online quote: yes. https://www.ageas.co.uk/home-insurance/ ("Get a home quote", home.ageas.co.uk/yourproperty). Underwriter Ageas Insurance Limited. `providers.yml` lists Ageas as PCW-only; it also sells direct. Ageas's own press boilerplate: "offers car and home insurance directly, through price comparison websites and electronically traded brokers and intermediary partners."
- PCWs: Compare the Market yes (2026-09-06); Confused.com yes; MoneySuperMarket /providers/ageas/ 404 (list not exhaustive).
- Owner: Ageas SA/NV group. Ageas UK completed the acquisition of esure Group: agreement 14 April 2025 for GBP 1.295bn (esure, Sheilas' Wheels, First Alternative; 2.1m policies) https://www.ageas.co.uk/press-releases/2025/ageas-reaches-agreement-with-bain-capital-to-acquire-esure-and-establish-a-top-3-uk-personal-lines-platform/ ; completion release https://www.ageas.co.uk/press-releases/2025/ageas-uk-completes-acquisition-of-esure/ (web page dated 29 Sep 2025; PDF version headed "UK, 30 September 2025 0715hrs" https://www.esuregroup.com/media/xn4hx3qp/ageas-press-release-esure-completion-250925-final-approved.pdf ). esure "will operate as a separate business within Ageas UK". Ageas also underwrites Saga home (the release refers to "our partnership with Saga"), which matches `providers.yml`.
- APIs: none public. Ageas trades with brokers electronically (ageasbroker.co.uk), partner-only.
- FCA VM 2025, Ageas Insurance Limited: 0-5%, 75-80%, GBP 10,500-11,000, 10-15%. esure Insurance Limited: 0-5%, 60-65%, GBP 7,500-8,000, 10-15%.

### 2.11 PCW provider lists, as read

| PCW | Page | Date on page | Named of the ten |
|---|---|---|---|
| Compare the Market | https://www.comparethemarket.com/home-insurance/providers/ | none (read 2026-09-06; WebFetch 403, plain HTTP 200) | Aviva, AXA, Churchill, Privilege, Admiral, Ageas. Not: Direct Line, Darwin, More Than, LV= |
| MoneySuperMarket | https://www.moneysupermarket.com/home-insurance/providers/ | "Reviewed on 3 Sep 2026"; "107 home insurance providers" | Featured: Admiral, Churchill, Privilege. Per-brand pages exist for aviva, axa, churchill, privilege, admiral, more-than, lv; 404 for direct-line, darwin, ageas |
| Confused.com | https://www.confused.com/home-insurance/providers | "Correct as of July 2026"; "up to 93" | Aviva, AXA, Direct Line, Churchill, Privilege, Admiral, More Than, LV=, Ageas (also Esure, Sheilas' Wheels). Not: Darwin |
| GoCompare | https://www.gocompare.com/partner-list/ and /home-insurance/providers/ | n/a | Bot wall on every attempt. Unverified |

These are marketing guide pages, not panel disclosures. Absence from a page is not
proof of absence from the panel.

## 3. Vendors and official sources

### 3.1 Consumer Intelligence

- Home Insurance Price Index. Monthly article series, e.g. 30 July 2026: quoted premiums down 7.5% in the year to June 2026, average rank 1-5 premium GBP 253. https://www.consumerintelligence.com/articles/home-insurance-premiums-down-7.5-over-the-year-but-quarterly-deflation-regains-pace . The "download" page https://www.consumerintelligence.com/home-insurance-price-index-download is behind a form and does not state the file format. Method (stated on that page): for each risk quoted in consecutive months, the change in the average of the five cheapest premiums on each PCW, averaged across risks and PCWs and chained from a base of 100. Uses "real customer quotes from PCWs and key direct brands".
- Collection: consented panel (Viewsbank), about 90,000 active risk profiles, quoted "across the UK's four major price comparison websites on the same day, alongside extensive direct insurer coverage". Article 29 June 2026 https://www.consumerintelligence.com/articles/behind-the-data-how-trusted-market-intelligence-is-built .
- ONS uses CI data for the house contents insurance and car insurance items of CPI (combined weight 0.43%). The ONS QA page (revised 26 March 2025) describes the feed as "a sample of insurance quotes" and says the data "are scraped from supplier websites". https://www.ons.gov.uk/economy/inflationandpriceindices/methodologies/qualityassuranceofadministrativedatausedincpih . CI's own wording is a consented panel. Both are recorded here; the difference is CI's problem to explain, not ours.
- Licensed products: Home Insurance Market View (brand-visible annual prices, compulsory and voluntary excess, ranking, average premiums; weekly or monthly; online portal, Excel raw data, price-claim files) https://www.consumerintelligence.com/home-insurance-market-view . Underwriter View (5,040 risks every 5 weeks, about 550,000 prices, underwriter behind each PCW brand taken from MoneySuperMarket, Power BI portal) https://www.consumerintelligence.com/underwriter-view . Pricing on request.
- This is the only vendor whose output shape matches `collect/vendor.py` and whose method is documented in public.

### 3.2 Pearson Ham Group

- **Update 2026-09-06.** Pearson Ham Group sold its insurance market pricing
  business to Defaqto (Fintel plc) on 19 January 2026 for GBP 11.0m; it was
  rebranded Defaqto Market Pricing on 1 June 2026, and Pearson Ham Group itself
  is now CIL Pearson Ham, a consultancy with no insurance data product. The
  product described below is therefore Defaqto's (3.3). `docs/VENDOR-EXTRACTS.md`
  §2.2 has the sources. The notes below are kept as the pre-sale description.
- General Insurance Price Index (home and motor): monthly top-5 figures released through the trade press (e.g. home -11.7% year on year in August 2025, median top-5 home premium GBP 196). Own pages: https://www.pearsonhamgroup.com/how-we-can-help/insights/ ("Daily pricing movements across the top 4 comparison sights, using our panel of over 6000 consumers"; home, motor, pet). https://www.pearsonhamgroup.com/insurance-insights/ returned 404. https://insuranceinsights.pearsonham.com/ describes quarterly free webinars (registration) and paid dashboards; its schedule text is dated 2021 and looks unmaintained.
- Delivery for clients (search summary, not read on a Pearson Ham page): Tableau dashboards, raw data files, daily/weekly/monthly reports. No downloadable public index file was found.

### 3.3 Defaqto

- Market Pricing Intelligence is the former Pearson Ham pricing business (see
  3.2). What it delivers, field by field, and the questions to ask before the
  first file, are in `docs/VENDOR-EXTRACTS.md`.
- Market Pricing Intelligence: daily PCW-level quotes from the four major PCWs using real customer risk profiles, each "run for a few consecutive days before dropping out of the rotation"; home covered; dashboards, raw data extracts, daily/weekly/monthly reports. Defaqto states it holds "explicit permission and agreements" with the PCWs. https://www.defaqto.com/solutions/market-pricing-intelligence . Pricing on request.
- Matrix 360: product feature and rating data (10,000+ products, refreshed four times daily), not a price feed. https://www.defaqto.com/matrix360 .

### 3.4 Insurance DataLab

- Benchmarking of insurer, MGA and broker performance (complaints, claims, customer experience; "more than 1,000 insurance companies and brands"). No quote or premium price data seen on https://www.insurancedatalab.com/ . Third-party listing (Datarade) quotes GBP 6,000 per purchase to GBP 17,950 per year; not confirmed on the vendor site. Free monthly newsletter. `COLLECTION.md` lists this vendor as a per-brand price source; on the evidence it is not one.

### 3.5 WTW and Confused.com

- Car only. The Q2 2025 Confused.com Car Insurance Price Index PDF (powered by WTW) contains no reference to home insurance. https://www.confused.com/-/media/confused/price-index/historic-price-index/price-index-q2-2025/price-index-q2-2025.pdf . No home index found on wtwco.com.

### 3.6 ABI Property Insurance Premium Tracker

- Quarterly. Measures price paid, not quoted: total value of business sold by participating insurers divided by policies sold (ABI blog 14 Aug 2023 https://www.abi.org.uk/news/blog-articles/2023/8/tracking-the-trackers/ ). "15.5 million policies sold a year."
- Q2 2026 (published 3 Aug 2026): combined GBP 383 (-2% year on year, +GBP 8 on the quarter, first quarterly rise since start of 2025); buildings-only GBP 309 (-5%); contents-only GBP 118 (-9%). https://www.abi.org.uk/media-hub/news-post/average-claim-for-subsidence-reaches-record-20000-amidst-hot-weather . Q2 2025 combined was GBP 391 (Insurance Age, 29 Jul 2025, citing ABI).
- Format: figures inside news posts only. No spreadsheet found; the ABI industry-data pages tried returned 404. Three numbers a quarter, keyed by hand.

### 3.7 FCA General Insurance Value Measures data 2025

- Page https://www.fca.org.uk/data/general-insurance-value-measures-data-2025 , published 21 July 2026, period 1 Jan-31 Dec 2025. File https://www.fca.org.uk/publication/data/gi-value-measures-data-2025.xlsx (HTTP 200, 147,512 bytes, last-modified 20 Jul 2026). Also mirrored on data.gov.uk for 2023 and 2024.
- Sheets: Information, Product Table, Firms (1,146 rows). Firms sheet columns: Firm Name, Product Category, Year, and banded Claims Frequency, Claims Acceptance Rate, Average Claims Payout, Claims Complaints as % of Claims. Threshold: at least 3,000 average policies in force and GBP 400,000 premium. Product Table adds, per product and year, average policies in force, total retail premiums written and % of premiums paid in claims, aggregate only.
- Home appears per firm as "Home - (buildings and contents combined)", plus buildings-only and contents-only where reported. Aggregate 2025 for combined home: 15.85m average policies, GBP 6.23bn written, 47.8% paid in claims.
- No premium or price per firm. Firms are legal underwriters (UKIL, EUI, LVIC), not brands. Useful as a per-underwriter denominator and a plausibility check, not as a price source.

### 3.8 FCA EP25/2, GIPP remedies evaluation

- Published 22 July 2025 (page updated 3 Dec 2025). PDF and technical annex only. Built on policy-level data from 16 home and 13 motor firms collected for the evaluation. No dataset published. https://www.fca.org.uk/publications/corporate-documents/evaluation-paper-25-2-general-insurance-pricing-practices-remedies ; https://www.fca.org.uk/publication/corporate/ep25-2.pdf .

### 3.9 ONS CPI

- D7F2: "CPI INDEX 12.5.2 : House contents insurance 2015=100", monthly; released 19 Aug 2026, next 16 Sep 2026; July 2026 = 115.6. https://www.ons.gov.uk/economy/inflationandpriceindices/timeseries/d7f2/mm23 . D7JE annual rate; D7MS monthly rate (labelled "insurance connected with the dwelling"); CJYP weight.
- CSV endpoint works without a key: `https://www.ons.gov.uk/generator?format=csv&uri=/economy/inflationandpriceindices/timeseries/d7f2/mm23` (tested 2026-09-06).
- Buildings insurance is an owner-occupier housing cost and is outside CPI; only contents is indexed. The series is driven by Consumer Intelligence quotes (3.1).

### 3.10 data.gov.uk, Bank of England

- data.gov.uk: FCA VM 2023 and 2024 datasets; HMRC Insurance Premium Tax bulletin (monthly tax receipts). No home premium dataset.
- Bank of England "Insurance aggregate data annual report" is Solvency II aggregate reporting; not premium prices. Page title confirmed only.

### 3.11 B2B distribution

- Polaris imarket is a commercial lines trading hub ("Polaris' commercial lines digital trading solution"; https://www.polaris.co.uk/products/imarket/ ). Personal lines home is traded broker-to-insurer over Polaris standards and software houses (Acturis, Applied, Open GI, SSP), all behind broker agency agreements. None of it is reachable without being a broker.
- No insurer in the ten publishes a consumer-facing or open quote API.

## 4. What is ingestible today without a licence

1. FCA GI Value Measures xlsx (2025, 2024, 2023). Per-underwriter banded claims metrics for home; aggregate premiums written. Not prices.
2. ONS D7F2 / D7JE / D7MS CSV via the generator endpoint. Monthly contents-insurance index. Not buildings.
3. ABI Property Premium Tracker: three quarterly averages, hand-keyed from the news post. Not a file.
4. Consumer Intelligence and Pearson Ham monthly index percentages, hand-keyed from articles. Aggregate top-5 movement only.
5. Your own renewal notice: ICOBS 6.5.1R requires the renewal premium and the premium at inception of the expiring policy (annualised after any mid-term change) to be shown together, and a shop-around statement from the fourth renewal. In force 1 Jan 2022. https://www.handbook.fca.org.uk/handbook/ICOBS/6/5.html . One real per-brand data point a year, free.
6. Manual quotes in your own browser, as `COLLECTION.md` describes. Real, per brand, per quote, and not scriptable.

Everything per-brand and per-quote at scale is Consumer Intelligence, Pearson
Ham or Defaqto under contract.

## 5. The terms boundary

- Compare the Market, Terms and Conditions, "Last updated: 11 Aug 2026", under "The Legal Bits": "You must not access, monitor, reproduce ... any content on the Platform, including Quotes, prices ... using a robot, spider, scraper or other automated tool, or any manual process, for any purpose not permitted". https://www.comparethemarket.com/information/terms-and-conditions/ (plain HTTP 200; WebFetch 403).
- MoneySuperMarket, Terms and Conditions, last updated 13 July 2026, clause 2.2(c): no "text or data mining or web scraping in relation to our Site, our App or any Services". https://www.moneysupermarket.com/legal/terms/ .
- Confused.com, Terms and Conditions, last updated 1 July 2025, section "Commercial use": bulk or commercial use is monitored and searches may be aborted. https://www.confused.com/privacy-and-security/terms-and-conditions/confused-com-terms-and-conditions .
- GoCompare: terms page https://www.gocompare.com/about/terms/ served a bot-detection page on every attempt. Clause not read.
- ICOBS 6.5.1R as above. The renewal notice is the one FCA-mandated place where a real premium for a real risk is put in writing for the customer.

## 6. Unverified / could not confirm

- GoCompare's home panel and its terms (bot wall on all three pages tried).
- Whether Compare the Market's providers page is its full home panel (it reads as a guide list; a "more than 50 providers" count appears in search snippets, not on the page read).
- Direct Line's presence on CTM, MSM and GoCompare after the "late September" 2026 expansion; only Confused.com is confirmed by Aviva.
- Admiral's own completion release text (admiralgroup.co.uk 403); confirmed via a syndicated copy and the Intact release.
- Ageas group release on ageas.com (403) and the exact GBP 1.295bn figure on the completion page (the figure is on the 14 April 2025 agreement release).
- Insurance DataLab pricing (third-party listing only) and whether it holds any premium data (none seen).
- Pearson Ham client delivery formats (from search summary; vendor page 404) and whether any public index file exists (none found).
- Consumer Intelligence's index download format (form-gated).
- ABI Q1 2026 combined figure (GBP 375 per search snippet; the ABI URL returned 404).
- Aviva developer portal contents (403 from this network).
- Allianz's 2019/2020 completion release for LV= GI (not fetched; ownership taken from the 24 April 2026 Allianz UK release).
- Whether Darwin is on any PCW for anything other than car (irrelevant to home; noted for completeness).

## 7. Sources

Insurers and groups
- https://www.aviva.com/newsroom/news-releases/2025/07/aviva-completes-acquisition-of-direct-line/
- https://www.investegate.co.uk/announcement/rns/direct-line-insurance-group--dlg/aviva-completes-acquisition-of-direct-line/8958714
- https://www.aviva.com/newsroom/news-and-research-overview/news-releases/2026/09/direct-line-home-insurance-launches-on-price-comparison-websites-for-the-first-time/
- https://www.aviva.com/newsroom/news-releases/
- https://www.aviva.co.uk/insurance/home-products/home-insurance/
- https://developer.aviva.co.uk/insurance
- https://www.axa.co.uk/home-insurance/
- https://www.directline.com/home-cover
- https://www.churchill.com/home-insurance
- https://www.privilege.com/home-insurance
- https://www.darwin-insurance.com/
- https://www.directlinegroup.co.uk/en/brands/darwin.html (redirects to aviva.com)
- https://www.directlinegroup.co.uk/en/news/company-news/2024/20240710.html (redirects to aviva.com)
- https://www.admiral.com/home-insurance
- https://www.admiralgroup.co.uk/news-releases/news-release-details/admiral-completes-acquisition-rsa-direct-home-and-pet-insurance (403)
- https://insurancenewsnet.com/oarticle/admiral-completes-the-acquisition-of-rsa-direct-home-and-pet-insurance-renewal-rights-for-82-5-million
- https://www.intactfc.com/press-releases/1/intact-financial-corporation-and-rsa-announce-sale-of-uk-direct-personal-lines-operations-to-admiral-group-plc
- https://www.morethan.com/home-insurance/
- https://www.lv.com/home-insurance
- https://www.allianz.co.uk/news-and-insight/news/allianz-and-lv-long-term-partnership.html
- https://www.ageas.co.uk/home-insurance/
- https://www.ageas.co.uk/press-releases/2025/ageas-reaches-agreement-with-bain-capital-to-acquire-esure-and-establish-a-top-3-uk-personal-lines-platform/
- https://www.ageas.co.uk/press-releases/2025/ageas-uk-completes-acquisition-of-esure/
- https://www.esuregroup.com/media/xn4hx3qp/ageas-press-release-esure-completion-250925-final-approved.pdf
- https://www.polaris.co.uk/products/imarket/

PCWs
- https://www.comparethemarket.com/home-insurance/providers/
- https://www.comparethemarket.com/information/terms-and-conditions/
- https://www.moneysupermarket.com/home-insurance/providers/
- https://www.moneysupermarket.com/legal/terms/
- https://www.confused.com/home-insurance/providers
- https://www.confused.com/privacy-and-security/terms-and-conditions/confused-com-terms-and-conditions
- https://www.gocompare.com/partner-list/ (bot wall)
- https://www.gocompare.com/home-insurance/providers/ (bot wall)
- https://www.gocompare.com/about/terms/ (bot wall)
- https://insurance-edge.net/2026/09/04/direct-line-home-products-now-available-on-comparison-sites/ (secondary, used only to locate the Aviva release)

Vendors
- https://www.consumerintelligence.com/home-insurance-price-index-download
- https://www.consumerintelligence.com/articles/home-insurance-premiums-down-7.5-over-the-year-but-quarterly-deflation-regains-pace
- https://www.consumerintelligence.com/articles/behind-the-data-how-trusted-market-intelligence-is-built
- https://www.consumerintelligence.com/home-insurance-market-view
- https://www.consumerintelligence.com/underwriter-view
- https://www.pearsonhamgroup.com/how-we-can-help/insights/
- https://www.pearsonhamgroup.com/insurance-insights/ (404)
- https://insuranceinsights.pearsonham.com/
- https://www.defaqto.com/solutions/market-pricing-intelligence
- https://www.defaqto.com/matrix360
- https://www.insurancedatalab.com/
- https://www.confused.com/-/media/confused/price-index/historic-price-index/price-index-q2-2025/price-index-q2-2025.pdf

Official
- https://www.abi.org.uk/media-hub/news-post/average-claim-for-subsidence-reaches-record-20000-amidst-hot-weather
- https://www.abi.org.uk/news/blog-articles/2023/8/tracking-the-trackers/
- https://www.insuranceage.co.uk/insight/7957001/home-insurance-premiums%E2%80%AFflat-in-q2-%E2%80%93-abi (secondary, Q2 2025 figure)
- https://www.fca.org.uk/data/general-insurance-value-measures-data-2025
- https://www.fca.org.uk/publication/data/gi-value-measures-data-2025.xlsx
- https://www.fca.org.uk/publications/corporate-documents/evaluation-paper-25-2-general-insurance-pricing-practices-remedies
- https://www.fca.org.uk/publication/corporate/ep25-2.pdf
- https://www.handbook.fca.org.uk/handbook/ICOBS/6/5.html
- https://www.ons.gov.uk/economy/inflationandpriceindices/timeseries/d7f2/mm23
- https://www.ons.gov.uk/economy/inflationandpriceindices/timeseries/d7ms/mm23
- https://www.ons.gov.uk/economy/inflationandpriceindices/methodologies/qualityassuranceofadministrativedatausedincpih
- https://www.data.gov.uk/dataset/c74cbcdc-7512-4347-bfd7-c4533c3c8823/fca-general-insurance-value-measures-data-2024
- https://www.bankofengland.co.uk/statistics/insurance-aggregate-annual-data-report
