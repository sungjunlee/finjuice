# JSON Output Schema Reference

> Generated from `schemas/*.schema.json`. Run `just docs-output-schemas` to update.

finjuice command JSON outputs use Draft 2020-12 schemas. Command schemas include
`_meta` by reference and keep additive fields open unless a command contract requires
a stricter nested shape.

`review --json`, `rules suggest --json`, `automation run --json`,
`checkup --json`, and `index --json` support `--privacy raw|redacted|compact`;
`_meta.privacy.profile` identifies the applied profile. The default is
raw-compatible for backward compatibility. `query --json` intentionally does not
expose privacy profiles because
arbitrary SQL projections can rename or compute sensitive row fields outside a stable
redaction contract.

Schemas for privacy-enabled commands model the shared envelope plus profile-specific
variants: raw/redacted keep the raw object shape with masked values where applicable,
while compact may remove path/sample fields and replace bulky collections with counts.

**Error envelopes are part of the CLI JSON contract.** When a `--json` invocation
fails, the process emits an object matching `schemas/_error.schema.json` — a `_meta`
block, an `error` object with a stable machine-readable `code` (see the enum in that
schema) and a human `message`, and a process `exit_code`. Agents should branch on
`error.code` rather than parsing `error.message`. The failure-mode matrix lives in
`tests/cli/test_error_envelope_contract_matrix.py` and pins representative
command/code/exit-code combinations against this schema.

## Artifact Catalog

| Artifact | Title | Required result fields |
|----------|-------|------------------------|
| `schemas/_meta.schema.json` | _meta envelope | `schema_version`, `finjuice_version`, `command`, `timestamp` |
| `schemas/_error.schema.json` | Error envelope | `error`, `exit_code` |
| `schemas/_pagination.schema.json` | Pagination envelope | `limit`, `cursor`, `next_cursor`, `has_more` |
| `schemas/all.schema.json` | all --json output | `command`, `steps` |
| `schemas/assets_balance.schema.json` | assets balance --json output | `has_data`, `latest_month`, `snapshot_date`, `total_assets`, `total_liabilities`, `assets`, `liabilities` |
| `schemas/assets_show.schema.json` | assets show --json output | `has_data` |
| `schemas/assets_status.schema.json` | assets status --json output | `has_data` |
| `schemas/audit_clear.schema.json` | audit clear --json output | `entries_kept`, `action`, `skipped_entries` |
| `schemas/audit_log.schema.json` | audit log --json output | `events`, `count`, `skipped_entries` |
| `schemas/audit_stats.schema.json` | audit stats --json output | `suggestions`, `executions`, `success_rate`, `top_commands`, `skipped_entries` |
| `schemas/automation_run.schema.json` | automation run --json output | `enabled`, `actionable`, `thresholds`, `pending_imports`, `tagging_pressure`, `large_transactions`, `next_steps`, `warnings` |
| `schemas/backup_create.schema.json` | backup create --json output | `status`, `schema_version`, `manifest_digest`, `entry_count`, `file_count`, `directory_count`, `byte_count`, `root_count`, `absent_optional_count`, `finjuice_version`, `data_schema_version`, `data_schema_version_status`, `consistency_kind` |
| `schemas/backup_restore.schema.json` | backup restore --json output | `status`, `schema_version`, `manifest_digest`, `entry_count`, `file_count`, `directory_count`, `byte_count`, `root_count`, `absent_optional_count`, `finjuice_version`, `data_schema_version`, `data_schema_version_status`, `consistency_kind`, `generation_status` |
| `schemas/backup_verify.schema.json` | backup verify --json output | `status`, `schema_version`, `manifest_digest`, `entry_count`, `file_count`, `directory_count`, `byte_count`, `root_count`, `absent_optional_count`, `finjuice_version`, `data_schema_version`, `data_schema_version_status`, `consistency_kind` |
| `schemas/budget_edit.schema.json` | budget edit --json output | `path`, `changes`, `monthly_budget` |
| `schemas/budget_status.schema.json` | budget status --json output | `month`, `goals_file`, `summary`, `categories`, `unmatched_goal_categories`, `health`, `actionable`, `signals`, `review`, `next_steps` |
| `schemas/budget_validate.schema.json` | budget validate --json output | `status`, `path`, `problems` |
| `schemas/checkup.schema.json` | checkup --json output | `summary`, `actionable`, `warnings`, `next_actions`, `domains` |
| `schemas/context.schema.json` | context --json output | `journals`, `status_snapshot`, `active_goals`, `financial_metadata`, `rule_notes`, `top_patterns` |
| `schemas/doctor.schema.json` | doctor --json output | `checks`, `summary`, `missing_extras`, `install_hint` |
| `schemas/explain.schema.json` | explain --json output | `query`, `date_filter` |
| `schemas/export.schema.json` | export --json output | - |
| `schemas/export_verify.schema.json` | export-verify --json output | `command`, `manifest_path`, `source`, `current`, `stale`, `integrity`, `files` |
| `schemas/history.schema.json` | history --json output | `records`, `count` |
| `schemas/import.schema.json` | import --json output | `files_processed`, `files_skipped`, `errors` |
| `schemas/index.schema.json` | index --json output | `workspace`, `collections`, `recommended_next`, `schema_ref` |
| `schemas/ingest.schema.json` | ingest --json output | `command`, `dry_run`, `source` |
| `schemas/init.schema.json` | init --json output | `status`, `data_dir`, `already_initialized` |
| `schemas/inspect_xlsx.schema.json` | inspect xlsx --json output | `file`, `summary`, `worksheets` |
| `schemas/journal_list.schema.json` | journal list --json output | `entries`, `count` |
| `schemas/manifest.schema.json` | manifest --json output | `manifest_schema_version`, `finjuice_version`, `commands` |
| `schemas/networth.schema.json` | networth --json output | `as_of`, `total_assets`, `total_liabilities`, `net_worth`, `health`, `actionable`, `signals`, `next_steps` |
| `schemas/networth_breakdown.schema.json` | networth breakdown --json output | `as_of`, `breakdown` |
| `schemas/networth_forecast.schema.json` | networth forecast --json output | - |
| `schemas/networth_history.schema.json` | networth history --json output | `history` |
| `schemas/networth_init.schema.json` | networth init --json output | `path`, `created`, `message` |
| `schemas/networth_validate.schema.json` | networth validate --json output | `path`, `exists`, `valid`, `status`, `version`, `manual_assets`, `liabilities`, `errors`, `warnings`, `problems` |
| `schemas/query.schema.json` | query --json output | `rows`, `row_count`, `pagination` |
| `schemas/reconcile.schema.json` | reconcile --json output | `command`, `evidence_count`, `payment_count`, `matched`, `partial`, `unmatched`, `groups` |
| `schemas/refresh.schema.json` | refresh --json output | `command`, `steps` |
| `schemas/review.schema.json` | review --json output | `transactions`, `total_count`, `filters`, `month`, `health`, `actionable`, `signals`, `rule_notes`, `next_steps`, `pagination` |
| `schemas/rules_add.schema.json` | rules add --json output | `action`, `rule`, `validation` |
| `schemas/rules_export.schema.json` | rules export --json output | `rule_count`, `rules` |
| `schemas/rules_gaps.schema.json` | rules gaps --json output | `summary`, `critical_gaps`, `mismatches`, `simulations` |
| `schemas/rules_list.schema.json` | rules list --json output | `rule_count`, `rules` |
| `schemas/rules_remove.schema.json` | rules remove --json output | `action`, `rule_name`, `validation` |
| `schemas/rules_suggest.schema.json` | rules suggest --json output | - |
| `schemas/rules_test.schema.json` | rules test --json output | `rule_name`, `scope`, `match_count`, `sample`, `monthly_distribution`, `cross_tags_top` |
| `schemas/rules_validate.schema.json` | rules validate --json output | `status`, `total_rules`, `errors`, `warnings`, `passed`, `problems` |
| `schemas/show.schema.json` | show --json output | `rows`, `row_count`, `total_matches`, `pagination` |
| `schemas/ssot_account_confirm.schema.json` | ssot account confirm output | `binding_id`, `account_id`, `committed_revision`, `replayed` |
| `schemas/ssot_account_correct.schema.json` | ssot account correct output | `binding_id`, `account_id`, `supersedes_binding_id`, `committed_revision`, `replayed` |
| `schemas/ssot_account_list.schema.json` | ssot account list output | `dataset_revision`, `accounts`, `bindings`, `candidates` |
| `schemas/ssot_account_ownership.schema.json` | ssot account ownership output | `dataset_revision`, `account_id`, `as_of` |
| `schemas/ssot_account_ownership_confirm.schema.json` | ssot account ownership-confirm output | `assertion_id`, `account_id`, `confirmation_state`, `evidence`, `shares`, `committed_revision`, `replayed` |
| `schemas/ssot_account_ownership_correct.schema.json` | ssot account ownership-correct output | `assertion_id`, `account_id`, `supersedes_assertion_id`, `confirmation_state`, `evidence`, `shares`, `committed_revision`, `replayed` |
| `schemas/ssot_account_preview.schema.json` | ssot account preview output | `expected_generation`, `expected_revision`, `before`, `after`, `observed_scope`, `historical_rows_rewritten`, `importer_supported` |
| `schemas/ssot_assets_confirm.schema.json` | ssot assets confirm output | `assertion_id`, `committed_revision`, `replayed` |
| `schemas/ssot_assets_correct.schema.json` | ssot assets correct output | `assertion_id`, `committed_revision`, `replayed` |
| `schemas/ssot_assets_list.schema.json` | ssot assets list output | `sources`, `pending`, `dataset_revision` |
| `schemas/ssot_assets_relation_confirm.schema.json` | ssot assets relation-confirm output | `assertion_id`, `committed_revision`, `replayed` |
| `schemas/ssot_assets_relation_correct.schema.json` | ssot assets relation-correct output | `assertion_id`, `committed_revision`, `replayed` |
| `schemas/ssot_assets_report.schema.json` | ssot assets report output | `completeness`, `net_worth_total`, `known_net_worth_subtotal`, `lines`, `issues`, `dataset_revision` |
| `schemas/ssot_backup_capture_bundle.schema.json` | ssot backup capture-bundle --json output | `kind`, `graph_digest`, `activation_sha256`, `wheel_basename`, `snapshot_generation`, `snapshot_backup_id`, `snapshot_manifest_digest`, `capsule_digest`, `snapshot_schema_version`, `snapshot_revision`, `activation_revision`, `file_count` |
| `schemas/ssot_backup_create.schema.json` | ssot backup create --json output | `backup_id`, `backup_kind`, `database_digest`, `manifest_digest`, `source_generation`, `byte_count`, `dataset_revision`, `file_count`, `manifest_schema_version`, `complete`, `status`, `warnings` |
| `schemas/ssot_backup_deliver_run.schema.json` | ssot backup deliver run --json output | `kind`, `job_id`, `recording`, `backup`, `source_observed_revision`, `coverage_as_of`, `pending_commit_count`, `last_verified_at`, `last_attempt_error_code`, `history_unknown`, `attempt` |
| `schemas/ssot_backup_deliver_status.schema.json` | ssot backup deliver status --json output | `kind`, `job_id`, `recording`, `backup`, `source_observed_revision`, `coverage_as_of`, `pending_commit_count`, `last_verified_at`, `last_attempt_error_code`, `history_unknown`, `attempt` |
| `schemas/ssot_backup_restore.schema.json` | ssot backup restore --json output | `restore_id`, `descriptor_digest`, `dataset_generation`, `initial_database_digest`, `source_manifest_digest`, `initial_dataset_revision`, `sqlite_schema_version` |
| `schemas/ssot_backup_restore_bundle.schema.json` | ssot backup restore-bundle --json output | `restore_id`, `descriptor_digest`, `dataset_generation`, `initial_database_digest`, `source_manifest_digest`, `initial_dataset_revision`, `sqlite_schema_version` |
| `schemas/ssot_backup_status.schema.json` | ssot backup status --json output | `byte_count`, `file_count`, `complete`, `reason`, `manifest_digest`, `source_generation` |
| `schemas/ssot_backup_store_capture.schema.json` | ssot backup store capture --json output | `kind`, `graph_digest`, `activation_sha256`, `wheel_basename`, `snapshot_generation`, `snapshot_backup_id`, `snapshot_manifest_digest`, `capsule_digest`, `snapshot_schema_version`, `snapshot_revision`, `activation_revision`, `file_count`, `copy_id`, `baseline_registered` |
| `schemas/ssot_backup_store_init.schema.json` | ssot backup store init --json output | `kind`, `store_id`, `activation_sha256`, `enrollment_digest` |
| `schemas/ssot_backup_store_list.schema.json` | ssot backup store list --json output | `kind`, `store_id`, `healthy_count`, `held_count`, `baseline_copy_ids`, `latest_healthy_id`, `copies`, `plan_digest` |
| `schemas/ssot_backup_store_plan.schema.json` | ssot backup store plan --json output | `kind`, `plan_digest`, `delete_count`, `keep_count`, `protected_count`, `latest_healthy_id`, `policy`, `keep_ids`, `delete_ids`, `protected_ids` |
| `schemas/ssot_backup_store_protect.schema.json` | ssot backup store protect --json output | `kind`, `copy_id`, `graph_digest` |
| `schemas/ssot_backup_store_prune.schema.json` | ssot backup store prune --json output | `kind`, `deleted_count`, `kept_count`, `held_count`, `plan_digest`, `deleted_ids`, `kept_ids` |
| `schemas/ssot_backup_store_restore.schema.json` | ssot backup store restore --json output | `restore_id`, `descriptor_digest`, `dataset_generation`, `initial_database_digest`, `source_manifest_digest`, `initial_dataset_revision`, `sqlite_schema_version` |
| `schemas/ssot_backup_store_verify.schema.json` | ssot backup store verify --json output | `kind`, `graph_digest`, `activation_sha256`, `wheel_basename`, `snapshot_generation`, `snapshot_backup_id`, `snapshot_manifest_digest`, `capsule_digest`, `snapshot_schema_version`, `snapshot_revision`, `activation_revision`, `file_count` |
| `schemas/ssot_backup_verify_bundle.schema.json` | ssot backup verify-bundle --json output | `kind`, `graph_digest`, `activation_sha256`, `wheel_basename`, `snapshot_generation`, `snapshot_backup_id`, `snapshot_manifest_digest`, `capsule_digest`, `snapshot_schema_version`, `snapshot_revision`, `activation_revision`, `file_count` |
| `schemas/ssot_close_history.schema.json` | ssot close history output | `revisions`, `periods` |
| `schemas/ssot_close_reopen.schema.json` | ssot close reopen output | `close_id`, `period`, `close_revision`, `replayed` |
| `schemas/ssot_close_run.schema.json` | ssot close run output | `close`, `close_id`, `report_digest`, `diff`, `reclosed`, `replayed` |
| `schemas/ssot_intake_confirm.schema.json` | ssot intake confirm output | `proposal_id`, `confirmation_id`, `applied`, `committed_revision`, `replayed` |
| `schemas/ssot_intake_list.schema.json` | ssot intake list output | `dataset_generation`, `dataset_revision`, `decisions` |
| `schemas/ssot_intake_revise.schema.json` | ssot intake revise output | `proposal_id`, `parent_proposal_id`, `parent_status`, `application_key`, `expected_generation`, `expected_revision`, `committed_revision`, `replayed` |
| `schemas/ssot_intake_submit.schema.json` | ssot intake submit output | `proposal_id`, `source_artifact_id`, `occurrence_id`, `committed_revision`, `replayed` |
| `schemas/ssot_intake_withdraw.schema.json` | ssot intake withdraw output | `proposal_id`, `confirmation_id`, `status`, `committed_revision`, `replayed` |
| `schemas/ssot_migrate_build.schema.json` | ssot migrate build --json output | `status`, `phase`, `manifest_digest`, `input_count`, `cutover_ready`, `limitations`, `generation_status`, `attempt_id`, `origin_kind`, `dataset_revision`, `checks` |
| `schemas/ssot_migrate_plan.schema.json` | ssot migrate plan --json output | `status`, `phase`, `manifest_digest`, `input_count`, `cutover_ready`, `limitations` |
| `schemas/ssot_migrate_verify.schema.json` | ssot migrate verify --json output | `status`, `phase`, `manifest_digest`, `input_count`, `cutover_ready`, `limitations`, `generation_status`, `attempt_id`, `origin_kind`, `dataset_revision`, `checks` |
| `schemas/ssot_reconcile_candidates.schema.json` | ssot reconcile candidates output | `dataset_generation`, `dataset_revision`, `candidates`, `evidence`, `allocations`, `withdrawals`, `ledger_cash_totals`, `payments` |
| `schemas/ssot_reconcile_confirm.schema.json` | ssot reconcile confirm output | `allocation_id`, `status`, `residual`, `currency`, `replayed` |
| `schemas/ssot_reconcile_submit.schema.json` | ssot reconcile submit output | `evidence_ids`, `source_artifact_id`, `inserted_count`, `replayed` |
| `schemas/ssot_reconcile_withdraw.schema.json` | ssot reconcile withdraw output | `allocation_id`, `withdrawal_id`, `status`, `replayed` |
| `schemas/status.schema.json` | status --json output | `data_directory`, `transactions`, `last_import`, `terminology`, `tagging`, `rules_file`, `health`, `actionable`, `signals`, `next_steps` |
| `schemas/tag.schema.json` | tag --json output | `status` |
| `schemas/template_list.schema.json` | template list --json output | `templates` |
| `schemas/template_run.schema.json` | template run --json output | `template_name`, `row_count`, `rows`, `pagination` |
| `schemas/template_show.schema.json` | template show --json output | `name`, `description`, `parameters`, `sql` |
| `schemas/transfer.schema.json` | transfer --json output | `status`, `candidate_rows`, `pairs_found`, `pairs_linked`, `confirmed_transfer_rows`, `unconfirmed_candidate_rows` |
| `schemas/validate.schema.json` | validate --json output | `valid`, `partitions_checked`, `valid_count`, `invalid_count`, `results` |
| `schemas/version.schema.json` | finjuice version output | `finjuice_version`, `schema_version` |

## `schemas/_meta.schema.json`

_meta envelope

| Field | Type | Required |
|-------|------|----------|
| `command` | `string` | yes |
| `finjuice_version` | `string` | yes |
| `privacy` | `object` | no |
| `schema_version` | `string` | yes |
| `timestamp` | `string` | yes |

```json
{
  "$id": "https://github.com/sungjunlee/finjuice/schemas/_meta.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "command": {
      "type": "string"
    },
    "finjuice_version": {
      "type": "string"
    },
    "privacy": {
      "additionalProperties": true,
      "properties": {
        "profile": {
          "enum": [
            "raw",
            "redacted",
            "compact"
          ],
          "type": "string"
        }
      },
      "required": [
        "profile"
      ],
      "type": "object"
    },
    "schema_version": {
      "pattern": "^[0-9]+\\.[0-9]+$",
      "type": "string"
    },
    "timestamp": {
      "format": "date-time",
      "type": "string"
    }
  },
  "required": [
    "schema_version",
    "finjuice_version",
    "command",
    "timestamp"
  ],
  "title": "_meta envelope",
  "type": "object"
}
```

## `schemas/_error.schema.json`

Error envelope

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `error` | `object` | yes |
| `exit_code` | enum(`0`, `1`, `2`, `3`, `4`, `130`) | yes |

```json
{
  "$id": "https://github.com/sungjunlee/finjuice/schemas/_error.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "error": {
      "additionalProperties": true,
      "properties": {
        "code": {
          "enum": [
            "GENERAL_ERROR",
            "DATA_DIR_NOT_INITIALIZED",
            "NO_DATA",
            "RULES_FILE_NOT_FOUND",
            "RULE_NOT_FOUND",
            "FILE_NOT_FOUND",
            "FILE_ACCESS_ERROR",
            "VALIDATION_FAILED",
            "INVALID_ARGS",
            "TAGGING_FAILED",
            "TRANSFER_FAILED",
            "EXPORT_FAILED",
            "QUERY_ERROR",
            "SIMULATION_FAILED",
            "INSPECTION_FAILED",
            "USER_CANCELLED",
            "UNEXPECTED_ERROR"
          ],
          "type": "string"
        },
        "message": {
          "type": "string"
        },
        "suggestion": {
          "type": [
            "string",
            "null"
          ]
        }
      },
      "required": [
        "code",
        "message"
      ],
      "type": "object"
    },
    "exit_code": {
      "enum": [
        0,
        1,
        2,
        3,
        4,
        130
      ],
      "minimum": 0,
      "type": "integer"
    }
  },
  "required": [
    "_meta",
    "error",
    "exit_code"
  ],
  "title": "Error envelope",
  "type": "object"
}
```

## `schemas/_pagination.schema.json`

Pagination envelope

| Field | Type | Required |
|-------|------|----------|
| `cursor` | `string` | yes |
| `has_more` | `boolean` | yes |
| `limit` | `integer` | yes |
| `next_cursor` | `string` \| `null` | yes |
| `total_estimate` | `integer` \| `null` | no |
| `truncated_by_bytes` | `boolean` | no |

```json
{
  "$id": "_pagination.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": false,
  "properties": {
    "cursor": {
      "type": "string"
    },
    "has_more": {
      "type": "boolean"
    },
    "limit": {
      "minimum": 0,
      "type": "integer"
    },
    "next_cursor": {
      "type": [
        "string",
        "null"
      ]
    },
    "total_estimate": {
      "minimum": 0,
      "type": [
        "integer",
        "null"
      ]
    },
    "truncated_by_bytes": {
      "type": "boolean"
    }
  },
  "required": [
    "limit",
    "cursor",
    "next_cursor",
    "has_more"
  ],
  "title": "Pagination envelope",
  "type": "object"
}
```

## `schemas/all.schema.json`

all --json output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `command` | `string` | yes |
| `steps` | `object` | yes |

```json
{
  "$id": "all.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "command": {
      "type": "string"
    },
    "steps": {
      "additionalProperties": true,
      "properties": {
        "export": {
          "additionalProperties": true,
          "type": "object"
        },
        "ingest": {
          "additionalProperties": true,
          "type": "object"
        },
        "tag": {
          "additionalProperties": true,
          "type": "object"
        },
        "transfer": {
          "additionalProperties": true,
          "type": "object"
        }
      },
      "required": [
        "ingest",
        "tag",
        "transfer",
        "export"
      ],
      "type": "object"
    }
  },
  "required": [
    "_meta",
    "command",
    "steps"
  ],
  "title": "all --json output",
  "type": "object"
}
```

## `schemas/assets_balance.schema.json`

assets balance --json output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `assets` | `array`[`object`] | yes |
| `has_data` | `boolean` | yes |
| `latest_month` | `string` \| `null` | yes |
| `liabilities` | `array`[`object`] | yes |
| `snapshot_date` | `string` \| `null` | yes |
| `total_assets` | `number` | yes |
| `total_liabilities` | `number` | yes |

```json
{
  "$id": "assets_balance.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "assets": {
      "items": {
        "additionalProperties": true,
        "properties": {
          "amount": {
            "type": "number"
          },
          "category": {
            "type": "string"
          },
          "currency": {
            "type": "string"
          },
          "item_name": {
            "type": "string"
          }
        },
        "required": [
          "category",
          "item_name",
          "amount",
          "currency"
        ],
        "type": "object"
      },
      "type": "array"
    },
    "has_data": {
      "type": "boolean"
    },
    "latest_month": {
      "type": [
        "string",
        "null"
      ]
    },
    "liabilities": {
      "items": {
        "additionalProperties": true,
        "properties": {
          "amount": {
            "type": "number"
          },
          "category": {
            "type": "string"
          },
          "currency": {
            "type": "string"
          },
          "item_name": {
            "type": "string"
          }
        },
        "required": [
          "category",
          "item_name",
          "amount",
          "currency"
        ],
        "type": "object"
      },
      "type": "array"
    },
    "snapshot_date": {
      "type": [
        "string",
        "null"
      ]
    },
    "total_assets": {
      "type": "number"
    },
    "total_liabilities": {
      "type": "number"
    }
  },
  "required": [
    "_meta",
    "has_data",
    "latest_month",
    "snapshot_date",
    "total_assets",
    "total_liabilities",
    "assets",
    "liabilities"
  ],
  "title": "assets balance --json output",
  "type": "object"
}
```

