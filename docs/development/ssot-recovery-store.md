# Managed local recovery graphs

`finjuice ssot backup store` manages complete recovery graphs as retained
copies. Each copy contains the snapshot and the release and migration evidence
needed by the [recovery operator](ssot-recovery-operator.md). Retention removes
whole eligible copies; it does not collect original source objects or arbitrary
dataset generations.

## Enrollment and capture

Keep the independently enrolled `--expected` JSON outside the store. Its exact
format is documented in the recovery operator guide. Store metadata binds the
container to that enrollment, but cannot replace the independent expectation.
Use a new store when activation or release enrollment changes.

Initialize with `store init --store STORE --expected EXPECTED`. Capture with
`store capture` and the explicit `--store`, `--expected`, `--source-data-dir`,
`--wheel`, `--dependency-lock`, `--binding`, and `--migration-candidate` options.
All commands support `--json`. Consult each command's `--help` for current
syntax.

The first successful capture registers a protected baseline. The returned
`copy_id` identifies the published graph. `store protect --copy-id COPY`
verifies an existing graph before registering an additional baseline; provide
`--store` and `--expected` as for other commands. Baseline registration is
durable and binds verified content, rather than a mutable health label. There
is no unprotect command. Keep the store's control directory with its copies;
deleting registration files is not a supported way to reset protection.

If the first capture is interrupted or its baseline registration fails, this
implementation refuses to bootstrap that store again. Preserve its remaining
copies and control evidence, and initialize a new store for the next capture.
An existing store whose required registration is lost also fails closed.

## Inspect, plan, and retain

`store list` verifies the inventory. `store verify --copy-id COPY` verifies one
copy. Both require `--store` and `--expected` and may perform substantial reads.
Incomplete, unreadable, or invalid entries cannot become deletion candidates
merely because they are old.

`store plan` accepts optional `--daily`, `--weekly`, and `--monthly` GFS windows.
Review its selected copy IDs and `plan_digest`. `store prune` accepts the same
policy and an optional `--plan-digest` to reject a changed plan. Prune always
recomputes eligibility while holding the exclusive store lease. Baselines and
the latest verified snapshot revision remain protected even with zero GFS
windows. A missing or invalid required baseline prevents cleanup.

Capture and source readers share the container lease through their actual
work. Prune waits for those readers. Deletion records durable intent before
moving an eligible copy out of the published inventory. Interrupted cleanup
is resumed with identity and protection checks; a newly created directory at
an old copy name is not the original deletion target. Retry through the CLI
instead of manually editing control records or deleting staging directories.
The prune receipt counts copies whose trees were actually removed during this
call, including resumed removals. Finishing only a leftover intent record after
an earlier call removed the tree does not count as another deletion.

## Restore and operational evidence

`store restore --copy-id COPY --target TARGET --store STORE --expected EXPECTED`
verifies the graph and restores into a fresh inactive workspace. The seven-field
restore receipt binds the restored manifest, generation, schema, and revision
to the verified source graph. Existing active-target guards still apply. A
restore does not activate the result; subsequent read, mutation, rebackup, and
second-restore checks provide separate evidence of usability.

This command family supplies a local retention mechanism. A successful local
capture or prune does not prove an off-device copy, independent key recovery,
a scheduled run, capacity readiness, measured RPO/RTO, or production cutover.
Those require separate recorded operations against the actual deployed release
and operating baseline. Preserve the independent expected document and the
store control data when planning that recovery path.
