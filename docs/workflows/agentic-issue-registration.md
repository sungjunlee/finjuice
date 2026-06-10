# Agentic Issue Registration Workflow (LLM + Template)

## Goal
GitHub 이슈 등록 자동화 스크립트 없이, 템플릿 기반으로 LLM이 등록하고 이후 `/issue-*` 워크플로우로 구현까지 이어지게 한다.

## Source of Truth
1. 계획/결정: `docs/plans/discussions/` 및 `docs/plans/execution/`
2. 템플릿: `docs/plans/templates/github-milestone-epic-issue-template.md`
3. 실행 워크플로우: `CLAUDE.md`의 `/issue-*` 명령 세트

## Step 1) Plan 정리
1. Milestone 목표/기한/비범위를 확정한다.
2. Epic과 Child Issue를 분해한다.
3. 각 항목에 `Plan-Key`를 부여한다.

## Step 2) Issue 본문 작성
템플릿의 필수 8섹션을 그대로 사용한다.
- Context
- Goal
- In Scope
- Out of Scope
- Inputs
- Checklist
- Verification
- Done Criteria

작성 시 품질 규칙:
1. `Verification`은 최소 1개 이상 실행 가능한 명령을 포함한다.
2. Epic Checklist는 "이슈 생성/연결"이 아니라 "진행/품질 게이트" 점검 항목으로 작성한다.
3. Done Criteria는 관찰 가능한 결과(닫힌 이슈, 통과 테스트, 생성 산출물)로 측정 가능해야 한다.

## Step 3) LLM으로 GitHub 등록
LLM에 아래 조건을 함께 전달한다.
1. 기존 이슈에서 동일 `Plan-Key`가 있는지 먼저 확인
2. 없다면 생성, 있으면 업데이트
3. 본문에 `Parent/Depends-on/Plan-Key`를 유지
4. GitHub native Sub-issue/Dependency도 연결

추천 프롬프트:
```md
`docs/plans/templates/github-milestone-epic-issue-template.md` 기준으로
Milestone/Epic/Issue를 생성/업데이트해줘.
중복 방지를 위해 Plan-Key를 먼저 확인하고,
생성 후 Sub-issue와 blocked-by dependency를 연결해줘.
```

## Step 4) 등록 후 검증
1. 모든 Child issue가 Parent epic을 가리키는지 확인
2. Depends-on 관계가 native dependency에도 반영됐는지 확인
3. Milestone due date와 범위가 계획 문서와 동일한지 확인
4. Deferred 항목은 milestone 없이 `deferred` 라벨만 적용
5. 모든 이슈의 Verification이 실행 커맨드 중심인지 확인

## Step 5) Plan-Key ↔ Issue 번호 매핑 고정
1. 등록 결과를 표로 기록한다. (예: `Plan-Key`, `Issue #`, `URL`)
2. 구현 대상은 반드시 `Plan-Key`와 `Issue #`를 함께 확인한다.
3. 매핑 표는 실행 문서(`docs/plans/execution/...`)에 최신 상태로 유지한다.

## Step 6) 구현 실행
1. `/issue-start N`
2. `/issue-tdd N --feature "..."`
3. `/issue-review`
4. `/issue-pr`
5. `/issue-done`

## Step 7) 이슈 품질 리프레시(주간)
1. Epic/Deferred 이슈의 Checklist/Verification이 실행 단계에 맞는지 점검한다.
2. Verification이 서술형으로만 남아 있으면 실행 명령으로 치환한다.
3. 완료된 child 반영으로 Parent Done Criteria를 최신 상태로 갱신한다.

## 운영 원칙 (Lean)
1. 신규 자동화 스크립트보다 템플릿 일관성을 우선한다.
2. 이슈당 결정이 남지 않도록 본문을 결정완료 수준으로 작성한다.
3. Scope creep를 막기 위해 Out of Scope를 반드시 유지한다.
4. 이슈는 에이전트가 단독으로 실행 가능한 수준(입력/검증/완료기준 명확화)으로 유지한다.

## References (2026-02 refresh)
1. GitHub Copilot coding agent - issue quality guidance:
   https://docs.github.com/en/copilot/tutorials/coding-agent/get-the-best-results
2. GitHub issue dependencies:
   https://docs.github.com/en/issues/tracking-your-work-with-issues/using-issues/creating-issue-dependencies
3. GitHub sub-issues:
   https://docs.github.com/en/issues/tracking-your-work-with-issues/using-issues/adding-sub-issues
4. GitHub issue forms syntax:
   https://docs.github.com/en/enterprise-cloud@latest/communities/using-templates-to-encourage-useful-issues-and-pull-requests/syntax-for-issue-forms
