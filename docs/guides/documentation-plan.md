# 📚 사용자 문서화 계획 (User Documentation Plan)

> **목표**: 비개발자도 5분 안에 시작할 수 있는 쉬운 한국어 문서
> **작성일**: 2025-12-06
> **우선순위**: 사용자 경험 > 기술 정확성 (단, 핵심은 정확하게)

---

## 🎯 핵심 원칙

1. **5분 시작 원칙**: 처음 사용자가 5분 안에 첫 리포트를 볼 수 있어야 함
2. **스크린샷 위주**: 텍스트 설명보다 실제 화면 캡처
3. **단계별 체크리스트**: ✅ 마크를 사용하여 진행 상황 확인
4. **실전 예시 우선**: 이론보다 "내 카페 지출 확인하기" 같은 실용적 예시
5. **문제 해결 먼저**: 막힐 만한 지점을 미리 예측하고 FAQ 제공

---

## 📋 문서 구조 (3단계)

### Phase 1: 핵심 사용자 가이드 (우선순위 높음)

#### 1.1 빠른 시작 가이드 (`docs/guides/ko/quickstart.md`)

**목표**: 15분 안에 첫 리포트 생성

**내용**:
```markdown
# 🚀 빠른 시작 (15분)

## 준비물 체크리스트
- [ ] 뱅크샐러드 앱 설치됨
- [ ] macOS/Linux 컴퓨터 (Windows는 별도 가이드)
- [ ] 커피 한 잔 ☕

## 단계 1: 뱅크샐러드에서 데이터 내보내기 (3분)
[스크린샷 1: 앱 설정 메뉴]
[스크린샷 2: 데이터 관리 > 내보내기]
[스크린샷 3: XLSX 파일 다운로드]

💡 **주의**: "가계부 내역" 시트만 지원합니다!

## 단계 2: 프로그램 설치 (5분)
```bash
# Homebrew 설치 (없으면)
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# finjuice 설치
brew tap sungjunlee/banksalad
brew install finjuice
```

[스크린샷 4: 터미널 명령어 실행 예시]

✅ 설치 확인:
```bash
finjuice --version
# → finjuice version 0.2.0
```

## 단계 3: 초기 설정 (2분)
```bash
finjuice init
```

[스크린샷 5: 디렉토리 구조 생성 확인]

## 단계 4: 데이터 넣고 실행 (5분)
```bash
# 1. XLSX 파일 복사
cp ~/Downloads/뱅크샐러드_2024-*.xlsx data/imports/

# 2. 실행!
finjuice refresh
```

[스크린샷 6: 파이프라인 실행 중]
[스크린샷 7: 완료 메시지]

## 단계 5: 결과 확인 🎉
```bash
# 리포트 폴더 열기
open data/exports/reports/
```

[스크린샷 8: 리포트 파일 목록]
[스크린샷 9: monthly_spend.csv 엑셀에서 열기]

✅ **성공!** 이제 월별 지출을 볼 수 있습니다!

## 다음 단계
- [태그 설정하기](tagging-guide.md) - 내 지출을 카테고리별로 분류
- [리포트 읽는 법](report-guide.md) - 숫자가 의미하는 것
```

**작업 시간**: 2시간 (스크린샷 포함)

---

#### 1.2 태깅 가이드 (`docs/guides/ko/tagging-guide.md`)

**목표**: 처음 사용자가 자기 지출 패턴에 맞게 태그를 설정할 수 있게

**내용**:
```markdown
# 🏷️ 태깅 가이드 - 내 지출 분류하기

## 태그가 뭔가요?
태그는 거래를 분류하는 라벨입니다.

**예시**:
- "스타벅스 강남점 결제" → 태그: `["카페", "커피"]`
- "GS25 야식" → 태그: `["편의점", "간식"]`
- "서울종합병원 건강검진" → 태그: `["의료", "검진"]`

## 기본 태그 사용해보기 (5분)

1. `data/rules/rules.yaml` 파일 열기
   [스크린샷: VSCode/메모장에서 열기]

2. 기본 규칙 확인:
   ```yaml
   rules:
     - name: cafe
       match: "스타벅스|투썸|이디야"
       fields: [merchant_raw]
       tags: ["카페", "커피"]
       priority: 80
   ```

3. 규칙 추가해보기:
   ```yaml
   # 내가 자주 가는 카페 추가
   - name: my_cafe
     match: "메가커피|빽다방"
     fields: [merchant_raw]
     tags: ["카페", "커피"]
     priority: 80
   ```

4. 다시 실행:
   ```bash
   finjuice tag
   finjuice export
   ```

5. 결과 확인:
   ```bash
   open data/exports/reports/by_tag.csv
   ```

[스크린샷: by_tag.csv에서 "카페" 태그 확인]

## 실전 예시: 육아 지출 추적

**목표**: 기저귀, 분유, 어린이집 비용을 한눈에 보기

```yaml
- name: childcare_diapers
  match: "기저귀|팸퍼스|하기스"
  fields: [merchant_raw, memo_raw]
  tags: ["육아", "기저귀", "필수지출"]
  priority: 90

