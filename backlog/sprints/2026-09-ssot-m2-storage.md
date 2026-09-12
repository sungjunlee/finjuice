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
- 운영 서비스와 데이터는 아직 0.7.1/CSV다. #433에서 기존 CLI·Config.data_dir·CSV writer를 바꾸거나 운영 전환을 하지 않는다. 새 generation 경로와 SQLite schema version은 CSV v4 및 backup manifest version과 분리한다.
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
