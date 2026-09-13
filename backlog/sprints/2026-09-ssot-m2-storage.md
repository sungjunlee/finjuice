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

- [x] #433 feat(storage): SQLite 정본·불변 원본·legacy 식별 계층 [branch:codex/ssot-m2-storage]

### Batch 2 — 원자 변경 경계

- [~] #434 feat(storage): 원자적 변경·정정 이력·멱등 쓰기 경로 [branch:codex/ssot-m2-mutations]

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
- 운영 서비스/데이터의 마지막 현장 검증은 M1 완료 시점의 0.7.1/CSV다. 다른 세션의 후속 배포 여부는 실제 이전·cutover 전에 다시 확인한다. #433에서 기존 CLI·Config.data_dir·CSV writer를 바꾸거나 운영 전환을 하지 않았다. 새 generation 경로와 SQLite schema version은 CSV v4 및 backup manifest version과 분리한다.
- 첫 이전은 중복 row_hash occurrence와 수동 상태를 보존한다. 기존 float 정규화기를 재사용하지 않고 정확한 숫자의 계수·소수 자릿수·원문을 저장한다. 통화 미상은 KRW로 추정하지 않는다.
- M1의 최초 기준선과 검토된 복구 절차는 영구 보호한다. #438과 실제 cutover의 기준선은 해당 시점 writer 통제 아래 새로 취득한다. 오래된 원격 capture plan이나 옛 helper를 그대로 재실행하지 않는다.
- 구현 writer는 저장 코드·합성 테스트를 맡고 오케스트레이터는 계약 판단·통합·다른 패밀리 최종 검토·GitHub 및 비공개 운영 검증을 맡는다. 같은 파일에 writer를 겹치지 않는다.
- 기존 DB의 사전 검사도 원본 WAL/SHM을 바꾸면 안 된다. SQLite의 일반 read-only 연결은 SHM을 변경할 수 있고 immutable 연결은 미반영 WAL을 놓칠 수 있음을 합성 시험으로 확인했다. 검사는 보존되는 별도 snapshot 경계를 사용한다.
- #433은 WAL 활성화를 요구하지 않는다. 새 WAL 운영을 도입할 때는 [SQLite WAL-reset 수정 버전](https://www.sqlite.org/wal.html)의 런타임을 확인한다. 현재 개발 SQLite 3.50.4에서 전역 런타임을 임의로 바꾸지 않는다.
- 실제 금융 자료·운영 경로·키·상세 차이는 비공개 증거에 둔다. 사용자 원래 checkout의 변경을 보존한다.
- CI는 일반 Ruff/mypy 외에도 `scripts/check_complexity_ratchet.py`와 `scripts/check_security_baselines.py`를 실행한다. 후속 구현의 로컬 마감 검사에 두 gate를 포함하고 새 경고를 기준 완화로 처리하지 않는다.

- #435 착수 gate: #434 schema v2에서 계약 §9의 소유권 assertion(유효기간·정확 지분·근거·확인·중첩/모호성 검증), 포함/중복 assertion, agent intake의 증거→추출→해석 제안→사용자 확인→적용 changeset 분리를 구현·검증한다. V1은 격리 저장 기반이며 첫 보존 이전은 V2 계약을 포함하고 #434 검증을 통과한 최신 스키마로 한다. V1 owner 필드는 확정 소유권 권한이 아니다. M5 도메인을 미리 구현하지 않는다.

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

- 2026-09-09: #433의 AC 4개를 검증 완료하고 PR #453을 merge `b7a94ba`로 머지한 뒤 COMPLETED로 닫았다. 최종 head `8344dbe`는 전체 pytest 2,558 PASS·1 Windows SKIP(155.88s), Linux CI 2,556 PASS·4 platform SKIP(107.90s), coverage 87.79%, 새 wheel/sdist 설치·SQLite smoke·전체 정적/보안 gate·최종 Opus 검토(P1/P2 없음)를 통과했다. 원래 사용자 변경 6개를 보존했다. 최신 main에서 `codex/ssot-m2-mutations`를 시작하고 live #434의 AC 5개를 실행 입력으로 확정한다. 운영은 아직 CSV다.
- 2026-09-09: #434 core `ac13e54`에 실제 v1→v2, 원자 변경·감사·멱등·revision, 유한 대기 authority lease, 소유권·포함 관계·agent intake 경계를 구현했다. 전체 테스트 2,589 PASS·1 SKIP, coverage 87.94%, Ruff/mypy(368 files)/complexity/Bandit/pip-audit/PII/pre-commit을 통과했다. 독립 합성 검증에서 발견한 지분 단위·확정 관계 모순·유효 날짜·stale 제안 재생성 경계를 보완하고 계약 §9.1에 명시했다. 고정 core의 Grok 4.6 high 교차 리뷰와 수동 수정·rules/goals CLI 연결을 병행한다. 기존 설치본의 합성 mutation/read 기준 결과도 별도로 보관했다. named writer 전체 연결과 최종 설치본·CI 검증이 남아 있어 #434 AC는 아직 완료 처리하지 않는다.

- 2026-09-09: 고정 core의 Grok 4.6 high 검토에서 P1 없음, P2 2건(영수증 envelope 사전 검증 누락, 적용할 수 없는 배열 형태 proposal)을 받았다. 재현·수정을 진행하며, config_heads 추가는 기존 v2 DB도 보존 업그레이드하는 v3 migration으로 구현한다. 자동 승인 심사로 멈췄던 수동 수정·rules/goals 원자 갱신 및 CLI 연결·합성 테스트는 사용자 명시 승인을 받고 재개했다. 실제 데이터 변경이나 운영 전환은 아직 없다.
- 2026-09-09: core 검토 2건을 독립 재현하고 수정했다. v3 focused 86개와 정적 검사가 통과했고, 실제 ac13e54 v2 사본의 43개 테이블·원본 파일 4개 보존, fresh/upgrade 구조 동등성, 이전 receipt 재시도를 별도 검증했다. 수동/config CLI 연결과 Windows legacy coordination 검증은 진행 중이다. 최종 교차 리뷰·전체 gate·named writer 연결 전까지 #434는 미완료다.

