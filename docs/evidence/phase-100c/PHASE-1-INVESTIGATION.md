# Phase 100-C Phase 1 investigation — Shenwan industry point-in-time visibility

Status: `PROVABLE` — Phase 2 integration proceeded.
Scope: Tushare `index_classify` and `index_member_all` (申万行业分类/成分).
Provider account: 6000-point tier. Real credentials were used only for isolated,
read-only verification against an isolated `byq_domain_test` database; they were
never persisted to any database, log or evidence artifact.

## 1. Official documentation facts

| Item | `index_classify` | `index_member_all` |
|---|---|---|
| Purpose | Shenwan industry tree, per source version | Shenwan membership by third-level industry or stock |
| Minimum points | 2000 | 2000 |
| Page limit | no stated per-request cap (511/359 rows observed) | 2000 rows per request, no total cap |
| As-of date parameter | none | none |
| Request selectors | `index_code`, `level`, `parent_code`, `src` | `l1_code`, `l2_code`, `l3_code`, `ts_code`, `is_new` |
| Output fields | `index_code`, `industry_name`, `parent_code`, `level`, `industry_code`, `is_pub`, `src` | `l1_code`, `l1_name`, `l2_code`, `l2_name`, `l3_code`, `l3_name`, `ts_code`, `name`, `in_date`, `out_date`, `is_new` |

`index_classify` is versioned by `src` (`SW2014` / `SW2021`); it carries no dates.
`index_member_all` is the only point-in-time signal, through explicit
`in_date`/`out_date` columns plus the `is_new` snapshot flag (`Y` current, `N` removed).

## 2. Real isolated observations

- `index_classify` SW2021 = 511 rows (31 L1 / 134 L2 / 346 L3); SW2014 = 359 rows
  (28 L1 / 104 L2 / 227 L3). `parent_code` is the 6-digit `industry_code` of the
  parent (or `"0"` for L1), not an `.SI` index code. SW2014 returns a null `is_pub`.
- `index_member_all` current (`is_new=Y`) = 5913 rows; removed (`is_new=N`) = 2006 rows.
  Pagination is required and works via `offset`/`limit` (pages of 2000).
- Every persisted membership row carries `in_date`; settled (`N`) rows carry
  `out_date`. No missing `in_date`, no `out_date < in_date`, and no current (`Y`)
  row carries an `out_date`.
- Intervals are non-overlapping per stock: 0 overlapping interval pairs across all
  7918 rows. 302 stocks have more than one removed interval, i.e. multi-stint
  industry history is preserved (e.g. `000004.SZ`: 住宅开发 1989→2008,
  化学制剂 2008→2021, IT服务 2021→2021).
- One row (`T00018.SH`) is a non-canonical historical identity; it is quarantined
  by the provider contract and reported (`rows_quarantined=1`) rather than stored
  or silently dropped.
- The version switchover is real: 564 removals dated `out_date=20210729` and 519
  additions dated `in_date=20210730` around the SW2014→SW2021 transition.

## 3. Point-in-time proof

Inclusion/exclusion dates truly exist and reproduce point-in-time membership:

- Membership as-of a date is `in_date <= as_of < out_date` (or `out_date` null),
  reconstructed from the union of the `Y` and `N` snapshots.
- Cross-date reconstruction changes membership count and identity for every probe:
  - `850531.SI` (黄金): 10 / 11 / 12 / 11 / 13 members at
    2015/2018/2020/2022/2025.
  - `850551.SI` (铝): 21 / 23 / 26 / 36 / 36.
  - `857831.SI` (股份制银行Ⅲ): 8 / 8 / 9 / 9 / 9.
- Current constituents are never backfilled: a stock whose `in_date` is after the
  as-of date is excluded, even when it is a current member.
- The interface is deterministic: identical queries return identical rows.

## 4. Critical provider trap (recorded)

`index_member_all` has **no** as-of date parameter. Passing `trade_date`,
`start_date` or `end_date` is silently ignored and returns the *current*
constituents; it does not fail and does not produce historical membership. A naive
integration would therefore silently leak current membership into history.

Consequence (implementation boundary): the BYQ contract exposes **no** date field
for `index_member_all`, rejects unknown date-like sync fields at the boundary, and
performs point-in-time reconstruction locally from persisted intervals only.

## 5. Licensing / coverage caveats

- Both endpoints require 2000 points; the account is in the 6000-point tier.
- The provider controls the completeness of the removed (`N`) history; BYQ does not
  claim completeness. It records per-row content hashes and provenance, and the
  coverage audit reports open/settled counts, interval overlaps, orphan industry
  codes and quarantined identities.
- 35 SW2021 L3 codes have no current constituent; 1 member L3 code (`850412.SI`)
  is absent from the SW2021 classification tree. These are provider realities and
  are surfaced by the coverage audit, not hidden.

## 6. Verdict and implementation boundary

Point-in-time semantics are provable from explicit `in_date`/`out_date` intervals,
so Phase 2 proceeded with:

1. A provider-neutral contract (`IndexClassifyRequest`/`IndexMemberAllRequest`,
   `IndexMember.interval_sha256`) with fail-able negatives and no date filter.
2. Authoritative PostgreSQL storage (`market_index_classify`,
   `market_index_member_all`) with per-row content hashes and provenance.
3. Idempotent incremental sync jobs (`kind=classify|member`) with an idempotency
   key, request hash, audit trail, terminal no-op, and open→settled reconciliation
   that never rewrites settled history.
4. A fail-closed coverage audit and `membership_asof`/`readiness` computed only
   from persisted intervals, plus `market_readiness` integration via the declared
   `industry_membership` dataset.
