# Rule Editing Workflow with Claude Code CLI

Claude Code CLI를 활용하여 tagging rules (`rules.yaml`)를 효율적으로 편집하는 방법을 실전 시나리오와 함께 안내합니다.

---

## 📋 Overview

이 가이드는 Claude Code CLI를 사용하여 거래 내역 태그 규칙을 추가, 수정, 최적화하는 실용적인 워크플로우를 제공합니다.

**주요 장점**:
- 🤖 AI 어시스턴트가 자동으로 규칙 패턴 생성
- 🔍 기존 규칙과의 충돌 자동 감지
- ✅ Before/After 비교로 변경사항 명확히 확인
- 🚀 즉시 검증 가능한 커맨드 제공

**예상 소요 시간**: 규칙 1개당 2-5분

---

## 🎯 Prerequisites

다음 사항을 준비해주세요:

- ✅ Claude Code CLI 설치 및 인증 완료
- ✅ `~/.finjuice/rules.yaml` 파일 존재 (없으면 `data/examples/rules.yaml` 복사)
- ✅ 기본적인 YAML 문법 이해
- ✅ `finjuice` CLI 사용 가능

**확인 방법**:
```bash
# Claude CLI 확인
claude --version

# Rules 파일 확인
ls ~/.finjuice/rules.yaml

# finjuice 확인
finjuice --help
```

---

## 📚 Quick Reference

| 시나리오 | Claude 명령어 패턴 | 예상 시간 |
|----------|-------------------|-----------|
| 새 가맹점 추가 | `claude "rules.yaml에 [가맹점명] 규칙 추가"` | 2분 |
| 카테고리 변경 | `claude "rules.yaml에서 [가맹점] 태그 변경"` | 3분 |
| 패턴 매칭 | `claude "rules.yaml에 [패턴] 정규식 규칙 추가"` | 5분 |
| 메모 태그 | `claude "memo_raw 필드로 [키워드] 태깅"` | 4분 |
| 우선순위 조정 | `claude "rules.yaml 우선순위 충돌 해결"` | 5분 |

---

## 🎬 Real-World Scenarios

### Scenario 1: 새로운 가맹점 추가 (Beginner)

#### 문제 상황
뱅크샐러드 export에서 "투썸플레이스" 거래 내역이 태그되지 않아 리포트에서 누락됩니다.

#### 해결 방법

**1. Claude에게 규칙 추가 요청**:
```bash
claude "~/.finjuice/rules.yaml 파일을 읽고, '투썸플레이스' 가맹점을 '카페', '커피' 태그로 분류하는 규칙을 추가해줘. 스타벅스 규칙과 비슷한 우선순위(80)로 설정하고, 변경 전후를 보여줘"
```

**2. Claude 응답 예시**:

> 📝 **변경 전 (rules.yaml 일부)**:
> ```yaml
> # 카페
> - name: cafe_starbucks
>   match: "스타벅스|STARBUCKS"
>   fields: [merchant_raw]
>   tags: ["카페", "커피"]
>   priority: 80
> ```
>
> 📝 **변경 후 (추가된 규칙)**:
> ```yaml
> # 카페
> - name: cafe_starbucks
>   match: "스타벅스|STARBUCKS"
>   fields: [merchant_raw]
>   tags: ["카페", "커피"]
>   priority: 80
>
> - name: cafe_twosome
>   match: "투썸플레이스|투썸|TWOSOME"
>   fields: [merchant_raw]
>   tags: ["카페", "커피"]
>   priority: 80
> ```

**3. 변경사항 적용 확인**:
```bash
# Claude가 파일을 수정했는지 확인
git -C ~/.finjuice diff -- rules.yaml

# 규칙 적용 및 검증
finjuice tag

# 결과 확인
finjuice export
# exports/reports/by_tag.csv에서 "카페" 태그 증가 확인
```

#### 💡 Tips
- **다양한 표기 포함**: "투썸플레이스|투썸|TWOSOME" 처럼 여러 버전을 OR(|) 연산자로 연결
- **기존 규칙 참고**: 비슷한 카테고리 규칙을 찾아 동일한 priority 사용
- **즉시 검증**: `finjuice tag` 실행 후 exports/ 폴더에서 결과 확인