- 2026-09-09: 실제 Windows Python 3.13.3에서 lease 5개와 CSV writer fence를 포함한 기존 probe 7개를 통과했다. 명시 data root만 받는 API로 바꾼 후 추가한 junction probe에서는 inactive alias를 통한 active target CSV 쓰기 우회를 재현했다. 합성 임시 데이터만 사용했으며 junction 경로 차단 수정·재검증을 진행한다. root의 mutation/CSV focused 46개는 통과했고, facade의 새 복잡도 3건 및 CLI 연결은 아직 작업 중이다.
- 2026-09-09 21:46 KST: Windows junction 수정 후 실제 Python 3.13.3 검증 8개를 모두 통과했다. junction alias 거부·대상 신규 partition 부재, 활성화 후 빈 쓰기 차단, thread/process timeout 및 crash 후 재획득을 확인했다. 실행한 authority/CSV/object helper의 SHA-256과 회수 artifact를 대조했다. 이는 legacy CSV coordination의 검증이며 SQLite 운영 지원·전환 완료 판정은 아니다.
- 2026-09-09 22:01 KST: 고정 temp symlink 쓰기 우회를 합성 재현 후 배타적으로 생성한 고유 temp로 수정했다. Windows CRT의 줄바꿈 변환도 실제 검증에서 발견해 O_BINARY로 수정했고, 최신 writer의 Windows 9개 검증이 전부 통과했다. 중간 전체 테스트는 2,600 PASS·1 SKIP·9 FAIL이었으며, 실패한 macOS alias fixture 8개와 benchmark 구 API 1개를 수정한 관련 63개 테스트가 통과했다. 전체 결과는 최종 gate가 아니며 CLI adapter 연결 후 고정 소스로 재검증한다.

- 2026-09-09: 최신 mutation CLI wrapper에서 오케스트레이터의 합성 검증 21개(tag 9·rules 6·budget 6)를 통과했다. 동일 요청 재시도, stale 수정 거부, 확인 대화 중 concurrent 수정 보존, 기존 rules/goals 파일 미변경을 확인했다. 남은 manual/config 진입점 fence와 입력 사전검증은 구현 중이다. Opus에 XLSX 원문 증거 reader와 합성 테스트 두 파일을 분리 위임하고 Fable에 active ingest 연결 설계를 read-only로 위임했다. Cursor/Grok route는 CLI 인증이 없어 실행하지 못했으며 quota 소진으로 분류하지 않는다. 전체 #434 완료·운영 전환 판정은 아니다.

- 2026-09-09: Opus의 XLSX 원문 reader를 독립 검토해 빈 셀 조각·인코딩·읽기 상한·관계/namespace 경계를 보완했다. 지원하지 않는 인코딩·시트는 명시적으로 거부하며 48개 합성 테스트를 오케스트레이터가 재실행해 통과했다. Fable의 공유 typed writer는 기존 builder와 23개 테이블의 결과 동등성 및 savepoint/외부 rollback 등 7개 테스트를 재검증했고, 17개 삽입 메서드의 SQL과 Ruff도 확인했다. 이 두 구성요소는 아직 ingest 및 builder/context에 연결하지 않았다. 예산 CLI 검증은 잘못된 값의 확인 전 거부와 active authority 표시까지 포함한 7개로 보강했다.

- 수동 편집·설정·구 writer 차단 checkpoint: 활성 전체 테스트 2,730 통과/1 skip, coverage88.14%, 전체 Ruff·관련 mypy·complexity·Bandit·pip-audit·PII 검사 통과. YAML 실행 태그 거부와 예산 opaque-head 재시도 포함 CLI 회귀12개 추가. 소스 동결 후 Grok 교차 리뷰 진행 중. 공통 typed writer 연결과 exact 이체 matcher는 독립 후속 구현 중이며, #434 전체 AC는 아직 완료하지 않음.

- 2026-09-10: 공통 typed writer의 builder/context 연결과 정확수 이체 matcher를 검증했다. 고정 시점 전체 pytest 2,763 PASS·1 SKIP(88.16%), Ruff·mypy 374개·complexity·Bandit·pip-audit 통과. Grok 교차 리뷰에서 두 구성요소의 재현 가능한 P1/P2는 없었다. 이후 manual/config 검토에서 발견한 audit symlink, YAML 실패 보존, omitted rule 필드 보존 세 P2를 수정 중이다. XLSX 원문 해석 mapper 및 v4 source evidence links도 진행 중이며 위 전체 검사는 후속 변경의 최종 gate를 대신하지 않는다. v4 관련 126개 테스트는 통과했지만, 링크가 없는 baseline 원본 증거의 다른 거래 재할당 결함을 추가 재현해 mutation 및 최종 invariant를 보완한다. Import/bulk tag/transfer와 남은 writer 연결, #435 보존 이전은 아직 완료하지 않았다.

- 2026-09-10: v4 source evidence links의 baseline 원본 재할당 결함을 즉시 가드와 최종 불변식으로 보완했고 관련 131개 테스트 및 독립 rollback 검증을 통과했다. 수동/config 세 P2의 Grok 재검토는 49개 테스트와 독립 probe를 통과해 P1/P2 없음으로 닫혔다. 후속 audit 실패 정리에서 발견한 동시 append 삭제를 제거했고, 별도 Grok 두 파일 검토(7개+독립 probe)와 실제 Windows 13개 검증·소스/산출물 SHA 대조를 통과했다. 레거시 실행 로그는 실패한 일부 suffix가 남을 수 있는 best-effort이며 SQLite 정본의 원자 감사 계약과 구분한다.
- 2026-09-10: 순수 XLSX exact mapper의 잘못된 UTC offset·서브마이크로초 절단·큰 serial 지수 계산을 보완했다. 원문/정밀도와 행 이슈를 보존하며 mapper+reader 70개 및 root 경계 probe를 통과했다. assets/overview/import-history CSV 진입점 fence는 구현 후 검증 중이며 원본 archive 시각 보존과 환경 독립 fixture를 보완하고 있다. `just docs`를 정상 실행해 CLI 문서와 tools 정의를 갱신했다. 이 기록은 #434의 전체 완료나 운영 전환 증거가 아니다.

- 2026-09-10 01:07 KST: 남은 assets/overview/import-history legacy writer 차단과 archive 원본 시각 보존 후 전체 pytest 2,866 PASS·1 SKIP(88.46%), Ruff·mypy 376개·complexity 126개·Bandit 20개 baseline·pip-audit 0건·PII 검사를 통과했다. 새 archive helper는 실제 Windows Python 3.13.3에서 bytes/atime/mtime 보존과 write/fsync/replace/metadata 실패 시 기존 파일 보존 7개를 통과했으며 실행 소스와 회수 artifact SHA를 대조했다. 후속 formatter의 18개 변경은 Python AST 동등성을 확인했다. wheel/sdist 구성 검사와 각각의 독립 venv 설치 smoke, 전체 pre-commit을 통과했다. Import/bulk tag/transfer의 SQLite 연결은 다음 구현 범위이며 #434의 전체 AC는 아직 열려 있다.