## `schemas/assets_show.schema.json`

assets show --json output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `error` | `string` | no |
| `has_data` | `boolean` | yes |
| `holdings` | `array`[`object`] | no |
| `month` | `string` | no |
| `snapshot_date` | `string` \| `null` | no |
| `total_count` | `integer` | no |

```json
{
  "$id": "assets_show.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "error": {
      "type": "string"
    },
    "has_data": {
      "type": "boolean"
    },
    "holdings": {
      "items": {
        "additionalProperties": true,
        "type": "object"
      },
      "type": "array"
    },
    "month": {
      "type": "string"
    },
    "snapshot_date": {
      "type": [
        "string",
        "null"
      ]
    },
    "total_count": {
      "type": "integer"
    }
  },
  "required": [
    "_meta",
    "has_data"
  ],
  "title": "assets show --json output",
  "type": "object"
}
```

## `schemas/assets_status.schema.json`

assets status --json output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `account_count` | `integer` | no |
| `accounts` | `array`[`object`] | no |
| `available_months` | `array`[`string`] | no |
| `has_data` | `boolean` | yes |
| `latest_month` | `string` \| `null` | no |
| `position_count` | `integer` | no |
| `snapshot_date` | `string` \| `null` | no |
| `total_value` | `number` | no |

```json
{
  "$id": "assets_status.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "account_count": {
      "type": "integer"
    },
    "accounts": {
      "items": {
        "additionalProperties": true,
        "type": "object"
      },
      "type": "array"
    },
    "available_months": {
      "items": {
        "type": "string"
      },
      "type": "array"
    },
    "has_data": {
      "type": "boolean"
    },
    "latest_month": {
      "type": [
        "string",
        "null"
      ]
    },
    "position_count": {
      "type": "integer"
    },
    "snapshot_date": {
      "type": [
        "string",
        "null"
      ]
    },
    "total_value": {
      "type": "number"
    }
  },
  "required": [
    "_meta",
    "has_data"
  ],
  "title": "assets status --json output",
  "type": "object"
}
```

## `schemas/audit_clear.schema.json`

audit clear --json output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `action` | `string` | yes |
| `entries_kept` | `integer` | yes |
| `skipped_entries` | `integer` | yes |

```json
{
  "$id": "audit_clear.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "action": {
      "type": "string"
    },
    "entries_kept": {
      "type": "integer"
    },
    "skipped_entries": {
      "type": "integer"
    }
  },
  "required": [
    "_meta",
    "entries_kept",
    "action",
    "skipped_entries"
  ],
  "title": "audit clear --json output",
  "type": "object"
}
```

## `schemas/audit_log.schema.json`

audit log --json output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `count` | `integer` | yes |
| `events` | `array`[`object`] | yes |
| `skipped_entries` | `integer` | yes |

```json
{
  "$id": "audit_log.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "count": {
      "type": "integer"
    },
    "events": {
      "items": {
        "additionalProperties": true,
        "type": "object"
      },
      "type": "array"
    },
    "skipped_entries": {
      "type": "integer"
    }
  },
  "required": [
    "_meta",
    "events",
    "count",
    "skipped_entries"
  ],
  "title": "audit log --json output",
  "type": "object"
}
```

## `schemas/audit_stats.schema.json`

audit stats --json output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `executions` | `object` | yes |
| `skipped_entries` | `integer` | yes |
| `success_rate` | `number` \| `null` | yes |
| `suggestions` | `object` | yes |
| `template_summary` | `object` | no |
| `top_commands` | `array`[`object`] | yes |

```json
{
  "$id": "audit_stats.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "executions": {
      "additionalProperties": true,
      "properties": {
        "failed": {
          "type": "integer"
        },
        "successful": {
          "type": "integer"
        },
        "total": {
          "type": "integer"
        }
      },
      "required": [
        "total",
        "successful",
        "failed"
      ],
      "type": "object"
    },
    "skipped_entries": {
      "type": "integer"
    },
    "success_rate": {
      "type": [
        "number",
        "null"
      ]
    },
    "suggestions": {
      "additionalProperties": true,
      "properties": {
        "confirmed": {
          "type": "integer"
        },
        "declined": {
          "type": "integer"
        },
        "total": {
          "type": "integer"
        }
      },
      "required": [
        "total",
        "confirmed",
        "declined"
      ],
      "type": "object"
    },
    "template_summary": {
      "additionalProperties": true,
      "type": "object"
    },
    "top_commands": {
      "items": {
        "additionalProperties": true,
        "properties": {
          "command": {
            "type": "string"
          },
          "count": {
            "type": "integer"
          }
        },
        "required": [
          "command",
          "count"
        ],
        "type": "object"
      },
      "type": "array"
    }
  },
  "required": [
    "_meta",
    "suggestions",
    "executions",
    "success_rate",
    "top_commands",
    "skipped_entries"
  ],
  "title": "audit stats --json output",
  "type": "object"
}
```

## `schemas/automation_run.schema.json`

automation run --json output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `actionable` | `boolean` | yes |
| `data_dir` | `string` | no |
| `enabled` | `boolean` | yes |
| `large_transactions` | `object` | yes |
| `next_steps` | `array`[`object`] | yes |
| `pending_imports` | `object` | yes |
| `tagging_pressure` | `object` | yes |
| `thresholds` | `object` | yes |
| `warnings` | `array`[`string`] | yes |

```json
{
  "$defs": {
    "tagging_review_terms": {
      "additionalProperties": {
        "type": "string"
      },
      "description": "Canonical tagging/review terminology for this JSON contract.",
      "properties": {
        "needs_review": {
          "description": "The explicit row flag needs_review == 1, not every row shown by review.",
          "type": "string"
        },
        "rule_matched": {
          "description": "A transaction with rule-derived output: non-empty tags_rule or non-empty category_rule.",
          "type": "string"
        },
        "suggestable_untagged": {
          "description": "An untagged transaction eligible for rules suggest after excluding confirmed internal transfer pairs.",
          "type": "string"
        },
        "uncategorized": {
          "description": "A transaction whose category_final is the fallback category 미분류.",
          "type": "string"
        },
        "untagged": {
          "description": "A transaction whose tags_final is null or an empty tag array.",
          "type": "string"
        }
      },
      "type": "object"
    }
  },
  "$id": "automation_run.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "allOf": [
    {
      "if": {
        "properties": {
          "_meta": {
            "properties": {
              "privacy": {
                "properties": {
                  "profile": {
                    "enum": [
                      "raw",
                      "redacted"
                    ],
                    "type": "string"
                  }
                },
                "required": [
                  "profile"
                ],
                "type": "object"
              }
            },
            "required": [
              "privacy"
            ],
            "type": "object"
          }
        },
        "required": [
          "_meta"
        ],
        "type": "object"
      },
      "then": {
        "properties": {
          "tagging_pressure": {
            "required": [
              "merchant_pressure"
            ],
            "type": "object"
          }
        },
        "required": [
          "data_dir"
        ]
      }
    },
    {
      "if": {
        "properties": {
          "_meta": {
            "properties": {
              "privacy": {
                "properties": {
                  "profile": {
                    "enum": [
                      "compact"
                    ],
                    "type": "string"
                  }
                },
                "required": [
                  "profile"
                ],
                "type": "object"
              }
            },
            "required": [
              "privacy"
            ],
            "type": "object"
          }
        },
        "required": [
          "_meta"
        ],
        "type": "object"
      },
      "then": {
        "not": {
          "required": [
            "data_dir"
          ]
        },
        "properties": {
          "tagging_pressure": {
            "not": {
              "required": [
                "merchant_pressure"
              ]
            },
            "required": [
              "merchant_pressure_count"
            ],
            "type": "object"
          }
        }
      }
    }
  ],
  "description": "automation run --json output. The raw and redacted privacy profiles include data_dir and merchant_pressure samples; compact replaces those samples with counts. Canonical pending samples have validation_skips:null because exact-import dispositions are distinct from legacy validation skips; independent preview totals are identified in _meta.",
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "actionable": {
      "type": "boolean"
    },
    "data_dir": {
      "type": "string"
    },
    "enabled": {
      "type": "boolean"
    },
    "large_transactions": {
      "additionalProperties": true,
      "type": "object"
    },
    "next_steps": {
      "items": {
        "additionalProperties": true,
        "properties": {
          "command": {
            "type": "string"
          },
          "message": {
            "type": "string"
          },
          "signal": {
            "type": "string"
          }
        },
        "required": [
          "signal",
          "message",
          "command"
        ],
        "type": "object"
      },
      "type": "array"
    },
    "pending_imports": {
      "additionalProperties": true,
      "properties": {
        "estimated_new_asset_rows": {
          "type": "integer"
        },
        "estimated_new_rows": {
          "type": "integer"
        },
        "failed_file_count": {
          "type": "integer"
        },
        "failed_files": {
          "items": {
            "additionalProperties": true,
            "properties": {
              "error": {
                "type": "string"
              },
              "source_file": {
                "type": [
                  "string",
                  "null"
                ]
              }
            },
            "type": "object"
          },
          "type": "array"
        },
        "files_found": {
          "type": "integer"
        },
        "pending_files": {
          "type": "integer"
        },
        "sample_file_count": {
          "type": "integer"
        },
        "sample_files": {
          "items": {
            "additionalProperties": true,
            "properties": {
              "estimated_new_asset_rows": {
                "type": "integer"
              },
              "estimated_new_rows": {
                "type": "integer"
              },
              "source_file": {
                "type": [
                  "string",
                  "null"
                ]
              },
              "validation_skips": {
                "type": [
                  "integer",
                  "null"
                ]
              }
            },
            "type": "object"
          },
          "type": "array"
        },
        "status": {
          "type": "string"
        }
      },
      "type": "object"
    },
    "tagging_pressure": {
      "additionalProperties": true,
      "properties": {
        "coverage_pct": {
          "type": "number"
        },
        "merchant_pressure": {
          "items": {
            "additionalProperties": true,
            "properties": {
              "avg_amount": {
                "type": [
                  "number",
                  "null"
                ]
              },
              "merchant": {
                "type": "string"
              },
              "sample_memos": {
                "items": {
                  "type": "string"
                },
                "type": "array"
              },
              "total_amount": {
                "type": [
                  "number",
                  "null"
                ]
              },
              "transaction_count": {
                "type": "integer"
              }
            },
            "required": [
              "merchant",
              "transaction_count",
              "total_amount",
              "avg_amount",
              "sample_memos"
            ],
            "type": "object"
          },
          "type": "array"
        },
        "merchant_pressure_count": {
          "type": "integer"
        },
        "status": {
          "type": "string"
        },
        "suggestable_coverage_pct": {
          "type": "number"
        },
        "suggestable_untagged_transactions": {
          "type": "integer"
        },
        "threshold": {
          "type": "integer"
        },
        "threshold_basis": {
          "type": "string"
        },
        "threshold_exceeded": {
          "type": "boolean"
        },
        "total_transactions": {
          "type": "integer"
        },
        "transfer_excluded_untagged_transactions": {
          "type": "integer"
        },
        "untagged_transactions": {
          "type": "integer"
        }
      },
      "required": [
        "status",
        "total_transactions",
        "untagged_transactions",
        "coverage_pct",
        "suggestable_untagged_transactions",
        "suggestable_coverage_pct",
        "transfer_excluded_untagged_transactions",
        "threshold",
        "threshold_basis",
        "threshold_exceeded"
      ],
      "type": "object"
    },
    "thresholds": {
      "additionalProperties": true,
      "properties": {
        "large_transaction": {
          "type": "number"
        },
        "untagged_count": {
          "type": "integer"
        }
      },
      "required": [
        "untagged_count",
        "large_transaction"
      ],
      "type": "object"
    },
    "warnings": {
      "items": {
        "type": "string"
      },
      "type": "array"
    }
  },
  "required": [
    "_meta",
    "enabled",
    "actionable",
    "thresholds",
    "pending_imports",
    "tagging_pressure",
    "large_transactions",
    "next_steps",
    "warnings"
  ],
  "title": "automation run --json output",
  "type": "object",
  "x-finjuice-field-definitions": {
    "tagging_pressure.suggestable_untagged_transactions": "suggestable_untagged",
    "tagging_pressure.threshold_basis": "automation.thresholds.untagged_count is evaluated against suggestable_untagged_transactions",
    "tagging_pressure.transfer_excluded_untagged_transactions": "untagged rows excluded from rule suggestions because they are confirmed transfer pairs",
    "tagging_pressure.untagged_transactions": "untagged"
  }
}
```

## `schemas/backup_create.schema.json`

backup create --json output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `absent_optional_count` | `integer` | yes |
| `byte_count` | `integer` | yes |
| `consistency_kind` | `string` | yes |
| `data_schema_version` | `integer` \| `null` | yes |
| `data_schema_version_status` | enum(`present`, `missing`, `invalid`) | yes |
| `directory_count` | `integer` | yes |
| `entry_count` | `integer` | yes |
| `file_count` | `integer` | yes |
| `finjuice_version` | `string` | yes |
| `generation_status` | enum(`inactive`) | no |
| `manifest_digest` | `string` | yes |
| `root_count` | `integer` | yes |
| `schema_version` | `string` | yes |
| `status` | enum(`ok`, `already_complete`) | yes |

```json
{
  "$id": "backup_create.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "absent_optional_count": {
      "type": "integer"
    },
    "byte_count": {
      "type": "integer"
    },
    "consistency_kind": {
      "type": "string"
    },
    "data_schema_version": {
      "type": [
        "integer",
        "null"
      ]
    },
    "data_schema_version_status": {
      "enum": [
        "present",
        "missing",
        "invalid"
      ],
      "type": "string"
    },
    "directory_count": {
      "type": "integer"
    },
    "entry_count": {
      "type": "integer"
    },
    "file_count": {
      "type": "integer"
    },
    "finjuice_version": {
      "type": "string"
    },
    "generation_status": {
      "enum": [
        "inactive"
      ],
      "type": "string"
    },
    "manifest_digest": {
      "type": "string"
    },
    "root_count": {
      "type": "integer"
    },
    "schema_version": {
      "type": "string"
    },
    "status": {
      "enum": [
        "ok",
        "already_complete"
      ],
      "type": "string"
    }
  },
  "required": [
    "_meta",
    "status",
    "schema_version",
    "manifest_digest",
    "entry_count",
    "file_count",
    "directory_count",
    "byte_count",
    "root_count",
    "absent_optional_count",
    "finjuice_version",
    "data_schema_version",
    "data_schema_version_status",
    "consistency_kind"
  ],
  "title": "backup create --json output",
  "type": "object"
}
```

## `schemas/backup_restore.schema.json`

backup restore --json output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `absent_optional_count` | `integer` | yes |
| `byte_count` | `integer` | yes |
| `consistency_kind` | `string` | yes |
| `data_schema_version` | `integer` \| `null` | yes |
| `data_schema_version_status` | enum(`present`, `missing`, `invalid`) | yes |
| `directory_count` | `integer` | yes |
| `entry_count` | `integer` | yes |
| `file_count` | `integer` | yes |
| `finjuice_version` | `string` | yes |
| `generation_status` | enum(`inactive`) | yes |
| `manifest_digest` | `string` | yes |
| `root_count` | `integer` | yes |
| `schema_version` | `string` | yes |
| `status` | enum(`ok`, `already_complete`) | yes |

```json
{
  "$id": "backup_restore.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "absent_optional_count": {
      "type": "integer"
    },
    "byte_count": {
      "type": "integer"
    },
    "consistency_kind": {
      "type": "string"
    },
    "data_schema_version": {
      "type": [
        "integer",
        "null"
      ]
    },
    "data_schema_version_status": {
      "enum": [
        "present",
        "missing",
        "invalid"
      ],
      "type": "string"
    },
    "directory_count": {
      "type": "integer"
    },
    "entry_count": {
      "type": "integer"
    },
    "file_count": {
      "type": "integer"
    },
    "finjuice_version": {
      "type": "string"
    },
    "generation_status": {
      "enum": [
        "inactive"
      ],
      "type": "string"
    },
    "manifest_digest": {
      "type": "string"
    },
    "root_count": {
      "type": "integer"
    },
    "schema_version": {
      "type": "string"
    },
    "status": {
      "enum": [
        "ok",
        "already_complete"
      ],
      "type": "string"
    }
  },
  "required": [
    "_meta",
    "status",
    "schema_version",
    "manifest_digest",
    "entry_count",
    "file_count",
    "directory_count",
    "byte_count",
    "root_count",
    "absent_optional_count",
    "finjuice_version",
    "data_schema_version",
    "data_schema_version_status",
    "consistency_kind",
    "generation_status"
  ],
  "title": "backup restore --json output",
  "type": "object"
}
```

## `schemas/backup_verify.schema.json`

backup verify --json output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `absent_optional_count` | `integer` | yes |
| `byte_count` | `integer` | yes |
| `consistency_kind` | `string` | yes |
| `data_schema_version` | `integer` \| `null` | yes |
| `data_schema_version_status` | enum(`present`, `missing`, `invalid`) | yes |
| `directory_count` | `integer` | yes |
| `entry_count` | `integer` | yes |
| `file_count` | `integer` | yes |
| `finjuice_version` | `string` | yes |
| `generation_status` | enum(`inactive`) | no |
| `manifest_digest` | `string` | yes |
| `root_count` | `integer` | yes |
| `schema_version` | `string` | yes |
| `status` | enum(`ok`, `already_complete`) | yes |

```json
{
  "$id": "backup_verify.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "absent_optional_count": {
      "type": "integer"
    },
    "byte_count": {
      "type": "integer"
    },
    "consistency_kind": {
      "type": "string"
    },
    "data_schema_version": {
      "type": [
        "integer",
        "null"
      ]
    },
    "data_schema_version_status": {
      "enum": [
        "present",
        "missing",
        "invalid"
      ],
      "type": "string"
    },
    "directory_count": {
      "type": "integer"
    },
    "entry_count": {
      "type": "integer"
    },
    "file_count": {
      "type": "integer"
    },
    "finjuice_version": {
      "type": "string"
    },
    "generation_status": {
      "enum": [
        "inactive"
      ],
      "type": "string"
    },
    "manifest_digest": {
      "type": "string"
    },
    "root_count": {
      "type": "integer"
    },
    "schema_version": {
      "type": "string"
    },
    "status": {
      "enum": [
        "ok",
        "already_complete"
      ],
      "type": "string"
    }
  },
  "required": [
    "_meta",
    "status",
    "schema_version",
    "manifest_digest",
    "entry_count",
    "file_count",
    "directory_count",
    "byte_count",
    "root_count",
    "absent_optional_count",
    "finjuice_version",
    "data_schema_version",
    "data_schema_version_status",
    "consistency_kind"
  ],
  "title": "backup verify --json output",
  "type": "object"
}
```

## `schemas/budget_edit.schema.json`

budget edit --json output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `changes` | `array`[`object`] | yes |
| `monthly_budget` | `object` | yes |
| `path` | `string` | yes |

```json
{
  "$id": "budget_edit.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "changes": {
      "items": {
        "additionalProperties": true,
        "properties": {
          "new": {},
          "old": {},
          "path": {
            "type": "string"
          }
        },
        "required": [
          "path",
          "old",
          "new"
        ],
        "type": "object"
      },
      "type": "array"
    },
    "monthly_budget": {
      "additionalProperties": true,
      "properties": {
        "categories": {
          "additionalProperties": true,
          "type": "object"
        },
        "notes": {
          "type": [
            "string",
            "null"
          ]
        },
        "total": {
          "type": "integer"
        },
        "updated": {
          "type": [
            "string",
            "null"
          ]
        }
      },
      "required": [
        "total",
        "categories",
        "updated",
        "notes"
      ],
      "type": "object"
    },
    "path": {
      "type": "string"
    }
  },
  "required": [
    "_meta",
    "path",
    "changes",
    "monthly_budget"
  ],
  "title": "budget edit --json output",
  "type": "object"
}
```

## `schemas/budget_status.schema.json`

budget status --json output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `actionable` | `boolean` | yes |
| `categories` | `array`[`object`] | yes |
| `goals_file` | `object` | yes |
| `health` | `object` | yes |
| `month` | `string` | yes |
| `next_steps` | `array`[`object`] | yes |
| `review` | `object` | yes |
| `signals` | `object` | yes |
| `summary` | `object` or `null` | yes |
| `unmatched_goal_categories` | `array`[`object`] | yes |

```json
{
  "$id": "budget_status.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "actionable": {
      "type": "boolean"
    },
    "categories": {
      "items": {
        "additionalProperties": true,
        "properties": {
          "actual": {
            "type": "integer"
          },
          "name": {
            "type": "string"
          },
          "progress_pct": {
            "type": [
              "number",
              "null"
            ]
          },
          "remaining": {
            "type": "integer"
          },
          "status": {
            "enum": [
              "under",
              "on-track",
              "over",
              "untracked"
            ],
            "type": "string"
          },
          "target": {
            "type": "integer"
          }
        },
        "required": [
          "name",
          "target",
          "actual",
          "remaining",
          "progress_pct",
          "status"
        ],
        "type": "object"
      },
      "type": "array"
    },
    "goals_file": {
      "additionalProperties": true,
      "properties": {
        "authority": {
          "type": "string"
        },
        "exists": {
          "type": "boolean"
        },
        "notes": {
          "type": [
            "string",
            "null"
          ]
        },
        "path": {
          "type": [
            "string",
            "null"
          ]
        },
        "revision_id": {
          "type": [
            "string",
            "null"
          ]
        },
        "selection_state": {
          "type": "string"
        },
        "updated": {
          "type": [
            "string",
            "null"
          ]
        }
      },
      "required": [
        "path",
        "exists"
      ],
      "type": "object"
    },
    "health": {
      "additionalProperties": true,
      "properties": {
        "reasons": {
          "items": {
            "type": "string"
          },
          "type": "array"
        },
        "status": {
          "enum": [
            "ok",
            "warning",
            "critical"
          ],
          "type": "string"
        }
      },
      "required": [
        "status",
        "reasons"
      ],
      "type": "object"
    },
    "month": {
      "type": "string"
    },
    "next_steps": {
      "items": {
        "additionalProperties": true,
        "properties": {
          "command": {
            "type": "string"
          },
          "message": {
            "type": "string"
          },
          "signal": {
            "type": "string"
          }
        },
        "required": [
          "signal",
          "message",
          "command"
        ],
        "type": "object"
      },
      "type": "array"
    },
    "review": {
      "additionalProperties": true,
      "properties": {
        "actual": {
          "type": [
            "integer",
            "null"
          ]
        },
        "at_risk_categories": {
          "items": {
            "type": "string"
          },
          "type": "array"
        },
        "month": {
          "type": "string"
        },
        "over_budget_categories": {
          "items": {
            "type": "string"
          },
          "type": "array"
        },
        "remaining": {
          "type": [
            "integer",
            "null"
          ]
        },
        "target": {
          "type": [
            "integer",
            "null"
          ]
        },
        "unbudgeted_categories": {
          "items": {
            "type": "string"
          },
          "type": "array"
        }
      },
      "required": [
        "month",
        "target",
        "actual",
        "remaining",
        "at_risk_categories",
        "over_budget_categories",
        "unbudgeted_categories"
      ],
      "type": "object"
    },
    "signals": {
      "additionalProperties": true,
      "type": "object"
    },
    "summary": {
      "anyOf": [
        {
          "additionalProperties": true,
          "properties": {
            "actual": {
              "type": "integer"
            },
            "name": {
              "type": "string"
            },
            "progress_pct": {
              "type": [
                "number",
                "null"
              ]
            },
            "remaining": {
              "type": "integer"
            },
            "status": {
              "enum": [
                "under",
                "on-track",
                "over",
                "untracked"
              ],
              "type": "string"
            },
            "target": {
              "type": "integer"
            }
          },
          "required": [
            "name",
            "target",
            "actual",
            "remaining",
            "progress_pct",
            "status"
          ],
          "type": "object"
        },
        {
          "type": "null"
        }
      ]
    },
    "unmatched_goal_categories": {
      "items": {
        "additionalProperties": true,
        "properties": {
          "actual": {
            "type": "integer"
          },
          "name": {
            "type": "string"
          },
          "suggested": {
            "items": {
              "type": "string"
            },
            "type": "array"
          }
        },
        "required": [
          "name",
          "actual"
        ],
        "type": "object"
      },
      "type": "array"
    }
  },
  "required": [
    "_meta",
    "month",
    "goals_file",
    "summary",
    "categories",
    "unmatched_goal_categories",
    "health",
    "actionable",
    "signals",
    "review",
    "next_steps"
  ],
  "title": "budget status --json output",
  "type": "object"
}
```