---

### Scenario 2: 카테고리 분류 변경 (Intermediate)

#### 문제 상황
"GS25" 거래가 "편의점, 식비" 태그로 분류되는데, 실제로는 주로 생활용품 구매에 사용합니다. "편의점, 생활용품"으로 변경하고 싶습니다.

#### 해결 방법

**1. Claude에게 수정 요청**:
```bash
claude "~/.finjuice/rules.yaml에서 convenience_gs25 규칙의 태그를 '편의점, 식비'에서 '편의점, 생활용품'으로 변경해줘. 변경 전후 비교도 보여줘"
```

**2. Claude 응답 예시**:

> 📝 **변경 전**:
> ```yaml
> # 편의점
> - name: convenience_gs25
>   match: "GS25|GS리테일"
>   fields: [merchant_raw]
>   tags: ["편의점", "식비"]
>   priority: 75
> ```
>
> 📝 **변경 후**:
> ```yaml
> # 편의점
> - name: convenience_gs25
>   match: "GS25|GS리테일"
>   fields: [merchant_raw]
>   tags: ["편의점", "생활용품"]
>   priority: 75
> ```

**3. 검증 및 재분류**:
```bash
# 변경사항 확인
git -C ~/.finjuice diff -- rules.yaml

# 전체 거래 내역 재태깅 (기존 태그 덮어쓰기)
finjuice tag

# 결과 확인
finjuice export
cat exports/reports/by_tag.csv | grep "생활용품"
```

#### ⚠️ 주의사항
- **전체 재태깅 기본 동작**: `finjuice tag`는 현재 CSV 파티션 전체에 규칙을 다시 적용합니다
- **태그 일관성**: 다른 규칙에서도 "생활용품" 태그를 사용하는지 확인하여 리포트 정확도 향상

---

### Scenario 3: 복잡한 패턴 매칭 (Intermediate-Advanced)

#### 문제 상황
"병원", "의원", "종합병원" 등 다양한 의료기관을 구분하여 태깅하고 싶습니다. 특히 "종합병원"은 높은 우선순위로 분류하고, 일반 "의원"은 낮은 우선순위로 처리하려 합니다.

#### 해결 방법

**1. Claude에게 계층적 규칙 생성 요청**:
```bash
claude "~/.finjuice/rules.yaml에 의료기관 규칙을 추가해줘:
1. '종합병원' 키워드 포함 시 '의료', '종합병원' 태그, priority 90
2. '병원' 또는 '의원' 키워드는 '의료', '병원' 태그, priority 75
3. 정규식 패턴을 사용해서 종합병원이 우선 매칭되도록 설정
변경 전후와 함께 설명도 추가해줘"
```

**2. Claude 응답 예시**:

> 📝 **추가될 규칙** (우선순위 순서대로):
> ```yaml
> # 의료 - 종합병원 (높은 우선순위)
> - name: medical_general_hospital
>   match: "종합병원|대학병원|.*병원.*종합"
>   fields: [merchant_raw, minor_raw]
>   tags: ["의료", "종합병원"]
>   priority: 90
>
> # 의료 - 일반 병원/의원
> - name: medical_clinic
>   match: "병원|의원|클리닉|CLINIC"
>   fields: [merchant_raw, minor_raw]
>   tags: ["의료", "병원"]
>   priority: 75
> ```
>
> 💡 **동작 원리**:
> - Priority 90 규칙이 먼저 체크되므로 "서울종합병원"은 `["의료", "종합병원"]` 태그 획득
> - "삼성서울병원"처럼 "종합"이 명시되지 않아도 `.*병원.*종합` 패턴으로 매칭 가능
> - Priority 75 규칙은 "동네이비인후과" 같은 일반 의원에만 적용

**3. 검증 - 실제 거래로 테스트**:
```bash
# 규칙 적용
finjuice tag

# 종합병원 태그 확인
finjuice export
cat exports/reports/by_tag.csv | grep "종합병원"

# (Optional) 특정 거래 확인
cat exports/master_*.csv | grep "종합병원"
```

