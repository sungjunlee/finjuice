# Design Review: Finjuice Skill-CLI Integration

> **Date**: 2025-12-27
> **Status**: Review Complete
> **Reviewer**: Claude Code with skill-creator best practices

---

## Executive Summary

현재 finjuice 스킬은 **첫 번째 시도**로서 기본 구조는 갖추었으나, skill-creator 가이드라인과 비교 시 **중요한 설계 개선이 필요**합니다.

### Critical Issues (3)
1. **CLI 명령어와 스킬 중복** - 이미 존재하는 CLI를 스킬에서 Polars 코드로 재구현
2. **Progressive Disclosure 미적용** - 405줄 단일 파일 (권장: <500줄, 핵심만)
3. **Frontmatter description 부족** - 트리거 조건이 body에 분산

### High Priority Gaps (5)
1. `finjuice suggest-rules --apply` 미노출 (Interactive Tagging의 핵심 기능)
2. `finjuice insights` 미노출 (이상치/트렌드 감지)
3. `finjuice ask --report` 8개 중 3개만 문서화
4. `finjuice stats` 풍부한 옵션 미노출
5. Polars 코드 예제 중복 (5개 capability에서 같은 패턴 반복)

---

## 1. Skill-Creator 가이드라인 대비 분석

### 1.1 Frontmatter Description

**현재 상태 (문제):**
```yaml
description: |
  Personal finance assistant for Banksalad data.
  뱅크샐러드 데이터용 개인 금융 어시스턴트.
  Supports: interactive tagging, spending analysis, subscription detection, report generation.
```

**문제점:**
- "When to use" 정보가 body에 분산되어 있음
- 트리거 조건이 description에 포함되지 않음
- skill-creator: "Include all 'when to use' information here - Not in the body"

**권장 수정:**
```yaml
description: |
  Personal finance assistant for Banksalad transaction data.
  뱅크샐러드 거래 데이터용 개인 금융 어시스턴트.

  Use when user:
  - Asks about spending: "월별 지출", "10월 얼마 썼어?", "태그별 분석"
  - Mentions tagging: "태깅률", "미태깅", "규칙 추가"
  - Asks about subscriptions: "구독료", "정기 결제", "매달 나가는 돈"
  - Wants reports: "리포트", "분석해줘", "export"
  - Mentions cards: "카드 혜택", "어떤 카드"

  Capabilities: interactive tagging, monthly/tag analysis, subscription detection, card rewards, insights/anomalies.
```

### 1.2 Conciseness (간결성)

**현재 상태 (문제):**
- SKILL.md: 405줄
- 각 capability에 ~80-100줄의 Polars 코드 예제
- 같은 data loading 패턴이 5번 반복

**skill-creator 원칙:**
> "Only add context Claude doesn't already have. Challenge each piece of information: 'Does Claude really need this explanation?'"

**문제점:**
- Claude는 이미 Polars 코드 작성 가능 - 모든 예제 불필요
- CLI 명령어가 존재하면 Polars 코드는 불필요
- `load_transactions()` 함수가 Common Patterns에서 정의되고, 각 capability에서 다시 작성됨

### 1.3 Progressive Disclosure

**현재 상태 (문제):**
```
finjuice/
└── SKILL.md (405 lines - everything in one file)
```

**권장 구조:**
```
finjuice/
├── SKILL.md (~150 lines - core workflow only)
└── references/
    ├── cli-commands.md (full CLI reference)
    ├── polars-patterns.md (code examples if needed)
    └── report-types.md (8 report types documentation)
```

---

## 2. CLI-Skill Integration Gap Analysis

### 2.1 Critical: Interactive Tagging vs `suggest-rules --apply`

**스킬에서 정의된 Capability 1 워크플로우:**
```
1. Analyze untagged: Group by merchant_raw
2. Present patterns: Show top untagged
3. User confirms: User explains
4. Generate rules: Create YAML
5. Apply & report: Run finjuice tag
```

**이미 존재하는 CLI 명령어:**
```bash
finjuice suggest-rules --apply      # 위 워크플로우를 CLI로 구현!
finjuice suggest-rules --apply --yes   # 자동 적용
```

**Gap:** 스킬이 CLI를 활용하지 않고 Polars 코드로 재구현하고 있음.

**권장:** Capability 1을 아래로 수정:
```markdown
### Execution
finjuice suggest-rules --apply
```

### 2.2 Missing: `finjuice insights`

**CLI 기능:**
```bash
finjuice insights                 # 이상치, 트렌드, 규칙 제안
finjuice insights --period 2024-11
finjuice insights -i              # Interactive mode
```

**스킬 현재 상태:** 언급 없음

**권장:** 새 Capability 추가 또는 기존 capability에 통합

### 2.3 Incomplete: `finjuice ask --report` Types