## `schemas/budget_validate.schema.json`

budget validate --json output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `authority` | `string` | no |
| `path` | `string` \| `null` | yes |
| `problems` | `array`[`object`] | yes |
| `revision_id` | `string` \| `null` | no |
| `selection_state` | `string` | no |
| `status` | enum(`valid`, `invalid`) | yes |

```json
{
  "$id": "budget_validate.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "authority": {
      "type": "string"
    },
    "path": {
      "type": [
        "string",
        "null"
      ]
    },
    "problems": {
      "items": {
        "additionalProperties": true,
        "type": "object"
      },
      "type": "array"
    },
    "revision_id": {
      "type": [
        "string",
        "null"
      ]
    },
    "selection_state": {
      "type": "string"
    },
    "status": {
      "enum": [
        "valid",
        "invalid"
      ],
      "type": "string"
    }
  },
  "required": [
    "_meta",
    "status",
    "path",
    "problems"
  ],
  "title": "budget validate --json output",
  "type": "object"
}
```

## `schemas/checkup.schema.json`

checkup --json output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `actionable` | `boolean` | yes |
| `data_dir` | `string` | no |
| `domains` | `object` | yes |
| `next_actions` | `array`[`object`] | yes |
| `summary` | `object` | yes |
| `warnings` | `array`[`string`] | yes |

```json
{
  "$id": "checkup.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "allOf": [
    {
      "if": {
        "properties": {
          "_meta": {
            "properties": {
              "privacy": {
                "properties": {
                  "profile": {
                    "enum": [
                      "raw",
                      "redacted"
                    ],
                    "type": "string"
                  }
                },
                "required": [
                  "profile"
                ],
                "type": "object"
              }
            },
            "required": [
              "privacy"
            ],
            "type": "object"
          }
        },
        "required": [
          "_meta"
        ],
        "type": "object"
      },
      "then": {
        "required": [
          "data_dir"
        ]
      }
    },
    {
      "if": {
        "properties": {
          "_meta": {
            "properties": {
              "privacy": {
                "properties": {
                  "profile": {
                    "enum": [
                      "compact"
                    ],
                    "type": "string"
                  }
                },
                "required": [
                  "profile"
                ],
                "type": "object"
              }
            },
            "required": [
              "privacy"
            ],
            "type": "object"
          }
        },
        "required": [
          "_meta"
        ],
        "type": "object"
      },
      "then": {
        "not": {
          "required": [
            "data_dir"
          ]
        }
      }
    }
  ],
  "description": "checkup --json output. The raw and redacted privacy profiles include data_dir; compact omits that path while preserving workflow-driving summary fields.",
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "actionable": {
      "type": "boolean"
    },
    "data_dir": {
      "type": "string"
    },
    "domains": {
      "additionalProperties": true,
      "properties": {
        "budget": {
          "additionalProperties": true,
          "type": "object"
        },
        "networth": {
          "additionalProperties": true,
          "type": "object"
        },
        "obligations": {
          "additionalProperties": true,
          "type": "object"
        },
        "pipeline": {
          "additionalProperties": true,
          "type": "object"
        },
        "review": {
          "additionalProperties": true,
          "type": "object"
        }
      },
      "required": [
        "pipeline",
        "review",
        "budget",
        "networth",
        "obligations"
      ],
      "type": "object"
    },
    "next_actions": {
      "items": {
        "additionalProperties": true,
        "properties": {
          "command": {
            "type": "string"
          },
          "domain": {
            "type": "string"
          },
          "priority": {
            "enum": [
              "high",
              "medium",
              "low"
            ],
            "type": "string"
          },
          "reason": {
            "type": "string"
          }
        },
        "required": [
          "domain",
          "priority",
          "reason",
          "command"
        ],
        "type": "object"
      },
      "type": "array"
    },
    "summary": {
      "additionalProperties": true,
      "properties": {
        "domains_needing_attention": {
          "items": {
            "type": "string"
          },
          "type": "array"
        },
        "headline": {
          "type": "string"
        },
        "next_action_count": {
          "type": "integer"
        },
        "priority": {
          "type": [
            "string",
            "null"
          ]
        },
        "recommended_command": {
          "type": [
            "string",
            "null"
          ]
        },
        "status": {
          "enum": [
            "ok",
            "needs_attention"
          ],
          "type": "string"
        },
        "warning_count": {
          "type": "integer"
        }
      },
      "required": [
        "status",
        "priority",
        "headline",
        "recommended_command",
        "domains_needing_attention",
        "warning_count",
        "next_action_count"
      ],
      "type": "object"
    },
    "warnings": {
      "items": {
        "type": "string"
      },
      "type": "array"
    }
  },
  "required": [
    "_meta",
    "summary",
    "actionable",
    "warnings",
    "next_actions",
    "domains"
  ],
  "title": "checkup --json output",
  "type": "object"
}
```

## `schemas/context.schema.json`

context --json output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `active_goals` | `array` \| `null` | yes |
| `financial_metadata` | `object` \| `null` | yes |
| `journals` | `array`[`object`] | yes |
| `rule_notes` | `array`[`object`] | yes |
| `status_snapshot` | `object` | yes |
| `top_patterns` | `array` \| `null` | yes |

```json
{
  "$id": "context.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "active_goals": {
      "items": {},
      "type": [
        "array",
        "null"
      ]
    },
    "financial_metadata": {
      "additionalProperties": true,
      "type": [
        "object",
        "null"
      ]
    },
    "journals": {
      "items": {
        "additionalProperties": true,
        "properties": {
          "created": {
            "type": [
              "string",
              "null"
            ]
          },
          "data_range": {
            "type": [
              "string",
              "null"
            ]
          },
          "filename": {
            "type": "string"
          },
          "path": {
            "type": "string"
          },
          "snapshot": {
            "additionalProperties": true,
            "type": "object"
          },
          "snapshot_metadata": {
            "additionalProperties": true,
            "type": "object"
          },
          "snapshot_metadata_basis": {
            "enum": [
              "historical_journal_observation"
            ]
          },
          "summary_200": {
            "type": "string"
          },
          "topic": {
            "type": "string"
          }
        },
        "required": [
          "path",
          "filename",
          "topic",
          "created",
          "data_range",
          "snapshot",
          "summary_200"
        ],
        "type": "object"
      },
      "type": "array"
    },
    "rule_notes": {
      "items": {
        "additionalProperties": true,
        "properties": {
          "category": {
            "type": "string"
          },
          "notes": {
            "type": "string"
          },
          "rule_name": {
            "type": "string"
          },
          "tags": {
            "items": {
              "type": "string"
            },
            "type": "array"
          }
        },
        "required": [
          "rule_name",
          "notes",
          "tags"
        ],
        "type": "object"
      },
      "type": "array"
    },
    "status_snapshot": {
      "additionalProperties": true,
      "type": "object"
    },
    "top_patterns": {
      "items": {
        "additionalProperties": true,
        "properties": {
          "delta_krw": {
            "type": "integer"
          },
          "direction": {
            "type": "string"
          },
          "label": {
            "type": "string"
          }
        },
        "required": [
          "label",
          "delta_krw",
          "direction"
        ],
        "type": "object"
      },
      "type": [
        "array",
        "null"
      ]
    }
  },
  "required": [
    "_meta",
    "journals",
    "status_snapshot",
    "active_goals",
    "financial_metadata",
    "rule_notes",
    "top_patterns"
  ],
  "title": "context --json output",
  "type": "object"
}
```

## `schemas/doctor.schema.json`

doctor --json output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `checks` | `array`[`object`] | yes |
| `install_hint` | `string` \| `null` | yes |
| `missing_extras` | `array`[`string`] | yes |
| `summary` | `object` | yes |

```json
{
  "$id": "doctor.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "checks": {
      "items": {
        "additionalProperties": true,
        "properties": {
          "basis": {
            "enum": [
              "repository",
              "runtime_observation",
              "staged_observation"
            ],
            "type": "string"
          },
          "detail": {
            "type": [
              "string",
              "null"
            ]
          },
          "message": {
            "type": "string"
          },
          "name": {
            "type": "string"
          },
          "status": {
            "enum": [
              "pass",
              "warn",
              "fail"
            ],
            "type": "string"
          },
          "suggestion": {
            "type": [
              "string",
              "null"
            ]
          }
        },
        "required": [
          "name",
          "status",
          "message",
          "detail",
          "suggestion"
        ],
        "type": "object"
      },
      "type": "array"
    },
    "install_hint": {
      "type": [
        "string",
        "null"
      ]
    },
    "missing_extras": {
      "items": {
        "type": "string"
      },
      "type": "array"
    },
    "summary": {
      "additionalProperties": true,
      "properties": {
        "errors": {
          "type": "integer"
        },
        "passed": {
          "type": "integer"
        },
        "total": {
          "type": "integer"
        },
        "warnings": {
          "type": "integer"
        }
      },
      "required": [
        "total",
        "passed",
        "warnings",
        "errors"
      ],
      "type": "object"
    }
  },
  "required": [
    "_meta",
    "checks",
    "summary",
    "missing_extras",
    "install_hint"
  ],
  "title": "doctor --json output",
  "type": "object"
}
```

## `schemas/explain.schema.json`

explain --json output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `candidates` | `array`[`object`] | no |
| `classification` | `object` \| `null` | no |
| `date_filter` | `string` \| `null` | yes |
| `match_count` | `integer` | no |
| `matches` | `array`[`object`] | no |
| `query` | `string` | yes |
| `rule_trace` | `array`[`object`] | no |
| `selected_index` | `integer` | no |
| `transaction` | `object` \| `null` | no |

```json
{
  "$id": "explain.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "candidates": {
      "items": {
        "additionalProperties": true,
        "properties": {
          "amount": {
            "type": [
              "number",
              "null"
            ]
          },
          "category_final": {
            "type": [
              "string",
              "null"
            ]
          },
          "date": {
            "type": [
              "string",
              "null"
            ]
          },
          "index": {
            "type": "integer"
          },
          "major_raw": {
            "type": [
              "string",
              "null"
            ]
          },
          "memo_raw": {
            "type": [
              "string",
              "null"
            ]
          },
          "merchant_raw": {
            "type": [
              "string",
              "null"
            ]
          },
          "minor_raw": {
            "type": [
              "string",
              "null"
            ]
          },
          "row_hash": {
            "type": [
              "string",
              "null"
            ]
          }
        },
        "type": "object"
      },
      "type": "array"
    },
    "classification": {
      "type": [
        "object",
        "null"
      ]
    },
    "date_filter": {
      "type": [
        "string",
        "null"
      ]
    },
    "match_count": {
      "type": "integer"
    },
    "matches": {
      "items": {
        "additionalProperties": true,
        "type": "object"
      },
      "type": "array"
    },
    "query": {
      "type": "string"
    },
    "rule_trace": {
      "items": {
        "additionalProperties": true,
        "type": "object"
      },
      "type": "array"
    },
    "selected_index": {
      "type": "integer"
    },
    "transaction": {
      "type": [
        "object",
        "null"
      ]
    }
  },
  "required": [
    "_meta",
    "query",
    "date_filter"
  ],
  "title": "explain --json output",
  "type": "object"
}
```

## `schemas/export.schema.json`

export --json output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `assumptions` | `object` | no |
| `breakdown` | `object` | no |
| `command` | `string` | no |
| `domain` | `string` | no |
| `dry_run` | `boolean` | no |
| `format` | `string` | no |
| `generated_at` | `string` | no |
| `output_files` | `array`[`object`] | no |
| `period` | `string` \| `null` | no |
| `review_items` | `array`[`object`] | no |
| `skipped_outputs` | `array`[`object`] | no |
| `summary` | `object` | no |
| `transaction_count` | `integer` | no |
| `year` | `integer` | no |

```json
{
  "$id": "export.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "assumptions": {
      "additionalProperties": true,
      "type": "object"
    },
    "breakdown": {
      "additionalProperties": true,
      "type": "object"
    },
    "command": {
      "type": "string"
    },
    "domain": {
      "type": "string"
    },
    "dry_run": {
      "type": "boolean"
    },
    "format": {
      "type": "string"
    },
    "generated_at": {
      "type": "string"
    },
    "output_files": {
      "items": {
        "additionalProperties": true,
        "properties": {
          "available": {
            "type": "boolean"
          },
          "estimated_size_bytes": {
            "type": [
              "integer",
              "null"
            ]
          },
          "kind": {
            "type": "string"
          },
          "path": {
            "type": "string"
          },
          "reason": {
            "type": [
              "string",
              "null"
            ]
          },
          "row_count": {
            "type": [
              "integer",
              "null"
            ]
          }
        },
        "type": "object"
      },
      "type": "array"
    },
    "period": {
      "type": [
        "string",
        "null"
      ]
    },
    "review_items": {
      "items": {
        "additionalProperties": true,
        "type": "object"
      },
      "type": "array"
    },
    "skipped_outputs": {
      "items": {
        "additionalProperties": true,
        "properties": {
          "available": {
            "type": "boolean"
          },
          "estimated_size_bytes": {
            "type": [
              "integer",
              "null"
            ]
          },
          "kind": {
            "type": "string"
          },
          "path": {
            "type": "string"
          },
          "reason": {
            "type": [
              "string",
              "null"
            ]
          },
          "row_count": {
            "type": [
              "integer",
              "null"
            ]
          }
        },
        "type": "object"
      },
      "type": "array"
    },
    "summary": {
      "additionalProperties": true,
      "type": "object"
    },
    "transaction_count": {
      "type": "integer"
    },
    "year": {
      "type": "integer"
    }
  },
  "required": [
    "_meta"
  ],
  "title": "export --json output",
  "type": "object"
}
```

## `schemas/export_verify.schema.json`

export-verify --json output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `command` | `any` | yes |
| `current` | `object` | yes |
| `files` | `array`[`object`] | yes |
| `integrity` | enum(`intact`, `mismatch`) | yes |
| `manifest_path` | `string` | yes |
| `manifest_sha256` | `string` | no |
| `source` | `object` | yes |
| `stale` | `boolean` | yes |
| `verification_policy` | `any` | no |

```json
{
  "$id": "export_verify.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "command": {
      "const": "export-verify"
    },
    "current": {
      "additionalProperties": true,
      "type": "object"
    },
    "files": {
      "items": {
        "additionalProperties": true,
        "properties": {
          "path": {
            "type": "string"
          },
          "status": {
            "enum": [
              "intact",
              "modified",
              "missing"
            ]
          }
        },
        "required": [
          "path",
          "status"
        ],
        "type": "object"
      },
      "type": "array"
    },
    "integrity": {
      "enum": [
        "intact",
        "mismatch"
      ]
    },
    "manifest_path": {
      "type": "string"
    },
    "manifest_sha256": {
      "pattern": "^[a-f0-9]{64}$",
      "type": "string"
    },
    "source": {
      "additionalProperties": true,
      "type": "object"
    },
    "stale": {
      "type": "boolean"
    },
    "verification_policy": {
      "const": "local_export_receipt.v1"
    }
  },
  "required": [
    "_meta",
    "command",
    "manifest_path",
    "source",
    "current",
    "stale",
    "integrity",
    "files"
  ],
  "title": "export-verify --json output",
  "type": "object",
  "x-command": "export-verify"
}
```

## `schemas/history.schema.json`

history --json output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `count` | `integer` | yes |
| `records` | `array`[`object`] | yes |
| `summary` | `object` | no |

```json
{
  "$id": "history.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "count": {
      "type": "integer"
    },
    "records": {
      "items": {
        "additionalProperties": true,
        "properties": {
          "archived": {
            "type": [
              "boolean",
              "string",
              "null"
            ]
          },
          "archived_path": {
            "type": [
              "string",
              "null"
            ]
          },
          "artifact_id": {
            "type": "string"
          },
          "field_issues": {
            "items": {
              "type": "string"
            },
            "type": "array"
          },
          "file_id": {
            "type": [
              "string",
              "null"
            ]
          },
          "import_counts": {
            "additionalProperties": true,
            "type": "object"
          },
          "imported_at": {
            "type": [
              "string",
              "null"
            ]
          },
          "imported_from": {
            "type": [
              "string",
              "null"
            ]
          },
          "legacy_file_ids": {
            "items": {
              "type": "string"
            },
            "type": "array"
          },
          "occurrence_id": {
            "type": "string"
          },
          "origin": {
            "type": "string"
          },
          "original_filename": {
            "type": [
              "string",
              "null"
            ]
          },
          "provenance_id": {
            "type": "string"
          },
          "source_artifact_preserved": {
            "type": "boolean"
          },
          "source_cells": {
            "items": {
              "additionalProperties": true,
              "type": "object"
            },
            "type": "array"
          },
          "source_fields": {
            "additionalProperties": true,
            "type": "object"
          },
          "source_row": {
            "type": "integer"
          },
          "source_rows": {
            "type": [
              "integer",
              "null"
            ]
          }
        },
        "required": [
          "file_id",
          "imported_at"
        ],
        "type": "object"
      },
      "type": "array"
    },
    "summary": {
      "additionalProperties": true,
      "properties": {
        "archived_files": {
          "type": "integer"
        },
        "known_source_rows": {
          "type": "integer"
        },
        "unknown_archive_records": {
          "type": "integer"
        },
        "unknown_source_rows_records": {
          "type": "integer"
        }
      },
      "type": "object"
    }
  },
  "required": [
    "_meta",
    "records",
    "count"
  ],
  "title": "history --json output",
  "type": "object"
}
```

## `schemas/import.schema.json`

import --json output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `dry_run` | `boolean` | no |
| `errors` | `integer` | yes |
| `files_processed` | `integer` | yes |
| `files_skipped` | `integer` | yes |
| `pipeline_result` | `object` | no |
| `steps` | `object` | no |
| `transactions_inserted` | `integer` | no |

```json
{
  "$id": "import.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "dry_run": {
      "type": "boolean"
    },
    "errors": {
      "type": "integer"
    },
    "files_processed": {
      "type": "integer"
    },
    "files_skipped": {
      "type": "integer"
    },
    "pipeline_result": {
      "additionalProperties": true,
      "type": "object"
    },
    "steps": {
      "additionalProperties": true,
      "type": "object"
    },
    "transactions_inserted": {
      "type": "integer"
    }
  },
  "required": [
    "_meta",
    "files_processed",
    "files_skipped",
    "errors"
  ],
  "title": "import --json output",
  "type": "object"
}
```

## `schemas/index.schema.json`

index --json output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `collections` | `array`[`object`] | yes |
| `recommended_next` | `array`[`string`] | yes |
| `schema_ref` | `string` | yes |
| `workspace` | `object` | yes |

```json
{
  "$id": "index.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "allOf": [
    {
      "if": {
        "properties": {
          "_meta": {
            "properties": {
              "privacy": {
                "properties": {
                  "profile": {
                    "enum": [
                      "redacted",
                      "compact"
                    ],
                    "type": "string"
                  }
                },
                "required": [
                  "profile"
                ],
                "type": "object"
              }
            },
            "required": [
              "privacy"
            ],
            "type": "object"
          }
        },
        "required": [
          "_meta"
        ],
        "type": "object"
      },
      "then": {
        "properties": {
          "collections": {
            "items": {
              "properties": {
                "path": {
                  "type": "null"
                },
                "path_included": {
                  "const": false
                }
              },
              "type": "object"
            },
            "type": "array"
          },
          "workspace": {
            "properties": {
              "path": {
                "type": "null"
              },
              "path_included": {
                "const": false
              }
            },
            "type": "object"
          }
        }
      }
    },
    {
      "if": {
        "properties": {
          "_meta": {
            "properties": {
              "privacy": {
                "properties": {
                  "profile": {
                    "enum": [
                      "compact"
                    ],
                    "type": "string"
                  }
                },
                "required": [
                  "profile"
                ],
                "type": "object"
              }
            },
            "required": [
              "privacy"
            ],
            "type": "object"
          }
        },
        "required": [
          "_meta"
        ],
        "type": "object"
      },
      "then": {
        "properties": {
          "collections": {
            "items": {
              "properties": {
                "latest_modified": {
                  "type": "null"
                },
                "notes": {
                  "maxItems": 0,
                  "type": "array"
                },
                "recommended_commands": {
                  "maxItems": 0,
                  "type": "array"
                }
              },
              "type": "object"
            },
            "type": "array"
          },
          "recommended_next": {
            "maxItems": 0,
            "type": "array"
          }
        }
      }
    }
  ],
  "description": "index --json output. The raw privacy profile preserves the full catalog shape and only includes paths when --include-paths is requested. Redacted and compact profiles suppress resolved workspace and collection paths; compact also drops operational command and note detail. Canonical financial collections retain repository/count/selection provenance with no filesystem paths or mtimes. External file observations and runtime inventory remain distinct. An unavailable external observation has null exists and count; canonical logical existence remains boolean. Unknown counts are never partial totals.",
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "collections": {
      "items": {
        "additionalProperties": true,
        "properties": {
          "basis": {
            "enum": [
              "repository",
              "filesystem_observation",
              "runtime_inventory"
            ]
          },
          "count": {
            "type": [
              "integer",
              "null"
            ]
          },
          "count_basis": {
            "type": "string"
          },
          "count_label": {
            "type": "string"
          },
          "count_state": {
            "enum": [
              "known",
              "absent",
              "unavailable"
            ]
          },
          "exists": {
            "type": [
              "boolean",
              "null"
            ]
          },
          "latest_modified": {
            "type": [
              "string",
              "null"
            ]
          },
          "name": {
            "type": "string"
          },
          "notes": {
            "items": {
              "type": "string"
            },
            "type": "array"
          },
          "path": {
            "type": [
              "string",
              "null"
            ]
          },
          "path_included": {
            "type": "boolean"
          },
          "privacy_level": {
            "type": "string"
          },
          "recommended_commands": {
            "items": {
              "type": "string"
            },
            "type": "array"
          },
          "revision_id": {
            "type": [
              "string",
              "null"
            ]
          },
          "selection_state": {
            "type": [
              "string",
              "null"
            ]
          },
          "status": {
            "type": "string"
          },
          "type": {
            "type": "string"
          },
          "unavailable_reason": {
            "type": [
              "string",
              "null"
            ]
          }
        },
        "required": [
          "name",
          "type",
          "status",
          "exists",
          "count",
          "count_label",
          "latest_modified",
          "privacy_level",
          "path",
          "path_included",
          "recommended_commands",
          "notes"
        ],
        "type": "object"
      },
      "type": "array"
    },
    "recommended_next": {
      "items": {
        "type": "string"
      },
      "type": "array"
    },
    "schema_ref": {
      "type": "string"
    },
    "workspace": {
      "additionalProperties": true,
      "properties": {
        "data_dir_source": {
          "type": "string"
        },
        "path": {
          "type": [
            "string",
            "null"
          ]
        },
        "path_included": {
          "type": "boolean"
        },
        "status": {
          "type": "string"
        }
      },
      "required": [
        "status",
        "data_dir_source",
        "path",
        "path_included"
      ],
      "type": "object"
    }
  },
  "required": [
    "_meta",
    "workspace",
    "collections",
    "recommended_next",
    "schema_ref"
  ],
  "title": "index --json output",
  "type": "object"
}
```

