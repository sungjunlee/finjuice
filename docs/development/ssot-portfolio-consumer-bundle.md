# Revision-pinned portfolio consumer inputs

`materialize_portfolio_consumer_bundle()` derives balance, investment, and loan
CSV partitions from one `RepositoryReader` snapshot. Operating callers must open
that reader through the enrolled authority boundary; this internal API does not
approve a data root or release on its own.

The original `materialize_legacy_consumer_bundle()` remains a historical capture
projection. Repeating that historical API at a newer revision does not include
new native reports. The portfolio API uses primary captured typed reports and
native overview rows, retaining empty latest partitions and distinct identities.

## Output and reuse

- Existing consumer paths remain `banksalad/<domain>/YYYY/MM/<domain>.csv`.
- Each CSV has an exact JSON companion retaining coefficients, scales, lexical
  values, per-value currencies, and original rate units.
- The manifest records generation, revision, schema, domain dates, output hashes,
  and readiness. Captured overlay bytes are verified and preserved together.
- Publication is atomic. A matching complete output can be reused; a stale,
  modified, or unsafe output is rejected rather than overwritten.

## Readiness boundary

Readiness concerns the declared report inputs. It does not establish current
household coverage, ownership, exchange rates, or freshness of a captured manual
overlay. Consumers must retain these limits in their report, rather than treating
a current repository revision as current market data.

Unknown currency, missing required values, unsupported percentage units, and
unrepresented native projection evidence prevent a usable report decision.
Native asset snapshots are not silently merged into overview totals: their
classification and overlap cannot be inferred from names. Source rate units are
preserved; fraction-versus-percentage conversion is not guessed.

The legacy report implementation remains a consumer policy. This projection
neither changes its formulas nor proves that its totals represent complete
family net worth. Operating integration and first actual use remain separate
acceptance work under #439 and #440.
