# SSOT 기능 수용 근거

2026-09-15 사용자가 승인한 [기능 완료 계약](../../goals/finjuice-ssot.md)에 따른 기록이다. 원래 #355 및 #425~#448의 기능 범위를 유지한다. 실제 가족 정보·현장 신규 기록·특정 장비의 키 복구·미래 예약 실행은 별도 운영 후속이다.

## 통합 상태

**최종 통합 진행 중이다.** #538의 목표 변경은 main에 머지됐다. #532의 최종 입력 연동 소스는 `d5f84c8`이며, 마지막 교차 리뷰와 전체 CI 결과를 확인한 뒤 머지해야 한다. 아래 정적 AC 대조와 부분 실행 결과만으로 전체 완료를 선언하지 않는다.

## 원래 기능 요구와 검증 경계

표의 테스트는 저장소의 합성 fixture와 assertion을 직접 대조한 근거다. 파일명은 `tests/` 아래 경로이며, 최종 실행 결과는 다음 절에서 별도로 기록한다.

| 범위 이슈 | 기능 요구 | 코드·테스트 근거 |
|---|---|---|
| #425 | M1~M5 기능과 운영 수용 구분 | 이 표 전체와 `goals/finjuice-ssot.md`. 이슈 CLOSED 개수를 기능 증거로 대신하지 않는다. |
| #426, #430 | 단일 정본·보존 이전·쓰기 통제·설치 검증 계약 | ADR-0014, `ssot-migration-recovery-contract.md`. 첫 이전에서 계좌 병합·소유자 추정·재분류를 하지 않는다. |
| #431, #432 | 전체 사본·참조·안전한 경로·원본 변경·공간 부족·재시도 | `pipeline/test_backup.py`: `test_create_verify_restore_full_roots`, `test_source_content_change_during_capture`, `test_required_root_missing_is_never_skipped`, `test_insufficient_space_and_enospc`, `test_malicious_portable_paths`, `test_create_retry_already_complete_leaves_source`. 기존 장비 밖 복원 기록은 새 실행으로 재표시하지 않는다. |
| #427, #433 | 불변 원본·정확 금액·영구 ID·FK·schema 실패 보존 | `pipeline/test_sqlite_objects.py`, `test_sqlite_values_and_ids.py`, `test_sqlite_repository.py`. object digest 재사용, float 거부·정확 lexical 값, FK/참조 손상, upgrade 실패 시 원본 보존 assertion. |
| #434 | 원자적 이력·멱등성·stale revision·프로세스 중단·writer 경합 | `pipeline/test_sqlite_mutations.py`: 수동 정정 replay/noop, config/audit/receipt 실패 rollback, process termination 후 재시도, 동일 revision의 두 writer 중 정확히 하나 commit. |
| #435, #438 | 필드·수동 상태·원문·미지원 자료·격리·재이전 보존 | `migration/test_migration_integration.py::test_mixed_capture_cli_preserves_independent_expected_values`, `test_cross_file_overview_preservation_seam`; `migration/test_workflow.py::test_build_verify_and_retry_preserve_source`; `migration/test_attempt_crash.py`. 독립 기대값, 두 빌드 의미 동일성, 입력/원본 bytes 불변, 중단·실패 재시도를 검사한다. |
| #436 | human/JSON·DuckDB·수동 marker·동일 revision 파생·stale 식별 | `pipeline/test_sqlite_query_explain.py`, `test_sqlite_read_compat.py`; `cli/commands/test_repository_show.py`, `test_repository_export.py`. CSV baseline 결과, marker 보존, 보고서 bytes/셀, revision 고정 및 파생 파일 편집 후 정본 불변을 비교한다. |
| #437 | snapshot·config/원본 참조 폐쇄·격리 복원·재백업·전송 실패 | `pipeline/test_sqlite_backup_config_closure.py::test_config_history_and_objects_are_pinned_before_live_head_mutation`, `test_sqlite_backup_verify.py`; `test_backup_delivery.py::test_mutation_transfer_oserror_preserves_committed_receipt`. 전송 실패를 이미 commit된 기록의 실패로 바꾸지 않는다. |
| #439 | 구 writer 차단·동일 revision 소비자·수동 상태 유지 | `cli/commands/test_repository_mutation_fences.py`, `test_remaining_legacy_writer_fences.py`; `pipeline/test_consumer_bundle.py::test_bundle_uses_pinned_snapshot_and_ignores_poisoned_live_csv`. 과거 실제 서비스 namespace 차단·소비자 실행 근거는 별도 운영 기록으로 보존한다. |
| #428, #440 | 전환 이후 변경을 버리지 않는 복구 기능 | `pipeline/test_inactive_restore.py::test_restored_manual_edit_read_replay_and_rebackup_preserve_source`, `test_backup_delivery.py::test_destination_restore_mutate_rebackup`. 실제 합성 정정→revision 증가→재시도→재백업→재복원 rows/audit 및 원본 불변을 검사한다. 정상 실사용 신규 기록의 현장 실증은 별도다. |
| #441 | 예약·실패/재시도 상태·보호된 보존·복원 연습·RPO/RTO/runbook | `test_backup_ops_structure.py`, `pipeline/test_backup_delivery.py::test_transfer_shared_lease_blocks_prune`. 최신 정상 사본·고정 이전 기준선 보호와 transfer 중 prune 차단. 신규 금융 상태 복원 주장은 바로 위 inactive restore 검사와 함께 판단한다. |
| #429, #442 | 계좌 안정 ID·미확인/기간별 공동 소유·정정·재임포트 | `pipeline/test_account_bindings.py::test_confirmed_binding_preserves_stable_account_across_different_xlsx_and_restore`, `test_account_decisions.py::test_ownership_cli_exact_correction_replay_import_and_restore`. 정확 지분·미확인 잔여·before/after 및 복원 후 결과를 검사한다. |
| #443 | 부분/과거 자료·요약/상세·수동 중복·평가/현금흐름·근거 | `pipeline/test_canonical_assets.py::test_canonical_assets_scope_relations_flow_correction_and_capture_restore`, `test_asset_unknown_ownership_fx_pending_and_immutable_relation_correction`. 제외 근거·미확정 소유권/환율·정정 이력·복원 후 합계를 확인한다. |
| #444 | 입력 증빙·확인·일회 정정·재전송·XLSX 이후 유지 | `pipeline/test_intake_asset_observation.py::test_confirm_dedup_xlsx_preservation_and_actual_restore`, `test_retransmission_cannot_undo_explicit_meaning_correction`; `test_intake_lifecycle.py::test_revision_resolves_stale_uncertainty_corrects_applied_fact_and_restores`. human/JSON, 원본 보존, stale/불확실성, 변경 대상·유형 보존을 검사한다. |
| #445 | 가족 입력→확인/정정→재임포트→조회→복원 | 위 #442~#444의 통합 시나리오와 자산/소유권 복원 assertion. 합성 수용이며 실제 가족 사실의 확인으로 표시하지 않는다. |
| #355, #446 | N:M·할부·환불·부분/미매칭·잔차·확정/철회·중복 방지 | `pipeline/test_canonical_reconcile.py`: `test_actual_installment_confirm_withdraw_retry_and_capture_restore`, `test_many_orders_refund_partial_and_long_exact_amounts`, `test_explicit_many_to_many_and_same_evidence_new_retry_key`. 원거래·현금총액과 복원 결과를 보존한다. 함수명의 actual은 실제 쓰기 경로이며 자료는 합성이다. |
| #447 | revision 마감·늦은 입력·재개방·재마감·재생성·미확인 항목 | `pipeline/test_canonical_close.py::test_close_late_data_reopen_reclose_diff_and_restore`; `test_canonical_close_integrity.py`의 후속 이체 변경, 가족 자산 확정 범위, 미대사 구매 검사를 통해 과거 마감 의미를 유지한다. |
| #448 | 추가 입력 경로의 전체/부분/과거·출처 중첩·실패/재시도 | `pipeline/test_canonical_statement_json.py`; `cli/commands/test_repository_statement_ingest.py`. 일반 ingest/refresh, 배치 미리보기, 실제 가져오기 시각, 보류 표시, 동일 문서 무변경 재수집, 계좌 확인 후 재처리, 수동 정정·원본·정확 금액·복원을 검사한다. `pipeline/test_sqlite_source_lookup.py`는 XLSX 전용 archive 선택의 JSON 거부가 구조화된 오류이며 정본을 바꾸지 않음을 검사한다. |