## `schemas/ingest.schema.json`

ingest --json output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `archive_requested` | `boolean` | no |
| `command` | `string` | yes |
| `dry_run` | `boolean` | yes |
| `from_archive` | `string` | no |
| `history_skipped` | `integer` | no |
| `preview` | `object` | no |
| `source` | `string` | yes |
| `summary` | `object` | no |
| `would_parse` | `integer` | no |

```json
{
  "$id": "ingest.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "archive_requested": {
      "type": "boolean"
    },
    "command": {
      "type": "string"
    },
    "dry_run": {
      "type": "boolean"
    },
    "from_archive": {
      "type": "string"
    },
    "history_skipped": {
      "type": "integer"
    },
    "preview": {
      "additionalProperties": true,
      "type": "object"
    },
    "source": {
      "type": "string"
    },
    "summary": {
      "additionalProperties": true,
      "type": "object"
    },
    "would_parse": {
      "type": "integer"
    }
  },
  "required": [
    "_meta",
    "command",
    "dry_run",
    "source"
  ],
  "title": "ingest --json output",
  "type": "object"
}
```

## `schemas/init.schema.json`

init --json output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `already_initialized` | `boolean` | yes |
| `data_dir` | `string` | yes |
| `status` | enum(`ok`) | yes |

```json
{
  "$id": "init.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "already_initialized": {
      "type": "boolean"
    },
    "data_dir": {
      "type": "string"
    },
    "status": {
      "enum": [
        "ok"
      ],
      "type": "string"
    }
  },
  "required": [
    "_meta",
    "status",
    "data_dir",
    "already_initialized"
  ],
  "title": "init --json output",
  "type": "object"
}
```

## `schemas/inspect_xlsx.schema.json`

inspect xlsx --json output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `file` | `object` | yes |
| `summary` | `object` | yes |
| `worksheets` | `array`[`object`] | yes |

```json
{
  "$id": "inspect_xlsx.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "file": {
      "additionalProperties": true,
      "properties": {
        "extension": {
          "type": "string"
        },
        "name": {
          "type": "string"
        }
      },
      "required": [
        "name",
        "extension"
      ],
      "type": "object"
    },
    "summary": {
      "additionalProperties": true,
      "properties": {
        "detected_roles": {
          "items": {
            "type": "string"
          },
          "type": "array"
        },
        "worksheet_count": {
          "type": "integer"
        }
      },
      "required": [
        "worksheet_count",
        "detected_roles"
      ],
      "type": "object"
    },
    "worksheets": {
      "items": {
        "additionalProperties": true,
        "properties": {
          "allowlisted_anchors": {
            "items": {
              "additionalProperties": true,
              "properties": {
                "anchor": {
                  "type": "string"
                },
                "column": {
                  "type": "integer"
                },
                "row": {
                  "type": "integer"
                }
              },
              "required": [
                "anchor",
                "row",
                "column"
              ],
              "type": "object"
            },
            "type": "array"
          },
          "column_count": {
            "type": "integer"
          },
          "detected_blocks": {
            "items": {
              "type": "string"
            },
            "type": "array"
          },
          "detected_roles": {
            "items": {
              "type": "string"
            },
            "type": "array"
          },
          "index": {
            "type": "integer"
          },
          "name": {
            "type": "string"
          },
          "row_count": {
            "type": "integer"
          }
        },
        "required": [
          "index",
          "name",
          "row_count",
          "column_count",
          "detected_roles",
          "detected_blocks",
          "allowlisted_anchors"
        ],
        "type": "object"
      },
      "type": "array"
    }
  },
  "required": [
    "_meta",
    "file",
    "summary",
    "worksheets"
  ],
  "title": "inspect xlsx --json output",
  "type": "object"
}
```

## `schemas/journal_list.schema.json`

journal list --json output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `count` | `integer` | yes |
| `entries` | `array`[`object`] | yes |

```json
{
  "$id": "journal_list.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "count": {
      "type": "integer"
    },
    "entries": {
      "items": {
        "additionalProperties": true,
        "properties": {
          "created": {
            "type": [
              "string",
              "null"
            ]
          },
          "filename": {
            "type": "string"
          },
          "path": {
            "type": "string"
          },
          "size_bytes": {
            "type": "integer"
          },
          "topic": {
            "type": "string"
          }
        },
        "required": [
          "path",
          "filename",
          "topic",
          "created",
          "size_bytes"
        ],
        "type": "object"
      },
      "type": "array"
    }
  },
  "required": [
    "_meta",
    "entries",
    "count"
  ],
  "title": "journal list --json output",
  "type": "object"
}
```

## `schemas/manifest.schema.json`

manifest --json output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `commands` | `array`[`object`] | yes |
| `error_codes` | `array`[enum(`GENERAL_ERROR`, `DATA_DIR_NOT_INITIALIZED`, `NO_DATA`, `RULES_FILE_NOT_FOUND`, `RULE_NOT_FOUND`, `FILE_NOT_FOUND`, `FILE_ACCESS_ERROR`, `VALIDATION_FAILED`, `INVALID_ARGS`, `TAGGING_FAILED`, `TRANSFER_FAILED`, `EXPORT_FAILED`, `QUERY_ERROR`, `SIMULATION_FAILED`, `INSPECTION_FAILED`, `USER_CANCELLED`, `UNEXPECTED_ERROR`)] | no |
| `error_schema_ref` | `string` | no |
| `examples` | `array`[`object`] | no |
| `exit_codes` | `object` | no |
| `finjuice_version` | `string` | yes |
| `global_options` | `array`[`object`] | no |
| `manifest_schema_version` | `string` | yes |
| `panels` | `array`[`string`] | no |
| `privacy_profiles` | `object` | no |
| `root_env` | `array`[`object`] | no |

```json
{
  "$id": "manifest.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "commands": {
      "items": {
        "additionalProperties": true,
        "properties": {
          "arguments": {
            "items": {
              "additionalProperties": true,
              "properties": {
                "default": {},
                "help": {
                  "type": [
                    "string",
                    "null"
                  ]
                },
                "name": {
                  "type": "string"
                },
                "required": {
                  "type": "boolean"
                },
                "type": {
                  "type": "string"
                }
              },
              "required": [
                "name",
                "type",
                "required"
              ],
              "type": "object"
            },
            "type": "array"
          },
          "error_schema_ref": {
            "type": "string"
          },
          "examples": {
            "items": {
              "type": "string"
            },
            "type": "array"
          },
          "help": {
            "type": [
              "string",
              "null"
            ]
          },
          "help_oneline": {
            "type": [
              "string",
              "null"
            ]
          },
          "mutates_data": {
            "type": "boolean"
          },
          "name": {
            "type": "string"
          },
          "options": {
            "items": {
              "additionalProperties": true,
              "properties": {
                "default": {},
                "envvar": {
                  "type": [
                    "string",
                    "null"
                  ]
                },
                "help": {
                  "type": [
                    "string",
                    "null"
                  ]
                },
                "is_flag": {
                  "type": "boolean"
                },
                "name": {
                  "type": "string"
                },
                "short": {
                  "type": [
                    "string",
                    "null"
                  ]
                },
                "type": {
                  "type": "string"
                }
              },
              "required": [
                "name",
                "type",
                "is_flag"
              ],
              "type": "object"
            },
            "type": "array"
          },
          "output_schema_ref": {
            "type": [
              "string",
              "null"
            ]
          },
          "path": {
            "type": "string"
          },
          "privacy_profile": {
            "type": "string"
          },
          "requires_confirmation": {
            "type": "boolean"
          },
          "rich_help_panel": {
            "type": [
              "string",
              "null"
            ]
          },
          "safe_readonly": {
            "type": "boolean"
          }
        },
        "required": [
          "path",
          "output_schema_ref"
        ],
        "type": "object"
      },
      "type": "array"
    },
    "error_codes": {
      "items": {
        "enum": [
          "GENERAL_ERROR",
          "DATA_DIR_NOT_INITIALIZED",
          "NO_DATA",
          "RULES_FILE_NOT_FOUND",
          "RULE_NOT_FOUND",
          "FILE_NOT_FOUND",
          "FILE_ACCESS_ERROR",
          "VALIDATION_FAILED",
          "INVALID_ARGS",
          "TAGGING_FAILED",
          "TRANSFER_FAILED",
          "EXPORT_FAILED",
          "QUERY_ERROR",
          "SIMULATION_FAILED",
          "INSPECTION_FAILED",
          "USER_CANCELLED",
          "UNEXPECTED_ERROR"
        ],
        "type": "string"
      },
      "type": "array"
    },
    "error_schema_ref": {
      "type": "string"
    },
    "examples": {
      "items": {
        "additionalProperties": true,
        "properties": {
          "command": {
            "type": "string"
          },
          "description": {
            "type": "string"
          }
        },
        "required": [
          "description",
          "command"
        ],
        "type": "object"
      },
      "type": "array"
    },
    "exit_codes": {
      "additionalProperties": false,
      "properties": {
        "GENERAL_ERROR": {
          "const": 1,
          "type": "integer"
        },
        "NO_DATA": {
          "const": 4,
          "type": "integer"
        },
        "OK": {
          "const": 0,
          "type": "integer"
        },
        "SUCCESS": {
          "const": 0,
          "type": "integer"
        },
        "USAGE_ERROR": {
          "const": 2,
          "type": "integer"
        },
        "USER_CANCELLED": {
          "const": 130,
          "type": "integer"
        },
        "VALIDATION_ERROR": {
          "const": 3,
          "type": "integer"
        }
      },
      "required": [
        "SUCCESS",
        "OK",
        "GENERAL_ERROR",
        "USAGE_ERROR",
        "VALIDATION_ERROR",
        "NO_DATA",
        "USER_CANCELLED"
      ],
      "type": "object"
    },
    "finjuice_version": {
      "type": "string"
    },
    "global_options": {
      "items": {
        "additionalProperties": true,
        "properties": {
          "default": {},
          "envvar": {
            "type": [
              "string",
              "null"
            ]
          },
          "help": {
            "type": [
              "string",
              "null"
            ]
          },
          "is_flag": {
            "type": "boolean"
          },
          "name": {
            "type": "string"
          },
          "short": {
            "type": [
              "string",
              "null"
            ]
          },
          "type": {
            "type": "string"
          }
        },
        "required": [
          "name",
          "type",
          "is_flag"
        ],
        "type": "object"
      },
      "type": "array"
    },
    "manifest_schema_version": {
      "type": "string"
    },
    "panels": {
      "items": {
        "type": "string"
      },
      "type": "array"
    },
    "privacy_profiles": {
      "additionalProperties": {
        "additionalProperties": true,
        "properties": {
          "description": {
            "type": "string"
          },
          "external_disclosure": {
            "type": "string"
          }
        },
        "required": [
          "description",
          "external_disclosure"
        ],
        "type": "object"
      },
      "type": "object"
    },
    "root_env": {
      "items": {
        "additionalProperties": true,
        "properties": {
          "help": {
            "type": [
              "string",
              "null"
            ]
          },
          "name": {
            "type": "string"
          },
          "option": {
            "type": "string"
          }
        },
        "required": [
          "name",
          "option"
        ],
        "type": "object"
      },
      "type": "array"
    }
  },
  "required": [
    "_meta",
    "manifest_schema_version",
    "finjuice_version",
    "commands"
  ],
  "title": "manifest --json output",
  "type": "object"
}
```

## `schemas/networth.schema.json`

networth --json output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `actionable` | `boolean` | yes |
| `as_of` | `string` \| `null` | yes |
| `health` | `object` | yes |
| `net_worth` | `number` | yes |
| `next_steps` | `array`[`object`] | yes |
| `signals` | `object` | yes |
| `total_assets` | `number` | yes |
| `total_liabilities` | `number` | yes |

```json
{
  "$id": "networth.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "actionable": {
      "type": "boolean"
    },
    "as_of": {
      "type": [
        "string",
        "null"
      ]
    },
    "health": {
      "additionalProperties": true,
      "properties": {
        "reasons": {
          "items": {
            "type": "string"
          },
          "type": "array"
        },
        "status": {
          "enum": [
            "ok",
            "warning",
            "critical"
          ],
          "type": "string"
        }
      },
      "required": [
        "status",
        "reasons"
      ],
      "type": "object"
    },
    "net_worth": {
      "type": "number"
    },
    "next_steps": {
      "items": {
        "additionalProperties": true,
        "properties": {
          "command": {
            "type": "string"
          },
          "message": {
            "type": "string"
          },
          "signal": {
            "type": "string"
          }
        },
        "required": [
          "signal",
          "message",
          "command"
        ],
        "type": "object"
      },
      "type": "array"
    },
    "signals": {
      "additionalProperties": true,
      "type": "object"
    },
    "total_assets": {
      "type": "number"
    },
    "total_liabilities": {
      "type": "number"
    }
  },
  "required": [
    "_meta",
    "as_of",
    "total_assets",
    "total_liabilities",
    "net_worth",
    "health",
    "actionable",
    "signals",
    "next_steps"
  ],
  "title": "networth --json output",
  "type": "object"
}
```

## `schemas/networth_breakdown.schema.json`

networth breakdown --json output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `as_of` | `string` \| `null` | yes |
| `breakdown` | `array`[`object`] | yes |

```json
{
  "$id": "networth_breakdown.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "as_of": {
      "type": [
        "string",
        "null"
      ]
    },
    "breakdown": {
      "items": {
        "additionalProperties": true,
        "type": "object"
      },
      "type": "array"
    }
  },
  "required": [
    "_meta",
    "as_of",
    "breakdown"
  ],
  "title": "networth breakdown --json output",
  "type": "object"
}
```

## `schemas/networth_forecast.schema.json`

networth forecast --json output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `projections` | `array`[`object`] | no |
| `scenario` | `string` | no |
| `scenarios` | `object` | no |
| `summary` | `object` | no |

```json
{
  "$id": "networth_forecast.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "projections": {
      "items": {
        "additionalProperties": true,
        "properties": {
          "date": {
            "type": "string"
          },
          "events_fired": {
            "items": {
              "additionalProperties": true,
              "type": "object"
            },
            "type": "array"
          },
          "net_worth": {
            "type": "number"
          },
          "total_assets": {
            "type": "number"
          },
          "total_liabilities": {
            "type": "number"
          }
        },
        "required": [
          "date",
          "total_assets",
          "total_liabilities",
          "net_worth",
          "events_fired"
        ],
        "type": "object"
      },
      "type": "array"
    },
    "scenario": {
      "type": "string"
    },
    "scenarios": {
      "additionalProperties": true,
      "type": "object"
    },
    "summary": {
      "additionalProperties": true,
      "type": "object"
    }
  },
  "required": [
    "_meta"
  ],
  "title": "networth forecast --json output",
  "type": "object"
}
```

## `schemas/networth_history.schema.json`

networth history --json output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `history` | `array`[`object`] | yes |

```json
{
  "$id": "networth_history.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "history": {
      "items": {
        "additionalProperties": true,
        "properties": {
          "as_of": {
            "type": "string"
          },
          "net_worth": {
            "type": "number"
          }
        },
        "required": [
          "as_of",
          "net_worth"
        ],
        "type": "object"
      },
      "type": "array"
    }
  },
  "required": [
    "_meta",
    "history"
  ],
  "title": "networth history --json output",
  "type": "object"
}
```

## `schemas/networth_init.schema.json`

networth init --json output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `authority` | `string` | no |
| `created` | `boolean` | yes |
| `message` | `string` | yes |
| `path` | `string` \| `null` | yes |
| `revision_id` | `string` \| `null` | no |
| `selection_state` | `string` | no |

```json
{
  "$id": "networth_init.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "authority": {
      "type": "string"
    },
    "created": {
      "type": "boolean"
    },
    "message": {
      "type": "string"
    },
    "path": {
      "type": [
        "string",
        "null"
      ]
    },
    "revision_id": {
      "type": [
        "string",
        "null"
      ]
    },
    "selection_state": {
      "type": "string"
    }
  },
  "required": [
    "_meta",
    "path",
    "created",
    "message"
  ],
  "title": "networth init --json output",
  "type": "object"
}
```

## `schemas/networth_validate.schema.json`

networth validate --json output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `authority` | `string` | no |
| `errors` | `integer` | yes |
| `exists` | `boolean` | yes |
| `liabilities` | `integer` | yes |
| `manual_assets` | `integer` | yes |
| `path` | `string` \| `null` | yes |
| `problems` | `array`[`object`] | yes |
| `revision_id` | `string` \| `null` | no |
| `selection_state` | `string` | no |
| `status` | enum(`valid`, `issues`) | yes |
| `valid` | `boolean` | yes |
| `version` | `integer` \| `null` | yes |
| `warnings` | `integer` | yes |

```json
{
  "$id": "networth_validate.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "authority": {
      "type": "string"
    },
    "errors": {
      "type": "integer"
    },
    "exists": {
      "type": "boolean"
    },
    "liabilities": {
      "type": "integer"
    },
    "manual_assets": {
      "type": "integer"
    },
    "path": {
      "type": [
        "string",
        "null"
      ]
    },
    "problems": {
      "items": {
        "additionalProperties": true,
        "properties": {
          "column": {
            "type": [
              "integer",
              "null"
            ]
          },
          "formatted": {
            "type": "string"
          },
          "line": {
            "type": [
              "integer",
              "null"
            ]
          },
          "message": {
            "type": "string"
          },
          "path": {
            "type": "string"
          },
          "severity": {
            "type": "string"
          },
          "type": {
            "type": "string"
          }
        },
        "required": [
          "severity",
          "type",
          "path",
          "message",
          "line",
          "column",
          "formatted"
        ],
        "type": "object"
      },
      "type": "array"
    },
    "revision_id": {
      "type": [
        "string",
        "null"
      ]
    },
    "selection_state": {
      "type": "string"
    },
    "status": {
      "enum": [
        "valid",
        "issues"
      ],
      "type": "string"
    },
    "valid": {
      "type": "boolean"
    },
    "version": {
      "type": [
        "integer",
        "null"
      ]
    },
    "warnings": {
      "type": "integer"
    }
  },
  "required": [
    "_meta",
    "path",
    "exists",
    "valid",
    "status",
    "version",
    "manual_assets",
    "liabilities",
    "errors",
    "warnings",
    "problems"
  ],
  "title": "networth validate --json output",
  "type": "object"
}
```

## `schemas/query.schema.json`

query --json output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `pagination` | `$ref` _pagination.schema.json | yes |
| `row_count` | `integer` | yes |
| `rows` | `array`[`object`] | yes |

```json
{
  "$id": "query.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "pagination": {
      "$ref": "_pagination.schema.json"
    },
    "row_count": {
      "type": "integer"
    },
    "rows": {
      "items": {
        "additionalProperties": true,
        "type": "object"
      },
      "type": "array"
    }
  },
  "required": [
    "_meta",
    "rows",
    "row_count",
    "pagination"
  ],
  "title": "query --json output",
  "type": "object"
}
```

## `schemas/reconcile.schema.json`

reconcile --json output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `command` | `string` | yes |
| `evidence_count` | `integer` | yes |
| `groups` | `array`[`object`] | yes |
| `matched` | `integer` | yes |
| `partial` | `integer` | yes |
| `payment_count` | `integer` | yes |
| `unmatched` | `integer` | yes |

```json
{
  "$id": "reconcile.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "command": {
      "type": "string"
    },
    "evidence_count": {
      "type": "integer"
    },
    "groups": {
      "items": {
        "additionalProperties": true,
        "type": "object"
      },
      "type": "array"
    },
    "matched": {
      "type": "integer"
    },
    "partial": {
      "type": "integer"
    },
    "payment_count": {
      "type": "integer"
    },
    "unmatched": {
      "type": "integer"
    }
  },
  "required": [
    "_meta",
    "command",
    "evidence_count",
    "payment_count",
    "matched",
    "partial",
    "unmatched",
    "groups"
  ],
  "title": "reconcile --json output",
  "type": "object"
}
```

## `schemas/refresh.schema.json`

refresh --json output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `command` | `string` | yes |
| `steps` | `object` | yes |

```json
{
  "$id": "refresh.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "command": {
      "type": "string"
    },
    "steps": {
      "additionalProperties": true,
      "properties": {
        "export": {
          "additionalProperties": true,
          "type": "object"
        },
        "ingest": {
          "additionalProperties": true,
          "type": "object"
        },
        "tag": {
          "additionalProperties": true,
          "type": "object"
        },
        "transfer": {
          "additionalProperties": true,
          "type": "object"
        }
      },
      "required": [
        "ingest",
        "tag",
        "transfer",
        "export"
      ],
      "type": "object"
    }
  },
  "required": [
    "_meta",
    "command",
    "steps"
  ],
  "title": "refresh --json output",
  "type": "object"
}
```

## `schemas/review.schema.json`

review --json output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `actionable` | `boolean` | yes |
| `filters` | `object` | yes |
| `health` | `object` | yes |
| `month` | `string` \| `null` | yes |
| `next_steps` | `array`[`object`] | yes |
| `pagination` | `$ref` _pagination.schema.json | yes |
| `rule_notes` | `array`[`object`] | yes |
| `signals` | `object` | yes |
| `total_count` | `integer` | yes |
| `transactions` | `array`[`object`] | yes |

