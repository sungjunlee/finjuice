# finjuice SSOT 실행 연속성

2026-09-08 준비. GitHub Issues가 명세·AC·상태의 정본이며 이 파일에는 재개에 필요한 운영 맥락만 둔다.

- 로드맵: https://github.com/sungjunlee/finjuice/issues/425
- 실행 계약/시작 프롬프트: `goals/finjuice-ssot.md`.
- 첫 활성 실행 계획: `backlog/sprints/2026-09-ssot-m1-recovery.md`. 목표 실행을 시작했고 #430이 진행 중이다. 작업 branch는 `codex/ssot-m1-contract`이며 `git worktree list`로 해당 작업 공간을 확인한다.
- 전체 순서: M1 복구 계약 → M2 정본/보존 이전 → M3 실제 운영 전환 → M4 가족 재산 → M5 증빙/마감/추가 출처.
- 에픽: M1 #426, M2 #427, M3 #428, M4 #429, M5 #355. 실행 이슈 #430~#448. 첫 작업 #430.

## 재개 시 확인할 사실

준비 당시 이 Mac checkout과 원격 main·실제 설치본의 버전이 달랐다. 현재 상태는 매번 다시 확인한다. 사용자 미커밋 변경을 보존하고 최신 main의 별도 `codex/` branch/worktree에서 개발한다. 실행 worktree에 `goals/`와 `backlog/`를 이어받았다. 초기 계약 PR에 함께 보존하며 이후에는 해당 branch/commit에서 이어간다.

SSH `openclaw`의 Hermes wealth가 실제 소비자다. `sjlee-environment`와 현재 서비스·CLI 설정으로 운영 경로를 확인한다. 원본과 파생 자료, 수동 태그/메모/분류, rules/goals, 별도 분석 도구의 수동 자산 보정, audit/history가 이전 대상이다. 자세한 데이터/호스트 경로·통계는 공개 파일에 옮기지 않는다.

기존 부분 사본이나 data Git 존재만으로 백업이 유효하다고 가정하지 않는다. 장비 밖 전체 사본·키 복구·실제 restore가 M1 gate다. 호스트/VM 백업과 과거 이미지 원본의 보관 상태는 실행 시 재확인한다.

## 유지할 결정

- baseline 이전과 금융 의미 교정을 분리한다. 원본 재수입만으로 수동 축적을 복구하려 하지 않는다.
- SQLite를 정본으로 전환해도 기존 CLI/JSON/DuckDB 의미를 보존한다. 호환 CSV는 파생 결과다.
- 정정 이력과 상태 변경은 함께 저장한다. 과거 audit로 복원할 수 없는 이력을 새로 꾸미지 않는다.
- 소비자 전환은 먼저 격리 환경에서 준비한다. 운영 CSV writer의 실제 차단은 #440 cutover에서 한다.
- 새 기록이 생긴 뒤 과거 백업을 덮어쓰는 rollback은 허용하지 않는다.
- 운영 이슈 #432·#440·#441 등은 PR 머지만으로 닫지 않는다. 첫 실제 실행/사용/복원 증거가 필요하다.
- #355의 과거 본문은 보관된 제안이다. 현재 상단 AC와 하위 #446~#448이 실행 범위다.
- #423과 수정 파일이 겹치는지 구현 전 확인한다. #51의 dependency major bump는 자동 선행 조건이 아니다.

## 기록 경계

공개 가능한 issue/PR·worktree·검사 요약·다음 행동은 활성 스프린트에 남긴다. 실제 금융 데이터·비밀·상세 운영 경로·검증 원본은 repo 밖 비공개 기록에 둔다. 각 스프린트를 마친 뒤 그 실행 기록을 보존하고 다음 마일스톤 스프린트로 이어간다.
