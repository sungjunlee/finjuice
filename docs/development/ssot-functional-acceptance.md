# SSOT 기능 수용 근거

2026-09-15 사용자가 승인한 [기능 완료 계약](../../goals/finjuice-ssot.md)에 따른 기록이다. 원래 #355 및 #425~#448의 기능 범위를 유지한다. 실제 가족 정보·현장 신규 기록·특정 장비의 키 복구·미래 예약 실행은 별도 운영 후속이다.

## 통합 상태

**최종 통합 진행 중이다.** #538의 목표 변경은 main에 머지됐다. #532의 최종 입력 연동 소스는 `7786045`다. 입력·진단 통합과 저장소 오류 경계의 설치본 검증을 완료했고, 교차 리뷰와 후속 호환성·표시 통합 검토를 마쳤고 전체 CI·머지를 기다린다. 아래 AC 대조를 전체 통합 완료 선언으로 대신하지 않는다.

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
| #448 | 추가 입력 경로의 전체/부분/과거·출처 중첩·실패/재시도 | `pipeline/test_canonical_statement_json.py`; `cli/commands/test_repository_statement_ingest.py`, `test_repository_mixed_ingest.py`, `test_repository_statement_inventory.py`. Doctor/checkup/automation의 JSON 신규·완료·계좌 확인 후 재처리·잘못된 금액/ID·fast 모드와 캡처 bytes/revision 고정도 검증한다. JSON→XLSX·XLSX→XLSX 중첩 및 동일 XLSX 반복 배치의 preview/write counts 일치와 read-only·재시도를 포함하며 일반 ingest/refresh, 배치 미리보기, 실제 가져오기 시각, 보류 표시, 동일 문서 무변경 재수집, 계좌 확인 후 재처리, 수동 정정·원본·정확 금액·복원을 검사한다. `pipeline/test_sqlite_source_lookup.py`는 XLSX 전용 archive 선택의 JSON 거부가 구조화된 오류이며 정본을 바꾸지 않음을 검사한다. |

## 실행 증거

- 최종 `7786045`: 혼합 inbox는 확정 JSON을 먼저 처리해 파일명에 따른 중복 생성을 제거했다. 변경 전 날짜·시각·UTC 3건 모두 중복 생성 실패를 재현했고, 수정 후 소스40건·실제 Python3.10 신규3건 PASS. 설치본40건 PASS(10.18초), 모듈547개 설치 경로·source/wheel/installed748파일 일치 및 CLI smoke PASS. Grok4.6 한정 교차 리뷰 no_findings와 해당 리뷰 thread 해결을 확인했다.