```json
{
  "$defs": {
    "tagging_review_terms": {
      "additionalProperties": {
        "type": "string"
      },
      "description": "Canonical tagging/review terminology for this JSON contract.",
      "properties": {
        "needs_review": {
          "description": "The explicit row flag needs_review == 1, not every row shown by review.",
          "type": "string"
        },
        "rule_matched": {
          "description": "A transaction with rule-derived output: non-empty tags_rule or non-empty category_rule.",
          "type": "string"
        },
        "suggestable_untagged": {
          "description": "An untagged transaction eligible for rules suggest after excluding confirmed internal transfer pairs.",
          "type": "string"
        },
        "uncategorized": {
          "description": "A transaction whose category_final is the fallback category 미분류.",
          "type": "string"
        },
        "untagged": {
          "description": "A transaction whose tags_final is null or an empty tag array.",
          "type": "string"
        }
      },
      "type": "object"
    }
  },
  "$id": "review.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "allOf": [
    {
      "if": {
        "properties": {
          "_meta": {
            "properties": {
              "privacy": {
                "properties": {
                  "profile": {
                    "enum": [
                      "raw",
                      "redacted"
                    ],
                    "type": "string"
                  }
                },
                "required": [
                  "profile"
                ],
                "type": "object"
              }
            },
            "required": [
              "privacy"
            ],
            "type": "object"
          }
        },
        "required": [
          "_meta"
        ],
        "type": "object"
      },
      "then": {
        "properties": {
          "rule_notes": {
            "items": {
              "required": [
                "rule_name",
                "notes",
                "tags"
              ]
            },
            "type": "array"
          }
        }
      }
    },
    {
      "if": {
        "properties": {
          "_meta": {
            "properties": {
              "privacy": {
                "properties": {
                  "profile": {
                    "enum": [
                      "compact"
                    ],
                    "type": "string"
                  }
                },
                "required": [
                  "profile"
                ],
                "type": "object"
              }
            },
            "required": [
              "privacy"
            ],
            "type": "object"
          }
        },
        "required": [
          "_meta"
        ],
        "type": "object"
      },
      "then": {
        "properties": {
          "rule_notes": {
            "items": {
              "not": {
                "anyOf": [
                  {
                    "required": [
                      "rule_name"
                    ]
                  },
                  {
                    "required": [
                      "notes"
                    ]
                  }
                ]
              }
            },
            "type": "array"
          }
        }
      }
    }
  ],
  "description": "review --json output. The raw and redacted privacy profiles keep full rule note shape; compact rule notes omit merchant-derived rule names and free-text notes.",
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "actionable": {
      "type": "boolean"
    },
    "filters": {
      "additionalProperties": true,
      "type": "object"
    },
    "health": {
      "additionalProperties": true,
      "type": "object"
    },
    "month": {
      "type": [
        "string",
        "null"
      ]
    },
    "next_steps": {
      "items": {
        "additionalProperties": true,
        "properties": {
          "command": {
            "type": "string"
          },
          "message": {
            "type": "string"
          },
          "signal": {
            "type": "string"
          }
        },
        "required": [
          "signal",
          "message",
          "command"
        ],
        "type": "object"
      },
      "type": "array"
    },
    "pagination": {
      "$ref": "_pagination.schema.json"
    },
    "rule_notes": {
      "items": {
        "additionalProperties": true,
        "properties": {
          "category": {
            "type": "string"
          },
          "notes": {
            "type": "string"
          },
          "rule_name": {
            "type": "string"
          },
          "tags": {
            "items": {
              "type": "string"
            },
            "type": "array"
          }
        },
        "type": "object"
      },
      "type": "array"
    },
    "signals": {
      "additionalProperties": true,
      "type": "object"
    },
    "total_count": {
      "type": "integer"
    },
    "transactions": {
      "items": {
        "additionalProperties": true,
        "properties": {
          "amount": {
            "type": [
              "integer",
              "number",
              "null"
            ]
          },
          "category_final": {
            "type": [
              "string",
              "null"
            ]
          },
          "confidence": {
            "type": [
              "number",
              "null"
            ]
          },
          "date": {
            "type": [
              "string",
              "null"
            ]
          },
          "merchant_raw": {
            "type": [
              "string",
              "null"
            ]
          },
          "needs_review": {
            "type": [
              "boolean",
              "integer",
              "null"
            ]
          },
          "reasons": {
            "items": {
              "type": "string"
            },
            "type": "array"
          },
          "row_hash": {
            "type": [
              "string",
              "null"
            ]
          },
          "rule_matched": {
            "type": "boolean"
          },
          "severity": {
            "enum": [
              "high",
              "medium",
              "low"
            ],
            "type": "string"
          },
          "tags_final": {
            "items": {
              "type": "string"
            },
            "type": "array"
          }
        },
        "required": [
          "row_hash",
          "needs_review",
          "rule_matched",
          "reasons",
          "severity"
        ],
        "type": "object"
      },
      "type": "array"
    }
  },
  "required": [
    "_meta",
    "transactions",
    "total_count",
    "filters",
    "month",
    "health",
    "actionable",
    "signals",
    "rule_notes",
    "next_steps",
    "pagination"
  ],
  "title": "review --json output",
  "type": "object",
  "x-finjuice-field-definitions": {
    "signals.needs_review_count": "needs_review",
    "signals.needs_review_flag_count": "needs_review",
    "signals.rule_matched_count": "rule_matched",
    "signals.uncategorized_count": "uncategorized",
    "signals.unclassified_count": "uncategorized",
    "signals.untagged_count": "untagged",
    "transactions[].needs_review": "needs_review",
    "transactions[].reasons": "review reason labels",
    "transactions[].rule_matched": "rule_matched",
    "transactions[].severity": "highest severity derived from review reasons"
  }
}
```

## `schemas/rules_add.schema.json`

rules add --json output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `action` | enum(`added`, `updated`) | yes |
| `coverage_after` | `number` | no |
| `dry_run` | `boolean` | no |
| `dry_run_action` | enum(`added`, `updated`) | no |
| `impact` | `object` | no |
| `preview_action` | enum(`would_add`, `would_update`) | no |
| `rule` | `object` | yes |
| `rules_file_modified` | `boolean` | no |
| `validation` | `object` | yes |

```json
{
  "$id": "rules_add.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "action": {
      "enum": [
        "added",
        "updated"
      ],
      "type": "string"
    },
    "coverage_after": {
      "type": "number"
    },
    "dry_run": {
      "type": "boolean"
    },
    "dry_run_action": {
      "enum": [
        "added",
        "updated"
      ],
      "type": "string"
    },
    "impact": {
      "additionalProperties": true,
      "type": "object"
    },
    "preview_action": {
      "enum": [
        "would_add",
        "would_update"
      ],
      "type": "string"
    },
    "rule": {
      "additionalProperties": true,
      "properties": {
        "category": {
          "type": [
            "string",
            "null"
          ]
        },
        "confidence": {
          "type": "number"
        },
        "created_at": {
          "type": [
            "string",
            "null"
          ]
        },
        "created_by": {
          "type": [
            "string",
            "null"
          ]
        },
        "enabled": {
          "type": "boolean"
        },
        "fields": {
          "items": {
            "type": "string"
          },
          "type": "array"
        },
        "match": {
          "type": "string"
        },
        "name": {
          "type": "string"
        },
        "notes": {
          "type": [
            "string",
            "null"
          ]
        },
        "priority": {
          "type": "integer"
        },
        "tags": {
          "items": {
            "type": "string"
          },
          "type": "array"
        }
      },
      "required": [
        "name",
        "match",
        "fields",
        "tags",
        "priority",
        "enabled",
        "category",
        "created_by",
        "created_at",
        "confidence",
        "notes"
      ],
      "type": "object"
    },
    "rules_file_modified": {
      "type": "boolean"
    },
    "validation": {
      "additionalProperties": true,
      "properties": {
        "errors": {
          "type": "integer"
        },
        "passed": {
          "type": "integer"
        },
        "problems": {
          "items": {
            "additionalProperties": true,
            "properties": {
              "message": {
                "type": "string"
              },
              "rules": {
                "items": {
                  "type": "string"
                },
                "type": "array"
              },
              "severity": {
                "type": "string"
              },
              "suggestion": {
                "type": [
                  "string",
                  "null"
                ]
              },
              "type": {
                "type": "string"
              }
            },
            "required": [
              "severity",
              "type",
              "message",
              "rules",
              "suggestion"
            ],
            "type": "object"
          },
          "type": "array"
        },
        "status": {
          "enum": [
            "valid",
            "issues"
          ],
          "type": "string"
        },
        "total_problems": {
          "type": "integer"
        },
        "total_rules": {
          "type": "integer"
        },
        "warnings": {
          "type": "integer"
        }
      },
      "required": [
        "status",
        "total_rules",
        "errors",
        "warnings",
        "passed",
        "problems",
        "total_problems"
      ],
      "type": "object"
    }
  },
  "required": [
    "_meta",
    "action",
    "rule",
    "validation"
  ],
  "title": "rules add --json output",
  "type": "object"
}
```

## `schemas/rules_export.schema.json`

rules export --json output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `rule_count` | `integer` | yes |
| `rules` | `array`[`object`] | yes |

```json
{
  "$id": "rules_export.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "rule_count": {
      "type": "integer"
    },
    "rules": {
      "items": {
        "additionalProperties": true,
        "properties": {
          "category": {
            "type": [
              "string",
              "null"
            ]
          },
          "fields": {
            "items": {
              "type": "string"
            },
            "type": "array"
          },
          "match": {
            "type": "string"
          },
          "name": {
            "type": "string"
          },
          "priority": {
            "type": "integer"
          },
          "tags": {
            "items": {
              "type": "string"
            },
            "type": "array"
          }
        },
        "required": [
          "name",
          "match",
          "fields",
          "tags",
          "category",
          "priority"
        ],
        "type": "object"
      },
      "type": "array"
    }
  },
  "required": [
    "_meta",
    "rule_count",
    "rules"
  ],
  "title": "rules export --json output",
  "type": "object"
}
```

## `schemas/rules_gaps.schema.json`

rules gaps --json output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `critical_gaps` | `array`[`object`] | yes |
| `mismatches` | `array`[`object`] | yes |
| `simulations` | `array`[`object`] | yes |
| `summary` | `object` | yes |

```json
{
  "$id": "rules_gaps.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "critical_gaps": {
      "items": {
        "additionalProperties": true,
        "properties": {
          "actionable": {
            "type": "boolean"
          },
          "banksalad_category": {
            "type": [
              "string",
              "null"
            ]
          },
          "current_tags": {
            "items": {
              "type": "string"
            },
            "type": "array"
          },
          "expected_category": {
            "type": [
              "string",
              "null"
            ]
          },
          "gap_type": {
            "type": "string"
          },
          "merchant": {
            "type": "string"
          },
          "mismatch_severity": {
            "type": "string"
          },
          "mismatch_type": {
            "type": [
              "string",
              "null"
            ]
          },
          "suggested_action": {
            "type": "string"
          },
          "total_amount": {
            "type": "number"
          },
          "transaction_count": {
            "type": "integer"
          }
        },
        "required": [
          "merchant",
          "transaction_count",
          "total_amount",
          "banksalad_category",
          "current_tags",
          "gap_type",
          "suggested_action"
        ],
        "type": "object"
      },
      "type": "array"
    },
    "mismatches": {
      "items": {
        "additionalProperties": true,
        "properties": {
          "actionable": {
            "type": "boolean"
          },
          "banksalad_category": {
            "type": [
              "string",
              "null"
            ]
          },
          "current_tags": {
            "items": {
              "type": "string"
            },
            "type": "array"
          },
          "expected_category": {
            "type": [
              "string",
              "null"
            ]
          },
          "gap_type": {
            "type": "string"
          },
          "merchant": {
            "type": "string"
          },
          "mismatch_severity": {
            "type": "string"
          },
          "mismatch_type": {
            "type": [
              "string",
              "null"
            ]
          },
          "suggested_action": {
            "type": "string"
          },
          "total_amount": {
            "type": "number"
          },
          "transaction_count": {
            "type": "integer"
          }
        },
        "required": [
          "merchant",
          "transaction_count",
          "total_amount",
          "banksalad_category",
          "current_tags",
          "gap_type",
          "suggested_action"
        ],
        "type": "object"
      },
      "type": "array"
    },
    "simulations": {
      "items": {
        "additionalProperties": true,
        "type": "object"
      },
      "type": "array"
    },
    "summary": {
      "additionalProperties": true,
      "properties": {
        "actionable_mismatch_count": {
          "type": "integer"
        },
        "actionable_only": {
          "type": "boolean"
        },
        "category_mismatch_count": {
          "type": "integer"
        },
        "complete_count": {
          "type": "integer"
        },
        "conflict_count": {
          "type": "integer"
        },
        "critical_count": {
          "type": "integer"
        },
        "filtered_mismatch_count": {
          "type": "integer"
        },
        "filtered_out_mismatch_count": {
          "type": "integer"
        },
        "mismatch_count": {
          "type": "integer"
        },
        "multi_tag_noise_count": {
          "type": "integer"
        },
        "total_mismatch_count": {
          "type": "integer"
        }
      },
      "required": [
        "critical_count",
        "mismatch_count",
        "complete_count"
      ],
      "type": "object"
    }
  },
  "required": [
    "_meta",
    "summary",
    "critical_gaps",
    "mismatches",
    "simulations"
  ],
  "title": "rules gaps --json output",
  "type": "object"
}
```

## `schemas/rules_list.schema.json`

rules list --json output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `rule_count` | `integer` | yes |
| `rules` | `array`[`object`] | yes |

```json
{
  "$id": "rules_list.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "rule_count": {
      "type": "integer"
    },
    "rules": {
      "items": {
        "additionalProperties": true,
        "properties": {
          "category": {
            "type": [
              "string",
              "null"
            ]
          },
          "fields": {
            "items": {
              "type": "string"
            },
            "type": "array"
          },
          "match": {
            "type": "string"
          },
          "name": {
            "type": "string"
          },
          "priority": {
            "type": "integer"
          },
          "tags": {
            "items": {
              "type": "string"
            },
            "type": "array"
          }
        },
        "required": [
          "name",
          "match",
          "fields",
          "tags",
          "category",
          "priority"
        ],
        "type": "object"
      },
      "type": "array"
    }
  },
  "required": [
    "_meta",
    "rule_count",
    "rules"
  ],
  "title": "rules list --json output",
  "type": "object"
}
```

## `schemas/rules_remove.schema.json`

rules remove --json output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `action` | enum(`removed`) | yes |
| `rule_name` | `string` | yes |
| `validation` | `object` | yes |

```json
{
  "$id": "rules_remove.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "action": {
      "enum": [
        "removed"
      ],
      "type": "string"
    },
    "rule_name": {
      "type": "string"
    },
    "validation": {
      "additionalProperties": true,
      "properties": {
        "errors": {
          "type": "integer"
        },
        "passed": {
          "type": "integer"
        },
        "problems": {
          "items": {
            "additionalProperties": true,
            "properties": {
              "message": {
                "type": "string"
              },
              "rules": {
                "items": {
                  "type": "string"
                },
                "type": "array"
              },
              "severity": {
                "type": "string"
              },
              "suggestion": {
                "type": [
                  "string",
                  "null"
                ]
              },
              "type": {
                "type": "string"
              }
            },
            "required": [
              "severity",
              "type",
              "message",
              "rules",
              "suggestion"
            ],
            "type": "object"
          },
          "type": "array"
        },
        "status": {
          "enum": [
            "valid",
            "issues"
          ],
          "type": "string"
        },
        "total_problems": {
          "type": "integer"
        },
        "total_rules": {
          "type": "integer"
        },
        "warnings": {
          "type": "integer"
        }
      },
      "required": [
        "status",
        "total_rules",
        "errors",
        "warnings",
        "passed",
        "problems",
        "total_problems"
      ],
      "type": "object"
    }
  },
  "required": [
    "_meta",
    "action",
    "rule_name",
    "validation"
  ],
  "title": "rules remove --json output",
  "type": "object"
}
```

## `schemas/rules_suggest.schema.json`

rules suggest --json output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `applied` | `integer` | no |
| `coverage_after_pct` | `number` | no |
| `coverage_before_pct` | `number` | no |
| `dry_run` | `boolean` | no |
| `message` | `string` | no |
| `rules_file` | `string` \| `null` | no |
| `rules_file_modified` | `boolean` | no |
| `skipped` | `integer` | no |
| `suggestable_coverage_before_pct` | `number` | no |
| `suggestable_total_count` | `integer` | no |
| `suggestable_untagged_count` | `integer` | no |
| `suggestions` | `array`[`object`] | no |
| `total_count` | `integer` | no |
| `transfer_exclusions` | `object` | no |
| `untagged_count` | `integer` | no |
| `would_apply` | `array`[`object`] | no |

```json
{
  "$defs": {
    "tagging_review_terms": {
      "additionalProperties": {
        "type": "string"
      },
      "description": "Canonical tagging/review terminology for this JSON contract.",
      "properties": {
        "needs_review": {
          "description": "The explicit row flag needs_review == 1, not every row shown by review.",
          "type": "string"
        },
        "rule_matched": {
          "description": "A transaction with rule-derived output: non-empty tags_rule or non-empty category_rule.",
          "type": "string"
        },
        "suggestable_untagged": {
          "description": "An untagged transaction eligible for rules suggest after excluding confirmed internal transfer pairs.",
          "type": "string"
        },
        "uncategorized": {
          "description": "A transaction whose category_final is the fallback category 미분류.",
          "type": "string"
        },
        "untagged": {
          "description": "A transaction whose tags_final is null or an empty tag array.",
          "type": "string"
        }
      },
      "type": "object"
    }
  },
  "$id": "rules_suggest.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "applied": {
      "type": "integer"
    },
    "coverage_after_pct": {
      "type": "number"
    },
    "coverage_before_pct": {
      "type": "number"
    },
    "dry_run": {
      "type": "boolean"
    },
    "message": {
      "type": "string"
    },
    "rules_file": {
      "type": [
        "string",
        "null"
      ]
    },
    "rules_file_modified": {
      "type": "boolean"
    },
    "skipped": {
      "type": "integer"
    },
    "suggestable_coverage_before_pct": {
      "type": "number"
    },
    "suggestable_total_count": {
      "type": "integer"
    },
    "suggestable_untagged_count": {
      "type": "integer"
    },
    "suggestions": {
      "items": {
        "additionalProperties": true,
        "properties": {
          "ambiguous_reason": {
            "type": [
              "string",
              "null"
            ]
          },
          "auto_apply_eligible": {
            "type": "boolean"
          },
          "default_action": {
            "type": "string"
          },
          "distinct_dates": {
            "type": "integer"
          },
          "merchant_kind": {
            "type": "string"
          },
          "name_variants": {
            "items": {
              "type": "string"
            },
            "type": "array"
          }
        },
        "type": "object"
      },
      "type": "array"
    },
    "total_count": {
      "type": "integer"
    },
    "transfer_exclusions": {
      "additionalProperties": true,
      "properties": {
        "definition": {
          "type": "string"
        },
        "excluded_count": {
          "type": "integer"
        },
        "excluded_untagged_count": {
          "type": "integer"
        }
      },
      "required": [
        "excluded_count",
        "excluded_untagged_count",
        "definition"
      ],
      "type": "object"
    },
    "untagged_count": {
      "type": "integer"
    },
    "would_apply": {
      "items": {
        "additionalProperties": true,
        "type": "object"
      },
      "type": "array"
    }
  },
  "required": [
    "_meta"
  ],
  "title": "rules suggest --json output",
  "type": "object",
  "x-finjuice-field-definitions": {
    "suggestable_untagged_count": "suggestable_untagged",
    "transfer_exclusions.excluded_untagged_count": "untagged rows excluded from rule suggestions because they are confirmed transfer pairs",
    "untagged_count": "untagged"
  }
}
```

## `schemas/rules_test.schema.json`

rules test --json output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `cross_tags_top` | `array`[`object`] | yes |
| `match_count` | `integer` | yes |
| `monthly_distribution` | `object` | yes |
| `rule_name` | `string` | yes |
| `sample` | `array`[`object`] | yes |
| `scope` | `object` | yes |

```json
{
  "$id": "rules_test.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "cross_tags_top": {
      "items": {
        "additionalProperties": true,
        "properties": {
          "count": {
            "type": "integer"
          },
          "tag": {
            "type": "string"
          }
        },
        "required": [
          "tag",
          "count"
        ],
        "type": "object"
      },
      "type": "array"
    },
    "match_count": {
      "type": "integer"
    },
    "monthly_distribution": {
      "additionalProperties": true,
      "type": "object"
    },
    "rule_name": {
      "type": "string"
    },
    "sample": {
      "items": {
        "additionalProperties": true,
        "type": "object"
      },
      "type": "array"
    },
    "scope": {
      "additionalProperties": true,
      "properties": {
        "month": {
          "type": [
            "string",
            "null"
          ]
        },
        "total_rows_scanned": {
          "type": "integer"
        }
      },
      "required": [
        "month",
        "total_rows_scanned"
      ],
      "type": "object"
    }
  },
  "required": [
    "_meta",
    "rule_name",
    "scope",
    "match_count",
    "sample",
    "monthly_distribution",
    "cross_tags_top"
  ],
  "title": "rules test --json output",
  "type": "object"
}
```

## `schemas/rules_validate.schema.json`

rules validate --json output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `errors` | `integer` | yes |
| `passed` | `integer` | yes |
| `problems` | `array`[`object`] | yes |
| `status` | enum(`valid`, `issues`) | yes |
| `total_rules` | `integer` | yes |
| `warnings` | `integer` | yes |

```json
{
  "$id": "rules_validate.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "errors": {
      "type": "integer"
    },
    "passed": {
      "type": "integer"
    },
    "problems": {
      "items": {
        "additionalProperties": true,
        "properties": {
          "message": {
            "type": "string"
          },
          "rules": {
            "items": {
              "type": "string"
            },
            "type": "array"
          },
          "severity": {
            "type": "string"
          },
          "suggestion": {
            "type": [
              "string",
              "null"
            ]
          },
          "type": {
            "type": "string"
          }
        },
        "required": [
          "severity",
          "type",
          "message",
          "rules",
          "suggestion"
        ],
        "type": "object"
      },
      "type": "array"
    },
    "status": {
      "enum": [
        "valid",
        "issues"
      ],
      "type": "string"
    },
    "total_rules": {
      "type": "integer"
    },
    "warnings": {
      "type": "integer"
    }
  },
  "required": [
    "_meta",
    "status",
    "total_rules",
    "errors",
    "warnings",
    "passed",
    "problems"
  ],
  "title": "rules validate --json output",
  "type": "object"
}
```

## `schemas/show.schema.json`

show --json output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `pagination` | `$ref` _pagination.schema.json | yes |
| `row_count` | `integer` | yes |
| `rows` | `array`[`object`] | yes |
| `total_matches` | `integer` | yes |

```json
{
  "$id": "show.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "pagination": {
      "$ref": "_pagination.schema.json"
    },
    "row_count": {
      "type": "integer"
    },
    "rows": {
      "items": {
        "additionalProperties": true,
        "properties": {
          "account": {
            "type": [
              "string",
              "null"
            ]
          },
          "amount": {
            "type": "number"
          },
          "category_final": {
            "type": [
              "string",
              "null"
            ]
          },
          "category_rule": {
            "type": [
              "string",
              "null"
            ]
          },
          "confidence": {
            "type": [
              "number",
              "null"
            ]
          },
          "counterparty": {
            "type": [
              "string",
              "null"
            ]
          },
          "currency": {
            "type": [
              "string",
              "null"
            ]
          },
          "date": {
            "type": "string"
          },
          "datetime": {
            "type": [
              "string",
              "null"
            ]
          },
          "file_id": {
            "type": [
              "string",
              "null"
            ]
          },
          "is_transfer": {
            "type": [
              "boolean",
              "integer",
              "null"
            ]
          },
          "major_raw": {
            "type": [
              "string",
              "null"
            ]
          },
          "memo_raw": {
            "type": [
              "string",
              "null"
            ]
          },
          "merchant_raw": {
            "type": [
              "string",
              "null"
            ]
          },
          "minor_raw": {
            "type": [
              "string",
              "null"
            ]
          },
          "needs_review": {
            "type": [
              "boolean",
              "integer",
              "null"
            ]
          },
          "row_hash": {
            "type": "string"
          },
          "source_row": {
            "type": [
              "integer",
              "null"
            ]
          },
          "tags_ai": {
            "items": {
              "type": "string"
            },
            "type": "array"
          },
          "tags_final": {
            "items": {
              "type": "string"
            },
            "type": "array"
          },
          "tags_manual": {
            "items": {
              "type": "string"
            },
            "type": "array"
          },
          "tags_rule": {
            "items": {
              "type": "string"
            },
            "type": "array"
          },
          "time": {
            "type": [
              "string",
              "null"
            ]
          },
          "transfer_group_id": {
            "type": [
              "string",
              "null"
            ]
          },
          "type_norm": {
            "type": [
              "string",
              "null"
            ]
          },
          "type_raw": {
            "type": [
              "string",
              "null"
            ]
          }
        },
        "required": [
          "row_hash",
          "date",
          "amount"
        ],
        "type": "object"
      },
      "type": "array"
    },
    "total_matches": {
      "type": "integer"
    }
  },
  "required": [
    "_meta",
    "rows",
    "row_count",
    "total_matches",
    "pagination"
  ],
  "title": "show --json output",
  "type": "object"
}
```

## `schemas/ssot_account_confirm.schema.json`

