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
- 기존 DB의 사전 검사도 원본 WAL/SHM을 바꾸면 안 된다. SQLite의 일반 read-only 연결은 SHM을 변경할 수 있고 immutable 연결은 미반영 WAL을 놓칠 수 있음을 합성 시험으로 확인했다. 검사는 보존되는 별도 snapshot 경계를 사용한다.
- #433은 WAL 활성화를 요구하지 않는다. 새 WAL 운영을 도입할 때는 [SQLite WAL-reset 수정 버전](https://www.sqlite.org/wal.html)의 런타임을 확인한다. 현재 개발 SQLite 3.50.4에서 전역 런타임을 임의로 바꾸지 않는다.
- 실제 금융 자료·운영 경로·키·상세 차이는 비공개 증거에 둔다. 사용자 원래 checkout의 변경을 보존한다.
- CI는 일반 Ruff/mypy 외에도 `scripts/check_complexity_ratchet.py`와 `scripts/check_security_baselines.py`를 실행한다. 후속 구현의 로컬 마감 검사에 두 gate를 포함하고 새 경고를 기준 완화로 처리하지 않는다.

- #435 착수 gate: #434 schema v2에서 계약 §9의 소유권 assertion(유효기간·정확 지분·근거·확인·중첩/모호성 검증), 포함/중복 assertion, agent intake의 증거→추출→해석 제안→사용자 확인→적용 changeset 분리를 구현·검증한다. V1은 격리 저장 기반이며 첫 보존 이전은 V2로 한다. V1 owner 필드는 확정 소유권 권한이 아니다. M5 도메인을 미리 구현하지 않는다.

## Progress
- 2026-09-09: M1 완료 후 최신 main에서 M2를 시작했다. #433의 live AC 4개와 선행 #430·#432·#426의 COMPLETED 상태를 확인했다. 저장 계층 경계와 테스트 계획 탐색을 마쳤으며 첫 SQLite repository 구현을 시작한다.
- 2026-09-09: Sol high를 #433의 단독 writer로 배정했다. 오케스트레이터의 SQLite 합성 probe에서 read-only의 SHM 변경과 immutable의 이전 WAL 상태 조회를 확인해 사전 검사·upgrade 실패 보존 테스트 요구에 반영했다.
- 2026-09-09: 후보 패키지와 skill runtime 요구 버전을 0.7.3으로 동기화했다. lock의 변경은 로컬 패키지 버전뿐이며 CLI 버전·runtime 검사 30개를 통과했다. 운영 설치 변경이나 SQLite 활성화는 아직 하지 않았다.
- 2026-09-09: #433 구현을 인계받았다. 합성 테스트 19개, 전체 Ruff와 365개 소스의 mypy를 통과했다. 원본 누락 검출, upgrade 중 실패 시 원본 DB/WAL/SHM 보존, FK 위반 검출과 FIFO 입력 거부를 포함한다. 전체 pytest·wheel/sdist 설치 smoke·Opus 5 교차 리뷰를 진행 중이며 AC와 이슈 상태는 검증 완료 후 갱신한다.
- 2026-09-09: 전체 pytest 2,505 PASS·Windows 전용 1 SKIP, 커버리지 87.63%를 확인했다. wheel/sdist의 새 환경 설치·CLI 및 SQLite 후보 생성/읽기/원본 포함 upgrade smoke를 통과했다. 형식 정리는 Python AST 동일성을 확인했고 pre-commit도 통과했다. Opus 검토와 draft PR의 최종 CI 결과를 대기한다.
- 2026-09-09: draft PR #453을 열었다. CI의 테스트·패키지·문서·CodeQL은 통과했으나 복잡도 5건과 Bandit의 SQL 구성 2건을 수정 중이다. Opus 5 검토 후 빌더의 부분 삽입 방지·공개 전 관계 검증·불변 ID·원문 증거·scratch 보존 경계를 보강한다. namespace는 직접 계산해 계약과 일치함을 확인했으며, 같은 schema의 논리적 복제와 새로운 활성화를 구분한다.

- Corrected review preflight (2026-09-09 10:52 KST): Claude configured account, 5h used 74% / remaining 26%, reset 11:30 KST; weekly used 12% / remaining 88%, reset 2026-09-13 01:00 KST. Both pace windows report lasting until reset; monthly/absolute exhaustion ETA unavailable. Source `claude`, confidence `percentOnly`. Review remains bounded and code/synthetic-evidence only.

- Revision `4af77d4` passed local pytest (2,523 passed, 1 Windows-only skip), all static gates, fresh wheel/sdist installation plus SQLite smoke, and all required CI. Linux/Python 3.13 CI: 2,521 passed, 4 platform/filesystem skips, coverage 87.67%. Installed SQLite source hashes match the review capture.
- A second Opus 5 review found further preservation gaps. Corrections in progress: immutable migration identity inputs, money-valued overview facts, partial asset values, unsupported v0 rejection, publication fsync ordering, zero-origin builder revisions, and successful-WAL/supersession failure-path tests. Issue #433 and PR #453 remain incomplete pending corrected verification and review.

- Revision `8e1db58` passed local pytest (2,545 passed, 1 Windows-only skip), static/security gates, fresh wheel/sdist smoke and all required CI. Linux/Python 3.13: 2,543 passed, 4 platform/filesystem skips, 87.76% coverage. The full Opus review found no P1 and four storage corrections plus required pre-migration extension points. Metadata/occurrence closure and real failure-path tests are being corrected in #433; the contract §9 extension gate is assigned to #434 before #435, without weakening the first-migration contract.

- Revision `385f3f5` passed all local/static/security/installed-artifact/CI gates: local pytest 2,558 passed, 1 Windows-only skip; Linux/Python 3.13 2,556 passed, 4 platform skips, 87.79% coverage. Opus closed the four runtime findings and accepted the mandatory #434 extension gate. Its remaining assurance finding was corrected by comparing actual SQLite authorizer reads with live schema columns; the fixed runtime SQL is unchanged. Final assurance review is pending before #433 closure.