- 2026-09-10 02:02 KST: checkpoint `9da19fc`를 draft PR #463으로 보존했고 모든 적용 CI를 통과했다(Linux 2,868 PASS·4 SKIP, coverage 88.42%). 이후 bulk tag/transfer를 동일 snapshot의 정확수·정수 결과와 원자 이력으로 연결했다. 일반 지출/환불 비매칭, 미확인 이체 후보 유지, stale before-state 거부, 잘못된 confidence 단위 재계산, 없는 규칙과 명시 빈 규칙 구분을 보강했다. 미리보기는 읽기 전용 BEGIN 이후 revision을 읽으며 경쟁 writer의 실제 COMMIT 및 잘못된 preview 쓰기 거부를 검증했다. 직접 CLI 및 전체 pipeline의 tag/transfer 단계 12개, legacy pipeline 29개, 수동 편집 16개 회귀가 통과했다. 자산 exact mapper는 ISO 날짜·수식 통화 불확실성·오류 식별자·엄격 숫자 어휘 보완 후 29개 검증 및 Sol의 P2 재검증을 통과했다. CLI 교차 리뷰와 거래 mapper 보완·overview mapper가 진행 중이다. 이 후속 변경은 아직 커밋하지 않았으며 전체 import/refresh·최종 설치본 검증·#434 AC와 #435는 미완료다.

- 2026-09-12 재개: 기존 M1~M5 범위와 완료 계약을 유지했다. 원격 PR #463의 리팩터링 반영분을 `be2ec43`으로 병합하고 미커밋 파일을 stash 사본과 함께 보존했다. mapper 교차 리뷰에서 좌우 대차표의 한쪽 합계가 반대쪽 정상 항목을 누락시키는 P2를 재현해 column band별로 수정했다. 거래·현황 mapper와 bulk CLI 95개가 통과했고, 자산29개와 bulk mutation17개도 재실행해 통과했다. 극단 serial 검사는 실제 import I/O 지연을 확인해 파싱 watchdog과 시작 제한을 분리했다. exact file importer 도메인 구현 중이며 CLI import/refresh와 #434 최종 gate는 아직 미완료다.

- 2026-09-12: 진행 중 임포터와 분리한 고정 bulk/mapper 사본에서 Grok 4.6 high 교차 리뷰를 완료했다. 현황32·거래43·bulk mutation17·CLI22 등 114개가 통과했고 지정 변경의 P1/P2는 없었다. active refresh의 legacy schema 메타데이터 미변경과 실제 이체 pair/candidate 건수도 검증했다. 후속 pipeline failure 처리에서는 partial ingest와 export 예외의 completed-step 결과 보존 및 기존 통합11개가 통과했다. 임포터 초안의 기본15개는 통과했으나 독립 계약10개에서 완료 manifest 연결/건수 검증, parser 변경 재시도, 통화·동일 instant overlap, overview 미해석 건수 오류를 재현해 수정 중이다. active CLI 연결은 별도 writer가 맡았고 도메인 수정과 파일 소유권을 분리했다. 아직 #434 완료·merge·운영 전환은 아니다.

- 2026-09-12: exact importer의 완료 manifest/typed record/provenance 연결과 건수 검증, 안정 parser 정책·원래 key 재시도, 통화/UTC instant/분·일 정밀도 overlap, overview 미해석 건수 및 partial asset 보존을 보완했다. 실제 mapper 버전 변경을 단언하는 독립 계약16개와 기존 importer15개가 통과했다. active import/ingest/refresh를 레거시 초기화·복사·schema 기록보다 먼저 분기하고 검증된 source archive 조회·단일 파일 요청 identity·미리보기·부분 실패 영수증 보존을 연결했다. 단독 ingest의 부분 실패도 nonzero로 고쳤으며, 공통 보조 코드를 CLI 명령 계층 밖으로 옮겨 의존성 경계를 지켰다. 관련 CLI/legacy/boundary71개, mutation/import/bulk86개, mypy416개·복잡도·PII·보안 baseline·wheel/sdist 설치 smoke·pre-commit을 통과했다. 전체 최종 검사와 실패 처리 교차 리뷰는 진행 중이다. #436 정본 export가 아직 없으므로 active import/refresh는 완료한 ingest/tag/transfer 결과를 보존한 채 export 불가를 보고한다. #434 완료나 운영 전환을 의미하지 않는다.

- 최종 로컬 검사: 전체 pytest 3,061 PASS·1 플랫폼 SKIP, coverage 89.10%; Ruff·mypy416개·complexity·PII·Bandit20개 baseline/pip-audit0개·문서 생성·wheel/sdist 독립 설치·설치본 CLI JSON10개·새 파일 포함 pre-commit 통과. 고정된 구버전 Ruff와 호환되도록 공유 pytest fixture 연결을 정리한 뒤 관련66개를 재검증했다. 실패 처리에 한정한 Grok 교차 리뷰와 원격 CI 결과를 기다리며 draft PR #463에 체크포인트로 보존한다. AC 체크·머지·운영 전환은 아직 하지 않는다.

- 체크포인트 `5492bbd`의 원격 CI 전체 통과 후, Grok 검토의 P2 한 건을 보완했다. 단계 내부 검증/충돌 실패도 exit2/3과 JSON 오류 코드를 유지하면서 완료 영수증과 원문 비노출을 보존한다. active import dry-run 부분 실패도 nonzero로 처리한다. 후속 전체 pytest 3,071 PASS·1 SKIP(`--no-cov`), 관련78개·mypy416개·Ruff·complexity·pre-commit·wheel/sdist 독립 설치·설치본 CLI JSON10개를 통과했다. Grok 재검토는 기존 P2 해결, 해당 수정의 새 P1/P2 없음으로 종료했다. 최신 head CI와 #434 최종 AC 판정 후 첫 보존 이전 #435로 이어간다. 정본 export/projection #436과 실제 운영 전환은 후속 범위다.

- 2026-09-12 다른 세션 통합: main의 PR #473(대상 파일만 import)·#474(legacy 처리 이력 skip), 기준 `c146d9a`를 현재 PR #463에 통합했다. `FullPipelineOptions`의 생략/빈 파일 목록 구분과 기존 목적지 skip을 보존하고, 활성 SQLite에서는 legacy 파일명 이력을 읽지 않고 내용 identity로 판단한다. 이름만 바뀐 같은 원본은 재사용하고 같은 파일명의 바뀐 바이트는 신규 수입한다. `--force`/`--only-unprocessed` 충돌은 쓰기 전에 거부하며 도움말도 두 저장 방식의 의미를 구분한다. 실행 계약에는 다른 세션 대조·승인 대기와 구현 완료 구분을 명시했다.
- 통합 검토에서 파일별 stale/validation 오류가 일반 실패로 바뀌는 기존 연결부 P2를 수정했다. 원래 오류 유형과 선행 receipt를 내부 batch에 함께 보존하고 standalone/composed CLI가 exit 2·3을 유지한다. 실제 stale revision·단일/부분 실패·미리보기 무변경·원문 비노출의 새 50개와 기존 관련 39개를 통과했다. 매개변수만 묶은 뒤 50개와 복잡도 검사를 다시 통과했으며 baseline을 완화하지 않았다. Claude Opus 5의 좁은 읽기 전용 재검토는 기존 P2 해결, 새 P1/P2 없음으로 종료했다.
- 최종 통합 검증: `uv run pytest -q` 3,152 PASS·1 플랫폼 SKIP(500.16초), coverage 89.19%; Ruff check/format, mypy 419개, complexity, PII, Bandit 20개 baseline/pip-audit 0개 통과. `just docs`로 문서를 생성했고 새 wheel/sdist의 각각 독립 설치 smoke와 새 dist wheel의 CLI JSON 10개 schema 검증을 통과했다. GitHub main은 최신 main에 대한 Public PR Gate와 approving review 1건을 요구한다. 로컬/CLI 교차 리뷰는 GitHub 승인을 대신하지 않으며 보호 규칙을 우회하지 않는다. 원격 CI와 승인 상태는 PR #463의 현재 head에서 확인한다. #434는 아직 OPEN이며 운영 데이터 이전·활성화는 수행하지 않았다.
- 비차단 후속 검토: typed 오류로 종료된 active import 미리보기의 ingest metadata에는 `force_requested`/`unavailable_sources`/`preview_unavailable` 부가 키가 생략될 수 있다. 오류 코드·실패 파일·선행 영수증·무변경 및 원문 비노출 계약은 유지된다. 이 표시 보완은 후속 정리 항목으로 남긴다.
- #435 읽기 전용 사전 조사: backup manifest/fingerprint, `RepositoryBuilder`와 원문 occurrence/payload/disposition 계층을 재사용할 수 있다. plan/build/verify 조정과 `legacy_current_state` baseline revision 계약, 모든 legacy 행/키/필드 대응은 추가 구현이 필요하다. 신규 import의 중복 후보 격리 로직을 보존 이전에 그대로 사용하지 않는다. #434 gate 전에는 구현·운영 자료 접근을 시작하지 않았다.

