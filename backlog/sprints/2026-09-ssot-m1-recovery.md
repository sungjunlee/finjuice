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

- [x] #430 design(ssot): 전환 ADR·보존 불변조건·배포 계약 확정 (PR: #449·#450, latest merge: 54c47ec)

### Batch 2 — 전체 사본과 격리 복원

- [~] #431 feat(backup): 기존 데이터셋 전체 사본·검증·격리 복원 [branch:codex/ssot-m1-operations]

### Batch 3 — 장비 밖 복원 실증

- [~] #432 ops(backup): 장비 밖 백업·키 복구·첫 복원 실증 [branch:codex/ssot-m1-operations]

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
- 현재 checkpoint: 실제 캡처·Linux 격리 복원·장비 밖 독립 복원은 통과했다. 아래 최신 기록의 운영 보완 교차 검토를 마친 뒤 #431·#432·#426을 닫고 M2로 이어간다. 이전 날짜의 미실행/검토 대기 항목은 당시 상태다.
- 2026-09-08: 사용자 요청으로 `/goal` 실행 계약과 첫 스프린트를 준비했다. 기준 이슈 25개를 모두 조회했으며 전부 OPEN이다. 목표는 아직 활성화하지 않았다.
- 2026-09-08: 목표 실행 시작. 최신 origin/main 761e875 기준 별도 codex/ssot-m1-contract worktree를 준비하고 실행 파일을 이어받았다. 원래 checkout의 사용자 파일 6개 hash를 비공개 실행 기록에 보존했다. #430 문서 작성과 읽기 전용 운영 inventory를 분리해 진행한다.

- 2026-09-08: #430 ADR-0014와 보존·복구 실행 계약 작성. 설치/checkout/schema·원본·수동 상태·외부 소비자/overlay·Git·스케줄러·저널/config의 비공개 inventory를 기록했다. 이는 동결 기준선이나 복원 성공 증거가 아니다. 문서 테스트 42개, Ruff, mypy(345개 source) 통과. 전체 회귀 검사와 Grok 교차 리뷰 진행 중.
- 2026-09-08: Grok 4.6 high 교차 리뷰 완료. 6개 지적을 통합해 hidden marker 호환 codec, staging builder 예외, activation descriptor 백업, M1 writer 중단 경계, Decimal 변환 및 UUIDv5 namespace를 고정했다. 사전 pre-commit 문서 검사는 통과했다.
- 2026-09-08: #449 머지(6fc23b1), #430 COMPLETED. 전체 회귀 2403 passed/1 skipped, coverage 87.82% 및 모든 GitHub CI 통과. #431을 시작했다. 백업 코드 writer는 Grok 4.6 high이며 오케스트레이터는 코드 통합·리뷰와 비공개 실제 복원 검증을 담당한다.
- 2026-09-08: #449 이후 완료된 비동기 리뷰의 후속 보완을 위해 #430을 재개했다. 멱등 결과 조회를 새 요청 revision 검사보다 먼저 수행하고, ID seed를 빌드 전 capture digest로 고정한다. 공개 연속성 기록의 운영 식별자도 논리 역할로 바꾼다. 이 정정은 별도 PR로 처리하며 #431의 코드 구현과 원본 데이터에는 영향을 주지 않는다.
- 2026-09-08: 후속 정정의 문서 테스트 42개, pre-commit·문서 링크·계약 assertion 통과. Grok 4.6 high가 정정 diff를 다시 검토해 추가 발견 없음으로 확인했다.
- 2026-09-08: 비동기 리뷰 3건의 계약 정정 #450도 머지 완료했다. Grok 재검토 및 GitHub 자동 리뷰에 추가 발견이 없고 문서 CI가 통과했다. 기존 설치 버전의 복구 wheel/sdist를 준비했으며 설치본 패키지 파일 380개와 hash 차이가 0이다. 격리 설치와 version/manifest JSON/help smoke 통과. 실제 backup/restore는 미실행이다.
- 2026-09-08: #431 합성 검증에서 short write·대상 경합·복원 실패 보존 문제를 수정했다. Sol 독립 검토의 manifest/경로/fsync 관련 발견과 현행 조회의 수정 시각 보존을 보완 중이다. 공개 코드 검증과 실제 운영 AC를 분리하며 #431은 아직 OPEN이다.
- 2026-09-08: 기존 프로그램 복구 artifact의 Mac·Linux 격리 설치 및 CLI smoke가 통과했다. 현행 설치본 대표 조회 4개도 정상 실행됐다(미동결 사전 점검). 장비 밖 합성 복원·별도 프로세스 키 복구·빈 암호화 저장소 무결성 검사는 통과했으며 실제 금융 사본·운영 복원은 미실행이다.
- 2026-09-08: Sol 보완의 scoped 185개 검사 통과 후 writer 소유권을 회수했다. capture interval/parent attempt 정보를 추가하고 백업 검사 60개, 전체 Ruff·mypy 355개 source, pre-commit을 통과했다. 0.7.2 버전으로 정리했으며 전체 회귀와 Grok 최종 교차 리뷰가 남아 있다.
- 2026-09-08: draft PR #451을 열었다. 전체 회귀 2469 passed/1 skipped와 Linux CI의 테스트·패키지·문서·보안 검사가 통과했다. CI의 복잡도 지적을 기준 완화 없이 함수 분리로 해결했다. 추가로 publication fsync 실패 후 재시도와 새 상위 폴더의 내구성을 보완해 백업 검사 62개·전체 Ruff·mypy·복잡도 검사가 통과했다. 최종 교차 리뷰 및 변경 후 전체 검사를 진행하며 실제 금융 데이터 capture는 아직 실행하지 않았다.
- 2026-09-08: Grok 최종 리뷰의 재현 가능한 지적 3건을 반영했다. 파일시스템 identity로 경로 별칭 겹침을 차단하고, 실패 시 읽기 전용 staging도 정리하며, 백엔드 restore의 활성 데이터 경계를 필수로 했다. 백업 검사 69개와 Ruff·mypy·복잡도 검사가 통과했다. 캡처의 숨김 파일 누락 지적은 실제 호스트 Python 3.12의 합성 검증으로 재현되지 않아 근거와 함께 제외했다. 최종 변경분의 교차 재검토와 전체 검사가 남아 있다.
- 2026-09-09: dc09b86의 전체 회귀 2478 passed/1 skipped, coverage 87.80%, Linux CI와 Grok 수정분 리뷰(추가 P1/P2 없음)를 확인했다. 이후 완료된 GitHub 자동 리뷰에 따라 파일인 기본 source를 게시 전 거부하고, manifest와 같은 이름의 출력 디렉터리를 지원하도록 보완했다. 이번 create/restore 지원 플랫폼은 검증된 Linux/macOS로 명시하며 다른 환경은 쓰기 전 거부한다. 백업 pipeline 64개·CLI 13개, Ruff·mypy·복잡도 검사가 통과했고 생성 문서를 갱신했다. 이 수정분의 최종 검증 후 머지하며 실제 운영 capture는 아직 미실행이다.

