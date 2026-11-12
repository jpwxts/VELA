# Validation protocol amendment — 12 November 2026

Status: approved for the Arnhem reserve run on 12 November 2026.
Version: 2026-11-12b.

## Preserved result

The original four-week attempt stands as reported:

| Week | Eligible cell-days | Weekly absolute error (percentage points) |
|---|---:|---|
| Cerrado 22–28 Feb 2021 | 4,964 | raw 0.020; logistic 85.980; forest 0.675 |
| California 22–28 Mar 2021 | 4,613 | raw 0.130; logistic 47.579; forest 0.395 |
| Zambia 19–25 Jul 2021 | 7,493 | raw 7.247; logistic 9.609; forest 1.122 |
| Yakutia 22–28 Nov 2021 | 0 | undefined |

Yakutia remains an attempted week with undefined error. It is not replaced by a silent substitute. The 2023–2024 final test and Pantanal stay reserved. NOAA-20 and NOAA-21 raw observations stay available; their calibration stays pending.

## Existing rules that still apply

1. Development scoring uses 2021–2022 tune weeks only.
2. Candidates stay frozen. No refit during selection.
3. Selection needs four scored weeks (`min_tune_weeks`).
4. Equal-weight mean of weekly absolute errors in percentage points; tie-break raw VIIRS, then logistic regression, then random forest.
5. Catalog preselection and budget walks do not use fire counts.
6. A week with zero catalog daytime pairs may draw the next reserve during the metadata search (`scripts/plan_validation.py`).
7. The budget walk does not skip ahead to a later smaller week.

## Gap this amendment fills

There was no written rule for a week that has catalog daytime pairs, downloads successfully, and then yields zero cell-days with shared visible land under the half-cell rule. Yakutia is that case.

## Proposed reserve-week rule

1. Keep every attempted week in the published table. If it is not scorable, record the reason and leave its absolute error undefined.
2. Eligible development dates remain 2021–2022 tune weeks outside Pantanal and outside 2023–2024.
3. Deterministic candidate order: the existing `validation_priority.next_preselected_weeks` list in `data/models/model_selection.json`, starting after the last attempted week. Do not reorder by fire counts, Aqua activity rates, or candidate errors.
4. Coverage-only eligibility check before scoring: after processing, a week is scorable only when `summarize_week` reports `coverage_status == "ok"` on jointly eligible Aqua–Suomi-NPP cell-days. Catalog footprint overlap alone is not enough.
5. Stopping rule: attempt the next ordered week; stop when four weeks are scored, when the reserve list is exhausted, or when a download would exceed the active byte budget. Do not skip an unscorable attempted week out of the published record.
6. Fire counts, Aqua activity rates, and candidate errors stay out of the choice of which week to attempt next.

## How a reserve enters the four-week selection rule

1. A reserve week that passes the coverage-only eligibility check is scored with the frozen candidates on the same absolute-error metric as the primary weeks: the absolute difference between each method’s aggregate activity rate and the observed Aqua rate, in percentage points.
2. Unscorable attempted weeks, including Yakutia, stay in the published table with undefined error and are excluded from the equal-weight mean.
3. When four scored weeks exist, compute the equal-weight mean of those four weekly absolute errors and apply the documented tie-break (raw VIIRS, then logistic regression, then random forest).
4. Keep two labeled records: the original four-week attempt with Yakutia undefined, and a separate reserve-inclusive selection result that lists every attempted week and uses only the scored weeks in the mean.

## First reserve under this amendment

Arnhem Land, 28 November–4 December 2022 (`next_preselected_weeks` after Yakutia). This week is a 2022 tune week. It is outside the frozen candidates’ training years (2013, 2014, 2017, 2019) and training regions (California, Cerrado, Yakutia), and it is outside the reserved 2023–2024 final test and Pantanal. Its place in the order was fixed by `next_preselected_weeks` before fire counts or model scores were inspected.
