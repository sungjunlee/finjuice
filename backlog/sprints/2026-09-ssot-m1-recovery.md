---
milestone: SSOT M1 · 복구 기반과 전환 계약
status: active
started: 2026-09-08
due: TBD
scope: ["**"]
---

# SSOT M1 복구 기반과 전환 계약

## Goal
기존 자료·수동 상태·외부 보정 정보를 보존하는 전환 계약이 확정되고, 장비 밖 전체 사본을 격리 복원해 현행 설치본의 조회가 재현된다.

## Plan
### Batch 1 — 전환 계약

- [~] #430 design(ssot): 전환 ADR·보존 불변조건·배포 계약 확정 (branch: codex/ssot-m1-contract)

### Batch 2 — 전체 사본과 격리 복원

- [ ] #431 feat(backup): 기존 데이터셋 전체 사본·검증·격리 복원

### Batch 3 — 장비 밖 복원 실증

- [ ] #432 ops(backup): 장비 밖 백업·키 복구·첫 복원 실증

### Batch 4 — M1 검증과 다음 단계 연결

- [ ] #426 epic: SSOT 전환 계약과 전체 백업·복원

## Running Context
- 실행 계약은 `goals/finjuice-ssot.md`, 공통 맥락은 `_context.md`를 읽는다. 명세와 AC는 GitHub에서 최신 상태를 확인한다.
- 목표가 활성화됐고 #430을 시작했다. 문서 초안 위임은 완료됐고 writer 소유권은 오케스트레이터로 회수했다. 운영 inventory·통합·GitHub 상태도 오케스트레이터가 담당한다.
- 첫 행동은 사용자 변경 보존·최신 main 작업 공간 준비와 #430의 현재 명세 확인이다.
- 비용/기간 추정은 실제 inventory와 접근 상태 확인 후 갱신한다. 생성기의 기본 시간 추정은 사용하지 않는다.
- batch 간 선행 관계가 있으므로 순서대로 진행한다. M1 종료 후 M2 스프린트를 만들며 전체 #425 목표는 계속된다.
- 범위는 finjuice 저장소 전체이며, 동시에 같은 범위의 별도 활성 스프린트를 만들지 않는다. 외부 운영 작업은 해당 이슈와 비공개 기록으로 추적한다.

## Progress
- 2026-09-08: 사용자 요청으로 `/goal` 실행 계약과 첫 스프린트를 준비했다. 기준 이슈 25개를 모두 조회했으며 전부 OPEN이다. 목표는 아직 활성화하지 않았다.
- 2026-09-08: 목표 실행 시작. 최신 origin/main 761e875 기준 별도 codex/ssot-m1-contract worktree를 준비하고 실행 파일을 이어받았다. 원래 checkout의 사용자 파일 6개 hash를 비공개 실행 기록에 보존했다. #430 문서 작성과 읽기 전용 운영 inventory를 분리해 진행한다.

- 2026-09-08: #430 ADR-0014와 보존·복구 실행 계약 작성. 설치/checkout/schema·원본·수동 상태·외부 소비자/overlay·Git·스케줄러·저널/config의 비공개 inventory를 기록했다. 이는 동결 기준선이나 복원 성공 증거가 아니다. 문서 테스트 42개, Ruff, mypy(345개 source) 통과. 전체 회귀 검사와 Grok 교차 리뷰 진행 중.
- 2026-09-08: Grok 4.6 high 교차 리뷰 완료. 6개 지적을 통합해 hidden marker 호환 codec, staging builder 예외, activation descriptor 백업, M1 writer 중단 경계, Decimal 변환 및 UUIDv5 namespace를 고정했다. 사전 pre-commit 문서 검사는 통과했다.
