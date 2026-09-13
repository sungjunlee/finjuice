# finjuice SSOT 실행 연속성

2026-09-08 준비. GitHub Issues가 명세·AC·상태의 정본이며 이 파일에는 재개에 필요한 운영 맥락만 둔다.

- 로드맵: https://github.com/sungjunlee/finjuice/issues/425
- 실행 계약/시작 프롬프트: `goals/finjuice-ssot.md`.
- 활성 실행 계획: `backlog/sprints/2026-09-ssot-m2-storage.md`. #433 완료, #434는 ready PR #463에서 진행 중이다. 2026-09-12 다른 세션의 main PR #473~#476을 통합해 대상 파일 import·legacy 처리 이력, 증빙 대사 첫 부분과 0.8.0 버전을 보존했다. 최신 head의 로컬/설치본/CI 검증 근거는 PR #463과 Issue #434에서 확인한다. GitHub 필수 approving review 1건 후 머지한다. 2026-09-12 추가 위임으로 #435 합성 준비를 #463 head 4fcf0b7 기반 별도 stacked branch `codex/ssot-m2-migrate`에서 진행한다. #434 머지나 #435 전체 완료를 뜻하지 않는다. #436 정본 export가 없어 active import/refresh는 앞선 변경 영수증을 보존하고 export에서 실패한다. 이번 통합에서 운영 데이터 이전이나 SQLite 활성화는 수행하지 않았다. 실행 작업 공간은 `git worktree list`로 확인한다.
- 2026-09-13 현재 #435 작업은 PR #481 / `codex/ssot-m2-migrate`다. main 0.8.2를 `5297c05`로 통합했고 전체 3,303 PASS·1 SKIP를 확인했다. canonical rules/goals head 선택은 `09c8247`에 구현했다. 이어 새 v3 계획은 기존 CSV 해석기의 공백·중복 marker 선택 의미를 재현하면서 원문/visible 순서·중복/저장된 최종 분류를 보존한다. 기존 v1/v2 후보는 원래 정책으로 재생하며 v3도 canonical 설정 선택을 유지한다. 이어 실패 단계 journal과 검증된 부모 계보를 구현한다. 새 lifecycle manifest v2는 portable 계보를 필수로 보존하고 기존 manifest v1 재생을 유지한다. 교차 파일 ADR-0015는 별도 legacy reported 값과 독립 참조 판정, 기존 v1/v2/v3 계획의 schema4 재생을 유지하는 새 schema5 방향으로 채택하고 저장·adapter를 구현했다(소비자·실운영 검증 미완료). Consumer parity 및 실운영 검증은 후속 수용 조건이다. #463의 필수 GitHub 승인을 대체하지 않는다.
- 완료 실행 기록: `backlog/sprints/2026-09-ssot-m1-recovery.md`. #430은 #449·#450, 백업 구현은 #451, 실제 운영 검증과 스프린트 마감은 #452로 머지됐다. M1의 실제 캡처·Linux 격리 복원·장비 밖 독립 복원·최종 교차 검토와 복구 절차 보존을 통과했고 #431·#432·#426 및 milestone 2를 완료했다.
- 전체 순서: M1 복구 계약 → M2 정본/보존 이전 → M3 실제 운영 전환 → M4 가족 재산 → M5 증빙/마감/추가 출처.
- 에픽: M1 #426, M2 #427, M3 #428, M4 #429, M5 #355. 실행 이슈 #430~#448. 첫 작업 #430.

## 재개 시 확인할 사실

준비 당시 이 Mac checkout과 원격 main·실제 설치본의 버전이 달랐다. 현재 상태는 매번 다시 확인한다. 사용자 미커밋 변경을 보존하고 최신 main의 별도 `codex/` branch/worktree에서 개발한다. 실행 worktree에 `goals/`와 `backlog/`를 이어받았다. 초기 계약 PR에 함께 보존하며 이후에는 해당 branch/commit에서 이어간다.

운영 에이전트 프로필이 실제 소비자다. 비공개 운영 inventory와 현재 서비스·CLI 설정으로 대상 호스트와 운영 경로를 확인한다. 원본과 파생 자료, 수동 태그/메모/분류, rules/goals, 별도 분석 도구의 수동 자산 보정, audit/history가 이전 대상이다. 자세한 데이터/호스트 경로·통계는 공개 파일에 옮기지 않는다.

기존 부분 사본이나 data Git 존재만으로 백업이 유효하다고 가정하지 않는다. 장비 밖 전체 사본·키 복구·실제 restore가 M1 gate다. 호스트/VM 백업과 과거 이미지 원본의 보관 상태는 실행 시 재확인한다.

## 유지할 결정

