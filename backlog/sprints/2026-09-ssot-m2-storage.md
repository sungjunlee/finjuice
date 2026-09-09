---
milestone: SSOT M2 · SQLite 정본과 보존 마이그레이션
status: active
started: 2026-09-09
due: TBD
scope: ["**"]
---

# SSOT M2 SQLite 정본과 보존 마이그레이션

## Goal
동결 자료의 의미와 수동 상태를 보존하는 별도 SQLite 세대가 기존 조회·원자 변경·백업·복원 검증을 통과하고 실제 운영 전환을 준비한다.

## Plan
### Batch 1 — 정본 저장 계층

- [~] #433 feat(storage): SQLite 정본·불변 원본·legacy 식별 계층 [branch:codex/ssot-m2-storage]

### Batch 2 — 원자 변경 경계

- [ ] #434 feat(storage): 원자적 변경·정정 이력·멱등 쓰기 경로

### Batch 3 — 보존 이전

- [ ] #435 feat(migrate): 동결 자료에서 별도 DB로 보존 이전

### Batch 4 — 조회 호환

- [ ] #436 feat(query): SQLite 읽기와 기존 CLI·DuckDB 호환

### Batch 5 — SQLite 복구

- [ ] #437 feat(backup): SQLite snapshot과 원본 참조의 일관된 복원

### Batch 6 — 실제 보존 수용 검증

- [ ] #438 test(migrate): 실데이터 보존·재시도·복구 수용 검증

### Batch 7 — M2 완료

- [ ] #427 epic: SQLite 정본·단일 쓰기 경로·보존 마이그레이션

## Running Context
- GitHub Issues의 최신 본문과 AC가 작업 명세·상태의 정본이다. 실행 권한은 `goals/finjuice-ssot.md`, 저장·보존 계약은 ADR-0014와 `docs/development/ssot-migration-recovery-contract.md`를 따른다.
- M1 #430·#431·#432·#426과 milestone 2를 완료했다. 운영 기록 PR #452의 merge f56f5d5 기준으로 `codex/ssot-m2-storage`를 시작했다. `git worktree list`로 실행 작업 공간을 확인한다.
- 운영 서비스와 데이터는 아직 0.7.1/CSV다. #433에서 기존 CLI·Config.data_dir·CSV writer를 바꾸거나 운영 전환을 하지 않는다. 새 generation 경로와 SQLite schema version은 CSV v4 및 backup manifest version과 분리한다.
- 첫 이전은 중복 row_hash occurrence와 수동 상태를 보존한다. 기존 float 정규화기를 재사용하지 않고 정확한 숫자의 계수·소수 자릿수·원문을 저장한다. 통화 미상은 KRW로 추정하지 않는다.
- M1의 최초 기준선과 검토된 복구 절차는 영구 보호한다. #438과 실제 cutover의 기준선은 해당 시점 writer 통제 아래 새로 취득한다. 오래된 원격 capture plan이나 옛 helper를 그대로 재실행하지 않는다.
- 구현 writer는 저장 코드·합성 테스트를 맡고 오케스트레이터는 계약 판단·통합·다른 패밀리 최종 검토·GitHub 및 비공개 운영 검증을 맡는다. 같은 파일에 writer를 겹치지 않는다.
- 실제 금융 자료·운영 경로·키·상세 차이는 비공개 증거에 둔다. 사용자 원래 checkout의 변경을 보존한다.

## Progress
- 2026-09-09: M1 완료 후 최신 main에서 M2를 시작했다. #433의 live AC 4개와 선행 #430·#432·#426의 COMPLETED 상태를 확인했다. 저장 계층 경계와 테스트 계획 탐색을 마쳤으며 첫 SQLite repository 구현을 시작한다.
