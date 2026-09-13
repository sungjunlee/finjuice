# M2 mutation PR의 main 0.8.3 통합

2026-09-13. PR #463 (`codex/ssot-m2-mutations`)의 기반 main을 `309c42b`로 갱신한다. 이전 head는 `4fcf0b7`이며, 후속 migration/read 작업은 PR #481에서 별도로 진행한다.

## 통합한 동작

- 다른 작업에서 머지한 #477–499의 release, 대사 보완, tag/rules CLI, explain/doctor, 예산, suggest 수정과 0.8.3을 보존했다.
- 충돌4파일은 rules mutations, tag, tag_edit, rules-add 테스트다. 기존에 검증한 main 통합 해법을 대조하여 SQLite UUID/legacy hash 분기, 활성 mutation/receipt 계약, 잘못된 legacy hash의 조기 거부, rules focus/post-removal validation을 함께 유지했다.
- 후속 PR481 전용 migration/read 구현은 이 기반 PR에 포함하지 않았다. 운영 데이터 이전과 SQLite 활성화는 수행하지 않았다.

## 검증

- 전체 pytest: 3,197 PASS·1 SKIP, coverage89.31%, 193.52s.
- 관련203 PASS(8.18s), Ruff/format, mypy426, complexity122, 적용 pre-commit 및 CLI 문서 생성 통과.
- 프로젝트 lock 기반의 별도 wheel 설치본:85 PASS(15.77s). 로드된389개 모듈의 설치경로, 변경 production22개 및 JSON schema57개의 SHA256 일치.
- Cursor/Grok4.6high 교차 리뷰 exit0/640.36s: 근거있는P1/P2없음. 충돌4파일 및자동merge를양쪽parent와대조했고범위한정프로브도통과했다. SQLite UUID는CSV전용16hex검증전에분기됨을확인했다. 위결과는GitHub승인이나새head의CI를대신하지않으며, push후CI결과는PR463에서확인한다.

## 다음 조건

GitHub 필수 비작성자 승인과 새 head의 적용 CI를 충족한 후 머지한다. PR481은 이 기반 commit을 통합하고 자산·현황의 정본 조회를 계속한다. #435 전수 보존, #436 전체 소비자 parity, 실제 운영 전환은 미완료다.
