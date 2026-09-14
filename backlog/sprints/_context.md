# finjuice SSOT 실행 연속성

GitHub Issues가 명세·AC·상태의 정본이다. 실행 권한과 완료 조건은 `goals/finjuice-ssot.md`, 상세 구현·검사 이력은 `backlog/sprints/2026-09-ssot-m2-storage.md`에 있다. 이 문서는 현재 재개 지점만 유지한다.

## 목표와 현재 상태

- 전체 범위는 #425, #426–#429, #355와 #430–#448의 원래 25개 이슈다. 마지막 감사에서 25개를 찾았고 20개가 미완료였다. 부분 구현이나 스프린트 종료를 전체 목표 완료로 취급하지 않는다.
- M1은 #449–#452로 구현·실제 캡처·Linux 격리 및 장비 밖 복원·운영 검증을 마쳤다. 영구 기록은 `2026-09-ssot-m1-recovery.md`다. 그때 운영 서비스는 0.7.1이었으며, 당시 legacy 복원 증거는 현재 SQLite cutover 증거가 아니다.
- 활성 스프린트는 `2026-09-ssot-m2-storage.md`다. M2 정본/보존 이전 → M3 실제 운영 전환 → M4 가족 재산 → M5 증빙/마감/추가 출처 순서와 원래 AC를 유지한다.
- PR #463(`codex/ssot-m2-mutations`, 마지막 확인5083f34)은 필수 GitHub approving review 대기다. 이를 우회하거나 교차 리뷰로 대체하지 않는다. PR #481은 그 branch 위의 stacked draft다.
- #436/#437 및 #446–#448은 부분 구현 PR의 자동 종료 후 다시 열었다. 실제 전체 AC가 충족될 때만 닫는다.

## 현재 작업 공간과 검증