- 2026-09-09: #451 머지(2c1ad6f). 최종 회귀 2486 passed/1 skipped, coverage 87.81%, Ruff·mypy·복잡도·pre-commit과 Linux CI 통과. 머지 artifact의 0.7.2를 별도로 설치해 합성 create/verify/retry/restore 검증을 마쳤다. 기존 운영 프로그램은 0.7.1을 유지한다.
- 2026-09-09: 실제 동결 전체 사본과 Linux 격리 복원이 통과했다. 전체 원본 fingerprint 보존, 모든 manifest entry의 내용·권한·수정 시각 일치, 기존 프로그램의 대표 조회 4개 일치 및 서비스 정상 재개를 확인했다. 첫 시도는 서비스가 failed 상태로 종료돼 원본 캡처 전에 중단됐으며, PID·cgroup 정지 판정 보완과 20개 합성 시험 후 재취득했다. 실패 기록은 보존한다.
- 2026-09-09: 실제 암호화 장비 밖 snapshot과 전체 데이터 검사를 통과했다. 원본 장비 접속 없이 새 경로로 내려받고 복원된 artifact에서 0.7.1·0.7.2를 새로 설치해 모든 manifest entry와 대표 조회 4개를 검증했다. 첫 Mac 해제에서 Unicode 파일명 표현이 바뀌어 검사가 실패했고, 정확한 파일명·PAX 나노초 시각을 보존하는 해제 절차로 보완했다. 실패 조사까지 포함한 실증은 약 360초, 성공한 새 독립 시도는 약 34초였다. 이는 정기 백업 RPO 보장을 의미하지 않는다.
- 2026-09-09: 운영 보완의 최종 교차 검토는 아직 남아 있다. 수정된 복구 절차도 장비 밖 별도 snapshot으로 보관하고 내려받은 모든 파일 hash가 일치함을 확인했다. 최종 교차 검토 후 실제 AC에 따라 #431·#432·#426을 닫는다. 금융 자료·운영 경로·키·상세 보고서는 비공개 증거로 유지한다.