- name: childcare_formula
  match: "분유|앱솔루트|임페리얼"
  fields: [merchant_raw, memo_raw]
  tags: ["육아", "분유", "필수지출"]
  priority: 90

- name: childcare_daycare
  match: "어린이집|유치원"
  fields: [merchant_raw, memo_raw]
  tags: ["육아", "보육", "정기지출"]
  priority: 95
```

[스크린샷: 육아 태그 적용 전후 비교]

## 실전 예시: 병원/약국 지출 정리

**목표**: 병원, 약국, 정기 검진 비용을 별도 태그로 분류

```yaml
- name: medical_checkup
  match: "검진|건강검진|종합검진"
  fields: [merchant_raw, memo_raw]
  tags: ["의료", "검진"]
  priority: 95

- name: pharmacy
  match: "약국|PHARMACY"
  fields: [merchant_raw, memo_raw]
  tags: ["의료", "약국"]
  priority: 90
```

## 💡 태그 작성 팁

### ✅ 좋은 예시
```yaml
# 다양한 표기 포함
match: "스타벅스|STARBUCKS|Starbucks"

# 메모 필드도 검색
fields: [merchant_raw, memo_raw]

# 용도별 태그 분리
tags: ["의료", "종합병원", "검진"]
```

### ❌ 나쁜 예시
```yaml
# 영문 표기 누락
match: "스타벅스"

# 너무 광범위 (오탐 위험)
match: ".*카페.*"

# 태그 중복
tags: ["카페", "커피", "카페", "음료"]
```

## 자주 묻는 질문 (FAQ)

**Q: 규칙을 추가했는데 태그가 안 붙어요**
A: `finjuice tag` 명령어를 실행하셨나요? 규칙 변경 후엔 꼭 재실행 필요합니다.

**Q: 같은 거래가 여러 규칙에 매칭되면?**
A: 매칭된 모든 활성 규칙의 태그가 `priority` 높은 순서로 병합됩니다.
`category_rule`은 카테고리가 있는 가장 높은 우선순위의 매칭 규칙에서 정합니다.

**Q: 과거 거래도 다시 태그되나요?**
A: 네, `finjuice tag`를 다시 실행하면 전체 거래에 규칙이 재적용됩니다.

## 다음 단계
- [Claude CLI로 규칙 편집하기](../../workflows/rule-editing-with-claude.md)
- [고급 정규식 패턴](advanced-tagging.md)
```

**작업 시간**: 3시간 (예시 + 스크린샷)

---

#### 1.3 리포트 읽는 법 (`docs/guides/ko/report-guide.md`)

**목표**: 숫자를 보고 인사이트를 얻는 법