ssot account confirm output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `account_id` | `string` | yes |
| `binding_id` | `string` | yes |
| `committed_revision` | `integer` | yes |
| `external_key` | `string` | no |
| `replayed` | `boolean` | yes |
| `source_namespace` | `string` | no |

```json
{
  "$id": "ssot_account_confirm.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "account_id": {
      "type": "string"
    },
    "binding_id": {
      "type": "string"
    },
    "committed_revision": {
      "type": "integer"
    },
    "external_key": {
      "type": "string"
    },
    "replayed": {
      "type": "boolean"
    },
    "source_namespace": {
      "type": "string"
    }
  },
  "required": [
    "_meta",
    "binding_id",
    "account_id",
    "committed_revision",
    "replayed"
  ],
  "title": "ssot account confirm output",
  "type": "object"
}
```

## `schemas/ssot_account_correct.schema.json`

ssot account correct output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `account_id` | `string` | yes |
| `binding_id` | `string` | yes |
| `committed_revision` | `integer` | yes |
| `replayed` | `boolean` | yes |
| `supersedes_binding_id` | `string` | yes |

```json
{
  "$id": "ssot_account_correct.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "account_id": {
      "type": "string"
    },
    "binding_id": {
      "type": "string"
    },
    "committed_revision": {
      "type": "integer"
    },
    "replayed": {
      "type": "boolean"
    },
    "supersedes_binding_id": {
      "type": "string"
    }
  },
  "required": [
    "_meta",
    "binding_id",
    "account_id",
    "supersedes_binding_id",
    "committed_revision",
    "replayed"
  ],
  "title": "ssot account correct output",
  "type": "object"
}
```

## `schemas/ssot_account_list.schema.json`

ssot account list output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `accounts` | `array`[`object`] | yes |
| `bindings` | `array`[`object`] | yes |
| `candidates` | `array`[`object`] | yes |
| `dataset_revision` | `integer` | yes |

```json
{
  "$id": "ssot_account_list.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "accounts": {
      "items": {
        "additionalProperties": true,
        "type": "object"
      },
      "type": "array"
    },
    "bindings": {
      "items": {
        "additionalProperties": true,
        "type": "object"
      },
      "type": "array"
    },
    "candidates": {
      "items": {
        "additionalProperties": true,
        "type": "object"
      },
      "type": "array"
    },
    "dataset_revision": {
      "type": "integer"
    }
  },
  "required": [
    "_meta",
    "dataset_revision",
    "accounts",
    "bindings",
    "candidates"
  ],
  "title": "ssot account list output",
  "type": "object"
}
```

## `schemas/ssot_account_ownership.schema.json`

ssot account ownership output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `account_id` | `string` | yes |
| `as_of` | `string` | yes |
| `dataset_revision` | `integer` | yes |

```json
{
  "$id": "ssot_account_ownership.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "account_id": {
      "type": "string"
    },
    "as_of": {
      "type": "string"
    },
    "dataset_revision": {
      "type": "integer"
    }
  },
  "required": [
    "_meta",
    "dataset_revision",
    "account_id",
    "as_of"
  ],
  "title": "ssot account ownership output",
  "type": "object"
}
```

## `schemas/ssot_account_ownership_confirm.schema.json`

ssot account ownership-confirm output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `account_id` | `string` | yes |
| `assertion_id` | `string` | yes |
| `committed_revision` | `integer` | yes |
| `confirmation_state` | `any` | yes |
| `evidence` | `object` | yes |
| `replayed` | `boolean` | yes |
| `shares` | `array`[`object`] | yes |

```json
{
  "$id": "ssot_account_ownership_confirm.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "account_id": {
      "type": "string"
    },
    "assertion_id": {
      "type": "string"
    },
    "committed_revision": {
      "type": "integer"
    },
    "confirmation_state": {
      "const": "confirmed"
    },
    "evidence": {
      "additionalProperties": true,
      "type": "object"
    },
    "replayed": {
      "type": "boolean"
    },
    "shares": {
      "items": {
        "additionalProperties": true,
        "type": "object"
      },
      "type": "array"
    }
  },
  "required": [
    "_meta",
    "assertion_id",
    "account_id",
    "confirmation_state",
    "evidence",
    "shares",
    "committed_revision",
    "replayed"
  ],
  "title": "ssot account ownership-confirm output",
  "type": "object"
}
```

## `schemas/ssot_account_ownership_correct.schema.json`

ssot account ownership-correct output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `account_id` | `string` | yes |
| `assertion_id` | `string` | yes |
| `committed_revision` | `integer` | yes |
| `confirmation_state` | `any` | yes |
| `evidence` | `object` | yes |
| `replayed` | `boolean` | yes |
| `shares` | `array`[`object`] | yes |
| `supersedes_assertion_id` | `string` | yes |

```json
{
  "$id": "ssot_account_ownership_correct.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "account_id": {
      "type": "string"
    },
    "assertion_id": {
      "type": "string"
    },
    "committed_revision": {
      "type": "integer"
    },
    "confirmation_state": {
      "const": "confirmed"
    },
    "evidence": {
      "additionalProperties": true,
      "type": "object"
    },
    "replayed": {
      "type": "boolean"
    },
    "shares": {
      "items": {
        "additionalProperties": true,
        "type": "object"
      },
      "type": "array"
    },
    "supersedes_assertion_id": {
      "type": "string"
    }
  },
  "required": [
    "_meta",
    "assertion_id",
    "account_id",
    "supersedes_assertion_id",
    "confirmation_state",
    "evidence",
    "shares",
    "committed_revision",
    "replayed"
  ],
  "title": "ssot account ownership-correct output",
  "type": "object"
}
```

## `schemas/ssot_account_preview.schema.json`

ssot account preview output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `after` | `object` | yes |
| `before` | `object` | yes |
| `expected_generation` | `string` | yes |
| `expected_revision` | `integer` | yes |
| `historical_rows_rewritten` | `integer` | yes |
| `importer_supported` | `boolean` | yes |
| `observed_scope` | `array`[`object`] | yes |

```json
{
  "$id": "ssot_account_preview.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "after": {
      "additionalProperties": true,
      "type": "object"
    },
    "before": {
      "additionalProperties": true,
      "type": "object"
    },
    "expected_generation": {
      "type": "string"
    },
    "expected_revision": {
      "type": "integer"
    },
    "historical_rows_rewritten": {
      "type": "integer"
    },
    "importer_supported": {
      "type": "boolean"
    },
    "observed_scope": {
      "items": {
        "additionalProperties": true,
        "type": "object"
      },
      "type": "array"
    }
  },
  "required": [
    "_meta",
    "expected_generation",
    "expected_revision",
    "before",
    "after",
    "observed_scope",
    "historical_rows_rewritten",
    "importer_supported"
  ],
  "title": "ssot account preview output",
  "type": "object"
}
```

## `schemas/ssot_assets_confirm.schema.json`

ssot assets confirm output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `assertion_id` | `string` | yes |
| `committed_revision` | `integer` | yes |
| `replayed` | `boolean` | yes |

```json
{
  "$id": "ssot_assets_confirm.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "assertion_id": {
      "type": "string"
    },
    "committed_revision": {
      "type": "integer"
    },
    "replayed": {
      "type": "boolean"
    }
  },
  "required": [
    "_meta",
    "assertion_id",
    "committed_revision",
    "replayed"
  ],
  "title": "ssot assets confirm output",
  "type": "object"
}
```

## `schemas/ssot_assets_correct.schema.json`

ssot assets correct output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `assertion_id` | `string` | yes |
| `committed_revision` | `integer` | yes |
| `replayed` | `boolean` | yes |

```json
{
  "$id": "ssot_assets_correct.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "assertion_id": {
      "type": "string"
    },
    "committed_revision": {
      "type": "integer"
    },
    "replayed": {
      "type": "boolean"
    }
  },
  "required": [
    "_meta",
    "assertion_id",
    "committed_revision",
    "replayed"
  ],
  "title": "ssot assets correct output",
  "type": "object"
}
```

## `schemas/ssot_assets_list.schema.json`

ssot assets list output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `dataset_revision` | `integer` | yes |
| `pending` | `array`[`object`] | yes |
| `sources` | `array`[`object`] | yes |

```json
{
  "$id": "ssot_assets_list.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "dataset_revision": {
      "type": "integer"
    },
    "pending": {
      "items": {
        "additionalProperties": true,
        "type": "object"
      },
      "type": "array"
    },
    "sources": {
      "items": {
        "additionalProperties": true,
        "type": "object"
      },
      "type": "array"
    }
  },
  "required": [
    "_meta",
    "sources",
    "pending",
    "dataset_revision"
  ],
  "title": "ssot assets list output",
  "type": "object"
}
```

## `schemas/ssot_assets_relation_confirm.schema.json`

ssot assets relation-confirm output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `assertion_id` | `string` | yes |
| `committed_revision` | `integer` | yes |
| `replayed` | `boolean` | yes |

```json
{
  "$id": "ssot_assets_relation_confirm.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "assertion_id": {
      "type": "string"
    },
    "committed_revision": {
      "type": "integer"
    },
    "replayed": {
      "type": "boolean"
    }
  },
  "required": [
    "_meta",
    "assertion_id",
    "committed_revision",
    "replayed"
  ],
  "title": "ssot assets relation-confirm output",
  "type": "object"
}
```

## `schemas/ssot_assets_relation_correct.schema.json`

ssot assets relation-correct output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `assertion_id` | `string` | yes |
| `committed_revision` | `integer` | yes |
| `replayed` | `boolean` | yes |

```json
{
  "$id": "ssot_assets_relation_correct.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "assertion_id": {
      "type": "string"
    },
    "committed_revision": {
      "type": "integer"
    },
    "replayed": {
      "type": "boolean"
    }
  },
  "required": [
    "_meta",
    "assertion_id",
    "committed_revision",
    "replayed"
  ],
  "title": "ssot assets relation-correct output",
  "type": "object"
}
```

## `schemas/ssot_assets_report.schema.json`

ssot assets report output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `completeness` | `string` | yes |
| `dataset_revision` | `integer` | yes |
| `issues` | `array`[`object`] | yes |
| `known_net_worth_subtotal` | `object` or `null` | yes |
| `lines` | `array`[`object`] | yes |
| `net_worth_total` | `object` or `null` | yes |

```json
{
  "$id": "ssot_assets_report.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "completeness": {
      "type": "string"
    },
    "dataset_revision": {
      "type": "integer"
    },
    "issues": {
      "items": {
        "additionalProperties": true,
        "type": "object"
      },
      "type": "array"
    },
    "known_net_worth_subtotal": {
      "anyOf": [
        {
          "additionalProperties": true,
          "type": "object"
        },
        {
          "type": "null"
        }
      ]
    },
    "lines": {
      "items": {
        "additionalProperties": true,
        "type": "object"
      },
      "type": "array"
    },
    "net_worth_total": {
      "anyOf": [
        {
          "additionalProperties": true,
          "type": "object"
        },
        {
          "type": "null"
        }
      ]
    }
  },
  "required": [
    "_meta",
    "completeness",
    "net_worth_total",
    "known_net_worth_subtotal",
    "lines",
    "issues",
    "dataset_revision"
  ],
  "title": "ssot assets report output",
  "type": "object"
}
```

## `schemas/ssot_backup_capture_bundle.schema.json`

ssot backup capture-bundle --json output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `activation_revision` | `integer` | yes |
| `activation_sha256` | `string` | yes |
| `capsule_digest` | `string` | yes |
| `file_count` | `integer` | yes |
| `graph_digest` | `string` | yes |
| `kind` | `any` | yes |
| `snapshot_backup_id` | `string` | yes |
| `snapshot_generation` | `string` | yes |
| `snapshot_manifest_digest` | `string` | yes |
| `snapshot_revision` | `integer` | yes |
| `snapshot_schema_version` | `integer` | yes |
| `wheel_basename` | `string` | yes |

```json
{
  "$id": "ssot_backup_capture_bundle.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "activation_revision": {
      "minimum": 0,
      "type": "integer"
    },
    "activation_sha256": {
      "type": "string"
    },
    "capsule_digest": {
      "type": "string"
    },
    "file_count": {
      "minimum": 0,
      "type": "integer"
    },
    "graph_digest": {
      "type": "string"
    },
    "kind": {
      "const": "local_graph_verified"
    },
    "snapshot_backup_id": {
      "type": "string"
    },
    "snapshot_generation": {
      "type": "string"
    },
    "snapshot_manifest_digest": {
      "type": "string"
    },
    "snapshot_revision": {
      "minimum": 0,
      "type": "integer"
    },
    "snapshot_schema_version": {
      "minimum": 0,
      "type": "integer"
    },
    "wheel_basename": {
      "type": "string"
    }
  },
  "required": [
    "_meta",
    "kind",
    "graph_digest",
    "activation_sha256",
    "wheel_basename",
    "snapshot_generation",
    "snapshot_backup_id",
    "snapshot_manifest_digest",
    "capsule_digest",
    "snapshot_schema_version",
    "snapshot_revision",
    "activation_revision",
    "file_count"
  ],
  "title": "ssot backup capture-bundle --json output",
  "type": "object",
  "x-command": "ssot.backup.capture-bundle"
}
```

## `schemas/ssot_backup_create.schema.json`

ssot backup create --json output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `backup_id` | `string` | yes |
| `backup_kind` | `string` | yes |
| `byte_count` | `integer` | yes |
| `complete` | `any` | yes |
| `database_digest` | `string` | yes |
| `dataset_revision` | `integer` | yes |
| `file_count` | `integer` | yes |
| `manifest_digest` | `string` | yes |
| `manifest_schema_version` | `integer` | yes |
| `source_generation` | `string` | yes |
| `status` | `any` | yes |
| `warnings` | `array`[`string`] | yes |

```json
{
  "$id": "ssot_backup_create.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "backup_id": {
      "type": "string"
    },
    "backup_kind": {
      "type": "string"
    },
    "byte_count": {
      "minimum": 0,
      "type": "integer"
    },
    "complete": {
      "const": true
    },
    "database_digest": {
      "type": "string"
    },
    "dataset_revision": {
      "minimum": 0,
      "type": "integer"
    },
    "file_count": {
      "minimum": 0,
      "type": "integer"
    },
    "manifest_digest": {
      "type": "string"
    },
    "manifest_schema_version": {
      "minimum": 0,
      "type": "integer"
    },
    "source_generation": {
      "type": "string"
    },
    "status": {
      "const": "complete"
    },
    "warnings": {
      "items": {
        "type": "string"
      },
      "type": "array"
    }
  },
  "required": [
    "_meta",
    "backup_id",
    "backup_kind",
    "database_digest",
    "manifest_digest",
    "source_generation",
    "byte_count",
    "dataset_revision",
    "file_count",
    "manifest_schema_version",
    "complete",
    "status",
    "warnings"
  ],
  "title": "ssot backup create --json output",
  "type": "object"
}
```

## `schemas/ssot_backup_deliver_run.schema.json`

ssot backup deliver run --json output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `attempt` | `object` \| `null` | yes |
| `backup` | `object` | yes |
| `coverage_as_of` | `string` \| `null` | yes |
| `history_unknown` | `boolean` | yes |
| `job_id` | `string` | yes |
| `kind` | enum(`backup_delivery_status`, `backup_delivery_run`) | yes |
| `last_attempt_error_code` | `string` \| `null` | yes |
| `last_verified_at` | `string` \| `null` | yes |
| `pending_commit_count` | `integer` \| `null` | yes |
| `recording` | `object` \| `null` | yes |
| `source_observed_revision` | `integer` \| `null` | yes |

```json
{
  "$defs": {
    "projection": {
      "properties": {
        "attempt": {
          "type": [
            "object",
            "null"
          ]
        },
        "backup": {
          "properties": {
            "destination": {
              "enum": [
                "covered",
                "pending",
                "transfer_failed",
                "verification_failed",
                "unknown"
              ],
              "type": "string"
            },
            "local": {
              "enum": [
                "covered",
                "pending",
                "verification_failed",
                "unknown"
              ],
              "type": "string"
            }
          },
          "required": [
            "destination",
            "local"
          ],
          "type": "object"
        },
        "coverage_as_of": {
          "type": [
            "string",
            "null"
          ]
        },
        "history_unknown": {
          "type": "boolean"
        },
        "job_id": {
          "type": "string"
        },
        "kind": {
          "enum": [
            "backup_delivery_status",
            "backup_delivery_run"
          ],
          "type": "string"
        },
        "last_attempt_error_code": {
          "type": [
            "string",
            "null"
          ]
        },
        "last_verified_at": {
          "type": [
            "string",
            "null"
          ]
        },
        "pending_commit_count": {
          "minimum": 0,
          "type": [
            "integer",
            "null"
          ]
        },
        "recording": {
          "properties": {
            "changeset_id": {
              "type": "string"
            },
            "committed_revision": {
              "minimum": 0,
              "type": "integer"
            },
            "replayed": {
              "type": "boolean"
            },
            "status": {
              "enum": [
                "committed",
                "unknown"
              ],
              "type": "string"
            }
          },
          "type": [
            "object",
            "null"
          ]
        },
        "source_observed_revision": {
          "minimum": 0,
          "type": [
            "integer",
            "null"
          ]
        }
      },
      "required": [
        "kind",
        "job_id",
        "recording",
        "backup",
        "source_observed_revision",
        "coverage_as_of",
        "pending_commit_count",
        "last_verified_at",
        "last_attempt_error_code",
        "history_unknown",
        "attempt"
      ],
      "type": "object"
    }
  },
  "$id": "ssot_backup_deliver_run.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "attempt": {
      "type": [
        "object",
        "null"
      ]
    },
    "backup": {
      "properties": {
        "destination": {
          "enum": [
            "covered",
            "pending",
            "transfer_failed",
            "verification_failed",
            "unknown"
          ],
          "type": "string"
        },
        "local": {
          "enum": [
            "covered",
            "pending",
            "verification_failed",
            "unknown"
          ],
          "type": "string"
        }
      },
      "required": [
        "destination",
        "local"
      ],
      "type": "object"
    },
    "coverage_as_of": {
      "type": [
        "string",
        "null"
      ]
    },
    "history_unknown": {
      "type": "boolean"
    },
    "job_id": {
      "type": "string"
    },
    "kind": {
      "enum": [
        "backup_delivery_status",
        "backup_delivery_run"
      ],
      "type": "string"
    },
    "last_attempt_error_code": {
      "type": [
        "string",
        "null"
      ]
    },
    "last_verified_at": {
      "type": [
        "string",
        "null"
      ]
    },
    "pending_commit_count": {
      "minimum": 0,
      "type": [
        "integer",
        "null"
      ]
    },
    "recording": {
      "properties": {
        "changeset_id": {
          "type": "string"
        },
        "committed_revision": {
          "minimum": 0,
          "type": "integer"
        },
        "replayed": {
          "type": "boolean"
        },
        "status": {
          "enum": [
            "committed",
            "unknown"
          ],
          "type": "string"
        }
      },
      "type": [
        "object",
        "null"
      ]
    },
    "source_observed_revision": {
      "minimum": 0,
      "type": [
        "integer",
        "null"
      ]
    }
  },
  "required": [
    "_meta",
    "kind",
    "job_id",
    "recording",
    "backup",
    "source_observed_revision",
    "coverage_as_of",
    "pending_commit_count",
    "last_verified_at",
    "last_attempt_error_code",
    "history_unknown",
    "attempt"
  ],
  "title": "ssot backup deliver run --json output",
  "type": "object",
  "x-command": "ssot.backup.deliver.run"
}
```

## `schemas/ssot_backup_deliver_status.schema.json`

ssot backup deliver status --json output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `attempt` | `object` \| `null` | yes |
| `backup` | `object` | yes |
| `coverage_as_of` | `string` \| `null` | yes |
| `history_unknown` | `boolean` | yes |
| `job_id` | `string` | yes |
| `kind` | enum(`backup_delivery_status`, `backup_delivery_run`) | yes |
| `last_attempt_error_code` | `string` \| `null` | yes |
| `last_verified_at` | `string` \| `null` | yes |
| `pending_commit_count` | `integer` \| `null` | yes |
| `recording` | `object` \| `null` | yes |
| `source_observed_revision` | `integer` \| `null` | yes |

```json
{
  "$defs": {
    "projection": {
      "properties": {
        "attempt": {
          "type": [
            "object",
            "null"
          ]
        },
        "backup": {
          "properties": {
            "destination": {
              "enum": [
                "covered",
                "pending",
                "transfer_failed",
                "verification_failed",
                "unknown"
              ],
              "type": "string"
            },
            "local": {
              "enum": [
                "covered",
                "pending",
                "verification_failed",
                "unknown"
              ],
              "type": "string"
            }
          },
          "required": [
            "destination",
            "local"
          ],
          "type": "object"
        },
        "coverage_as_of": {
          "type": [
            "string",
            "null"
          ]
        },
        "history_unknown": {
          "type": "boolean"
        },
        "job_id": {
          "type": "string"
        },
        "kind": {
          "enum": [
            "backup_delivery_status",
            "backup_delivery_run"
          ],
          "type": "string"
        },
        "last_attempt_error_code": {
          "type": [
            "string",
            "null"
          ]
        },
        "last_verified_at": {
          "type": [
            "string",
            "null"
          ]
        },
        "pending_commit_count": {
          "minimum": 0,
          "type": [
            "integer",
            "null"
          ]
        },
        "recording": {
          "properties": {
            "changeset_id": {
              "type": "string"
            },
            "committed_revision": {
              "minimum": 0,
              "type": "integer"
            },
            "replayed": {
              "type": "boolean"
            },
            "status": {
              "enum": [
                "committed",
                "unknown"
              ],
              "type": "string"
            }
          },
          "type": [
            "object",
            "null"
          ]
        },
        "source_observed_revision": {
          "minimum": 0,
          "type": [
            "integer",
            "null"
          ]
        }
      },
      "required": [
        "kind",
        "job_id",
        "recording",
        "backup",
        "source_observed_revision",
        "coverage_as_of",
        "pending_commit_count",
        "last_verified_at",
        "last_attempt_error_code",
        "history_unknown",
        "attempt"
      ],
      "type": "object"
    }
  },
  "$id": "ssot_backup_deliver_status.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "attempt": {
      "type": [
        "object",
        "null"
      ]
    },
    "backup": {
      "properties": {
        "destination": {
          "enum": [
            "covered",
            "pending",
            "transfer_failed",
            "verification_failed",
            "unknown"
          ],
          "type": "string"
        },
        "local": {
          "enum": [
            "covered",
            "pending",
            "verification_failed",
            "unknown"
          ],
          "type": "string"
        }
      },
      "required": [
        "destination",
        "local"
      ],
      "type": "object"
    },
    "coverage_as_of": {
      "type": [
        "string",
        "null"
      ]
    },
    "history_unknown": {
      "type": "boolean"
    },
    "job_id": {
      "type": "string"
    },
    "kind": {
      "enum": [
        "backup_delivery_status",
        "backup_delivery_run"
      ],
      "type": "string"
    },
    "last_attempt_error_code": {
      "type": [
        "string",
        "null"
      ]
    },
    "last_verified_at": {
      "type": [
        "string",
        "null"
      ]
    },
    "pending_commit_count": {
      "minimum": 0,
      "type": [
        "integer",
        "null"
      ]
    },
    "recording": {
      "properties": {
        "changeset_id": {
          "type": "string"
        },
        "committed_revision": {
          "minimum": 0,
          "type": "integer"
        },
        "replayed": {
          "type": "boolean"
        },
        "status": {
          "enum": [
            "committed",
            "unknown"
          ],
          "type": "string"
        }
      },
      "type": [
        "object",
        "null"
      ]
    },
    "source_observed_revision": {
      "minimum": 0,
      "type": [
        "integer",
        "null"
      ]
    }
  },
  "required": [
    "_meta",
    "kind",
    "job_id",
    "recording",
    "backup",
    "source_observed_revision",
    "coverage_as_of",
    "pending_commit_count",
    "last_verified_at",
    "last_attempt_error_code",
    "history_unknown",
    "attempt"
  ],
  "title": "ssot backup deliver status --json output",
  "type": "object",
  "x-command": "ssot.backup.deliver.status"
}
```