- `b8ada1a`의 최종 원격 CI는 Linux 3,161 PASS·4 플랫폼 SKIP(142.58초), coverage 89.18%이며 적용 gate를 모두 통과했다. #434의 AC 5개에 구현 검증 근거를 반영했으나 이슈는 필수 리뷰/머지 전까지 OPEN이다.
- 이후 main에 PR #475(증빙 대사 첫 부분)·#476(0.8.0 버전)이 추가돼 GitHub의 정상 브랜치 업데이트로 `a76798d`에 통합했다. 로컬도 해당 head로 fast-forward했고 대사·schema·버전 관련 136개가 통과했다. `just docs`는 누락된 새 reconcile 도구 정의까지 포함해 `templates/tools.json` 62개를 생성했다. 이 버전 기준의 전체/설치본/원격 검증 결과는 PR #463과 Issue #434에 보존한다. #475는 #446의 첫 부분이며 전체 M5 완료가 아니다. 새 `reconcile`의 원장 조회는 현재 CSV이므로 #436의 SQLite 조회 전환 대상에 포함해 확인한다. 원격 main과 운영 설치본은 서로 다른 상태로 취급하며 이번 통합에서 운영 호스트를 변경하지 않았다.

- 2026-09-12 추가 위임: #463 승인 대기 중 독립 합성 #435 준비·구현을 별도 stacked branch `codex/ssot-m2-migrate`에서 허용했다. 기존 #463 checkout/PR/보호 규칙은 변경하지 않는다. plan/build/verify, 원문·CSV lexical 보존 adapter, 비활성 후보 CLI를 구현했으며 파생 overview FK 연결과 config head 선택은 명시적 미완성이다. 구현 범위와 제한은 `docs/development/ssot-migration-implementation.md`에 기록한다. 실제 자료·배포·activation은 실행하지 않았고 #435 AC를 완료 처리하지 않는다.

- 2026-09-13 PR #481 첫 교차 리뷰 후 합성 최소 수정: R2 대상 제약 사전검사와 부분 금융 typed 삽입 방지, R4 기존 repo/active/capture plan 출력 경계를 보완했다. R5/R6는 ENOSPC·일반 예외·게시/게시 후 sync 실패의 정리·원본/후보 불변 검증과 주석 정합성만 다뤘다. R1 marker 선택 의미 충돌은 미해결 acceptance로 유지하며 R3 disposition enum/schema·consumer 의미는 변경하지 않았다. 검증한 새 기준점과 좁은 교차 리뷰 결과는 기존 draft PR #481에 보존한다. 운영 자료·activation·#463 승인 게이트는 변경하지 않는다.
- 이번 수정의 리뷰 전 로컬 검증: focused 246 PASS, 전체 3,287 PASS·1 SKIP(157.12초), coverage89.42%; Ruff/format, mypy439, complexity122 baseline, PII, Bandit20 baseline/pip-audit0, docs/pre-commit 통과. 새 wheel/sdist build와 별도 wheel 설치의 합성 plan boundary/build/verify도 통과했다. 원격 feature-base CI와 별개인 로컬 증거다. 후속 단일 교차 리뷰를 위해 이 수정 기준점을 고정한다.