- 앞 단계 `378ecd5`: Python3.10에서도 UTC `Z`를 overlap 직전에 정규화하며 원문을 유지한다. Refresh human 출력도 기존 pending 건수 안내를 재사용한다. 실제 Python3.10에서 UTC·혼합 입력·refresh human/JSON25건 PASS(7.37초), Python3.13 설치본 관련68건 PASS(12.01초), 모듈547개 설치 경로·source/wheel/installed748파일 일치 및 CLI human/JSON smoke PASS. 시각 비교 변경의 Grok4.6 교차 리뷰 no_findings와 후속 두 경계의 담당·통합 검토를 완료했다.
- 앞 단계 `383b446`: 시각이 있는 JSON→XLSX 혼합 입력에서 중복 생성 회귀를 확인하고 수정했다. 관측 기준일은 보존하고 중복 판정만 원래 발생 타임스탬프를 사용하므로 기존 JSON 기록도 재작성하지 않는다. 미리보기/실제 처리의 날짜·시각 혼합6건 및 저장된 identity/미리보기의 날짜·분·초·소수초·UTC 일치5건 PASS. 설치본 JSON·XLSX·혼합 입력65건 PASS(59.08초), 모듈547개 설치 경로·source/wheel/installed748파일 일치와 CLI human/JSON smoke PASS.
- 앞 단계 `21b5cc9`: 재귀 파서 실패도 기존 안전한 캡처 실패로 정규화한다. 작은 합성 입력·예외 주입의 단위1건과 진단4경로 회귀를 추가했고, 설치본 캡처·진단29건 PASS(20.68초), 모듈528개 설치 경로·source/wheel/installed748파일 일치 및 CLI human/JSON smoke PASS. 앞 단계 교차 리뷰 뒤 변경은 명시적 예외1개 추가이며 담당·통합 검토 및 영향 회귀로 확인했다.
- 앞 단계 `3414a8d`: JSON 캡처는 descriptor 초기 크기와 읽는 도중 증가를 64MiB로 제한하며 디코딩 전에 거부한다. 단독 capture4건과 모든 진단 경로4건, 기존 백업 읽기 검증을 포함한 설치본104건 PASS(20.93초), 모듈548개 설치 경로·source/wheel/installed748파일 일치 및 CLI human/JSON smoke PASS. 제한 변경 교차 리뷰에서 새 P1/P2는 없었고, 단독 실행의 순환 import도 최소 이동으로 해결했다.
- 앞 단계 `a7cdb48`: DB 누락·손상·미지원 버전의 기본 화면 안내와 원본 불변 회귀3건, 저장소22건 PASS. 설치 환경에서 진단·입력·저장소 오류 경계72건 PASS(22.42초), 모듈548개의 설치 경로·source/wheel/installed748파일 일치와 CLI human/JSON smoke를 확인했다. 공통 저장소 오류를 안내로 처리하고 SQLite 헤더 읽기 실패도 typed integrity 오류로 변환한다. 마지막 교차 리뷰의 오류 분류·업그레이드 안내 의견2건은 비차단 개선으로 판정했다. 실제 코드는 손상을 확정하거나 자동 복구하지 않으며, 버전 오류는 타 애플리케이션 DB도 포함해 일률적인 업그레이드 안내가 맞지 않는다.
- 앞 단계 `250d35a`: 설치 환경에서 변경된 진단·입력·오류 경계 관련 47건 PASS(21.71초). 로드 모듈548개의 설치 경로와 source/wheel/installed748파일 일치 및 CLI human/JSON smoke를 확인했다. `54622f2..250d35a`의 제한 교차 리뷰에서 두 오류 처리 결함이 모두 해결됐고 새 P1/P2는 없었다.
- 최종 전체 pytest/ruff/mypy·보안·패키지 검사는 [CI34962555616](https://github.com/sungjunlee/finjuice/actions/runs/34962555616)에서 수집 중이다. 이전 커밋의 CI 결과를 최종 소스 전체 통과로 표시하지 않는다.
- `54622f2`: 입력 inventory 신규 10건, 기존 영향61건·staged12건·no-args1건과 Ruff/mypy·complexity PASS. 설치 환경 관련136건 PASS(64.67초), 모듈548개 설치 경로·source/wheel/installed748파일 일치. 후속 변경은 잘못된 UUID의 파일별 실패 처리와 미검증·누락·손상 저장소의 기본 화면 오류 경계다.
- `febc5e6`: JSON→XLSX·XLSX→XLSX 중첩 및 같은 XLSX 반복의 preview/write 집계·read-only·재시도 회귀3건 PASS. 설치본69건 PASS(26.92초), 모듈546개 설치 경로·source/wheel/installed747파일 일치. [CI34950353000](https://github.com/sungjunlee/finjuice/actions/runs/34950353000) 전체 성공과 Ruff/mypy614소스 검사를 확인했다.
- 앞 단계의 설치 근거도 보존한다. `b1bd806`은 입력·가족·대사·마감62건 PASS(98.52초), `d5f84c8`은 입력/history/archive39건 PASS(20.20초), `7ec024b`는 명시적 재시도 표시를 포함한40건 PASS(16초)였다. 각각 source/wheel/installed747파일 일치와 실제 설치 실행에 연결돼 있다. 이후 가족·대사·마감 구현은 변경하지 않았다.
- `summary.pending`은 현재 배치의 파일별 입력 처리 통계이며 재관측/건너뛴 파일의 보류 레코드도 포함한다. 고유 미확정 거래나 필요한 사용자 결정의 수가 아니다. `updated` 역시 파일별 재사용 합계이며, 실제 경제적 거래의 중복 방지는 별도 거래 수·원장 불변 assertion으로 검증한다.
- 설치 검증기의 초기 오류와 보정 기록도 보존한다. 빈 데이터의 `status --json`은 `NO_DATA`/종료 코드4가 올바른 계약이다. `54622f2`의 첫 실행에서는 제품 관련134건은 통과했으나 소스 구조 검사2건이 실행 경로 문제로 실패했고, 경로만 보정한 최종136건이 통과했다. 제품 코드 변경이나 실패 기록 삭제로 검사를 통과시키지 않았다.

비공개 실행 저장소에는 각 artifact hash, 모듈 경로, 시험 로그 및 기존 보존/운영 증거를 보존한다. 공개 문서에는 금융 원본·금액·계좌/소유자·인증정보·상세 호스트 경로를 넣지 않는다.

## 별도 운영 후속

- 실제 가족 소유권·동일 계좌 관계와 실제 주문·결제·할부·환불 사실 확인.
- 정상 업무의 신규 기록을 포함한 현장 백업/복원 실증.
- 특정 Mac/키 동시 손실, 아직 도래하지 않은 월간 예약 실행, 장기 RPO/RTO와 알림 전달 관측.

이 항목은 열린 운영 AC로 남긴다. 기능 완료를 위해 실제 사실을 추정하거나 운영 원장에 테스트 거래를 만들지 않는다. 최종 기능 완료와 모든 실운영 수용 완료는 서로 다른 판정이다.