## `schemas/ssot_backup_restore.schema.json`

ssot backup restore --json output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `dataset_generation` | `string` | yes |
| `descriptor_digest` | `string` | yes |
| `initial_database_digest` | `string` | yes |
| `initial_dataset_revision` | `integer` | yes |
| `restore_id` | `string` | yes |
| `source_manifest_digest` | `string` | yes |
| `sqlite_schema_version` | `integer` | yes |

```json
{
  "$id": "ssot_backup_restore.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "dataset_generation": {
      "type": "string"
    },
    "descriptor_digest": {
      "type": "string"
    },
    "initial_database_digest": {
      "type": "string"
    },
    "initial_dataset_revision": {
      "minimum": 0,
      "type": "integer"
    },
    "restore_id": {
      "type": "string"
    },
    "source_manifest_digest": {
      "type": "string"
    },
    "sqlite_schema_version": {
      "minimum": 0,
      "type": "integer"
    }
  },
  "required": [
    "_meta",
    "restore_id",
    "descriptor_digest",
    "dataset_generation",
    "initial_database_digest",
    "source_manifest_digest",
    "initial_dataset_revision",
    "sqlite_schema_version"
  ],
  "title": "ssot backup restore --json output",
  "type": "object"
}
```

## `schemas/ssot_backup_restore_bundle.schema.json`

ssot backup restore-bundle --json output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `dataset_generation` | `string` | yes |
| `descriptor_digest` | `string` | yes |
| `initial_database_digest` | `string` | yes |
| `initial_dataset_revision` | `integer` | yes |
| `restore_id` | `string` | yes |
| `source_manifest_digest` | `string` | yes |
| `sqlite_schema_version` | `integer` | yes |

```json
{
  "$id": "ssot_backup_restore_bundle.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "dataset_generation": {
      "type": "string"
    },
    "descriptor_digest": {
      "type": "string"
    },
    "initial_database_digest": {
      "type": "string"
    },
    "initial_dataset_revision": {
      "minimum": 0,
      "type": "integer"
    },
    "restore_id": {
      "type": "string"
    },
    "source_manifest_digest": {
      "type": "string"
    },
    "sqlite_schema_version": {
      "minimum": 0,
      "type": "integer"
    }
  },
  "required": [
    "_meta",
    "restore_id",
    "descriptor_digest",
    "dataset_generation",
    "initial_database_digest",
    "source_manifest_digest",
    "initial_dataset_revision",
    "sqlite_schema_version"
  ],
  "title": "ssot backup restore-bundle --json output",
  "type": "object",
  "x-command": "ssot.backup.restore-bundle"
}
```

## `schemas/ssot_backup_status.schema.json`

ssot backup status --json output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `byte_count` | `integer` | yes |
| `complete` | `boolean` | yes |
| `file_count` | `integer` | yes |
| `manifest_digest` | `string` \| `null` | yes |
| `reason` | `string` | yes |
| `source_generation` | `string` \| `null` | yes |

```json
{
  "$id": "ssot_backup_status.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "byte_count": {
      "minimum": 0,
      "type": "integer"
    },
    "complete": {
      "type": "boolean"
    },
    "file_count": {
      "minimum": 0,
      "type": "integer"
    },
    "manifest_digest": {
      "type": [
        "string",
        "null"
      ]
    },
    "reason": {
      "type": "string"
    },
    "source_generation": {
      "type": [
        "string",
        "null"
      ]
    }
  },
  "required": [
    "_meta",
    "byte_count",
    "file_count",
    "complete",
    "reason",
    "manifest_digest",
    "source_generation"
  ],
  "title": "ssot backup status --json output",
  "type": "object"
}
```

## `schemas/ssot_backup_store_capture.schema.json`

ssot backup store capture --json output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `activation_revision` | `integer` | yes |
| `activation_sha256` | `string` | yes |
| `baseline_registered` | `boolean` | yes |
| `capsule_digest` | `string` | yes |
| `copy_id` | `string` | yes |
| `file_count` | `integer` | yes |
| `graph_digest` | `string` | yes |
| `kind` | `any` | yes |
| `snapshot_backup_id` | `string` | yes |
| `snapshot_generation` | `string` | yes |
| `snapshot_manifest_digest` | `string` | yes |
| `snapshot_revision` | `integer` | yes |
| `snapshot_schema_version` | `integer` | yes |
| `wheel_basename` | `string` | yes |

```json
{
  "$id": "ssot_backup_store_capture.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "activation_revision": {
      "minimum": 0,
      "type": "integer"
    },
    "activation_sha256": {
      "type": "string"
    },
    "baseline_registered": {
      "type": "boolean"
    },
    "capsule_digest": {
      "type": "string"
    },
    "copy_id": {
      "type": "string"
    },
    "file_count": {
      "minimum": 0,
      "type": "integer"
    },
    "graph_digest": {
      "type": "string"
    },
    "kind": {
      "const": "local_recovery_store_captured"
    },
    "snapshot_backup_id": {
      "type": "string"
    },
    "snapshot_generation": {
      "type": "string"
    },
    "snapshot_manifest_digest": {
      "type": "string"
    },
    "snapshot_revision": {
      "minimum": 0,
      "type": "integer"
    },
    "snapshot_schema_version": {
      "minimum": 0,
      "type": "integer"
    },
    "wheel_basename": {
      "type": "string"
    }
  },
  "required": [
    "_meta",
    "kind",
    "graph_digest",
    "activation_sha256",
    "wheel_basename",
    "snapshot_generation",
    "snapshot_backup_id",
    "snapshot_manifest_digest",
    "capsule_digest",
    "snapshot_schema_version",
    "snapshot_revision",
    "activation_revision",
    "file_count",
    "copy_id",
    "baseline_registered"
  ],
  "title": "ssot backup store capture --json output",
  "type": "object",
  "x-command": "ssot.backup.store.capture"
}
```

## `schemas/ssot_backup_store_init.schema.json`

ssot backup store init --json output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `activation_sha256` | `string` | yes |
| `enrollment_digest` | `string` | yes |
| `kind` | `any` | yes |
| `store_id` | `string` | yes |

```json
{
  "$id": "ssot_backup_store_init.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "activation_sha256": {
      "type": "string"
    },
    "enrollment_digest": {
      "type": "string"
    },
    "kind": {
      "const": "local_recovery_store_initialized"
    },
    "store_id": {
      "type": "string"
    }
  },
  "required": [
    "_meta",
    "kind",
    "store_id",
    "activation_sha256",
    "enrollment_digest"
  ],
  "title": "ssot backup store init --json output",
  "type": "object",
  "x-command": "ssot.backup.store.init"
}
```

## `schemas/ssot_backup_store_list.schema.json`

ssot backup store list --json output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `baseline_copy_ids` | `array`[`string`] | yes |
| `copies` | `array`[`object`] | yes |
| `healthy_count` | `integer` | yes |
| `held_count` | `integer` | yes |
| `kind` | `any` | yes |
| `latest_healthy_id` | `string` \| `null` | yes |
| `plan_digest` | `string` \| `null` | yes |
| `store_id` | `string` | yes |

```json
{
  "$id": "ssot_backup_store_list.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "baseline_copy_ids": {
      "items": {
        "type": "string"
      },
      "type": "array"
    },
    "copies": {
      "items": {
        "properties": {
          "copy_id": {
            "type": "string"
          },
          "created_at": {
            "type": [
              "string",
              "null"
            ]
          },
          "graph_digest": {
            "type": [
              "string",
              "null"
            ]
          },
          "health": {
            "enum": [
              "healthy",
              "held"
            ],
            "type": "string"
          },
          "hold_reason": {
            "type": [
              "string",
              "null"
            ]
          },
          "protected": {
            "type": "boolean"
          }
        },
        "type": "object"
      },
      "type": "array"
    },
    "healthy_count": {
      "minimum": 0,
      "type": "integer"
    },
    "held_count": {
      "minimum": 0,
      "type": "integer"
    },
    "kind": {
      "const": "local_recovery_store_inventory"
    },
    "latest_healthy_id": {
      "type": [
        "string",
        "null"
      ]
    },
    "plan_digest": {
      "type": [
        "string",
        "null"
      ]
    },
    "store_id": {
      "type": "string"
    }
  },
  "required": [
    "_meta",
    "kind",
    "store_id",
    "healthy_count",
    "held_count",
    "baseline_copy_ids",
    "latest_healthy_id",
    "copies",
    "plan_digest"
  ],
  "title": "ssot backup store list --json output",
  "type": "object",
  "x-command": "ssot.backup.store.list"
}
```

## `schemas/ssot_backup_store_plan.schema.json`

ssot backup store plan --json output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `delete_count` | `integer` | yes |
| `delete_ids` | `array`[`string`] | yes |
| `keep_count` | `integer` | yes |
| `keep_ids` | `array`[`string`] | yes |
| `kind` | `any` | yes |
| `latest_healthy_id` | `string` \| `null` | yes |
| `plan_digest` | `string` | yes |
| `policy` | `object` | yes |
| `protected_count` | `integer` | yes |
| `protected_ids` | `array`[`string`] | yes |

```json
{
  "$id": "ssot_backup_store_plan.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "delete_count": {
      "minimum": 0,
      "type": "integer"
    },
    "delete_ids": {
      "items": {
        "type": "string"
      },
      "type": "array"
    },
    "keep_count": {
      "minimum": 0,
      "type": "integer"
    },
    "keep_ids": {
      "items": {
        "type": "string"
      },
      "type": "array"
    },
    "kind": {
      "const": "local_recovery_store_plan"
    },
    "latest_healthy_id": {
      "type": [
        "string",
        "null"
      ]
    },
    "plan_digest": {
      "type": "string"
    },
    "policy": {
      "properties": {
        "daily": {
          "minimum": 0,
          "type": "integer"
        },
        "monthly": {
          "minimum": 0,
          "type": "integer"
        },
        "weekly": {
          "minimum": 0,
          "type": "integer"
        }
      },
      "required": [
        "daily",
        "weekly",
        "monthly"
      ],
      "type": "object"
    },
    "protected_count": {
      "minimum": 0,
      "type": "integer"
    },
    "protected_ids": {
      "items": {
        "type": "string"
      },
      "type": "array"
    }
  },
  "required": [
    "_meta",
    "kind",
    "plan_digest",
    "delete_count",
    "keep_count",
    "protected_count",
    "latest_healthy_id",
    "policy",
    "keep_ids",
    "delete_ids",
    "protected_ids"
  ],
  "title": "ssot backup store plan --json output",
  "type": "object",
  "x-command": "ssot.backup.store.plan"
}
```

## `schemas/ssot_backup_store_protect.schema.json`

ssot backup store protect --json output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `copy_id` | `string` | yes |
| `graph_digest` | `string` | yes |
| `kind` | `any` | yes |

```json
{
  "$id": "ssot_backup_store_protect.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "copy_id": {
      "type": "string"
    },
    "graph_digest": {
      "type": "string"
    },
    "kind": {
      "const": "local_recovery_store_protected"
    }
  },
  "required": [
    "_meta",
    "kind",
    "copy_id",
    "graph_digest"
  ],
  "title": "ssot backup store protect --json output",
  "type": "object",
  "x-command": "ssot.backup.store.protect"
}
```

## `schemas/ssot_backup_store_prune.schema.json`

ssot backup store prune --json output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `deleted_count` | `integer` | yes |
| `deleted_ids` | `array`[`string`] | yes |
| `held_count` | `integer` | yes |
| `kept_count` | `integer` | yes |
| `kept_ids` | `array`[`string`] | yes |
| `kind` | `any` | yes |
| `plan_digest` | `string` | yes |

```json
{
  "$id": "ssot_backup_store_prune.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "deleted_count": {
      "minimum": 0,
      "type": "integer"
    },
    "deleted_ids": {
      "items": {
        "type": "string"
      },
      "type": "array"
    },
    "held_count": {
      "minimum": 0,
      "type": "integer"
    },
    "kept_count": {
      "minimum": 0,
      "type": "integer"
    },
    "kept_ids": {
      "items": {
        "type": "string"
      },
      "type": "array"
    },
    "kind": {
      "const": "local_recovery_store_pruned"
    },
    "plan_digest": {
      "type": "string"
    }
  },
  "required": [
    "_meta",
    "kind",
    "deleted_count",
    "kept_count",
    "held_count",
    "plan_digest",
    "deleted_ids",
    "kept_ids"
  ],
  "title": "ssot backup store prune --json output",
  "type": "object",
  "x-command": "ssot.backup.store.prune"
}
```

## `schemas/ssot_backup_store_restore.schema.json`

ssot backup store restore --json output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `dataset_generation` | `string` | yes |
| `descriptor_digest` | `string` | yes |
| `initial_database_digest` | `string` | yes |
| `initial_dataset_revision` | `integer` | yes |
| `restore_id` | `string` | yes |
| `source_manifest_digest` | `string` | yes |
| `sqlite_schema_version` | `integer` | yes |

```json
{
  "$id": "ssot_backup_store_restore.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "dataset_generation": {
      "type": "string"
    },
    "descriptor_digest": {
      "type": "string"
    },
    "initial_database_digest": {
      "type": "string"
    },
    "initial_dataset_revision": {
      "minimum": 0,
      "type": "integer"
    },
    "restore_id": {
      "type": "string"
    },
    "source_manifest_digest": {
      "type": "string"
    },
    "sqlite_schema_version": {
      "minimum": 0,
      "type": "integer"
    }
  },
  "required": [
    "_meta",
    "restore_id",
    "descriptor_digest",
    "dataset_generation",
    "initial_database_digest",
    "source_manifest_digest",
    "initial_dataset_revision",
    "sqlite_schema_version"
  ],
  "title": "ssot backup store restore --json output",
  "type": "object",
  "x-command": "ssot.backup.store.restore"
}
```

## `schemas/ssot_backup_store_verify.schema.json`

ssot backup store verify --json output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `activation_revision` | `integer` | yes |
| `activation_sha256` | `string` | yes |
| `capsule_digest` | `string` | yes |
| `file_count` | `integer` | yes |
| `graph_digest` | `string` | yes |
| `kind` | `any` | yes |
| `snapshot_backup_id` | `string` | yes |
| `snapshot_generation` | `string` | yes |
| `snapshot_manifest_digest` | `string` | yes |
| `snapshot_revision` | `integer` | yes |
| `snapshot_schema_version` | `integer` | yes |
| `wheel_basename` | `string` | yes |

```json
{
  "$id": "ssot_backup_store_verify.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "activation_revision": {
      "minimum": 0,
      "type": "integer"
    },
    "activation_sha256": {
      "type": "string"
    },
    "capsule_digest": {
      "type": "string"
    },
    "file_count": {
      "minimum": 0,
      "type": "integer"
    },
    "graph_digest": {
      "type": "string"
    },
    "kind": {
      "const": "local_graph_verified"
    },
    "snapshot_backup_id": {
      "type": "string"
    },
    "snapshot_generation": {
      "type": "string"
    },
    "snapshot_manifest_digest": {
      "type": "string"
    },
    "snapshot_revision": {
      "minimum": 0,
      "type": "integer"
    },
    "snapshot_schema_version": {
      "minimum": 0,
      "type": "integer"
    },
    "wheel_basename": {
      "type": "string"
    }
  },
  "required": [
    "_meta",
    "kind",
    "graph_digest",
    "activation_sha256",
    "wheel_basename",
    "snapshot_generation",
    "snapshot_backup_id",
    "snapshot_manifest_digest",
    "capsule_digest",
    "snapshot_schema_version",
    "snapshot_revision",
    "activation_revision",
    "file_count"
  ],
  "title": "ssot backup store verify --json output",
  "type": "object",
  "x-command": "ssot.backup.store.verify"
}
```

## `schemas/ssot_backup_verify_bundle.schema.json`

ssot backup verify-bundle --json output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `activation_revision` | `integer` | yes |
| `activation_sha256` | `string` | yes |
| `capsule_digest` | `string` | yes |
| `file_count` | `integer` | yes |
| `graph_digest` | `string` | yes |
| `kind` | `any` | yes |
| `snapshot_backup_id` | `string` | yes |
| `snapshot_generation` | `string` | yes |
| `snapshot_manifest_digest` | `string` | yes |
| `snapshot_revision` | `integer` | yes |
| `snapshot_schema_version` | `integer` | yes |
| `wheel_basename` | `string` | yes |

```json
{
  "$id": "ssot_backup_verify_bundle.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "activation_revision": {
      "minimum": 0,
      "type": "integer"
    },
    "activation_sha256": {
      "type": "string"
    },
    "capsule_digest": {
      "type": "string"
    },
    "file_count": {
      "minimum": 0,
      "type": "integer"
    },
    "graph_digest": {
      "type": "string"
    },
    "kind": {
      "const": "local_graph_verified"
    },
    "snapshot_backup_id": {
      "type": "string"
    },
    "snapshot_generation": {
      "type": "string"
    },
    "snapshot_manifest_digest": {
      "type": "string"
    },
    "snapshot_revision": {
      "minimum": 0,
      "type": "integer"
    },
    "snapshot_schema_version": {
      "minimum": 0,
      "type": "integer"
    },
    "wheel_basename": {
      "type": "string"
    }
  },
  "required": [
    "_meta",
    "kind",
    "graph_digest",
    "activation_sha256",
    "wheel_basename",
    "snapshot_generation",
    "snapshot_backup_id",
    "snapshot_manifest_digest",
    "capsule_digest",
    "snapshot_schema_version",
    "snapshot_revision",
    "activation_revision",
    "file_count"
  ],
  "title": "ssot backup verify-bundle --json output",
  "type": "object",
  "x-command": "ssot.backup.verify-bundle"
}
```

## `schemas/ssot_close_history.schema.json`

ssot close history output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `periods` | `object` | yes |
| `revisions` | `array`[`object`] | yes |

```json
{
  "$id": "ssot_close_history.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "periods": {
      "additionalProperties": true,
      "type": "object"
    },
    "revisions": {
      "items": {
        "additionalProperties": true,
        "type": "object"
      },
      "type": "array"
    }
  },
  "required": [
    "_meta",
    "revisions",
    "periods"
  ],
  "title": "ssot close history output",
  "type": "object"
}
```

## `schemas/ssot_close_reopen.schema.json`

ssot close reopen output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `close_id` | `string` | yes |
| `close_revision` | `integer` | yes |
| `committed_revision` | `integer` | no |
| `period` | `string` | yes |
| `replayed` | `boolean` | yes |

```json
{
  "$id": "ssot_close_reopen.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "close_id": {
      "type": "string"
    },
    "close_revision": {
      "type": "integer"
    },
    "committed_revision": {
      "type": "integer"
    },
    "period": {
      "type": "string"
    },
    "replayed": {
      "type": "boolean"
    }
  },
  "required": [
    "_meta",
    "close_id",
    "period",
    "close_revision",
    "replayed"
  ],
  "title": "ssot close reopen output",
  "type": "object"
}
```

## `schemas/ssot_close_run.schema.json`

ssot close run output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `close` | `object` | yes |
| `close_id` | `string` | yes |
| `committed_revision` | `integer` | no |
| `diff` | `array`[`object`] | yes |
| `reclosed` | `boolean` | yes |
| `replayed` | `boolean` | yes |
| `report_digest` | `string` | yes |

```json
{
  "$id": "ssot_close_run.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "close": {
      "additionalProperties": true,
      "type": "object"
    },
    "close_id": {
      "type": "string"
    },
    "committed_revision": {
      "type": "integer"
    },
    "diff": {
      "items": {
        "additionalProperties": true,
        "type": "object"
      },
      "type": "array"
    },
    "reclosed": {
      "type": "boolean"
    },
    "replayed": {
      "type": "boolean"
    },
    "report_digest": {
      "type": "string"
    }
  },
  "required": [
    "_meta",
    "close",
    "close_id",
    "report_digest",
    "diff",
    "reclosed",
    "replayed"
  ],
  "title": "ssot close run output",
  "type": "object"
}
```

## `schemas/ssot_intake_confirm.schema.json`

ssot intake confirm output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `applied` | `object` | yes |
| `committed_revision` | `integer` | yes |
| `confirmation_id` | `string` | yes |
| `proposal_id` | `string` | yes |
| `replayed` | `boolean` | yes |

```json
{
  "$id": "ssot_intake_confirm.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "applied": {
      "additionalProperties": true,
      "type": "object"
    },
    "committed_revision": {
      "type": "integer"
    },
    "confirmation_id": {
      "type": "string"
    },
    "proposal_id": {
      "type": "string"
    },
    "replayed": {
      "type": "boolean"
    }
  },
  "required": [
    "_meta",
    "proposal_id",
    "confirmation_id",
    "applied",
    "committed_revision",
    "replayed"
  ],
  "title": "ssot intake confirm output",
  "type": "object"
}
```

## `schemas/ssot_intake_list.schema.json`

ssot intake list output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `dataset_generation` | `string` | yes |
| `dataset_revision` | `integer` | yes |
| `decisions` | `array`[`object`] | yes |

```json
{
  "$id": "ssot_intake_list.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "dataset_generation": {
      "type": "string"
    },
    "dataset_revision": {
      "type": "integer"
    },
    "decisions": {
      "items": {
        "additionalProperties": true,
        "type": "object"
      },
      "type": "array"
    }
  },
  "required": [
    "_meta",
    "dataset_generation",
    "dataset_revision",
    "decisions"
  ],
  "title": "ssot intake list output",
  "type": "object"
}
```

## `schemas/ssot_intake_revise.schema.json`

ssot intake revise output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `application_key` | `string` | yes |
| `committed_revision` | `integer` | yes |
| `expected_generation` | `string` | yes |
| `expected_revision` | `integer` | yes |
| `parent_proposal_id` | `string` | yes |
| `parent_status` | `string` | yes |
| `proposal_id` | `string` | yes |
| `replayed` | `boolean` | yes |

```json
{
  "$id": "ssot_intake_revise.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "application_key": {
      "type": "string"
    },
    "committed_revision": {
      "type": "integer"
    },
    "expected_generation": {
      "type": "string"
    },
    "expected_revision": {
      "type": "integer"
    },
    "parent_proposal_id": {
      "type": "string"
    },
    "parent_status": {
      "type": "string"
    },
    "proposal_id": {
      "type": "string"
    },
    "replayed": {
      "type": "boolean"
    }
  },
  "required": [
    "_meta",
    "proposal_id",
    "parent_proposal_id",
    "parent_status",
    "application_key",
    "expected_generation",
    "expected_revision",
    "committed_revision",
    "replayed"
  ],
  "title": "ssot intake revise output",
  "type": "object"
}
```

## `schemas/ssot_intake_submit.schema.json`

ssot intake submit output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `committed_revision` | `integer` | yes |
| `occurrence_id` | `string` | yes |
| `proposal_id` | `string` | yes |
| `replayed` | `boolean` | yes |
| `source_artifact_id` | `string` | yes |

```json
{
  "$id": "ssot_intake_submit.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "committed_revision": {
      "type": "integer"
    },
    "occurrence_id": {
      "type": "string"
    },
    "proposal_id": {
      "type": "string"
    },
    "replayed": {
      "type": "boolean"
    },
    "source_artifact_id": {
      "type": "string"
    }
  },
  "required": [
    "_meta",
    "proposal_id",
    "source_artifact_id",
    "occurrence_id",
    "committed_revision",
    "replayed"
  ],
  "title": "ssot intake submit output",
  "type": "object"
}
```

## `schemas/ssot_intake_withdraw.schema.json`