## 실행 증거

- `b1bd806`: adapter/CLI/구조 회귀 고유 35건, 변경 소스 Ruff/mypy·complexity·보안 검사 통과. 별도 wheel 설치 환경의 입력 연동·가족·대사·마감 62건 통과(98.52초). 테스트에서 로드한 모듈의 설치본 경로와 source/wheel/installed 파일 747개의 bytes 일치를 확인했다.
- `d5f84c8`: 교차 리뷰의 인접 표시/오류 처리 3건을 수정했다. 입력/history 32건 및 source lookup 7건 통과. 변경 소스 Ruff/mypy·complexity와 commit hooks 통과. 마지막 수정은 입력 표시·summary·archive 오류 경계이며 가족·대사·마감 구현은 변경하지 않았다.
- 후속 교차 리뷰에서 위 3건의 해결을 확인했다. 추가로 제안된 `summary.pending`의 고유 ID 집계는 적용하지 않았다. 이 summary는 현재 배치의 파일별 입력 레코드 처리 통계이며, 재관측/건너뛴 파일의 보류 레코드도 포함한다. 고유한 미확정 거래나 필요한 사용자 결정의 수를 뜻하지 않는다. `updated` 역시 파일별 재사용 레코드 합계다. 실제 경제적 거래의 중복 방지는 별도의 거래 수·원장 불변 assertion으로 검증한다.
- 최종 `d5f84c8` wheel 설치본에서 영향받는 39건이 통과했다(20.20초). 로드된 모듈 546개가 설치본을 사용하고 source/wheel/installed 파일 747개가 일치함을 확인했다. 전체 CI·머지 결과는 아직 수집 중이다. 앞 커밋의 통과 결과를 최종 전체 CI 통과로 표시하지 않는다.
- 최종 Public PR Gate [34947871188](https://github.com/sungjunlee/finjuice/actions/runs/34947871188)에서 `uv run mypy src/` 614개 소스 및 전체 Ruff 검사가 통과했다. 전체 pytest 실행은 [34947871097](https://github.com/sungjunlee/finjuice/actions/runs/34947871097)에서 계속 수집한다.
- 첫 설치 smoke 스크립트는 빈 데이터 폴더의 `status --json`을 종료 코드 0으로 잘못 기대했다. 올바른 계약인 구조화된 `NO_DATA`/종료 코드 4로 검증기만 수정했고 제품 코드는 바꾸지 않았다. 원래 실패 기록도 보존했다.

비공개 실행 저장소에는 각 artifact hash, 모듈 경로, 시험 로그 및 기존 보존/운영 증거를 보존한다. 공개 문서에는 금융 원본·금액·계좌/소유자·인증정보·상세 호스트 경로를 넣지 않는다.

## 별도 운영 후속

- 실제 가족 소유권·동일 계좌 관계와 실제 주문·결제·할부·환불 사실 확인.
- 정상 업무의 신규 기록을 포함한 현장 백업/복원 실증.
- 특정 Mac/키 동시 손실, 아직 도래하지 않은 월간 예약 실행, 장기 RPO/RTO와 알림 전달 관측.

이 항목은 열린 운영 AC로 남긴다. 기능 완료를 위해 실제 사실을 추정하거나 운영 원장에 테스트 거래를 만들지 않는다. 최종 기능 완료와 모든 실운영 수용 완료는 서로 다른 판정이다.