- 주 writer: `codex/ssot-m2-migrate`, worktree 이름 `finjuice-ssot-migrate`. 정확한 절대 경로는 `git worktree list`로 확인한다. 기본 active checkout을 writer로 가정하지 않는다.
- 원격에 반영한 checkpoint는 `8a36a95`; main `fbc1682`(#504–#506)를 병합한 `cec0e9d`와 검증 기록을 포함한다. 전체4,447PASS/1SKIP,91.02%, 설치115PASS/494module origins/3runtime SHA, Cursor 독립115PASS/중요P1P2없음. 근거는 `/tmp/finjuice-main506-review/`와 PR #481이다.
- 기존 정확 계산·실제 작업량 계측을 nm.py로 보존하고 새 main close/evidence 모듈을 유지했다. JSON adapter는 현 append API와 전체 legacy lease를 사용한다. 새 sidecar/CSV 기능만으로 canonical M5 완료를 주장하지 않는다.
- 앞선 release helper와 migration capsule는 포함됐다. Capsule는 원본 source/candidate 삭제 후에도 보존 증거를 재검증하며 JSON 숫자 타입을 엄격히 비교한다. 상세 정책 replay·소비자·복원 이력은 활성 스프린트에 보존돼 있다.
- 현재 기능 소스 커밋은 `49add1b`다. 최신 recovery bundle와 capture/verify/restore CLI·독립 expected 입력·스키마를 함께 통합했다. Cursor 구현을 GPT 검토해 검증→복원 identity 누락3건을 재현하고 manifest digest/gen/schema/revision 연결로 수정했다. 원래 Cursor supervisor는 1008.67초/exit0로 종료됐으므로 다시 시작하지 않는다.
- 관련52개+catalog12개 및 정적검사/commit hooks 통과. 동결 커밋 전체pytest는4,486PASS/1SKIP91.04%,799.06초/exit0로 종료했다. `/tmp/finjuice-recovery-operator-checkpoint/full.log`의 최종 결과이며 재시작하지 않는다.
- 49add1b 실제wheel 설치265PASS(493개module origin), runtime/schema8개SHA일치. 실제wheel/lock을 담은 합성enrollment bundle의 원본제거→격리복원revision1→party수정→재백업→2차복원revision2도 통과(472개module origin). WheelSHA는6a38c3070253ed00a5cdda6844a741f164731ae7edd48d46c7c545e5fbc4ead8. 이는 운영trust/offdevice/cutover 증거가 아니다. 근거는 위 checkpoint 디렉터리다.
- 다른 에이전트 PR #507–#511은 마지막 확인 미머지였다. #510의 schema v2/별도 authority marker는 현재 schema5와 검증된 active.json 체계와 겹친다. main 또는 다른 branch를 덮어쓰지 말고 최신 상태와 필요한 동작을 대조한다. PR #503의 CLI 표면은 이미 안전한 엔진에 맞춰 반영했지만 그 PR 전체를 병합한 것은 아니다.

## 다음 행동

1. 기반 PR463 갱신은 별도 codex/ssot-base-main506의 36f4b25에 커밋됐다(5083f34 + main fbc1682). 전체 3,254 PASS/1 SKIP, 설치 115 PASS, runtime 18 SHA 및 동결 23파일 검증 완료. 최종 Opus 5 high supervisor PID37904가 진행 중이며 /tmp/finjuice-base-main506-checkpoint/에서 type=result를 회수한다. 완료 전 재시작하지 않는다. 현재 migrate와 merge-tree 결과의 tree diff는 0이며, 검토 완료 후 기반 push 및 ancestry 통합만 필요하다.
2. 복구 기능49add1b의 전체/설치/실제wheel복원 및 GPT 교차검토는 완료됐다. 새 근거 없이 반복하지 않는다. 기반 PR463는 최신main보다뒤처져갱신중이며GitHub필수승인1건이여전히필요하다.
3. 다음 retention/운영 연결은 PR507 작성 세션이 미확인이다. 네 제안 파일을 덮어쓰지 않는다. 읽기전용 연결점 지도는 `/tmp/finjuice-recovery-operator-checkpoint/pr507-bridge-map.md`; 실제graph/독립key/운영증거와 순수정책·상태계산을 구분한다.
4. Durable reference retention, private 전수 보존/성능, 실제 배포·cutover·첫 사용, 장비 밖 사본·키 복구·용량·RPO/RTO와 M4/M5 실제 사례는 아직 미완료다. 동작하지 않은 CLI나 운영 증거를 만들지 않는다.

## 계속 지킬 결정

- 이전은 기존 의미 보존이고 계좌 병합·소유자 추정·재분류는 근거 있는 별도 changeset이다. 원본/수동 태그·메모·분류 override·규칙·목표·외부 보정·참조·audit/history를 보존한다.
- 전환 전 legacy, 전환 후 SQLite 하나만 정본이다. CSV 실시간 이중 쓰기나 활성 조회의 live YAML/CSV fallback을 두지 않는다. 기존 policy 후보는 원래 schema와 해석으로 재생한다.
- 실제 cutover 전에 writer 통제 아래 새 기준선을 취득한다. 장비 밖 전체 사본과 독립 키 복구·격리 restore를 먼저 확인한다. 새 기록 후에는 옛 백업 덮어쓰기로 rollback하지 않는다.
- macOS/Linux 복원에서 Unicode 파일명 표현과 나노초 수정 시각을 보존한다. 검증된 PAX 절차와 독립 manifest를 사용하며 옛 기준선/복구 절차 사본을 덮어쓰지 않는다.
- 운영 에이전트 프로필은 실제 소비자다. 대상 호스트·경로·키는 비공개 inventory/현재 runtime으로 확인하고 공개 repo/Issue/PR/CI에 금융값·계좌·소유자·비밀·상세 운영 경로를 남기지 않는다.
- 사용자 목표 계약은 범위 내 구조·CLI/schema·의존성·커밋·PR·머지·배포·검증된 이전/백업/복원을 승인한다. Cursor --trust 승인도 유지된다. 플랫폼 필수 승인은 별도이며 새 금융 거래·범위 밖 원본 삭제·유료 계약은 포함되지 않는다.
- 사용자 효율 지시: 작은 helper마다 full pytest·wheel 설치·장시간 리뷰를 반복하지 않는다. 기능/AC 묶음 구현·자체검토 후 checkpoint에서 검증한다. 작은 후속 수정은 실패 재현+관련 회귀로 확인하고 이전 전체 결과의 적용 소스를 구분한다. 변경 없는 로그·refs·quota 재조회와 상세 이력 중복을 줄인다.
- quota는 dispatch·통합·publish 같은 결정 시점에 확인한다. unknown은 소진이 아니며 다른 계정/창의 잔여율을 혼합하지 않는다. credit reset/결제는 승인되지 않았다.

- 운영 설치 최신 관측(09-14 09:13KST): SSH로 표준계정경로finjuice0.8.3/uv0.10.7을확인했다. 기본비대화형PATH에는없다. 설치본authority/recovery_bundle/sqlite_backup CLI/nm모듈이없으므로현재통합판배포나cutover로간주하지않는다. 금융원본읽기/운영변경없음; 세부근거는활성스프린트와runtime-check기록을따른다.