**내용**:
```markdown
# 📊 리포트 읽는 법

## 리포트 파일 위치
```bash
data/exports/reports/
├── monthly_spend.csv      # 월별 지출
├── by_tag.csv             # 태그별 지출
├── by_account.csv         # 카드/계좌별
└── transfers.csv          # 이체 내역 (검증용)
```

## 1. monthly_spend.csv - 월별 지출

[스크린샷: 엑셀에서 열린 monthly_spend.csv]

**컬럼 설명**:
- `month`: 년-월 (예: 2024-10)
- `transaction_count`: 거래 건수
- `total_amount`: 총 지출 (음수는 지출, 양수는 수입)

**실전 활용**:
```
2024-09: -1,523,450원 (156건)
2024-10: -1,678,920원 (168건) ← 전월 대비 +10.2% 증가!
2024-11: -1,445,230원 (142건)
```

💡 **이렇게 해석하세요**:
- 10월에 지출이 많았네? → by_tag.csv에서 어디서 썼는지 확인
- 11월은 줄었네? → 의식적으로 줄인 건지, 큰 지출이 없었던 건지

## 2. by_tag.csv - 태그별 지출

[스크린샷: 엑셀 차트로 시각화]

**컬럼 설명**:
- `tag`: 태그 이름
- `transaction_count`: 거래 건수
- `total_amount`: 총 금액

**실전 활용**:
```
카페:        -450,000원 (89건)  ← 하루 15,000원!
편의점:      -280,000원 (142건)
온라인쇼핑:  -620,000원 (23건) ← 건당 27,000원
```

💡 **인사이트 찾기**:
- 카페 지출 많네? → 회사 근처 자판기 커피로 바꿔볼까?
- 온라인쇼핑 건당 금액 크네? → 충동구매 줄이기

## 3. by_account.csv - 카드별 지출

**활용 예시**:
```
신한카드:    -2,340,000원
삼성카드:      -780,000원
우리카드:      -450,000원
```

💡 **카드 혜택 최적화**:
- 신한카드 주로 쓰네? → 신한 할인 많은 가맹점 확인
- 우리카드는 거의 안 쓰네? → 해지 고려?

## 4. transfers.csv - 이체 검증

**왜 중요한가요?**
"신용카드 결제"나 "내 계좌 간 이체"가 지출로 잡히면 안 되니까요!

[스크린샷: transfers.csv 예시]

**확인 사항**:
- ✅ "신한카드 결제" ↔ "우리은행 출금" 페어링 확인
- ❌ 페어링 안 된 이체 있으면 → rules.yaml에 규칙 추가

## 실전 시나리오: 10월 지출 분석

**목표**: 10월에 왜 지출이 많았는지 찾기

1. **monthly_spend.csv 확인**:
   - 10월: -1,678,920원 (전월 대비 +10.2%)

2. **by_tag.csv에서 원인 찾기**:
   - "온라인쇼핑": -620,000원 ← 평소 30만원인데 2배!
   - "외식": -380,000원
   - "카페": -450,000원

3. **master_YYYYMMDD.xlsx에서 상세 확인**:
   - 온라인쇼핑: 에어컨 구매 -550,000원 (1회성)
   - 외식: 가족 외식 3회

4. **결론**:
   - 에어컨 구매는 필수 지출 (OK)
   - 외식은 좀 줄여볼까?

## 다음 단계
- [대시보드 사용하기](dashboard-guide.md) - 그래프로 보기
- [AI 질의하기](ai-query-guide.md) - "10월 카페 지출?" 물어보기
```

**작업 시간**: 2시간

---

### Phase 2: 고급 기능 가이드 (중간 우선순위)

#### 2.1 대시보드 가이드 (`docs/guides/ko/dashboard-guide.md`)

**내용**:
- Reflex 대시보드 실행 방법
- 월별 선택, 필터링
- AI 채팅 사용법
- 스크린샷 중심

**작업 시간**: 2시간

---

#### 2.2 AI 질의 가이드 (`docs/guides/ko/ai-query-guide.md`)

**내용**:
- Claude Code CLI 설치
- `finjuice ask` 명령어
- 자주 묻는 질문 예시
  - "10월 카페 지출은?"
  - "지난 3개월 외식비 추이는?"
  - "이번 달 구독료 총합은?"

**작업 시간**: 1.5시간

---

#### 2.3 데이터 백업 가이드 (`docs/guides/ko/backup-guide.md`)

**내용**:
- Git으로 데이터 관리
- 비공개 GitHub 레포 생성
- 정기 백업 자동화

**작업 시간**: 1시간

---

### Phase 3: 문제 해결 & FAQ (낮은 우선순위)

#### 3.1 문제 해결 가이드 (`docs/guides/ko/troubleshooting.md`)

**내용**:
- "XLSX 파일을 못 읽어요"
- "태그가 안 붙어요"
- "이체가 안 걸러져요"
- "설치가 안 돼요"

**작업 시간**: 2시간

---

#### 3.2 FAQ (`docs/guides/ko/faq.md`)

**내용**:
- 일반 질문
- 보안 관련
- 성능 관련
- 확장성 관련

**작업 시간**: 1시간

---

## 📅 작업 일정 (총 16.5시간)