#### 💡 Advanced Tips
- **정규식 테스트**: 복잡한 패턴은 [regex101.com](https://regex101.com)에서 먼저 테스트
- **Priority 갭**: 유사 카테고리 간 priority를 15-20 차이로 설정하여 명확히 구분
- **Fields 전략**: `merchant_raw`만으로 부족하면 `minor_raw`도 추가하여 정확도 향상

---

### Scenario 4: 메모 기반 태그 추가 (Intermediate)

#### 문제 상황
검진 거래에 "정기검진" 메모를 추가했는데, 이를 별도 태그로 분류하고 싶습니다.

#### 해결 방법

**1. Claude에게 메모 필드 규칙 생성 요청**:
```bash
claude "~/.finjuice/rules.yaml에 규칙을 추가해줘:
- memo_raw 필드에 '정기검진' 키워드가 있으면 '검진' 태그 추가
- 의료 카테고리이므로 priority 95 (높은 우선순위)
- 기존 의료 태그와 중복되지 않도록 추가 태그로 설정
변경 전후 보여줘"
```

**2. Claude 응답 예시**:

> 📝 **추가될 규칙**:
> ```yaml
> # 의료 - 정기 검진 (메모 기반, 최고 우선순위)
> - name: medical_checkup
>   match: "정기검진|건강검진|종합검진"
>   fields: [memo_raw]
>   tags: ["의료", "검진"]
>   priority: 95
> ```
>
> 💡 **설명**:
> - `fields: [memo_raw]`: 사용자가 직접 입력한 메모에서만 검색
> - `priority: 95`: 다른 의료 규칙(90, 75)보다 태그 병합 순서와 `category_rule` 선택에서 앞섬
> - `tags`에 "검진" 추가: 나중에 병원/약국 지출과 검진 지출을 분리하기 쉬움

**3. 메모 추가 및 검증**:
```bash
# 1. CSV 파티션에서 직접 메모 수정 (예시)
# ~/.finjuice/transactions/2024/10/transactions.csv
# row_hash,date,time,...,memo_raw,...
# abc123,2024-10-15,14:30,...,"정기검진",...

# 2. 규칙 적용
finjuice tag

# 3. 검진 태그 확인
finjuice export
cat exports/reports/by_tag.csv | grep "검진"
```

#### 💡 Tips
- **memo_raw 우선**: 메모 기반 규칙은 priority를 높게 설정하여 사용자 의도를 최우선 반영
- **다중 태그 전략**: `["의료", "검진", "정기지출"]`처럼 용도별 태그를 함께 추가
- **민감 정보 주의**: 메모에 민감한 개인정보는 기록하지 않도록 주의

---

### Scenario 5: 규칙 우선순위 조정 (Advanced)

#### 문제 상황
"카카오" 거래가 여러 규칙과 충돌합니다:
- "카카오톡" → 디지털서비스
- "카카오택시" → 교통
- "카카오페이" → 온라인결제

우선순위 조정으로 정확한 분류를 원합니다.

#### 해결 방법

**1. 현재 규칙 분석 요청**:
```bash
claude "~/.finjuice/rules.yaml에서 '카카오' 관련 규칙들을 찾아서 우선순위를 보여줘. 만약 없으면 새로 만들고, 있으면 충돌을 해결해줘"
```

**2. Claude가 기존 규칙 발견 시 응답**:

> 📝 **현재 규칙**:
> ```yaml
> # 카카오 서비스
> - name: service_kakao
>   match: "카카오|KAKAO"
>   fields: [merchant_raw]
>   tags: ["디지털서비스", "카카오"]
>   priority: 80
> ```
>
> ⚠️ **문제점**: 모든 "카카오" 거래가 priority 80으로 동일하게 매칭되어 세부 구분 불가능
>
> 📝 **개선된 규칙** (우선순위 계층화):
> ```yaml
> # 카카오 서비스 - 세부 분류 (높은 우선순위)
> - name: kakao_taxi
>   match: "카카오택시|카카오T|KAKAO.*TAXI"
>   fields: [merchant_raw]
>   tags: ["교통", "택시", "카카오"]
>   priority: 90
>
> - name: kakao_talk
>   match: "카카오톡|KAKAOTALK"
>   fields: [merchant_raw]
>   tags: ["디지털서비스", "메신저", "카카오"]
>   priority: 90
>
> - name: kakao_pay
>   match: "카카오페이|KAKAOPAY"
>   fields: [merchant_raw]
>   tags: ["온라인결제", "카카오"]
>   priority: 90
>
> # 카카오 서비스 - 일반 (낮은 우선순위, 폴백)
> - name: service_kakao
>   match: "카카오|KAKAO"
>   fields: [merchant_raw]
>   tags: ["디지털서비스", "카카오"]
>   priority: 70
> ```

**3. 우선순위 동작 원리**:

| Priority | 규칙 | 매칭 예시 | 태그 결과 |
|----------|------|-----------|-----------|
| 90 (높음) | `kakao_taxi` | "카카오택시 강남역" | `["교통", "택시", "카카오"]` |
| 90 (높음) | `kakao_talk` | "카카오톡 이모티콘" | `["디지털서비스", "메신저", "카카오"]` |
| 90 (높음) | `kakao_pay` | "카카오페이" | `["온라인결제", "카카오"]` |
| 70 (낮음) | `service_kakao` | "카카오 기타 서비스" | `["디지털서비스", "카카오"]` |

**4. 검증 및 충돌 디버깅**:
```bash
# 규칙 적용
finjuice tag

# 특정 가맹점으로 필터링하여 확인
finjuice export
cat exports/master_*.csv | grep "카카오" | head -10

# 태그별 집계 확인
cat exports/reports/by_tag.csv | grep "카카오"
```

#### 💡 Advanced Debugging Tips

**우선순위 충돌 확인 방법**:
```bash
# rules.yaml에서 priority 내림차순 정렬 확인
cat ~/.finjuice/rules.yaml | grep -E "priority:|name:" | paste - -

# 예상 출력:
# - name: kakao_taxi    priority: 90
# - name: service_kakao priority: 70
```

**Claude에게 자동 디버깅 요청**:
```bash
claude "~/.finjuice/rules.yaml의 모든 규칙을 priority 내림차순으로 정렬하고, 동일한 match 패턴을 가진 규칙이 있는지 찾아줘. 있으면 충돌 경고와 함께 해결 방법을 제시해줘"
```

---

## 📚 Best Practices

### 1. 규칙 작성 원칙

#### Priority 설정 가이드
- **95-100**: 메모 기반 사용자 의도 (최고 우선순위)
- **85-94**: 구체적 가맹점/서비스 (높은 신뢰도)
- **70-84**: 일반 카테고리 매칭
- **50-69**: 광범위 폴백 규칙

#### Match 패턴 작성
- ✅ **좋음**: `"스타벅스|STARBUCKS|Starbucks"` (다양한 표기)
- ✅ **좋음**: `"종합병원|대학병원"` (유사 키워드 OR)
- ⚠️ **주의**: `".*카페.*"` (너무 광범위, 오탐 가능)
- ❌ **나쁨**: `"스타벅스"` (영문 표기 누락)

#### 태그 전략
- **용도별 분류**: `["의료", "종합병원", "검진"]`
- **일관된 네이밍**: "디지털구독" vs "디지털서비스" (하나로 통일)
- **계층적 구조**: 대분류 → 중분류 → 세분류

#### between 연산자 값 포맷
- `between`은 두 가지 포맷을 모두 지원합니다.
- 권장 포맷은 YAML 리스트입니다: `value: [-50000, -10000]`
- 기존 호환 포맷인 CSV 문자열도 계속 동작합니다: `value: "-50000,-10000"`
- 두 값 모두 숫자여야 하고, 항상 `min <= max` 순서여야 합니다.

```yaml
- name: medium_expense
  conditions:
    - field: amount
      op: between
      value: [-50000, -10000]  # 권장
      # value: "-50000,-10000"  # 기존 호환 포맷
  tags: ["중간지출"]
  priority: 85
```

#### 다중 conditions + `logic: all` 예시
- 아래 예시는 `merchant_raw`, `type_norm`, `amount`를 함께 묶는 조건식 규칙입니다.
- 조건식 전체 문법은 [`docs/reference/rules-conditions.md`](../reference/rules-conditions.md) 기준으로 확인하세요.

```yaml
- name: coffee_subscription_charge
  conditions:
    - field: merchant_raw
      op: contains
      value: "스타벅스"
    - field: type_norm
      op: is
      value: "expense"
    - field: amount
      op: between
      value: [-20000, -3000]
  logic: all
  tags: ["카페", "정기결제"]
  priority: 82
```

### 2. Claude Code CLI 활용 팁

#### 효과적인 프롬프트 작성
```bash
# ✅ 좋은 예시: 구체적이고 명확
claude "~/.finjuice/rules.yaml에서 convenience_gs25 규칙의 tags를 ['편의점', '생활용품']으로 변경하고, 변경 전후를 보여줘"

# ⚠️ 나쁜 예시: 모호함
claude "GS25 태그 바꿔줘"
```

#### Before/After 비교 요청
항상 변경 전후를 명시적으로 요청:
```bash
claude "... 변경해줘. 변경 전후(Before/After)를 YAML 코드 블록으로 보여줘"
```

#### 변경 이유 설명 요청
```bash
claude "... 규칙을 추가하고, 왜 이렇게 설정했는지 이유도 설명해줘"
```

### 3. 검증 워크플로우

#### 단계별 검증
```bash
# 1. 규칙 수정 확인
git -C ~/.finjuice diff -- rules.yaml

# 2. 태깅 적용
finjuice tag

# 3. 결과 확인
finjuice export

# 4. 리포트 검토
cat exports/reports/by_tag.csv
cat exports/reports/by_account.csv

# 5. 문제 없으면 커밋
git -C ~/.finjuice add rules.yaml
git -C ~/.finjuice commit -m "feat: add rule for [규칙명]"
```

#### 특정 거래 검증
```bash
# 특정 가맹점 검색
cat exports/master_*.csv | grep "스타벅스"

# 특정 태그 필터링
cat exports/master_*.csv | grep "\"카페\""

# 날짜 범위 필터링
cat exports/master_*.csv | grep "2024-10"
```

#### Quick dry-run with `finjuice rules test`
```bash
# 규칙 1개만 읽기 전용으로 매칭 범위 확인
finjuice rules test llm_service --month 2024-10

# 오타가 있으면 비슷한 규칙명 제안
finjuice rules test llm_servicx
# Rule not found: llm_servicx
# Did you mean: llm_service
```

> 조건 연산자 의미는 [Conditional Rule Engine Reference](../reference/rules-conditions.md) 참고.

---

## 🔧 Troubleshooting

### 문제 1: 규칙이 적용되지 않음

**증상**: 규칙을 추가했는데 태그가 변경되지 않음

**원인 및 해결**:

1. **기본 데이터 디렉토리 외 다른 위치 사용 중**
   ```bash
   # ❌ 잘못된 방법: 기본 ~/.finjuice를 태깅함
   finjuice tag

   # ✅ 올바른 방법: 실제 데이터 위치를 지정
   finjuice --data-dir ~/Documents/my-finance-data tag
   ```

2. **Priority 충돌**
   ```bash
   # 기존 규칙이 새 규칙보다 priority가 높음
   # 해결: Claude에게 우선순위 조정 요청
   claude "~/.finjuice/rules.yaml에서 [규칙명]의 priority를 [새값]으로 변경해줘"
   ```

3. **Match 패턴 오류**
   ```bash
   # YAML 문법 검증
   python -c "from pathlib import Path; import yaml; yaml.safe_load(open(Path('~/.finjuice/rules.yaml').expanduser()))"

   # 정규식 테스트 (Python REPL)
   python
   >>> import re
   >>> re.search("스타벅스|STARBUCKS", "STARBUCKS 강남점", re.IGNORECASE)
   # <re.Match object ...> (성공)
   ```

### 문제 2: 우선순위 충돌 디버깅

**증상**: 특정 거래가 예상과 다른 태그를 받음

**디버깅 단계**:

1. **해당 거래의 merchant_raw 확인**:
   ```bash
   cat exports/master_*.csv | grep "2024-10-15" | grep "스타벅스"
   ```

2. **매칭되는 규칙 찾기**:
   ```bash
   claude "~/.finjuice/rules.yaml에서 '스타벅스'와 매칭되는 모든 규칙을 priority 순서대로 나열해줘"
   ```

3. **Priority 순서 검증**:
   ```bash
   cat ~/.finjuice/rules.yaml | grep -A 5 "스타벅스"
   ```

4. **해결: 우선순위 조정**:
   ```bash
   claude "~/.finjuice/rules.yaml에서 cafe_starbucks 규칙의 priority를 85로 올려줘"
   ```

### 문제 3: 정규식 패턴 오류

**증상**: `SyntaxError` 또는 예상치 못한 매칭

**해결 방법**:

1. **특수문자 이스케이프**:
   ```yaml
   # ❌ 잘못된 예시
   match: "(주)카카오"

   # ✅ 올바른 예시
   match: "\\(주\\)카카오"
   ```

2. **Regex 테스트 사이트 활용**:
   - https://regex101.com (Python flavor 선택)
   - Test String에 실제 merchant_raw 값 입력

3. **Claude에게 정규식 생성 요청**:
   ```bash
   claude "'(주)카카오' 문자열을 정확히 매칭하는 Python 정규식 패턴을 만들어줘. 특수문자 이스케이프 포함"
   ```

### 문제 4: YAML 문법 오류

**증상**: `finjuice tag` 실행 시 `YAMLError` 발생

**해결**:

1. **YAML 문법 검증**:
   ```bash
   python -c "from pathlib import Path; import yaml; print(yaml.safe_load(open(Path('~/.finjuice/rules.yaml').expanduser())))"
   ```

2. **들여쓰기 확인**:
   ```yaml
   # ❌ 잘못된 들여쓰기
   rules:
   - name: test
     match: "test"
       tags: ["test"]  # 들여쓰기 틀림

   # ✅ 올바른 들여쓰기
   rules:
     - name: test
       match: "test"
       tags: ["test"]
   ```

3. **Claude에게 수정 요청**:
   ```bash
   claude "~/.finjuice/rules.yaml 파일의 YAML 문법 오류를 찾아서 수정해줘"
   ```

---

## 🔗 Related Documentation

- [CLAUDE.md](../../CLAUDE.md) - Claude Code CLI 슬래시 커맨드 레퍼런스
- [templates/schema.yaml](../../templates/schema.yaml) - 데이터 스키마 및 `tags_final` 필드 정의
- [docs/architecture/specs/v0_initial.md](../architecture/specs/v0_initial.md) - 태깅 정책 및 규칙 엔진 상세 설명
- [data/examples/rules.yaml](../../data/examples/rules.yaml) - 전체 규칙 예시 파일

---

## 📝 Appendix: Claude Prompt Templates

자주 사용하는 Claude 프롬프트 템플릿 모음:

### 신규 규칙 추가
```bash
claude "~/.finjuice/rules.yaml에 새 규칙을 추가해줘:
- 가맹점명: [이름]
- 태그: [태그1, 태그2]
- Priority: [숫자]
- 비슷한 규칙: [참고할 규칙명]
변경 전후와 함께 이유도 설명해줘"
```

### 기존 규칙 수정
```bash
claude "~/.finjuice/rules.yaml에서 [규칙명] 규칙의 [필드명]를 [이전값]에서 [새값]으로 변경해줘. 변경 전후 비교 보여줘"
```

### 우선순위 조정
```bash
claude "~/.finjuice/rules.yaml의 모든 규칙을 priority 내림차순으로 정렬하고, [카테고리] 관련 규칙들의 우선순위가 올바른지 검증해줘. 문제가 있으면 수정안을 제시해줘"
```

### 충돌 감지
```bash
claude "~/.finjuice/rules.yaml에서 동일한 match 패턴을 가진 규칙들을 찾아서, priority 순서와 함께 나열해줘. 충돌이 있으면 해결 방법도 제안해줘"
```

### 패턴 생성
```bash
claude "'[가맹점명]'을 포함하는 거래를 매칭하는 정규식 패턴을 만들어줘. 한글/영문/대소문자를 모두 고려하고, 특수문자 이스케이프도 처리해줘"
```

---

**작성일**: 2025-11-20
**버전**: 1.0
**관련 Issue**: #7 (Rule Editing Workflow Documentation)
