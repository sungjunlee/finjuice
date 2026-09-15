# finjuice SSOT 실행 연속성

GitHub 이슈가 명세·AC·상태의 정본이다. 전체 목표는 `goals/finjuice-ssot.md`의 M1–M5 및 원래 25개 이슈(#355, #425–448)다. 부분 구현·검사 통과·PR 생성으로 전체 목표를 완료하지 않는다.

## 현재 재개점 — 2026-09-14

- 2026-09-15: 실제 설치본 소비자 비교에서 보존된 historical 행이 기본 조회에 혼입되는 차이를 발견했다. query/status/explain/export의 primary 범위를 수정하고 합성 실제 migration·native 유지·scope 오류 회귀를 추가했다. 원본 및 전체 진단은 보존한다. Opus 교차 리뷰 두 차례의 지적과 경계 조건 회귀를 반영했고, 수정된 최종 wheel의 실제 소비자 재비교 전에는 전환 수용을 완료하지 않는다. 호스트 설치에는 analytics extra와 object 읽기 전용 권한 보존이 필요함을 실제 실패·복구로 확인했다.

- PR #521 `ceae05d`의 CI 34852394131은 전체 PASS다. 사용자 승인으로 관리자 squash merge를 완료했다(main `16e4f82`).
- 새 실제 마이그레이션은 종료 코드 0: 980 inputs, DB integrity/FK/object hash/capture 재구성/adapter 재생성 의미 비교 PASS. 독립 비교 1,652,643개·consumer 비교 640,024개에서 차이 0이다. 미지원 CSV는 보존된 backups/exports/metadata이고 quarantine은 0이지만 원본 참조·소유권/환율·운영 수용의 불확실성을 숨기지 않는다.
- 설치된 #521 wheel이 만든 실제 입력과 수동 설정을 운영 분석 함수에 전달한 격리 비교는 원본 캡처와 일치했다. 원래 schema5 DB를 보존한 별도 schema9 upgrade도 53개 기존 테이블·1,045,729행/원래 컬럼 비교에서 차이 0, integrity/FK PASS다. 합성 Linux 사본에서 구 설치본이 새 marker를 무시하고 쓰는 경우와 OS 읽기 전용 경계의 차단(errno30)을 검증했다. 실제 서비스 적용·전환은 남아 있다.
- `codex/ssot-host-runtime`은 #521 위의 단독 작업 브랜치다. Cursor 구현 후 GPT 교차 검토로 compact root 옵션, host 옵션 종료, 숨김 패키지 리소스, Typer 내장 Click context 호환을 수정했다. 관련21 PASS, 최종 context 회귀3 PASS, 전체 Ruff/mypy608/complexity/security PASS. 실제 built wheel 설치6개 흐름과 별도 module subprocess PASS, 532개 로드 모듈 모두 설치본, package741개 소스/wheel/설치본 bytes 일치.
- 로컬 #521 전체 pytest는 4,807 PASS/1 FAIL/1 SKIP(2,818.20초)로 종료했다. 유일한 실패는 긴 human export 경로 줄바꿈에 대한 단언이며 host-runtime 브랜치에서 보완 후 해당 human/JSON 회귀가 통과했다. 실패한 full을 성공으로 재표시하거나 재시작하지 않는다. 현재 코드의 CI 결과를 별도로 확인한다.

- 앞선 main 기준은 #520 merge `77dfc1a`이며 해당 CI도 PASS다. 새 캡처와 release의 장비 밖 백업·격리 복원 hash 일치 및 별도 장비 키 저장소 이용을 확인했다. 키 저장소 자체까지 잃는 재해 복구는 증명하지 않았다.

## 이전 코드 통합 기록

- main 진입 PR #463: `codex/ssot-m2-mutations`. 월 마감 통합 소스 `6da728f`는 PR #519 최종 검증 소스 `9e945e8`과 전체 파일 tree가 같다. 사용자의 개인 프로젝트 관리자 머지 승인에 따라 PR #463을 squash merge했다(main `4ced76d`, 2026-09-14 17:34 KST). 이전 비작성자 승인 대기는 해소됐다.
- 작업 브랜치 PR #517 → #516 → #481은 CI 확인 후 순서대로 squash merge했다. 계좌·자산·증빙 입력·보존 이전·정본 소비·managed recovery/delivery가 이제 #463에 함께 있다. 저장소가 허용하지 않는 merge commit 대신 허용된 squash 방식으로 통합했다.
- `codex/ssot-intake-reconcile`에서 #444 제안 수정·철회와 추출 자산 관측, #446 schema8 정본 구매/할부 대사를 통합했다. 기준은 `47f7734`이며 두 독립 writer의 delta만 반영했다. 공유 mutation/facade/schema 생성기 충돌을 해결하고 자산 정정 대상은 불변 계보의 마지막 assertion, 보고/동일 증빙 재사용은 최신 확정 assertion으로 구분했다.
- 기능 소유자 검증: lifecycle10, 자산 관측10, 대사 핵심75+catalog8 통과. 실패는 해당 노드만 재실행했다. 통합 실제 흐름4 PASS/13.50초, 변경 source17 mypy와 Ruff 통과. 원본→수정/확정→다른 XLSX→capture/restore/query 포함. 기존 전체 검사는 반복하지 않았다.
- PR #518 (`0559cd6`) 설치 wheel에서 철회/재시도 및 일반 N:M 흐름2 PASS/6.46초, installed origins527, source/wheel/installed package722개 bytes 일치를 확인했다. wheel SHA `5b488af353dea067fed602d9b15da54963d8e44a3e21f2cdaba060d07f0e21f5`. 초기 revise-only2 PASS는 최종 확인 근거로 쓰지 않는다. Grok522.64초/exit0 리뷰 지적 중 철회한 제안의 재수정과 pending successor 후 동일 원본 재사용을 수정했다. 명시적으로 confirmed successor를 확정할 때 이전 confirmed 의미를 교체하는 동작은 의도한 정정 계약이며, 최종 apply/report까지 검증하도록 회귀를 확장했다. 변경 회귀4 PASS/3.19초, Ruff/mypy2 PASS. 최종373fc63 wheel 설치 회귀3 PASS/2.90초, installed origins528, package722개 source/wheel/installed bytes 일치. SHA `02c851d3efc6f869ee230b6972cb464d87890454b6536798f242d98052176446`. PR #518은 CI 통과 후15:35 KST에 정상 squash merge했고 통합 커밋은96504ce다. #445의 실제 가족 재산 운영 수용과 #446의 실제 월 검증은 남아 있어 이슈 완료로 간주하지 않는다. 적용된 asset observation의 수치 재작성과 단위 계약 없는 수량 관측은 명시 거절한다.
- #447 정본 월 마감/재개방 구현을 Opus5 high가1192.49초/exit0에 마쳤다. 관련296PASS1fixtureFAIL(260.78초), root가 v5캡처→현행clone upgrade fixture로 실패1개를 수정해4.99초에PASS. 초기9 close/raw4–8복원 검사는 통과했으며 이를 반복하지 않았다.
- `codex/ssot-close-adapter`는 최신ebfaa0c에서 #447 delta를 통합했다. 원본 writer의 마지막 소스와 snapshot hash가 같음을 확인했다. GPT 교차 검토에서 정밀 금액·이체 판단·원본 자산 단순합계·역사 재생성·미대사 상태·mutation manifest를 보완했다. 실제 수정 회귀3PASS/9.88초(최초2fixture실패 후 해당2+새미대사1만 검사), 추가기존 close→restore1PASS. 새 계산은cash.v1만 지원하고 자산에는 명시party/currency/source범위를 요구한다. 원본 close에는 당시 exact거래/자산판단/대사 입력을 보존해 history에서 재계산·digest를 검사한다.
- PR #519는 CI 확인 후15:54 KST 정상 squash merge했다(6da728f). 최종9e945e8 설치 실제 close/이체판단/재생성/복원 및 자산 정정2 PASS/3.88초, 설치 origins534, package728개 source/wheel/installed bytes 일치. wheel SHA `81e49b606f8776b83bc3563303737bb7e99ed3fc76a0c1cdf984f30c186332d4`. 소스/검증 원장은 `/tmp/finjuice-canonical-close/root-checkpoint.json`이다. 기존 검사를 재실행하지 않는다.
- #447 최초 writer `codex/ssot-canonical-close`는 동결됐다. #448 Cursor 최초 시도는 timeout으로 끝났으며 아래 새 Opus fallback 상태를 따른다.
- 기본 active checkout을 writer로 가정하지 않는다. 정확한 경로는 `git worktree list`로 확인한다. 이미 완료된 Cursor 리뷰/설치 검증은 재시작하지 않는다.

## 새 main 조회 통합과 추가 입력 실행

- main에 새로 머지된 #514(`56b2589`)를 확인해 #463 작업 브랜치에 통합했다. 활성 provider/정본 읽기를 우선하고, detached locator frame은 기존 정본 선택을 대체하지 않는다. 새 query package API와 legacy-mode query/show/status/template/export 호환은 유지했다.
- QuerySnapshot identity와 frame은 같은 RepositoryReader snapshot에서 읽도록 변경했다. export의 detached 파생/마스터/보고서도 동일한 captured frame을 사용하며 활성 정본 export의 guard·deterministic artifact는 보존했다. 관련52node 중51PASS/1구조위치FAIL(13.74초); export의 authority guard 이후 공통 구현으로 이동한 경계를 반영하고 실패노드만 확인했다. 변경17source mypy/Ruff 통과. 설치본은 이후 최종 adapter 묶음에서 검증한다.
- #436은 #514의 자동 종료로 다시 닫혔으나 활성 정본 구현이 아직 #463에 있어 재개했다. 원래 AC/범위를 줄이지 않는다.
- Cursor adapter86607은30분 hard deadline에서 SIGTERM/exit143로 종료됐고 git 변경이 없었다. `/tmp/finjuice-canonical-adapter/failure-report.json`에 근거가 있다. 재시작하지 않는다. #448은 최신98d266b 기반 `codex/ssot-json-adapter`에서 기존 Opus context를 fork해 직렬 fallback 중이다. 실행7132는529.9초/exit0으로 완료됐다. 로그 `/tmp/finjuice-json-adapter/`. 원래 close agent는 terminal이며 재시작하지 않았다.

## 완료된 검사 — 재실행하지 않을 것

- `c6b509b`: full **4609 PASS / 1 SKIP**, coverage **90.63%**, **1827.06초**, exit0. skip은 기존 Windows-only 사례다. 전체 Ruff, mypy572, build/package checks 통과.
- 같은 delivery wheel: 설치 실제 CLI3 PASS, package678개 source/wheel/installed bytes 일치. wheel SHA `2583ee244e83f83965c1cff919fe147562147194244e2290a37f399c2cf773e3`.
- 실제 wheel로 same-revision no-op257개의 대기→송수신 coverage를 확인했다. 자체 synthetic 원본/candidate/release/sender를 제거한 뒤 receiver-only restore→mutation→rebackup→second restore PASS, installed origins481. 로컬 합성 검증이며 장비 밖/운영 성공을 뜻하지 않는다.
- `8c046e9`: 관련 binding/import/schema/ownership 회귀와 실제 CLI 확인 후 whole Ruff/mypy576/build/package checks PASS. 별도 full은 시작하지 않았다.
- 계좌 설치 wheel 핵심 **8 PASS / 7.05초**, installed origins505, package686개 source/wheel/installed bytes 일치. 실제 다른 XLSX→stable ID→복원/교정과 schema5 raw restore→명시 clone upgrade 포함. wheel SHA `035f4c3e70c627bcd9ea00e0dbd69699c15b9a491cd05daa995e14ea833c1dbd`.
- 최종 계좌 흐름 fbaec52: 설치7PASS/7.90초,508origins,692package bytes, wheel SHA `2cfc029906326322a4b25806faf14a261290c905b53c8a3516aede92fa26d9f7`. 전체 Ruff/mypy579 및 최종delta PASS. 두 번째 Grok 범위리뷰도 exit0/P1·P2 없음. `/tmp/finjuice-account-decisions-review/`의 결과를 재사용한다.
- 새main #515의 flat-path 불일치는 `7f1091e`(#481), `fbaec52`(계좌 소스)에서 immutable attempt 선택/lease로 수정했다. 실패4개+pointer교체1개 및 통합tree8개 PASS, 설치포인터교체도 PASS. 직접 SQL correction 보조함수는 여전히 canonical 변경 증거가 아니다.
- 로컬 상세 근거는 `/tmp/finjuice-backup-delivery/final/` 및 `/tmp/finjuice-account-binding-review/`. Cursor 원본 delivery 실행은 이미 terminal이며 재시작하지 않는다. 계좌 및 자산/입력 범위 리뷰도 모두 종료됐다.

- `5d2d324`: 설치 실제 자산 human/JSON capture→restore→query, 증빙 submit→confirm→retry, 반복 규칙 교정·제거, catalog 회귀 **6 PASS / 17.71초**. 설치 origins524, package710개 소스/wheel/설치본 bytes 일치. wheel SHA `b9f6d36d40219c86c782fcf85716cd8d214f0b8d6972c529d5a910aed2729a55`. 관련 source 회귀와 Ruff/mypy, 패키지 구성 검사 통과. full 재실행 없음. 근거 `/tmp/finjuice-canonical-assets-review/`, `/tmp/finjuice-canonical-assets/handoff.md`. Grok 리뷰는 682.56초/exit0, P1 없음/P2 두 건 교정 완료. 최종 교정 `abb56ec` 설치 회귀3PASS/5.42초,520origins,710package bytes, wheel SHA `4f16b151b711d93365e3e00bf848ada66905061e79dcf001254bc8001159e60a`.

## 남은 실제 완료 조건

- M1은 #449–452로 당시 legacy 캡처·Linux/장비 밖 복원을 마쳤다. 당시 버전의 증거를 현재 SQLite cutover 증거로 대체하지 않는다.
- 현재 묶음은 기존 행 소급 재연결, 미확인 자료까지 포함한 실제 가족 재산 확인, 일반 agent intake 전체, 운영 schema upgrade/cutover를 완료하지 않았다. 기존 main의 in-memory registry/별도 JSON ledger를 canonical DB 기능 완료로 취급하지 않는다.
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

## 최신 최종 통합 checkpoint

- main514 통합0ffe93b 이후 #448 JSON adapter를 e62f6d5로 통합했다. 명시 create/link/pending, exact 문자열 금액, 원본 보존, 다른 요청 key 재수입·교차 출처 매핑을 schema9 정본에 연결했다. GPT 교차 검토로 기존 외부ID의 다른 거래 재지정 거절, 처리 완료된 pending 목록 제거, mutating/idempotency manifest와 생성 CLI 문서를 보완했다. 관련15PASS/11.06초, 변경3source mypy 및 Ruff 통과.
- 최종 통합 전체 pytest는 handle37396에서 실행 중이다. 로그 `/tmp/finjuice-json-adapter/final-integrated-pytest.log`. 중단/재개 시 같은 handle부터 회수하고 새 전체 검사를 시작하지 않는다. 최종 검사가 완료됐다고 주장하지 않는다.
- 전체 Ruff PASS. 전체 mypy606에서 main514 통합의 StatusFacts optional annotation1건이 발견돼475ec70에서 수정했다. 변경 status12source mypy PASS; 전체 pytest 실행 중 변경은 이 annotation 한 줄뿐이며 관련 결과를 구분한다.
- 475ec70 wheel build 완료. 설치본 adapter exact금액·수동정정·capture/restore와 canonical query 검사를 실행했다. 상세 결과 `/tmp/finjuice-json-adapter/final-installed.log`, origins JSON 및 wheel bytes JSON. source/wheel/installed739개 bytes 일치, wheel SHA `8f762f96316ba0dd8e3128f3b3fe24076e73405f098ba77de5d32c93d6dd5612`.
- PR463 필수 비작성자 승인은 여전히 REVIEW_REQUIRED이며 충돌 없이 BLOCKED다. 실제 운영 배포/전환 및25이슈 완료는 아직 증명되지 않았다. 이전 status-only 응답은 no-progress였으며 이번 turn에는 설치본 증거와 연속성 기록을 추가했다.
- Claude quota16:12 KST: provider Claude(계정 label 미제공), source claude, confidence percentOnly. 5시간64%사용/36%잔여,16:30 reset, pace상 reset까지 유지. 주간33%사용/67%잔여,9월20일01:00 reset, 예상소진3일7시간. 월간 unknown. 새 위임 없음.

- e6c74f1에서 CI complexity 실패를 수정했다. 대사 원본 계획/개별 검증, 백업 domain facts, catalog/복원 assertion을 분리했다. 분기/문장 제한을 유지하고 명시 CLI/레코드 인자 수7건만 rationale과 함께 baseline에 기록했다. 전체 mypy606/Ruff/complexity PASS. 관련19PASS, lifecycle 기대상태2개를 revised로 바로잡아 실패2+환경authority6=8PASS/10.41초. 환경locator가 기존CSV가 있는 선택 데이터셋의 show/status를 바꾸지 않도록 했다. e6c74f1 Public PR Gate PASS/2분29초.
- 전체37396 실행은 계속 살아 있으며 현재 source가 수집 시작 시점과 달라졌으므로 final exact-source 결과로 과장하지 않는다. 최종 head의 CI full 결과와 변경 delta를 함께 회수한다. 새 전체 실행은 시작하지 않는다.
- 발견된 migration 실패는 v5정책 사본을 reader기본v9로 읽는 테스트 경계였다. 정책/프로덕션 reader는 바꾸지 않고 사본 reader/semantic_snapshot에v5를 명시했다. 실제 활성 status 사례는 명시clone upgrade 후 실행한다. 마이그레이션56PASS/23.34초, status2개 import경로 교정 후2PASS/1.95초, portfolio display6PASS/4초. 진행 상세는 `/tmp/finjuice-json-adapter/`에 있다. 아직 final 전체 성공·운영 배포·25개AC 완료로 간주하지 않는다.

- 최초 최종통합 전체pytest37396은 종료했다(exit1):4751PASS/47FAIL/1SKIP,1062.80초. 실행 중 source가 변경됐으므로 현재head의 전체성공으로 표시하지 않는다. 47개 실패 목록은 `/tmp/finjuice-json-adapter/full-failed-nodes.json`; 현재 수정본 재검사42PASS/5FAIL(34.27초) 후 남은 schema5 reader5개만 교정해5PASS/2.88초. 모든 원래 실패는 개별 재검사에서 해결됐지만 최종 exact-source full 증거는 최신CI 종료 결과가 필요하다. 원래37396은 재시작하지 않는다.
- 55668c5 보안gate 수정: fixed TABLE_KEYS와 실제 pragma_table_info 컬럼 검증 뒤 insert하며 값은 bound placeholder를 유지한다. 정적SQL15지점의 검토근거를 baseline에 기록했고 per-site 중복 개수를 유지했다. Bandit43covered PASS, 대사/close17PASS16.64초. 해당CI Security Baselines/Lint/Package Artifacts PASS를 확인했다.
- 122815f에서 query/explain/source-frame/export도 선택된 기존CSV를 locator환경으로 대체하지 않도록 했고 남은 실제 migration 편집 fixture는 명시clone upgrade 후 실행한다. 관련 실패6PASS3.42초.
- 하이픈 CLI 명령6개의 생성schema에 x-command를 추가해 tool manifest의 출력schema 연결을 복원했다. 실제 generator와 doc/tools를 재생성했고 실패한 tool schema1PASS0.39초. 전체 Ruff/mypy606 및 complexity PASS. 마지막 source 패키지를 동결해 설치검사를 이어가며 과거475ec70 wheel을 최종으로 재표시하지 않는다.

## PR #463 머지 후 CI 수정

- main `4ced76d` CI 34823421584 종료: 4789 PASS, 6 FAIL, 4 SKIP. Lint/Security/Package는 통과했다. 기존 full run을 재시작하지 않는다.
- 최신 main 기반 `codex/ssot-final-fixes`에서 실패 원인을 묶어 수정했다: 긴 경로의 refresh manifest 이름 줄바꿈, HTML/MD dry-run 기간별 거래 수, 철회 상태 fixture 오기, detached SQLite API와 legacy CLI 선택 계약을 혼동한 테스트.
- 관련 9개 회귀 PASS(16.12초), Ruff/mypy 606개/complexity 통과. 원래 main full CI 성공으로 잘못 표기하지 않는다. 최종 수정 소스의 CI와 설치 artifact 확인 후 실제 배포로 진행한다.
- 실제 운영 전환·첫 사용·전환 후 장비 밖 복원 및 M4/M5 실제 수용 증거는 여전히 남아 있다. 목표 전체를 완료 처리하지 않는다.

## Native portfolio consumer projection follow-up

- PR #522 head `67839ba` fixes the sole failure in the prior full CI (4846 passed, 4 skipped): an analytics test mock lacked the new typed scope evidence. The corrected six-test file passes; package sources and the installed artifact are unchanged. Exact-head CI 34867296195 is running.
- `codex/portfolio-consumer-projection` adds investment/loan display and a single-snapshot native-aware bundle. Preserved unsupported native overview projections now contribute to incomplete readiness rather than disappearing from coverage. Initial 39 focused tests passed. Five cross-family findings were fixed; the final focused set of 37 tests, changed-source Ruff/mypy, and diff checks pass. Full Ruff/mypy (609 sources) also passed before those localized review corrections.
- Historical compatibility, operating cutover, new-record recovery, and confirmed family ownership remain separate gates. No operating source or service was changed by this implementation.

## 2026-09-15 운영 전환 완료 checkpoint

- #522 관리자 squash merge `f011526`, CI34867296195 PASS. #523 최종 head `ff0236e`, CI34872364225 PASS 후 `2ddf9da`로 관리자 squash merge했다. 최종 설치 package와 merge source는 일치한다.
- 최종 동결 원본 8개 범위의 내용·권한·mtime 및 별도 writer probe를 확인했다. 원본/후보 artifact와 최종 metadata 증거를 장비 밖에 백업하고 격리 복원해 검증했다. 기존 checker의 역사 자료/미확정 참조 진단을 지우지 않고 후속 보존 증거·중요도 판단과 함께 보존했다.
- #438 보존 수용, #427 M2 에픽, #439 소비자 전환 준비를 실제 AC 충족 근거로 COMPLETED 처리했다. 미확정 가족 소유권을 확인된 사실로 바꾸지 않았다.
- 검토된 운영 파일 18개를 적용했고 실제 쿠팡 조회·자산 보고서 main 실행이 통과했다. 대상 서비스 재시작 및 실제 프로세스 mount namespace의 legacy CSV/수동 overlay 읽기 전용을 확인했다. 대상 밖 서비스는 변경하지 않았다.
- 전환 전 실패 시 기존 서비스 복구를 실제 확인했다. 전환 확정 뒤에는 자동 rollback을 막고 감시 타이머 해제를 확인한 후 새 서비스를 시작했다. 운영 DB/CSV에 가짜 거래를 넣지 않았다.
- 운영본 첫 장비 밖 백업과 별도 native inactive restore/admission·integrity/FK·대표 조회 검증 PASS(약 297초). 일일 03:10 백업과 매월 1일 04:10 복원 점검을 등록했다. 첫 일일 calendar 실행은 NAS 저장·정상 종료까지 PASS. 월간 첫 실행은 아직 예정 전이며 이후 정상 신규 기록 복구는 별도 완료 조건이다.
- #446/#448은 코드 구현과 실제 수용을 구분해 다시 열었다. #447 코드 수용과 M5 실제 업무 완료도 혼동하지 않는다.
- 가족 계좌 소유권·동일 계좌 판단과 M5 실제 입력의 통화/단위/주문 경계·할부/환불 사실은 사용자 확인이 남았다. 목표 전체는 active이며 M3/M4/M5 완료로 과장하지 않는다.
- 비공개 실행 checkpoint: 개인 실행 저장소의 `pr520-closeout/resume-approval-progress.json`. 실패 기록, 원본, 설치 artifact, 상세 재현 증거는 공개 저장소에 넣지 않는다.

- 당시 공개 연속성 branch: `codex/ssot-operating-closeout` (main `2ddf9da` 기반). 당시 범위 25개의 미완료는 #355/#425/#428/#429/#440/#441/#445/#446/#448이었다. 현재 상태는 아래 최신 기록과 live Issue를 따른다.
- private checkpoint의 오래된 진행 중 handle과 전환 전 false 상태는 별도 history로 보존하고 현재 상태를 정규화했다. 실제 신규 입력·가족/주문 사실을 받기 전 같은 검사를 반복하지 않는다.

## 2026-09-15 사용자 목표 변경 — 현재 지시

- 사용자가 실데이터 운영 수용과 기능 구현을 분리하고, 기능 완료를 향해 목표를 수정·재개하도록 요청했다. 현재 실행 계약은 `goals/finjuice-ssot.md`의 기능 완료 기준이다. 이전에 실제 가족/주문 사실이 없으면 전체 중단하도록 했던 기록은 현재 구현 지시가 아니다.
- 실제 소유자·주문 정보, 정상 신규 거래 이후 현장 복구, 특정 Mac/Keychain 및 장기 운영 실증은 운영 후속 검증으로 보존한다. 실제 데이터를 추정하지 않고 합성 fixture/격리 원장으로 기능을 검증한다. 기능 AC 자체는 생략하지 않는다.
- 재개 기준 main `122eafc`: #529 schema invariant 추출, #507 backup 운영 기능, #534 statement parse/apply 분리까지 반영됐다. 과거 운영 설치 artifact와 최신 코드 증거를 혼동하지 않는다.
- 다음 구현 판단은 #445/#446/#448의 기능 AC와 최신 통합 테스트의 차이를 먼저 대조한다. #440 같은 운영 조건의 미충족을 구현 차단으로 취급하지 않는다. 열린 리팩터링 작업과 충돌하지 않도록 기존 작업도 확인한다.
- 앱 goal은 도구상 기존 blocked 상태이며 직접 편집/재개 API가 없다. 앱 UI 접근도 안전 제한으로 거부됐다. 사용자가 대체 문구로 앱 goal을 수정·재개해야 자동 연속 실행 상태가 바뀐다. 이 제한과 별개로 현재 승인된 기능 작업은 진행 가능하다.
- 현재 연속성 branch는 `codex/ssot-functional-goal`, PR #538이다. main `122eafc`의 가족 계좌 정정·자산 범위/복원·다대다 대사·마감 의미 보존 관련 4개 파일 33개 테스트가 통과했다(92.84초). #445/#446에 합성 기능 검증 근거를 기록했으며 실제 운영 검증은 미완료로 유지했다.
- #532 head `e8f6c2e`는 기존 담당자의 3차 교차 리뷰 중이다. 최신 피드백의 배치 preview 상태 연속성·imported_at·pending 집계 문제를 해결하기 전 머지하지 않는다. 담당 작업과 중복 writer를 만들지 않는다.

## 2026-09-15 기능 목표 재개 및 최종 입력 통합

- 앱 목표는 사용자 재개 후 최신 기능 완료 문구의 `active` 상태로 확인됐다. 위의 blocked/UI 제한 기록은 과거 상태다. 실제 가족 정보·키체인을 기다리며 구현을 중단하지 않는다.
- #538 목표 변경은 `6b3a47b`로 머지됐다. #532는 기존 원격 head와 대조한 뒤 격리 branch `codex/ingest-final-fixes`에서 fast-forward로 수정했다. 최종 코드 head는 `7ec024b`다. 명시적 재시도의 신규 생성 표시도 0으로 정규화하고 저장된 원본 영수증을 보존한다.
- JSON 배치 미리보기·실제 imported_at·무변경 재수집·확인 후 pending 재처리, history/noop 구분·보류 표시·archive typed error를 보완했다. Opus 교차 리뷰에서 세 후속 결함의 해결을 확인했다. 파일별 pending 통계와 고유 거래/결정 대기열 수는 구분한다.
- `b1bd806` 설치본의 가족/대사/마감 포함 62건 PASS와 최종 `d5f84c8` 설치본 영향 범위 39건 PASS를 보존했다. 최종 source/wheel/installed 747개 bytes 일치, 로드된 모듈 546개 설치 경로 확인. 실제 운영 배포/원장은 변경하지 않았다.
- 최종 Public PR Gate34948999975(Ruff/mypy614/기타 gate)는 PASS. 최종 wheel의 영향 범위40건(16초)과 마지막 변경 교차 리뷰도 PASS. 전체 pytest CI34948999931 및 #532 머지는 아직 대기 중이다. 같은 전체 테스트를 추가 실행하지 않고 이 실행을 회수한다.
- 원래 25개 이슈의 기능 요구·실행 증거·별도 운영 항목은 `docs/development/ssot-functional-acceptance.md`에서 대조한다. 아직 최종 CI/머지가 남아 있으므로 목표 완료를 선언하지 않는다. 현재 문서 작업 branch는 `codex/ssot-functional-acceptance`, PR #541이다.

- 후속 자동 리뷰의 혼합 JSON→XLSX preview 불일치를 `febc5e6`에서 수정했다. XLSX→XLSX 중첩 및 동일 XLSX 반복도 포함한 회귀3건 PASS, 새 wheel 설치본69건 PASS(26.92초), source/wheel/installed747파일 일치. 최종 CI34950353000을 회수 중이며 과거 CI는 대체됐다. #532 및 #541 최종 머지 전에는 기능 완료로 표시하지 않는다.
- M2 sprint의 과거 Plan 진행 표시를 실제 완료된 #433~#438/#427 AC와 일치시키고 `sprint-close.sh`로 완료 처리했다. doctor PASS·reassess quiet. 원본 보존·정확 금액·단일 writer·비공개 증거 경계는 계속 적용한다. M1~M5 최종 기능 완료는 #532 CI/머지와 이 문서 PR의 통합이 남아 있다.