- 2026-09-13: `5297c05`에 main `5f8a1ec`(0.8.2, #477/#479/#480/#487/#488)을 통합했다. 충돌 4건에서 SQLite UUID/별칭·원자 설정 receipt·재실행과 main의 tag 도움말/legacy hash·focused validation을 함께 보존했다. 최종 전체 3,303 PASS·1 SKIP, coverage89.44%, Ruff/format/mypy439/complexity/버전/생성문서/적용 hooks 통과. 사용자 승인으로 현재 worktree Cursor trust를 적용해 Grok 읽기 전용 검토를 완료했고 근거·판단은 PR #481에 보존했다. #463은 OPEN/REVIEW_REQUIRED이고 #481은 stacked draft다.
- 2026-09-13 goal 재개: 전체 실행 권한을 확인하고 #435의 canonical rules/goals head 선택을 진행한다. native 단독 writer가 기존 SQLite schema 안에서 정확한 primary-root runtime 경로만 선택하고 다른 사본/invalid 원본을 보존한다. private plan에 명시적 adapter policy를 두어 기존 v1 후보 재생을 유지한다. 오케스트레이터가 실제 `5297c05` 소스로 합성 v1 후보를 생성해 새코드 교차버전 검증 기준으로 고정했다. 교차파일 관계·R1 선택·실자료/activation 및 #435 전체 AC는 아직 완료하지 않았다.

- canonical config head 검증 완료: 관련 89 PASS, 전체 3,307 PASS·1 SKIP(191.71초), coverage89.46%, Ruff/format786/mypy440/complexity122/적용 hooks 통과. 실제 `5297c05` 코드로 만든 v1 후보를 최종 코드로 verify/retry하여 head 부재와 원본·후보 불변을 확인했다. Opus5 high 읽기 전용 검토는 exit0/135.46초로 차단 사유·확정 P1 없음, 미래 가드/진단/기본값/issue명칭 의견4개를 남겼다. 현재 호출·분류·무결성 검증을 확인해 비차단으로 판단했으며 한 종류의 설정만 존재하는 두 경우를 추가한 config6개를 통과했다. 전체 검사 이후 생산 코드는 변경하지 않았다. PR #481에 원문과 판단을 구분해 보존하며 #435 전체 AC·운영전환은 계속 미완료다.

- 2026-09-13 R1 보존 수정: 새 sealed plan의 `legacy_preservation.manual_state.v3`는 기존 CSV helper와 같은 전체 tag 공백 제거·first-seen 중복 제거 후 마지막 nonempty marker suffix를 선택한다. visible 원문/순서/중복과 모든 marker payload, persisted category_final/tags_final/notes는 보존하고 v2 canonical config head를 유지한다. v1/v2 계획은 원래 literal 추출로 재생하며 올바른 manual parity는 새 v3 후보에서 검증한다. 실제 `09c8247` 소스로 만든 v2 후보를 최종 코드로 verify/retry해 원본·후보 불변을 확인했고, 같은 capture의 v3 후보는 기대한 category만 추출하면서 나머지 거래 값·ID·raw payload·config head를 유지했다. 별도 합성 4,681개 배열이 legacy helper의 category 선택과 일치했다.
- 최종 검사: migration106 PASS, manual3 PASS, 전체3,312 PASS·1 SKIP(150.34초), coverage89.46%; Ruff/format787/mypy440/complexity122 및 적용 hooks 통과. Opus5 high 읽기 전용 교차 리뷰(exit0/117.56초)는 P1 데이터 손실·replay 결함 없음과 P2 문서상 representation-code 표현1건을 보고했다. 실제로는 per-row code를 emit하지 않고 sealed policy로 구분함을 계약에 명시해 수정했다. unknown-policy 내부 helper/기본값/소비자 표시 의견은 현행 호출 및 문자열 검증과 구분해 후속 제안으로 보존한다. 생산 코드는 리뷰·전체 검사 후 변경하지 않았다. #435 전체 AC와 #463 승인·운영 cutover는 여전히 미완료이며 교차파일 typed 연결·실패 lineage·consumer parity로 이어간다.

- 2026-09-13 실패 계보 구현: 후보의 sibling private journal에 시작 전부터 immutable sealed/fsynced 단계 기록을 남기고 전체 시도 동안 nonblocking OS lock을 유지한다. 같은 계획/capture의 실제 failed/interrupted 부모만 새 target에 연결하며 live/성공/변조/다른계획/기존target 재사용은 거부한다. 새 lifecycle manifest v2는 자체 시작 snapshot과 portable 부모 chain을 필수로 검증하고 legacy manifest v1은 기존 parser/ID/adapter replay를 유지한다. 실제 process kill 전후와 rename 직후 중단 검증, human/JSON unknown parent와 traversal-before-I/O 검사, portable copy, storage failure를 추가했다.
- 1차 Opus5 high 검토(exit0/237.65초)는 P1 두 건·P2 여섯 건을 제기했다. CLI traversal은 경로 접근 전 기존 validate_attempt_id로 차단됨을 독립 검사로 확인했고, corrupt sibling failclosed와 동시 name precheck의 한계를 문서화했다. Generic version/digest 오류를 v1 전용 오보고로 해석한 의견은 실제 문자열과 구분했다. 실제 보완은 transient fsync 이후 이미 게시된 정확한 phase record를 인메모리 chain에 반영해 terminal 기록을 계속 쓰는 것, failure/close가 원래 오류를 덮지 않는 것, malformed v2 binding을 validation 오류로 처리하는 것이다. 수정 전 전체3,332 PASS·1 SKIP는 중간 근거이며 최종 검사를 대신하지 않는다. 수정 후 focused34 PASS·Ruff/mypy441/complexity122/hooks, 새 wheel/sdist와 별도 설치본의 linked candidate 검증 및 actual old candidate(v1/v2/v3 policy) 불변 검증을 통과했다. 최종 전체/좁은 재검토 결과를 기다린다.

- Opus5 high 좁은 재검토(exit0/112.77초)는 위 확정4수정 해소를 확인했다. 추가 의견은 기존 v1 malformed manifest의 오류 분류, lock/저널 중 새 KeyboardInterrupt 처리, 현재 이중호출이 없는 close의 방어성이다. 차단 사유가 아닌 후속 진단/취소 처리 의견으로 남기며 reviewer의 zero-P2 판정으로 보고하지 않는다. 현재 손실/재생 결함이 없다는 좁은 재검토를 전체 #435·운영 완료로 확대하지 않는다. 원문과 작성자 판단은 PR/비공개 합성검증 보고서에서 구분한다.

- 최종 동결 코드 전체 `uv run pytest -q`: **3,346 PASS·1 SKIP, coverage89.48%, 351.50초**. 최종 Ruff/format790/mypy441/complexity122와 적용 hooks 통과. 새 wheel/sdist의 별도 설치본에서 핵심 모듈 SHA 일치·linked lifecycle-v2 candidate build/verify와 실제 예전 소스로 만든 manifest-v1 후보의 adapter v1/v2/v3 불변 verify/retry를 확인했다. 운영 데이터·activation·#463 승인 보호는 변경하지 않았다. #435의 실패 기록/재시도 계보 구현 공백은 메웠으며 cross-file typed 연결·consumer parity·실제 보존/운영 증거는 후속이다.

- 2026-09-13 main 0.8.3 통합: upstream `309c42b`의 #496(미추적 예산 분류), #497(비대화형 explain/doctor 환경변수), #498(규칙 제안 PG·masked·generic 필터/잘린 상호 cluster), #499(release)를 충돌 없이 통합했다. 관련135 PASS, 전체3,367 PASS·1 SKIP(125.13초), coverage89.56%, Ruff/format791/mypy441/complexity122/PII/버전/생성문서 검사를 통과했다. 생성 tools에 0.8.3과 explain --pick을 반영했다. 새 wheel/sdist를 만들고 별도 wheel 설치본으로 새 후보 build/verify/retry 및 실제 과거 코드로 만든 v1/v2/v3 adapter 후보의 bytes 불변 verify/retry를 확인했다. Cursor trust는 사용자 승인을 유지하며 Grok4.6 high 읽기 전용 통합 리뷰를 실행한다. #463은 여전히 OPEN/REVIEW_REQUIRED, #481은 stacked draft이며 운영 설치본 변경이나 전체 #435 완료를 뜻하지 않는다.

- main0.8.3 통합 Cursor/Grok4.6 high 검토는 exit0/298.76초로 근거 있는 통합 P1/P2 없음이라고 보고했다. 조회·suggest-apply의 기존 fence와 CSV 소비 공백은 #436으로 구분했다. 리뷰는 GitHub 승인이나 후속 schema 변경 검증을 대신하지 않는다. 통합 commit `c1a3c94`, ADR/연속성 `7ebad60`을 PR #481에 push했다. ADR-0015의 reported 값/독립 참조 판정 방향을 채택했고 다음 단계로 기존 정책의 schema4 재생을 명시적으로 고정하는 내부 경계를 구현한다.

- ADR-0015 첫 구현 단계 완료: 기존 세 adapter policy→schema4를 단일 매핑으로 고정하고 builder/reader/validator/semantic snapshot이 정확한 v4 초기화·검증·테이블 목록을 선택한다. 기본runtime current는4 그대로이며 미지원requestedversion과header불일치는failclosed한다. 현재를시험상5로바꿔도 기존정책의build/verify/retry와digest·candidatebytes가유지된다. 새schema5나overview테이블을구현한것은아니며 향후v5는v4DDL/helper/registry내용을보존하며추가해야한다.
- 검증: 좁은67 PASS, 실제과거소스의세정책후보/source/capture bytes불변verify/retry, 최종전체3,380 PASS·1 SKIP(205.42초), coverage89.57%, Ruff/format792/mypy441/complexity122 통과. 새wheel/sdist와별도wheel설치본의핵심5모듈SHA일치·새후보build/verify/retry·과거세정책후보불변검증도통과했다. Opus5high 교차리뷰exit0/155.67초는근거있는P1/P2없음이며 테스트연결close·무순서SQL결과단정(P3)은테스트만수정했다. policy매핑Final표시와단일currentresolver에대한비차단관찰은현재런타임경계와구분했다. 생산코드는최종전체검사·리뷰후변경하지않았다. 다음은v5reported값테이블과새adapterpolicy, capture참조판정구현이다. #435전체완료/운영cutover/필수승인을주장하지않는다.

- 2026-09-13 schema5/report 구현: 새 기본 `legacy_preservation.overview_reports.v4`는 잔액·현금흐름·보험·투자·대출의 보고값을 observation/provenance에 연결한 별도 typed 테이블로 보존한다. 참조는 capture 전체의 원본 fact 후보를 빠짐없이 기록하며 missing/unverified/ambiguous로 남긴다. 동일 bytes의 다른 occurrence와 invalid typed fact 원본도 구별한다. Native projection FK는 유지하고 가짜 fact나 owner를 만들지 않는다. 기존 세 정책은 schema4 고정 재생, 일반 upgrade는 별도 schema5에 빈 테이블만 추가한다.
- 최종 전체3,434 PASS·1 SKIP(150.97초), coverage89.62%, Ruff/format798/mypy444/complexity122/PII/적용 hooks 통과. 최종 wheel/sdist·별도 설치본의 변경 생산11모듈 SHA256 일치, 실제 과거 코드4후보(기존 세 정책)의 원본/capture/candidate 불변 verify/retry, 새5종 reported 후보와 별도 v4→v5 upgrade를 확인했다.
- Opus5high 최초 리뷰(exit0/274.01초)의 P1 두 건·P2 네 건을 코드·회귀테스트와 대조했다. 잘못된 CSV 구조는 observation 생성 전에 제외됨을 실제 build/verify 테스트로 확인했고, fact 후보가 아닌 경로는 payload JSON 해석 전 제외하도록 보완했다. 좁은 Opus 후속(exit0/63.16초)은 실제 결론 없이 도구 호출을 흉내 낸 텍스트만 반환해 유효한 리뷰로 인정하지 않았다. 최신 quota/모델을 확인하고 사용자 승인 Cursor trust를 유지한 직렬 Grok4.6high 재검토(exit0/201.67초)는 현재 도달 가능한 결함 없음으로 판정했다. 다른 리뷰어의 재평가이며 Opus가 직접 철회한 것으로 표현하지 않는다.
- Grok는 malformed-row P1 전제와 primary-root P2를 현 코드/루트별 역할 계약에 따라 철회하고, 전 corpus payload 적재는 실제 메모리·시간 실측 게이트로 분류했다. disposition OR 문자열은 요약이며 typed/assessment/issue를 함께 읽는다. Optional unquoted null 금액은 nullable typed 값으로, quoted blank/invalid 수치는 opaque로 보존한다. 비CSV observation 미래 계약·clone 실패 잔류·#436 소비자 기대치 의견은 후속 경계로 남긴다. 전체 #435 전수 보존·#436 소비자 parity·운영 cutover는 완료하지 않았다. #463은 OPEN/REVIEW_REQUIRED, #481은 stacked draft다. 다음 연결 지점은 CSV 직접 조회 중인 DuckDB view와 revision별 repository 읽기다.

- 2026-09-13 #436 첫 읽기 연결: RepositoryReader.transaction_snapshot이 exact 거래 값·원래 alias·저장된 수동/최종상태와 canonical rules/status를 같은 revision에 고정한다. authority facade→Polars/Arrow→DuckDB→query로 연결하며 검증 실패 시 CSV fallback을 금지했다. UUID/legacy alias를 분리하고 중복 행을 유지하며, JSON에 generation/revision/schema/read policy를 추가했다. Float64는 명시적 표시 호환 계층이며 exact coefficient/scale/lexical을 별도로 보존한다.
- 실제 migration→query→메모 수정 검증에서 보존 중복/공백/빈 태그가 수동 parser에서 거부되고 receipt가 정규화된 배열을 보고하던 기존 공백을 수정했다. source-backed migration identity/provenance/observation이 일치하는 수동 편집만 보존 parser를 사용하며, note-only/no-op/replay는 배열/최종값을 유지하고 명시적 분류 변경에서만 재계산한다. Native strict parser는 유지했다.
- 최초 전체 실행은 새 snapshot 속성을 지정하지 않은 과거 MagicMock fixture가 YAML 파서에 들어간 상태에서 중단했다. legacy 상태 None을 명시하고 focused1PASS 후 재실행했으며 이 중단 실행을 통과 근거로 사용하지 않는다. 수정 전 전체3,461PASS1SKIP89.65%는 중간 증거다. 최종 P2 수정 후 전체 **3,467 PASS·1 SKIP(306.43초), coverage89.66%**, Ruff/format803/mypy446/complexity121/PII/hooks 통과. read/query62·수동편집72·P2/빈저장소 focused33을 확인했다.
- Cursor/Grok4.6high 최초 검토(exit0/565.17초)는 valid YAML이어도 canonical head가 invalid이면 쿼리가 필터를 사용한다는 P2를 제기했다. 같은 snapshot의 parsed_status를 전달하고 invalid/opaque head를 거부하도록 수정했다. --no-filter는 명시된 우회를 유지한다. 빈 repository의 require_transactions=True도 FileNotFoundError로 맞췄다. 좁은 재검토(exit0/44.47초)는 두 보완과 근거있는 새 P1/P2 없음으로 결론냈다. 최종 전체 검사나 운영 완료를 리뷰가 대신하지 않는다.
- 최종 wheel/sdist·별도 analytics 설치본에서 생산9모듈 SHA256 일치, 실제이전→활성조회/메모·rules revision/invalid·opaque head 등8시나리오, 실제과거4후보 불변 replay, 별도 v4→v5 upgrade를 통과했다. 원격main은309c42b그대로, #463OPEN/REVIEW_REQUIRED·#481stackeddraft를 유지한다.
- 추가 설치본 probe에서 같은 preserved duplicate tags_final의 **bulk recompute_tags는 여전히 canonical parser 오류로 거부**됨을 재현했다. 이번 note-only 보완을 bulk 전체 완료로 확대하지 않는다. 다음 우선 작업은 source-backed legacy bulk tagging/transfer 배열 처리와 dry-run/no-op/replay 경계 검증이다. 이어 template→show/explain→export→status/overview/assets 읽기를 연결한다. #435 전수보존, #436 전체소비자/결과물/stale판정, 실제capture성능 및 M3~M5 운영은 미완료다.

- 2026-09-13 bulk/template 후속: 설치본에서 재현한 bulk duplicate-tag 오류를 입력뿐 아니라 stored-derived와 stale-before 경계까지 수정했다. Migration identity 및 payload/provenance/observation이 일치하는 거래에만 보존 parser를 적용하고, before는 저장된 증거와 정확 비교하며 after canonical 검증은 유지한다. retag는 derived 필드만 재계산하고 transfer는 unrelated 태그·분류·수동notes를 보존한다. 실제 migration의 preview/apply/audit/no-op/replay와 native strict 회귀를 추가했다.
- template run은 authority/evidence를 먼저 결정하고 같은 snapshot의 canonical rules/status로 일반 SQL과 pivot을 실행한다. 외부 CSV/rules 수정의 영향, valid-YAML invalid/opaque 거부와 --no-filter, 동시 canonical rules 변경에도 revision pin, legacy/human parity를 검증했다. 예외 로그에는 금융 내용을 포함할 수 있는 원문 exception 대신 유형만 남긴다.
- 전체 **3,478PASS·1SKIP(318.44초), coverage89.68%**, bulk 관련94PASS/template68PASS, Ruff/format805/mypy446/complexity121/PII/적용 hooks 통과. 새 wheel/sdist와 별도 설치본 신규11회귀(14.47초), 변경3생산모듈SHA일치 및 로드405모듈 설치경로 검증을 통과했다. 첫 설치 테스트는 conftest의 src 우선 삽입 때문에 설치 증거로 인정하지 않았고, 설치 package 선로드 및 모든모듈 origin 검증을 추가한 실행으로 대체했다. 원격main309c42b 및 #496~#499 반영 여부를 확인했으며 추가 통합은 불필요했다. #463OPEN/REVIEW_REQUIRED, #481stackeddraft, 실제운영/전체#435/#436/M3~M5는 미완료다.
- Cursor/Grok4.6high 교차 리뷰는 사용자 승인 trust를 유지한 bounded 실행(exit0/425.20초)에서 근거있는 P1/P2 없음으로 결론냈다. 동일 source-proof JOIN·native/after strict·before evidence·derived-only 갱신과 template snapshot/필터 경계를 확인했다. 읽기 도구로 관련 소스를 추가 확인했으며 테스트 실행이나 GitHub 승인을 대신하지 않는다. 생산 코드는 전체 검사·설치본·리뷰 이후 변경하지 않았다. 다음은 원래 partition scope를 보존하는 show 연결이다.

- 2026-09-13 show 연결: `legacy_partition_scope.v1` 내부 sidecar는 같은 reader snapshot의 transaction/source/observation migration proof로 primary data-root의 정확한 transactions/YYYY/MM/transactions.csv 범위를 재현한다. 원문 date와달라도경로월을유지하고 file-level provenance inventory로빈최신월을보존한다. Row payload는fileinventory SQL에서제외한다. Native는유효effective_at의calendar월을시간대변환없이사용하며unknown도all-scope검색에는포함한다. 보조root/비표준path는정본query에서계속조회가능하며legacy primary show에는합치지않는다.
- 실제migration→show에서month/date불일치·빈최신월·태그/상호/untagged·human/JSON·canonical규칙의동시변경/invalid/opaque/우회·independent evidence 없는fallback금지를검증했다. 원래JSON sentinel표시기의dedup과저장원문의중복보존을구분한다. 모든표시후정본snapshot불변을확인했다.
- 별도 실제probe에서동일datetime의monthly/all조회순서차이를재현했다. UUID기본순서는기존CSV입력순서를재현하지못하므로증명된CSV record ordinal을sidecar에추가하고, all-scope의기존사전ascending datetime단계도유지했다. 1건씩나눈pagination을포함한최종focused29PASS. 수정전full실행은살아있는해당pytest PID에SIGINT후exit2종료를확인했으며통과근거로사용하지않는다. 최초Cursor리뷰와최종순서수정은별도로판단한다.
- 순서수정후최종전체 **3,497PASS·1SKIP(240.52초), coverage89.70%**, Ruff/format809/mypy448/complexity119/PII/docs/hooks통과. 새최종wheel/sdist및별도설치본19회귀PASS11.43초, 변경4생산모듈SHA일치·로드406모듈의설치경로를확인했다. 이전wheel/full실행과최종증거를구분하며production은최종전체실행이후동결했다.
- 사용자 승인 Cursor trust를 유지한 Grok4.6high 첫 교차 리뷰(exit0/528.36초)는 proof/JOIN cardinality/빈월/native구분/같은snapshot/query·template불변 경로에 근거있는P1/P2없음으로 결론냈다. 이후 source ordinal과 사전정렬 수정만 제공한 좁은 재검토(exit0/147.92초)도 missing/native/excluded와 pagination 경계에서 구체적P1/P2없음이었다. 리뷰는 테스트 실행·GitHub 승인을 대신하지 않는다. 최종검사·설치본·순서재검토 이후 생산코드는 변경하지 않았다. #436 전체 완료와 운영 활성화는 계속 미완료이며 다음은 explain의 same-snapshot 검색/규칙과 저장값·simulation 구분이다.

- 2026-09-13 explain 연결: 활성 저장소의 검색 거래와 canonical rules/status를 한 snapshot revision에 고정했다. UUID로 native 거래를 선택하고 #497의 JSON 자동 선택·후보·--pick 및 human 선택/취소를 유지한다. report filters는 검색에 적용하지 않으며 invalid/opaque tagging rules는 --no-filter로 우회하지 않는다. 저장된 수동/규칙/최종 분류·태그·notes와 current_rules_simulation.v1을 별도 표시한다. 규칙 판단에는 정본 coefficient/scale에서 복원한 exact 금액과 전체 거래 필드를 사용하며 표시값만 기존 Float64 계약을 따른다.
- 실제 migration 기반 회귀는 저장값 불변·동시 rules mutation revision pin·live CSV/rules 독립성·invalid head/evidence fallback 금지·큰 금액 경계·native null alias UUID·enabled/disabled regex·private-safe warning을 검증한다. focused30PASS(5.81초), 새 wheel/sdist와 설치본14PASS(54.52초), 변경4생산모듈SHA 일치 및 로드407모듈 설치경로 확인. Ruff/mypy449/complexity119/docs 통과. 전체 검사 및 Cursor/Grok 교차 리뷰 결과는 아래 최종 기록으로 확정한다.

- explain 최종 전체 **3,511PASS·1SKIP(364.21초), coverage89.73%**, format811과 적용 hooks 통과. 사용자 승인 trust를 유지한 Cursor/Grok4.6high 읽기 전용 교차 리뷰(exit0/636.44초)는 근거있는P1/P2없음으로 종료했다. 리뷰어는 테스트를 실행하지 않았으며 GitHub 승인을 대신하지 않는다. 금액의 원래 lexical spelling과 canonical exact representation을 문서에서 구분했다. stored category fallback, 같은날 UUID 후보순서, date_raw 필터, bulk/explain 조건필드 차이는 명시적 호환 경계로 남긴다. 최종 full/wheel 이후 생산코드 변경 없음.
- main309c42b는 이미 통합되어 추가머지가 불필요했고 #463은 OPEN/REVIEW_REQUIRED, #481은 stacked draft다. 다음 export는 full/report frame을 한 revision으로 전달하고 0행시 이전 날짜파일을 새 산출물로 잘못 등록하지 않도록 staging/실제생성 목록·digest manifest·현재 revision stale 비교를 연결한다. #435/#436 전체 및 M3~M5 운영 완료를 주장하지 않는다.

- 2026-09-13 #436 export 구현: 단일 검증 snapshot에서 전체 master/transactions.csv와 canonical-filtered reports를 분리했다. invalid/opaque head는실패하고 --no-filter만필터우회한다. HTML/MD의period는master/fullCSV를줄이지않는다. 출처가있는원래행순서를유지하며UUID·수동category·exactamount근거를추가 audit열로보존한다. source marker는내부에두고표시태그에서는제외한다. 기존activeimport/refresh임시export fence를제거했고실패시선행 mutation영수증보존은유지했다.
- 실행별staging→exports/runs/새디렉터리 rename으로과거날짜파일을재사용하지않으며manifest는새로만든파일들의digest/bytes와generation/revision/schema/read/calculationpolicy·basisdate·옵션을기록한다. 빈master/report는skip,빈fullCSV는헤더를생성한다. 기준일은정본의최신유효rawdate(없으면null)이며timestamp/Plotly ID/XLSX ZIP/tie순서를고정해같은revision/옵션/환경에서wallclock변경후에도동일bytes를생성한다. export-verify는현재정본revision과파일hash를각각비교하고pathescape/symlink를거부한다. 로컬receipt는인증된원장기록이아니며manifest와파일의동시위조를검출한다고주장하지않는다.
- 실제이전기반export/regression19개및pipeline/legacy를포함한focused87PASS23.53초. 정적mypy454/complexity119/PII통과. full실행중신규CLI를JSONschema catalogue에넣는누락을발견해관련3개PASS후기존실행을중단했다(SIGINT가CLI핸들러에흡수돼livePID에SIGTERM,exit143확인). 이실행을통과근거로사용하지않고최종전체검사를새로시작했다. 새wheel/sdist·20생산모듈설치SHA일치, 설치회귀·전체검사·Grok리뷰는최종기록으로확정한다.

- 독립실패주입에서기존generate_all_reports가집계오류를삼키고reportscount만줄여성공반환하는경계를재현했다(수정전test는exit0때문에실패). repository출력은성공집계count가요청수와같아야publication을허용하도록추가검증했고신규20회귀PASS6.27초. 오류는0행skip으로위장하지않으며부분파일은발행되지않는다. 이보완전full도livePID종료exit143확인후중단기록으로남기고새최종full을시작했다. 최종생산코드wheel은dist-final로구분한다.
- 첫설치검증3실패는templates선택의존성과testjsonschema누락때문이었다. 이를설치한같은wheel의19회귀는PASS14.44초였으며모든finjuice모듈설치origin을검증했다. 집계실패guard후최종wheel/full증거로대체예정이다.

- 최종출력스키마검사에서hyphen명령export-verify와underscore파일export_verify연결누락을확인했다(전체3,536PASS1FAIL1SKIP89.87%,212.59초). schema의명시x-command와toolgenerator연결, runtime manifest의hyphen→underscore참조를보완했다. 기존manifest테스트의문자열공식대조를실제파일존재검증으로바꿔동일결함복제를막았다. schema/manifest146PASS, 거래변이revisionpin·refresh실제경로/개수안내를포함한focused195PASS17.60초. 이후최종full을실행한다.
- Cursor/Grok4.6high 첫교차리뷰(exit0/635.53초)는근거있는P1/P2없음. XLSX/Plotly/TemporaryDirectory동작의좁은probe도실행했고전체suite나GitHub승인은대체하지않는다. refresh안내및행변이회귀관찰은보완했으며,집계실패guard·스키마연결·refresh변경만좁은후속리뷰로확인한다. manifest는선언파일만검사하며심볼릭링크data/export경로는거부한다.
- 독립설치latest Typer0.27.2/Click8.5.0에서기존Click isinstance기반manifest탐색이root1개만반환하는의존성호환문제를확인했다. 이번export변경으로정상이라고숨기지않고uv.lock의Typer0.25.1/Click8.4.2를설치환경에고정했다. 고정후runtime manifest66개명령과모든설치schema참조존재(export_verify포함)를확인했다. 운영release환경도lock된CLI버전을사용해야하며최신Typer호환수정은별도dependency후속사항이다. 프로그램/의존성핀없는pip최신설치를운영검증으로간주하지않는다.

- 최종통합 **3,538PASS·1SKIP(280.85초), coverage89.87%**, focused195PASS17.60초, Ruff/format818/mypy454/complexity119/PII/docs/적용hooks통과. 새최종wheel/sdist의변경22생산모듈SHA및모든패키지schema일치, lockCLI설치환경의export/import/refresh/manifest60회귀PASS15.99초·로드437모듈설치origin·66명령의설치schema참조존재검증을통과했다. 생산코드는최종full/wheel이후동결했다. Cursor좁은후속은exit0/20.24초였으나착수문장만있고도구호출/검토판정이없어리뷰로인정하지않았다. quota재확인후ClaudeOpus5high로마지막변경만직렬재검토한다.

- ClaudeOpus5high 직렬후속(exit0/265.05초)은근거있는P1/P2없음으로종료했다. reportscountguard가삼켜진집계실패를잡고staging을폐기함,생성schema/tool/runtime manifest의3단연결과누락ref0개,refresh실제산출물안내,실제행mutation시oldCSV값/revision0와currentrevision1stale분리를확인했다. 작은읽기전용manifest/tool비교만실행했으며전체suite·GitHub승인을대체하지않는다. previous_reports의중복방어·미래schema이름충돌·비문자열x-command처리는비차단관찰로남긴다. 최종full/설치본/후속리뷰이후생산코드변경없음. #463필수승인대기와#435/#436전체/M3~M5미완료를유지하며다음은basic+detailed status정본facts연결이다.