- baseline 이전과 금융 의미 교정을 분리한다. 원본 재수입만으로 수동 축적을 복구하려 하지 않는다.
- SQLite를 정본으로 전환해도 기존 CLI/JSON/DuckDB 의미를 보존한다. 호환 CSV는 파생 결과다.
- 정정 이력과 상태 변경은 함께 저장한다. 과거 audit로 복원할 수 없는 이력을 새로 꾸미지 않는다.
- 소비자 전환은 먼저 격리 환경에서 준비한다. 운영 CSV writer의 실제 차단은 #440 cutover에서 한다.
- 새 기록이 생긴 뒤 과거 백업을 덮어쓰는 rollback은 허용하지 않는다.
- 다른 OS에서 archive를 해제할 때 파일명의 Unicode 표현과 나노초 수정 시각도 검증한다. macOS 기본 tar의 실제 파일명 표현 차이를 확인했으며, manifest를 변경하는 대신 검증된 PAX 해제 절차로 원래 표현을 보존했다.
- 장비 밖 복원은 최신 검토 도구를 포함한 절차 사본과 초기 기준선을 함께 내려받아 수행한다. 전체 조회는 status 총 건수에, manifest는 독립 원본 목록에 대조한다. 초기 기준선과 모든 대응 절차 사본은 영구 보호하며 원래 사본의 옛 도구를 최신 도구로 덮어쓰지 않는다.
- M1 종료 시 운영 서비스는 0.7.1이다. SQLite 전환은 아직 하지 않았다. 후속 캡처는 최신 검토 도구 해시를 고정한 새 계획을 만들고, 실제 이전 검증과 cutover에서는 새 동결 기준선을 취득한다.
- 운영 이슈 #432·#440·#441 등은 PR 머지만으로 닫지 않는다. 첫 실제 실행/사용/복원 증거가 필요하다.
- #355의 과거 본문은 보관된 제안이다. 현재 상단 AC와 하위 #446~#448이 실행 범위다.
- #423과 수정 파일이 겹치는지 구현 전 확인한다. #51의 dependency major bump는 자동 선행 조건이 아니다.

## 기록 경계

공개 가능한 issue/PR·worktree·검사 요약·다음 행동은 활성 스프린트에 남긴다. 실제 금융 데이터·비밀·상세 운영 경로·검증 원본은 repo 밖 비공개 기록에 둔다. 각 스프린트를 마친 뒤 그 실행 기록을 보존하고 다음 마일스톤 스프린트로 이어간다.

- 최신 통합 checkpoint: `c1a3c94`는 main `309c42b`의 0.8.3 변경을 보존한다. 전체3,367 PASS·1 SKIP, coverage89.56%, 정적 검사 및 별도 설치본의 새 후보/과거 세 정책 후보 재생을 통과했다. 기존 세 policy의 schema4 고정과 정확한 reader/builder/검증/registry 경계를 구현했다. 전체3,380 PASS·1 SKIP89.57%, 실제옛후보와별도설치본재생, Opus5high의근거있는P1/P2없음을확인했다. 다음 구현은 v4내용을 보존하면서 v5reported 값 테이블·새정책과 capture참조판정을 추가하는 것이다.

- 2026-09-13 후속: schema5의 다섯 legacy reported 테이블과 capture-wide 참조 판정, 새 기본 policy `legacy_preservation.overview_reports.v4`를 구현했다. 기존 v1/v2/v3는 schema4 그대로 재생한다. 최종 전체3,434 PASS·1 SKIP89.62%, 새 설치본의 실제 과거4후보 불변 재생 및 별도 v4→v5 upgrade를 확인했다. Opus 최초 리뷰의 malformed-row 전제는 실제 build regression으로 대조했고 후보 제외 경로의 JSON 해석을 줄였다. 실제 capture peak-memory/성능, #436 소비자 parity, #435 전수 보존 및 운영 전환은 남아 있다. 리뷰 최종 판단과 commit은 활성 스프린트/PR #481에 기록한다.

- #436 첫 읽기 연결 진행: transaction_snapshot은 저장된 거래·수동/최종값·exact 수치와 같은 revision의 canonical rules를 고정한다. authority facade→Arrow/DuckDB→query에 연결해 활성 상태에서 CSV fallback을 금지했다. 메모만 수정할 때 보존 중복/공백 태그를 canonical parser가 거부하던 공백을 실제 migration으로 재현하고 source-backed legacy 수동 편집에 한정해 보완했다. 생산 코드 동결 후 최종 통합 검사/교차 리뷰를 수행하며 결과는 활성 스프린트에 기록한다. #436 전체 소비자·export·stale 결과와 실자료 검증은 미완료다.

- #436 후속 구현 순서(읽기 조사 결과, 아직 구현 아님): template_cmd/execution.py의 DuckDB/evidence·pinned filters·metadata → show_cmd.py의 CSV 존재/glob 이전 snapshot 분기와 태그 JSON decode → explain.py의 검색/규칙을 같은 snapshot에 고정하고 UUID와 legacy alias 분리 → export/result.py·result_outputs.py·result_helpers.py·master.py의 전체/필터 frame을 한 context로 전달 → status와 overview/assets 다중 도메인 snapshot. Export의 source_df가 None이면 CSV를 재조회하는 경로, master/dry-run 독립 CSV 로딩, status의 CSV partition/schema/import-history 진단을 함께 제거해야 한다. metadata만으로 stale 검증을 주장하지 않는다.

- 최종 읽기 checkpoint: 전체3,467PASS1SKIP89.66%, 최종 wheel8시나리오/9모듈SHA/과거4후보replay·upgrade, Grok P2 status수정 재검토 통과. 단 추가 설치본 probe에서 보존 중복 tags_final이 bulk recompute_tags의 strict parser에서 거부됨을 실제 재현했다. **다음은 bulk legacy 배열 경계를 먼저 보완**, 이후 위 소비자 연결 순서로 진행한다. note-only fix를 bulk 완료로 보지 않는다.
