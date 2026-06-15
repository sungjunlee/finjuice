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
| `schemas/budget_edit.schema.json` | budget edit --json output | `path`, `changes`, `monthly_budget` |
| `schemas/budget_status.schema.json` | budget status --json output | `month`, `goals_file`, `summary`, `categories`, `health`, `actionable`, `signals`, `review`, `next_steps` |
| `schemas/budget_validate.schema.json` | budget validate --json output | `status`, `path`, `problems` |
| `schemas/checkup.schema.json` | checkup --json output | `summary`, `actionable`, `warnings`, `next_actions`, `domains` |
| `schemas/context.schema.json` | context --json output | `journals`, `status_snapshot`, `active_goals`, `financial_metadata`, `rule_notes`, `top_patterns` |
| `schemas/doctor.schema.json` | doctor --json output | `checks`, `summary`, `missing_extras`, `install_hint` |
| `schemas/explain.schema.json` | explain --json output | `query`, `date_filter` |
| `schemas/export.schema.json` | export --json output | - |
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
| `schemas/refresh.schema.json` | refresh --json output | `command`, `steps` |
| `schemas/review.schema.json` | review --json output | `transactions`, `total_count`, `filters`, `month`, `health`, `actionable`, `signals`, `rule_notes`, `next_steps`, `pagination` |
| `schemas/rules_add.schema.json` | rules add --json output | `action`, `rule`, `validation` |
| `schemas/rules_export.schema.json` | rules export --json output | `rule_count`, `rules` |
| `schemas/rules_gaps.schema.json` | rules gaps --json output | `summary`, `critical_gaps`, `mismatches`, `simulations` |
| `schemas/rules_list.schema.json` | rules list --json output | `rule_count`, `rules` |
| `schemas/rules_remove.schema.json` | rules remove --json output | `action`, `rule_name` |
| `schemas/rules_suggest.schema.json` | rules suggest --json output | - |
| `schemas/rules_test.schema.json` | rules test --json output | `rule_name`, `scope`, `match_count`, `sample`, `monthly_distribution`, `cross_tags_top` |
| `schemas/rules_validate.schema.json` | rules validate --json output | `status`, `total_rules`, `errors`, `warnings`, `passed`, `problems` |
| `schemas/show.schema.json` | show --json output | `rows`, `row_count`, `total_matches`, `pagination` |
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
  "description": "automation run --json output. The raw and redacted privacy profiles include data_dir and merchant_pressure samples; compact replaces those samples with counts.",
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
                "type": "number"
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
              "over"
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
                "over"
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
    }
  },
  "required": [
    "_meta",
    "month",
    "goals_file",
    "summary",
    "categories",
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
| `path` | `string` | yes |
| `problems` | `array`[`object`] | yes |
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
    "path": {
      "type": "string"
    },
    "problems": {
      "items": {
        "additionalProperties": true,
        "type": "object"
      },
      "type": "array"
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
| `active_goals` | `array`[`any`] | yes |
| `financial_metadata` | `object` | yes |
| `journals` | `array`[`object`] | yes |
| `rule_notes` | `array`[`object`] | yes |
| `status_snapshot` | `object` | yes |
| `top_patterns` | `array`[`object`] | yes |

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
      "type": "array"
    },
    "financial_metadata": {
      "additionalProperties": true,
      "type": "object"
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
      "type": "array"
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

## `schemas/history.schema.json`

history --json output

| Field | Type | Required |
|-------|------|----------|
| `_meta` | `$ref` _meta.schema.json | yes |
| `count` | `integer` | yes |
| `records` | `array`[`object`] | yes |

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
          "file_id": {
            "type": "string"
          },
          "imported_at": {
            "type": "string"
          },
          "imported_from": {
            "type": [
              "string",
              "null"
            ]
          },
          "original_filename": {
            "type": [
              "string",
              "null"
            ]
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
  "description": "index --json output. The raw privacy profile preserves the full catalog shape and only includes paths when --include-paths is requested. Redacted and compact profiles suppress resolved workspace and collection paths; compact also drops operational command and note detail.",
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "collections": {
      "items": {
        "additionalProperties": true,
        "properties": {
          "count": {
            "type": [
              "integer",
              "null"
            ]
          },
          "count_label": {
            "type": "string"
          },
          "exists": {
            "type": "boolean"
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
          "status": {
            "type": "string"
          },
          "type": {
            "type": "string"
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
| `preview` | `object` | no |
| `source` | `string` | yes |
| `summary` | `object` | no |

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
| `created` | `boolean` | yes |
| `message` | `string` | yes |
| `path` | `string` | yes |

```json
{
  "$id": "networth_init.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": true,
  "properties": {
    "_meta": {
      "$ref": "_meta.schema.json"
    },
    "created": {
      "type": "boolean"
    },
    "message": {
      "type": "string"
    },
    "path": {
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
| `errors` | `integer` | yes |
| `exists` | `boolean` | yes |
| `liabilities` | `integer` | yes |
| `manual_assets` | `integer` | yes |
| `path` | `string` | yes |
| `problems` | `array`[`object`] | yes |
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
      "type": "string"
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
        "problems"
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
    }
  },
  "required": [
    "_meta",
    "action",
    "rule_name"
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
| `rules_file` | `string` | no |
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
      "type": "string"
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
          "type": "string"
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
| `coverage_pct` | `number` | no |
| `dry_run` | `boolean` | no |
| `operation` | `string` | no |
| `partition` | `object` | no |
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
      "additionalProperties": true,
      "type": "object"
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