| Report Type | CLI 지원 | SKILL 문서화 |
|-------------|---------|-------------|
| `monthly` | ✅ | ✅ |
| `summary` | ✅ | ❌ |
| `tags` | ✅ | ✅ |
| `merchants` | ✅ | ❌ |
| `subscriptions` | ✅ | ⚠️ 부분 |
| `anomalies` | ✅ | ❌ |
| `transfers` | ✅ | ❌ |

**Gap:** 8개 report type 중 3개만 문서화

### 2.4 Underutilized: `finjuice stats`

**CLI 옵션:**
```bash
finjuice stats --tag 식비        # 태그 필터링
finjuice stats --account 삼성카드  # 계정 필터링
finjuice stats --since 2024-01   # 기간 필터링
finjuice stats --json            # JSON 출력
finjuice stats --brief           # 요약
```

**스킬 현재 상태:**
```bash
finjuice stats --since 2024-10 --until 2024-11  # 기본만
```

---

## 3. Degrees of Freedom 분석

### 3.1 현재 문제

스킬이 **모든 작업에 낮은 자유도**를 적용 - 상세한 Polars 코드 제공

하지만 skill-creator 가이드에 따르면:
- **높은 자유도**: 다양한 접근법이 유효할 때 (텍스트 지침)
- **낮은 자유도**: 작업이 취약하고 오류 발생 쉬울 때 (스크립트)

### 3.2 권장 자유도 매핑

| Capability | 권장 자유도 | 근거 |
|------------|------------|------|
| Interactive Tagging | 높음 | CLI로 해결, 다양한 대화 가능 |
| Monthly Spending | 높음 | `finjuice stats` 또는 `ask --report monthly` |
| Tag Breakdown | 높음 | `finjuice ask --report tags` |
| Subscription Detection | 중간 | `ask --report subscriptions` + 휴리스틱 |
| Card Rewards | 중간 | 설정 파일 의존, 일부 가이드 필요 |

---

## 4. 권장 개선안

### 4.1 즉시 적용 (Quick Wins)

1. **Frontmatter description 강화**
   - 모든 트리거 조건을 description에 포함
   - Body의 "When to Use" 섹션 제거 또는 축소

2. **CLI 우선 접근으로 전환**
   - Polars 코드 예제 제거
   - 대신 해당 CLI 명령어 문서화

3. **Missing report types 추가**
   - `summary`, `merchants`, `anomalies`, `transfers`

### 4.2 구조 개선 (Medium Term)

1. **Progressive Disclosure 적용**
   ```
   SKILL.md: ~150줄 (핵심 워크플로우만)
   references/cli-reference.md: CLI 명령어 상세
   references/polars-examples.md: 고급 사용자용 코드 예제
   ```

2. **Capability 통합/재구성**
   - Capability 1 (Interactive Tagging) → `finjuice suggest-rules --apply` 활용
   - Capability 6 추가: Insights & Anomalies → `finjuice insights`

### 4.3 CLI 개선 필요 (Skill이 의존할 수 있도록)

1. **`finjuice tag --interactive`**: 대화형 태깅 모드
2. **`finjuice ask --interactive`**: 연속 대화 모드 (이미 존재)
3. **출력 형식 통일**: 모든 명령어에서 일관된 JSON/Markdown 출력

---

## 5. 리팩토링 우선순위

### P0: Critical (즉시 수정)
- [ ] Frontmatter description에 트리거 조건 추가
- [ ] Capability 1: `suggest-rules --apply` 사용하도록 변경
- [ ] Missing report types 문서화

### P1: High (다음 스프린트)
- [ ] Polars 코드 예제 제거 또는 references/로 이동
- [ ] `finjuice insights` capability 추가
- [ ] Progressive Disclosure 구조로 분리

### P2: Medium (후속)
- [ ] CLI 개선: `finjuice tag --interactive`
- [ ] references/ 폴더 구조화
- [ ] 테스트 케이스: 트리거 조건 검증

---

## 6. 예상 결과

### Before (현재)
- SKILL.md: 405줄
- CLI 활용: 30%
- 중복 코드: 5개 capability에서 동일 패턴
- 트리거 정확도: 낮음 (description 부족)

### After (개선 후)
- SKILL.md: ~150줄 + references/
- CLI 활용: 90%
- 중복 코드: 0 (CLI로 대체)
- 트리거 정확도: 높음 (comprehensive description)

---

## 7. Action Items

1. **GitHub Issue 생성**: `#159 - Skill-CLI Integration Improvements`
2. **SKILL.md 리팩토링 PR**: 위 권장사항 적용
3. **CLI 문서 업데이트**: skill에서 참조할 수 있도록
4. **테스트**: 트리거 조건 검증 (다양한 user intent로 테스트)

---

## References

- [skill-creator 가이드](~/.claude/plugins/cache/anthropic-agent-skills/document-skills/skills/skill-creator/SKILL.md)
- [finjuice CLI 도움말](finjuice --help)
- [현재 SKILL.md](skills/finjuice/SKILL.md)
