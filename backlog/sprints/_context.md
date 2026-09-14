# finjuice SSOT 실행 연속성

GitHub 이슈가 명세·AC·상태의 정본이다. 전체 목표는 `goals/finjuice-ssot.md`의 M1–M5 및 원래 25개 이슈(#355, #425–448)다. 부분 구현·검사 통과·PR 생성으로 전체 목표를 완료하지 않는다.

## 현재 코드와 PR

- 기반 PR #463: `codex/ssot-m2-mutations`, `c2864aa`. 기존 main75e의 38개 additive 파일에 이어 main `cf109f5`(#515)의 3개 추가 파일을 무충돌 병합했다. 필수 non-author approving review가 남았으며 저장소는 auto-merge를 허용하지 않는다. 보호 규칙을 우회하지 않는다.
- 통합 PR #481: `codex/ssot-m2-migrate`, 최신 기능 검증 소스 `c6b509b`, 기반 동기화 `bacf7bd`는 같은 파일 tree다. draft를 해제했다. 보존 이전·정본 소비·managed recovery store·immutable commit coverage·실제 postcommit filesystem delivery를 포함한다.
- 계좌 기능: `codex/ssot-account-binding`, `228b943`(검증 기능 소스 `fbaec52`, 동일 tree), #481 위 PR #516. schema6의 명시 source binding 확인/교정, 서로 다른 XLSX의 stable account 유지, `ssot account list|preview|confirm|correct|ownership-confirm|ownership-correct|ownership`의 실제 확인·교정 흐름과 exact as-of 지분/근거 조회를 구현했다. Grok read-only 교차 리뷰 exit0/P1·P2 없음으로 ready for review다.
- account-decisions 기능은 account-binding에 통합·게시 완료했다. 살아 있는 구현/검사/review 실행은 없다. 다음은 #443의 실제 canonical 자산 의미·가계 집계 및 #444 입력 연결을 현재 AC와 대조해 구현한다. 머지/운영 게이트와 원래 M5 범위도 유지한다. 새 작업은 기존 사용자 변경을 보존하는 별도 worktree에서 진행한다.
- 작업 공간의 정확한 절대 경로는 `git worktree list`로 확인한다. 기본 active checkout을 writer로 가정하지 않는다.

## 완료된 검사 — 재실행하지 않을 것

- `c6b509b`: full **4609 PASS / 1 SKIP**, coverage **90.63%**, **1827.06초**, exit0. skip은 기존 Windows-only 사례다. 전체 Ruff, mypy572, build/package checks 통과.
- 같은 delivery wheel: 설치 실제 CLI3 PASS, package678개 source/wheel/installed bytes 일치. wheel SHA `2583ee244e83f83965c1cff919fe147562147194244e2290a37f399c2cf773e3`.
- 실제 wheel로 same-revision no-op257개의 대기→송수신 coverage를 확인했다. 자체 synthetic 원본/candidate/release/sender를 제거한 뒤 receiver-only restore→mutation→rebackup→second restore PASS, installed origins481. 로컬 합성 검증이며 장비 밖/운영 성공을 뜻하지 않는다.
- `8c046e9`: 관련 binding/import/schema/ownership 회귀와 실제 CLI 확인 후 whole Ruff/mypy576/build/package checks PASS. 별도 full은 시작하지 않았다.
- 계좌 설치 wheel 핵심 **8 PASS / 7.05초**, installed origins505, package686개 source/wheel/installed bytes 일치. 실제 다른 XLSX→stable ID→복원/교정과 schema5 raw restore→명시 clone upgrade 포함. wheel SHA `035f4c3e70c627bcd9ea00e0dbd69699c15b9a491cd05daa995e14ea833c1dbd`.
- 최종 계좌 흐름 fbaec52: 설치7PASS/7.90초,508origins,692package bytes, wheel SHA `2cfc029906326322a4b25806faf14a261290c905b53c8a3516aede92fa26d9f7`. 전체 Ruff/mypy579 및 최종delta PASS. 두 번째 Grok 범위리뷰도 exit0/P1·P2 없음. `/tmp/finjuice-account-decisions-review/`의 결과를 재사용한다.
- 새main #515의 flat-path 불일치는 `7f1091e`(#481), `fbaec52`(계좌 소스)에서 immutable attempt 선택/lease로 수정했다. 실패4개+pointer교체1개 및 통합tree8개 PASS, 설치포인터교체도 PASS. 직접 SQL correction 보조함수는 여전히 canonical 변경 증거가 아니다.
- 로컬 상세 근거는 `/tmp/finjuice-backup-delivery/final/` 및 `/tmp/finjuice-account-binding-review/`. Cursor 원본 delivery 실행은 이미 terminal이며 재시작하지 않는다. 새 리뷰는 account-binding 전용 실행이다.

## 남은 실제 완료 조건

- M1은 #449–452로 당시 legacy 캡처·Linux/장비 밖 복원을 마쳤다. 당시 버전의 증거를 현재 SQLite cutover 증거로 대체하지 않는다.
- 현재 계좌 묶음은 기존 행 소급 재연결, 가계 집계, 일반 agent intake 전체, 운영 schema upgrade/cutover를 완료하지 않았다. 기존 main의 in-memory registry/별도 JSON ledger를 canonical DB 기능 완료로 취급하지 않는다.
- 운영 배포는 머지된 release artifact 기준이다. 최신 관측 운영 설치본0.8.3에는 현재 authority/recovery 기능이 없었다. 실제 배포·writer 차단·최종 기준선·cutover·첫 실제 사용이 필요하다.
- 장비 밖 destination 배치·키 복구·정기 실행의 첫 결과·용량·측정 RPO/RTO·새 기록 포함 복원이 남는다. 로컬 전달 성공으로 닫지 않는다.
- 보존된 과거 M1 사본의 실제 이전과 independent v4 검사는 완료했다: 1605234 checks/0 diff/41752 unresolved/6 notchecked. installed consumer-v3는 627953 checks/0 diff/3 unresolved/6 notchecked. 이는 새 stopped-writer 기준선이나 full family/FX/forecast 운영 증거가 아니다. 반복 이전/진단 확장을 하지 말고 남은 실제 기능·운영 연결을 수행한다.
- #436/#437 및 #435/#442/#443/#444/#446–448의 자동/근거 없는 종료는 원래 AC가 남아 있어 재개했다. 모듈 존재나 병합만으로 이슈를 닫지 않는다.
- PR #513은 caller pin harness, #514는 locator/분리 snapshot 경로라 정본 경로의 대체로 사용하지 않는다. #515는 maincf109f5에 머지되어 추가2모듈/1테스트파일을 반영했고 관련7PASS/0.38초 및 Ruff/mypy2 PASS다. 기존 정본 경로는 바뀌지 않았으며 그 직접 SQL correction 보조 함수는 canonical mutation/복구 완료 근거가 아니다. 이 추가분에 full을 반복하지 않았다.

## 실행 원칙

- 사용자 승인: 목표 범위 CLI/schema/의존성/PR/머지/배포/검증된 이전·복원 및 Cursor `--trust`. 같은 승인을 다시 묻지 않는다. 필수 GitHub 승인은 별도다.
- 사용자가 속도를 요구했다. **기능 묶음 구현→관련 회귀→통합**으로 진행하며 작은 helper마다 full/build/설치/대형 리뷰를 반복하지 않는다. 변경 없는 검사·quota·환경 진단을 반복하지 않는다.
- 살아 있는 실행은 handle로 회수한다. 관측 timeout은 종료가 아니며 같은 작업을 재시작하지 않는다. 실패 수정은 해당 회귀만 재확인하고 결과 적용 소스를 구분한다.
- private 데이터·금융 값·계좌/소유자·호스트 상세 경로는 공개 문서/PR/CI에 넣지 않는다. 원본과 수동 기록을 보존하며 운영 원장에 합성 거래를 넣지 않는다.
- quota는 큰 dispatch 결정 시 확인한다. unknown을 소진으로 간주하지 않고 공유 quota만 합산한다. credit reset/결제는 승인되지 않았다.