ssot intake withdraw output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `committed_revision` | `integer` | yes |
| `confirmation_id` | `string` | yes |
| `proposal_id` | `string` | yes |
| `replayed` | `boolean` | yes |
| `status` | `any` | yes |

```json
{
  "$id": "ssot_intake_withdraw.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "committed_revision": {
      "type": "integer"
    },
    "confirmation_id": {
      "type": "string"
    },
    "proposal_id": {
      "type": "string"
    },
    "replayed": {
      "type": "boolean"
    },
    "status": {
      "const": "rejected"
    }
  },
  "required": [
    "_meta",
    "proposal_id",
    "confirmation_id",
    "status",
    "committed_revision",
    "replayed"
  ],
  "title": "ssot intake withdraw output",
  "type": "object"
}
```

## `schemas/ssot_migrate_build.schema.json`

ssot migrate build --json output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `attempt_id` | `string` | yes |
| `checks` | `object` | yes |
| `cutover_ready` | `any` | yes |
| `dataset_revision` | `any` | yes |
| `generation_status` | `any` | yes |
| `input_count` | `integer` | yes |
| `limitations` | `array`[`string`] | yes |
| `manifest_digest` | `string` | yes |
| `origin_kind` | `any` | yes |
| `phase` | enum(`migration_plan`, `migration_verify`) | yes |
| `status` | enum(`ok`, `already_complete`) | yes |

```json
{
  "$id": "ssot_migrate_build.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "attempt_id": {
      "pattern": "^[a-f0-9]{32}$",
      "type": "string"
    },
    "checks": {
      "additionalProperties": {
        "enum": [
          "passed",
          "not_run",
          "failed"
        ]
      },
      "type": "object"
    },
    "cutover_ready": {
      "const": false
    },
    "dataset_revision": {
      "const": 0
    },
    "generation_status": {
      "const": "inactive"
    },
    "input_count": {
      "minimum": 0,
      "type": "integer"
    },
    "limitations": {
      "items": {
        "type": "string"
      },
      "type": "array"
    },
    "manifest_digest": {
      "pattern": "^sha256:[a-f0-9]{64}$",
      "type": "string"
    },
    "origin_kind": {
      "const": "legacy_current_state"
    },
    "phase": {
      "enum": [
        "migration_plan",
        "migration_verify"
      ]
    },
    "status": {
      "enum": [
        "ok",
        "already_complete"
      ]
    }
  },
  "required": [
    "_meta",
    "status",
    "phase",
    "manifest_digest",
    "input_count",
    "cutover_ready",
    "limitations",
    "generation_status",
    "attempt_id",
    "origin_kind",
    "dataset_revision",
    "checks"
  ],
  "title": "ssot migrate build --json output",
  "type": "object"
}
```

## `schemas/ssot_migrate_plan.schema.json`

ssot migrate plan --json output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `cutover_ready` | `any` | yes |
| `input_count` | `integer` | yes |
| `limitations` | `array`[`string`] | yes |
| `manifest_digest` | `string` | yes |
| `phase` | enum(`migration_plan`, `migration_verify`) | yes |
| `status` | enum(`ok`, `already_complete`) | yes |

```json
{
  "$id": "ssot_migrate_plan.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "cutover_ready": {
      "const": false
    },
    "input_count": {
      "minimum": 0,
      "type": "integer"
    },
    "limitations": {
      "items": {
        "type": "string"
      },
      "type": "array"
    },
    "manifest_digest": {
      "pattern": "^sha256:[a-f0-9]{64}$",
      "type": "string"
    },
    "phase": {
      "enum": [
        "migration_plan",
        "migration_verify"
      ]
    },
    "status": {
      "enum": [
        "ok",
        "already_complete"
      ]
    }
  },
  "required": [
    "_meta",
    "status",
    "phase",
    "manifest_digest",
    "input_count",
    "cutover_ready",
    "limitations"
  ],
  "title": "ssot migrate plan --json output",
  "type": "object"
}
```

## `schemas/ssot_migrate_verify.schema.json`

ssot migrate verify --json output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `attempt_id` | `string` | yes |
| `checks` | `object` | yes |
| `cutover_ready` | `any` | yes |
| `dataset_revision` | `any` | yes |
| `generation_status` | `any` | yes |
| `input_count` | `integer` | yes |
| `limitations` | `array`[`string`] | yes |
| `manifest_digest` | `string` | yes |
| `origin_kind` | `any` | yes |
| `phase` | enum(`migration_plan`, `migration_verify`) | yes |
| `status` | enum(`ok`, `already_complete`) | yes |

```json
{
  "$id": "ssot_migrate_verify.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "attempt_id": {
      "pattern": "^[a-f0-9]{32}$",
      "type": "string"
    },
    "checks": {
      "additionalProperties": {
        "enum": [
          "passed",
          "not_run",
          "failed"
        ]
      },
      "type": "object"
    },
    "cutover_ready": {
      "const": false
    },
    "dataset_revision": {
      "const": 0
    },
    "generation_status": {
      "const": "inactive"
    },
    "input_count": {
      "minimum": 0,
      "type": "integer"
    },
    "limitations": {
      "items": {
        "type": "string"
      },
      "type": "array"
    },
    "manifest_digest": {
      "pattern": "^sha256:[a-f0-9]{64}$",
      "type": "string"
    },
    "origin_kind": {
      "const": "legacy_current_state"
    },
    "phase": {
      "enum": [
        "migration_plan",
        "migration_verify"
      ]
    },
    "status": {
      "enum": [
        "ok",
        "already_complete"
      ]
    }
  },
  "required": [
    "_meta",
    "status",
    "phase",
    "manifest_digest",
    "input_count",
    "cutover_ready",
    "limitations",
    "generation_status",
    "attempt_id",
    "origin_kind",
    "dataset_revision",
    "checks"
  ],
  "title": "ssot migrate verify --json output",
  "type": "object"
}
```

## `schemas/ssot_reconcile_candidates.schema.json`

ssot reconcile candidates output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `allocations` | `array`[`object`] | yes |
| `candidates` | `array`[`object`] | yes |
| `dataset_generation` | `string` | yes |
| `dataset_revision` | `integer` | yes |
| `evidence` | `array`[`object`] | yes |
| `ledger_cash_totals` | `object` | yes |
| `payments` | `array`[`object`] | yes |
| `withdrawals` | `array`[`object`] | yes |

```json
{
  "$id": "ssot_reconcile_candidates.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "allocations": {
      "items": {
        "additionalProperties": true,
        "type": "object"
      },
      "type": "array"
    },
    "candidates": {
      "items": {
        "additionalProperties": true,
        "type": "object"
      },
      "type": "array"
    },
    "dataset_generation": {
      "type": "string"
    },
    "dataset_revision": {
      "type": "integer"
    },
    "evidence": {
      "items": {
        "additionalProperties": true,
        "type": "object"
      },
      "type": "array"
    },
    "ledger_cash_totals": {
      "additionalProperties": true,
      "type": "object"
    },
    "payments": {
      "items": {
        "additionalProperties": true,
        "type": "object"
      },
      "type": "array"
    },
    "withdrawals": {
      "items": {
        "additionalProperties": true,
        "type": "object"
      },
      "type": "array"
    }
  },
  "required": [
    "_meta",
    "dataset_generation",
    "dataset_revision",
    "candidates",
    "evidence",
    "allocations",
    "withdrawals",
    "ledger_cash_totals",
    "payments"
  ],
  "title": "ssot reconcile candidates output",
  "type": "object"
}
```

## `schemas/ssot_reconcile_confirm.schema.json`

ssot reconcile confirm output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `allocation_id` | `string` | yes |
| `currency` | `string` | yes |
| `replayed` | `boolean` | yes |
| `residual` | `string` | yes |
| `status` | `string` | yes |

```json
{
  "$id": "ssot_reconcile_confirm.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "allocation_id": {
      "type": "string"
    },
    "currency": {
      "type": "string"
    },
    "replayed": {
      "type": "boolean"
    },
    "residual": {
      "type": "string"
    },
    "status": {
      "type": "string"
    }
  },
  "required": [
    "_meta",
    "allocation_id",
    "status",
    "residual",
    "currency",
    "replayed"
  ],
  "title": "ssot reconcile confirm output",
  "type": "object"
}
```

## `schemas/ssot_reconcile_submit.schema.json`

ssot reconcile submit output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `evidence_ids` | `array`[`string`] | yes |
| `inserted_count` | `integer` | yes |
| `replayed` | `boolean` | yes |
| `source_artifact_id` | `string` | yes |

```json
{
  "$id": "ssot_reconcile_submit.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "evidence_ids": {
      "items": {
        "type": "string"
      },
      "type": "array"
    },
    "inserted_count": {
      "type": "integer"
    },
    "replayed": {
      "type": "boolean"
    },
    "source_artifact_id": {
      "type": "string"
    }
  },
  "required": [
    "_meta",
    "evidence_ids",
    "source_artifact_id",
    "inserted_count",
    "replayed"
  ],
  "title": "ssot reconcile submit output",
  "type": "object"
}
```

## `schemas/ssot_reconcile_withdraw.schema.json`

ssot reconcile withdraw output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `allocation_id` | `string` | yes |
| `replayed` | `boolean` | yes |
| `status` | `string` | yes |
| `withdrawal_id` | `string` | yes |

```json
{
  "$id": "ssot_reconcile_withdraw.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "allocation_id": {
      "type": "string"
    },
    "replayed": {
      "type": "boolean"
    },
    "status": {
      "type": "string"
    },
    "withdrawal_id": {
      "type": "string"
    }
  },
  "required": [
    "_meta",
    "allocation_id",
    "withdrawal_id",
    "status",
    "replayed"
  ],
  "title": "ssot reconcile withdraw output",
  "type": "object"
}
```

## `schemas/status.schema.json`

status --json output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `actionable` | `boolean` | yes |
| `data_directory` | `object` | yes |
| `detailed_stats` | `object` | no |
| `detailed_stats_warning` | `string` \| `null` | no |
| `health` | `object` | yes |
| `last_import` | `object` | yes |
| `next_steps` | `array`[`object`] | yes |
| `rules_file` | `object` | yes |
| `signals` | `object` | yes |
| `tagging` | `object` | yes |
| `terminology` | `object` | yes |
| `transactions` | `object` | yes |

```json
{
  "$defs": {
    "tagging_review_terms": {
      "additionalProperties": {
        "type": "string"
      },
      "description": "Canonical tagging/review terminology for this JSON contract.",
      "properties": {
        "needs_review": {
          "description": "The explicit row flag needs_review == 1, not every row shown by review.",
          "type": "string"
        },
        "rule_matched": {
          "description": "A transaction with rule-derived output: non-empty tags_rule or non-empty category_rule.",
          "type": "string"
        },
        "suggestable_untagged": {
          "description": "An untagged transaction eligible for rules suggest after excluding confirmed internal transfer pairs.",
          "type": "string"
        },
        "uncategorized": {
          "description": "A transaction whose category_final is the fallback category 미분류.",
          "type": "string"
        },
        "untagged": {
          "description": "A transaction whose tags_final is null or an empty tag array.",
          "type": "string"
        }
      },
      "type": "object"
    }
  },
  "$id": "status.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "actionable": {
      "type": "boolean"
    },
    "data_directory": {
      "additionalProperties": true,
      "properties": {
        "path": {
          "type": "string"
        },
        "source": {
          "type": "string"
        }
      },
      "required": [
        "path",
        "source"
      ],
      "type": "object"
    },
    "detailed_stats": {
      "additionalProperties": true,
      "type": "object"
    },
    "detailed_stats_warning": {
      "type": [
        "string",
        "null"
      ]
    },
    "health": {
      "additionalProperties": true,
      "properties": {
        "reasons": {
          "items": {
            "type": "string"
          },
          "type": "array"
        },
        "status": {
          "enum": [
            "ok",
            "warning",
            "critical"
          ],
          "type": "string"
        }
      },
      "required": [
        "status",
        "reasons"
      ],
      "type": "object"
    },
    "last_import": {
      "additionalProperties": true,
      "properties": {
        "file_id": {
          "type": [
            "string",
            "null"
          ]
        },
        "imported_at": {
          "type": [
            "string",
            "null"
          ]
        }
      },
      "required": [
        "imported_at",
        "file_id"
      ],
      "type": "object"
    },
    "next_steps": {
      "items": {
        "additionalProperties": true,
        "properties": {
          "command": {
            "type": "string"
          },
          "message": {
            "type": "string"
          },
          "signal": {
            "type": "string"
          }
        },
        "required": [
          "signal",
          "message",
          "command"
        ],
        "type": "object"
      },
      "type": "array"
    },
    "rules_file": {
      "additionalProperties": true,
      "properties": {
        "exists": {
          "type": "boolean"
        },
        "modified_at": {
          "type": [
            "string",
            "null"
          ]
        },
        "path": {
          "type": [
            "string",
            "null"
          ]
        }
      },
      "required": [
        "path",
        "exists",
        "modified_at"
      ],
      "type": "object"
    },
    "signals": {
      "additionalProperties": true,
      "properties": {
        "detailed_requested": {
          "type": "boolean"
        },
        "filters_applied": {
          "type": "integer"
        },
        "rules_file_exists": {
          "type": "boolean"
        },
        "tagging_rate": {
          "type": "number"
        },
        "untagged_count": {
          "type": "integer"
        }
      },
      "required": [
        "rules_file_exists",
        "tagging_rate",
        "untagged_count",
        "filters_applied",
        "detailed_requested"
      ],
      "type": "object"
    },
    "tagging": {
      "additionalProperties": true,
      "properties": {
        "suggestable_tagged_count": {
          "type": "integer"
        },
        "suggestable_tagging_rate": {
          "type": "number"
        },
        "suggestable_transaction_count": {
          "type": "integer"
        },
        "suggestable_untagged_count": {
          "type": "integer"
        },
        "tagged_count": {
          "type": "integer"
        },
        "tagging_rate": {
          "type": "number"
        },
        "transfer_candidate_count": {
          "type": "integer"
        },
        "transfer_excluded_count": {
          "type": "integer"
        },
        "transfer_excluded_untagged_count": {
          "type": "integer"
        },
        "transfer_exclusions": {
          "additionalProperties": true,
          "properties": {
            "candidate_count": {
              "type": "integer"
            },
            "confirmed_count": {
              "type": "integer"
            },
            "definition": {
              "type": "string"
            },
            "excluded_count": {
              "type": "integer"
            },
            "excluded_untagged_count": {
              "type": "integer"
            },
            "unconfirmed_candidate_count": {
              "type": "integer"
            }
          },
          "required": [
            "excluded_count",
            "confirmed_count",
            "candidate_count",
            "unconfirmed_candidate_count",
            "excluded_untagged_count",
            "definition"
          ],
          "type": "object"
        },
        "unconfirmed_transfer_candidate_count": {
          "type": "integer"
        },
        "untagged_count": {
          "type": "integer"
        },
        "untagged_merchants": {
          "items": {
            "additionalProperties": true,
            "properties": {
              "count": {
                "type": "integer"
              },
              "merchant": {
                "type": "string"
              }
            },
            "required": [
              "merchant",
              "count"
            ],
            "type": "object"
          },
          "type": "array"
        },
        "untagged_merchants_total": {
          "type": "integer"
        }
      },
      "required": [
        "tagged_count",
        "untagged_count",
        "tagging_rate",
        "suggestable_transaction_count",
        "suggestable_tagged_count",
        "suggestable_untagged_count",
        "suggestable_tagging_rate",
        "transfer_candidate_count",
        "transfer_excluded_count",
        "transfer_excluded_untagged_count",
        "unconfirmed_transfer_candidate_count",
        "transfer_exclusions",
        "untagged_merchants",
        "untagged_merchants_total"
      ],
      "type": "object"
    },
    "terminology": {
      "additionalProperties": true,
      "properties": {
        "definitions": {
          "additionalProperties": true,
          "properties": {
            "needs_review": {
              "type": "string"
            },
            "rule_matched": {
              "type": "string"
            },
            "suggestable_untagged": {
              "type": "string"
            },
            "uncategorized": {
              "type": "string"
            },
            "untagged": {
              "type": "string"
            }
          },
          "required": [
            "untagged",
            "uncategorized",
            "rule_matched",
            "needs_review",
            "suggestable_untagged"
          ],
          "type": "object"
        },
        "reference": {
          "type": "string"
        },
        "schema": {
          "type": "string"
        }
      },
      "required": [
        "reference",
        "schema",
        "definitions"
      ],
      "type": "object"
    },
    "transactions": {
      "additionalProperties": true,
      "properties": {
        "count": {
          "type": "integer"
        },
        "date_range": {
          "additionalProperties": true,
          "properties": {
            "end": {
              "type": [
                "string",
                "null"
              ]
            },
            "start": {
              "type": [
                "string",
                "null"
              ]
            }
          },
          "required": [
            "start",
            "end"
          ],
          "type": "object"
        },
        "partition_count": {
          "type": "integer"
        }
      },
      "required": [
        "count",
        "date_range",
        "partition_count"
      ],
      "type": "object"
    }
  },
  "required": [
    "_meta",
    "data_directory",
    "transactions",
    "last_import",
    "terminology",
    "tagging",
    "rules_file",
    "health",
    "actionable",
    "signals",
    "next_steps"
  ],
  "title": "status --json output",
  "type": "object",
  "x-finjuice-field-definitions": {
    "health.reasons.low_untagged_remainder": "non-alarming health cue when suggestable_untagged is small and coverage is >= 99%",
    "tagging.suggestable_untagged_count": "suggestable_untagged",
    "tagging.transfer_excluded_untagged_count": "untagged rows excluded from suggestable_untagged because they are confirmed transfer pairs",
    "tagging.untagged_count": "untagged",
    "terminology.reference": "schema documentation link for tagging/review terms"
  }
}
```

## `schemas/tag.schema.json`

tag --json output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `backup_delivery` | `$ref` ssot_backup_deliver_run.schema.json#/$defs/projection | no |
| `coverage_pct` | `number` | no |
| `dry_run` | `boolean` | no |
| `operation` | `string` | no |
| `partition` | `object` \| `null` | no |
| `row_hash` | `string` | no |
| `status` | `string` | yes |
| `tagged` | `integer` | no |
| `total` | `integer` | no |
| `transaction` | `object` | no |
| `untagged` | `integer` | no |
| `updated` | `boolean` | no |

```json
{
  "$id": "tag.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "backup_delivery": {
      "$ref": "ssot_backup_deliver_run.schema.json#/$defs/projection"
    },
    "coverage_pct": {
      "type": "number"
    },
    "dry_run": {
      "type": "boolean"
    },
    "operation": {
      "type": "string"
    },
    "partition": {
      "type": [
        "object",
        "null"
      ]
    },
    "row_hash": {
      "type": "string"
    },
    "status": {
      "type": "string"
    },
    "tagged": {
      "type": "integer"
    },
    "total": {
      "type": "integer"
    },
    "transaction": {
      "additionalProperties": true,
      "type": "object"
    },
    "untagged": {
      "type": "integer"
    },
    "updated": {
      "type": "boolean"
    }
  },
  "required": [
    "_meta",
    "status"
  ],
  "title": "tag --json output",
  "type": "object"
}
```

## `schemas/template_list.schema.json`

template list --json output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `templates` | `array`[`object`] | yes |

```json
{
  "$id": "template_list.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "templates": {
      "items": {
        "additionalProperties": true,
        "properties": {
          "description": {
            "type": "string"
          },
          "name": {
            "type": "string"
          },
          "params": {
            "additionalProperties": true,
            "type": "object"
          }
        },
        "required": [
          "name",
          "description",
          "params"
        ],
        "type": "object"
      },
      "type": "array"
    }
  },
  "required": [
    "_meta",
    "templates"
  ],
  "title": "template list --json output",
  "type": "object"
}
```

## `schemas/template_run.schema.json`

template run --json output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `pagination` | `$ref` _pagination.schema.json | yes |
| `row_count` | `integer` | yes |
| `rows` | `array`[`object`] | yes |
| `template_name` | `string` | yes |

```json
{
  "$id": "template_run.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "pagination": {
      "$ref": "_pagination.schema.json"
    },
    "row_count": {
      "type": "integer"
    },
    "rows": {
      "items": {
        "additionalProperties": true,
        "type": "object"
      },
      "type": "array"
    },
    "template_name": {
      "type": "string"
    }
  },
  "required": [
    "_meta",
    "template_name",
    "row_count",
    "rows",
    "pagination"
  ],
  "title": "template run --json output",
  "type": "object"
}
```

## `schemas/template_show.schema.json`

template show --json output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `description` | `string` | yes |
| `name` | `string` | yes |
| `parameters` | `object` | yes |
| `sql` | `string` | yes |

```json
{
  "$id": "template_show.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "description": {
      "type": "string"
    },
    "name": {
      "type": "string"
    },
    "parameters": {
      "additionalProperties": true,
      "type": "object"
    },
    "sql": {
      "type": "string"
    }
  },
  "required": [
    "_meta",
    "name",
    "description",
    "parameters",
    "sql"
  ],
  "title": "template show --json output",
  "type": "object"
}
```

## `schemas/transfer.schema.json`

transfer --json output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `candidate_rows` | `integer` | yes |
| `confirmed_transfer_rows` | `integer` | yes |
| `pairs_found` | `integer` | yes |
| `pairs_linked` | `integer` | yes |
| `status` | `string` | yes |
| `unconfirmed_candidate_rows` | `integer` | yes |

```json
{
  "$id": "transfer.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "candidate_rows": {
      "type": "integer"
    },
    "confirmed_transfer_rows": {
      "type": "integer"
    },
    "pairs_found": {
      "type": "integer"
    },
    "pairs_linked": {
      "type": "integer"
    },
    "status": {
      "type": "string"
    },
    "unconfirmed_candidate_rows": {
      "type": "integer"
    }
  },
  "required": [
    "_meta",
    "status",
    "candidate_rows",
    "pairs_found",
    "pairs_linked",
    "confirmed_transfer_rows",
    "unconfirmed_candidate_rows"
  ],
  "title": "transfer --json output",
  "type": "object"
}
```

## `schemas/validate.schema.json`

validate --json output

| Field | Type | Required |
|-------|------|----------|
| `invalid_count` | `integer` | yes |
| `partitions_checked` | `integer` | yes |
| `results` | `array`[`object`] | yes |
| `valid` | `boolean` | yes |
| `valid_count` | `integer` | yes |

```json
{
  "$id": "validate.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "invalid_count": {
      "type": "integer"
    },
    "partitions_checked": {
      "type": "integer"
    },
    "results": {
      "items": {
        "additionalProperties": true,
        "properties": {
          "compatibility_state": {
            "type": "string"
          },
          "detected_version": {
            "type": [
              "integer",
              "null"
            ]
          },
          "errors": {
            "items": {
              "type": "string"
            },
            "type": "array"
          },
          "path": {
            "type": "string"
          },
          "valid": {
            "type": "boolean"
          }
        },
        "required": [
          "valid",
          "errors",
          "detected_version",
          "compatibility_state",
          "path"
        ],
        "type": "object"
      },
      "type": "array"
    },
    "valid": {
      "type": "boolean"
    },
    "valid_count": {
      "type": "integer"
    }
  },
  "required": [
    "valid",
    "partitions_checked",
    "valid_count",
    "invalid_count",
    "results"
  ],
  "title": "validate --json output",
  "type": "object"
}
```

## `schemas/version.schema.json`

finjuice version output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `finjuice_version` | `string` | yes |
| `schema_version` | `integer` | yes |

```json
{
  "$id": "version.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "finjuice_version": {
      "description": "Installed finjuice software version",
      "type": "string"
    },
    "schema_version": {
      "description": "Data schema version number",
      "type": "integer"
    }
  },
  "required": [
    "_meta",
    "finjuice_version",
    "schema_version"
  ],
  "title": "finjuice version output",
  "type": "object"
}
```