| Phase | 문서 | 예상 시간 | 우선순위 |
|-------|------|-----------|----------|
| 1 | quickstart.md | 2h | 🔴 높음 |
| 1 | tagging-guide.md | 3h | 🔴 높음 |
| 1 | report-guide.md | 2h | 🔴 높음 |
| 2 | dashboard-guide.md | 2h | 🟡 중간 |
| 2 | ai-query-guide.md | 1.5h | 🟡 중간 |
| 2 | backup-guide.md | 1h | 🟡 중간 |
| 3 | troubleshooting.md | 2h | 🟢 낮음 |
| 3 | faq.md | 1h | 🟢 낮음 |
| - | **스크린샷 촬영** | 2h | - |
| **총합** | | **16.5h** | |

**1주 계획**:
- Day 1-2: Phase 1 (7시간) - 핵심 사용자 가이드
- Day 3-4: Phase 2 (4.5시간) - 고급 기능
- Day 5: Phase 3 + 스크린샷 (5시간)

---

## 🖼️ 스크린샷 체크리스트

### 필수 스크린샷 (20개)

**뱅크샐러드 앱**:
- [ ] 설정 메뉴
- [ ] 데이터 관리 > 내보내기
- [ ] XLSX 파일 다운로드 완료

**터미널**:
- [ ] Homebrew 설치
- [ ] finjuice 설치
- [ ] finjuice --version
- [ ] finjuice init 실행
- [ ] finjuice refresh 실행 중
- [ ] finjuice refresh 완료

**파일 탐색기**:
- [ ] data/imports/ 폴더
- [ ] data/exports/reports/ 폴더
- [ ] rules.yaml 파일 (VSCode)

**엑셀/CSV**:
- [ ] monthly_spend.csv
- [ ] by_tag.csv
- [ ] by_account.csv
- [ ] master_YYYYMMDD.xlsx

**대시보드**:
- [ ] Reflex 대시보드 메인
- [ ] 월별 선택
- [ ] AI 채팅 사이드바

**에러 화면**:
- [ ] XLSX 파일 없을 때
- [ ] 규칙 오류 메시지

---

## 📝 README.md 개선 사항

### 변경 전 (현재)
```markdown
## 사용법

### 기본 워크플로우

```bash
# 1. 뱅크샐러드에서 XLSX 파일 내보내기
...
```
```

### 변경 후 (제안)
```markdown
## 🚀 5분 시작하기

처음 사용하시나요? [빠른 시작 가이드](docs/guides/ko/quickstart.md)를 먼저 보세요!

### 기본 워크플로우 (요약)

```bash
# 1. 설치 (한 번만)
brew tap sungjunlee/banksalad
brew install finjuice

# 2. 초기화 (한 번만)
finjuice init

# 3. 데이터 넣고 실행 (매번)
cp ~/Downloads/뱅크샐러드_*.xlsx data/imports/
finjuice refresh

# 4. 결과 확인
open data/exports/reports/
```

✅ **성공!** 이제 `data/exports/reports/`에서 월별 지출을 확인할 수 있습니다.

### 다음 단계
- 📊 [리포트 읽는 법](docs/guides/ko/report-guide.md)
- 🏷️ [태그 설정하기](docs/guides/ko/tagging-guide.md)
- 💬 [AI로 질문하기](docs/guides/ko/ai-query-guide.md)
```

**변경 이유**:
- 5분 시작하기 강조
- 매번 vs 한 번만 구분
- 성공 메시지로 긍정 강화
- 다음 단계 명확히 제시

---

## 🎯 성공 기준

### Phase 1 완료 후
- [ ] 비개발자가 README만 보고 15분 안에 첫 리포트 생성
- [ ] 태깅 가이드 보고 5분 안에 첫 규칙 추가
- [ ] 리포트 보고 의미 파악 가능

### Phase 2 완료 후
- [ ] 대시보드 실행 가능
- [ ] AI 질의로 인사이트 얻기

### Phase 3 완료 후
- [ ] FAQ 10개 이상 작성
- [ ] 문제 해결 시나리오 5개 이상

---

## 📋 다음 액션

**지금 바로 시작**:
1. README.md 개선 (30분)
2. quickstart.md 작성 (2시간)
3. 스크린샷 촬영 계획 (1시간)

**어떤 것부터 시작할까요?**

---

**작성자**: Claude Code
**최종 수정**: 2025-12-06
