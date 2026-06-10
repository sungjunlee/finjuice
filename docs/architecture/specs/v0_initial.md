---

Title: banksalad-tools
Type: product-concept
Goal: Banksalad XLSX(가계부 내역)을 로컬에서 간단히 병합/정리하고, 규칙+AI 보조 태깅으로 가시성을 높인 개인 재무 파이프라인을 구축한다. 이후 필요시 Google Sheets/Drive, Beancount/Fava, Firefly III와 연동하는 어댑터를 추가한다.
Created: 2025-10-31
Status: draft
Stack: **Python + uv** (패키지/실행만), 로컬-퍼스트
----------------------------------------

# 0. 문제 정의 & 비전

## 문제 정의

* 모바일 중심 가계부(예: 뱅크샐러드)는 **대량 태깅/일괄 편집**이 어렵고, 자유도가 제한됨.
* 데이터는 매년 **XLSX로 Export** 가능하지만, 이를 **지속적으로 병합/관리**하고 **가시화**하는 간단하고 신뢰 가능한 로컬 파이프라인이 부족함.

## 비전

* **내가 이해하고 통제 가능한 로컬 파일 기반**으로, “원장(XLSX) → 병합/정제 → 규칙 태깅 → AI 보조 → 리치 리포트”까지 **최소 마찰**로 실행.
* 구글 동기화·PTA(Plain-Text Accounting)·PFM(Firefly) 등 **확장은 어댑터**로 뒤에 붙는 구조.
* “과하게 회계적이지 않아도” **체크할 것만 빠르게 확인**할 수 있는 가볍고 신뢰도 높은 개인 도구.

## 원칙

1. **로컬-퍼스트**: 오프라인에서도 완결. 외부 연동은 모두 옵트인.
2. **멱등/재현**: 같은 원본을 다시 넣어도 결과가 동일.
3. **가벼운 진실의 원천**: 통합 결과물(master + reports)이 사람이 열어볼 수 있는 파일(XLSX/CSV/Parquet).
4. **확장성**: 규칙/AI/리포트/어댑터는 느슨하게 결합.
5. **안전성**: 개인 금융 데이터의 노출을 최소화.

# 1. 범위(스코프)

## 포함(초기)

* 로컬 폴더의 Banksalad **XLSX 다건 병합**
* **규칙(YAML) 1차 태깅** + **AI 보조 태깅(옵션)**
* **이체/내부이체 인식** 후 리포트에서 제외
* **로컬 산출물** 생성: master + reports

## 제외(초기)

* 외부 자동 동기화(Google/클라우드) 강제 의존
* 완성형 예산 편집 UI, 모바일 앱, 알림 시스템
* 복잡한 회계 체계(복식부기 등) 강제

# 2. 사용자 시나리오(페르소나)

* **JY(본인, 개발자/가정 사용자)**: 분기/반기마다 XLSX를 폴더에 넣고 실행 → 월별/태그/계정별 리포트 확인 → 몇 건의 태그만 손보면 끝.
* **공유 뷰어(배우자)**: 필요 시 리포트 CSV/XLSX만 공유. 원본은 로컬에만.
* **향후 나(파워유저)**: 태깅 규칙을 깔끔히 관리하고, ‘검토 필요’ 큐만 처리. 연말에 연금/보험/세금성 지출만 확인.

## 포함(초기 MVP)

* 로컬 폴더의 Banksalad **XLSX 다건**을 스캔/정규화/업서트
* **규칙(YAML)** 기반 1차 태깅 + **LLM 보조**(옵션)
* **이체(내부이체) 페어링** 및 리포트에서 제외
* **로컬 산출물**: master(.xlsx/.csv/.parquet) + reports(csv)
* **(선택)** Streamlit **로컬 대시보드** + 저신뢰 리뷰 큐

## 제외(후순위)

* 실시간 은행 연동/자동 크롤링
* 완전한 예산관리 UI(예산 편집/알림)
* 모바일 앱

---

# 2. 사용자 입력/원본 스키마

원본: **뱅크샐러드 가계부 export**의 **“가계부 내역”** 탭.

| 원본 컬럼          | 내부 컬럼          | 메모                 |
| -------------- | -------------- | ------------------ |
| 날짜(YYYY-MM-DD) | `date`         | 필수                 |
| 시간(HH:MM)      | `time`         | 선택                 |
| 타입(지출/수입/이체)   | `type_raw`     |                    |
| 대분류            | `major_raw`    |                    |
| 소분류            | `minor_raw`    |                    |
| 내용(가맹점/내역)     | `merchant_raw` |                    |
| 금액             | `amount`       | 음수=지출, 양수=수입으로 정규화 |
| 화폐             | `currency`     | 기본 `KRW`           |
| 결제수단           | `account`      | 라벨 전체 보존           |
| 메모             | `memo_raw`     | 태그 후보 승계           |

부호 규칙: `지출 → -abs(금액)`, `수입 → +abs(금액)`

이체 처리: `type_raw='이체'` → `is_transfer=1`, 동일 시간대(±5분) & 동일 금액(부호 반대) & 사용자 계정 간 트랜잭션을 **페어링**(`transfer_group_id`) 시도.

---

# 3. 개념 아키텍처(기술중립)

```
[원본 XLSX 폴더]
   ↓ (스캔/정규화/멱등 업서트)
[통합 스토어(로컬 파일 기반)]
   ↓
[규칙 태깅(YAML)] → [AI 보조(옵션)]
   ↓
[결과 확정(카테고리/태그)]
   ↓
[리포트 산출물(master + reports)]
   ↘ (선택) [어댑터: Google Sheets/Drive]
   ↘ (선택) [어댑터: Beancount/Fava]
   ↘ (선택) [어댑터: Firefly III]
```

## 핵심 개념 정의

* **원본**: Banksalad “가계부 내역” 시트. 제공 컬럼을 신뢰하되, 컬럼명/스키마 변동에 유연하게 대응.
* **정규화**: 날짜/시간/부호/계정/가맹점 텍스트 정리 + 중복/정정 인식.
* **이체 인식**: `type=이체` 또는 내계좌 간 금액·시간 상호 매칭을 통해 **내부이체** 구분.
* **태깅 정책**: “반복/명확 → 규칙”, “애매/신규 → AI 제안”의 하이브리드.
* **최종 확정**: 규칙 우선, AI는 신뢰도 기준(예: 0.7) 이상만 자동 반영. 나머지는 검토 큐.
* **결과물**: 사람이 파일로 바로 확인 가능한 **master(행 단위)** + **reports(집계)**.

# 4. 데이터 모델(개념 수준)

* **필수 속성**: 날짜·시간·타입·대분류/소분류·내용·금액·화폐·결제수단·메모
* **정규화 속성**: 표준화된 부호(지출 음수), 표준 타입(expense/income/transfer), 카운터파티(상호 정규화)
* **태깅 속성**: `category_rule`, `tags_rule[]`, `category_ai`, `tags_ai[]`, `confidence`, `category_final`, `tags_final[]`, `needs_review`
* **이체 속성**: `is_transfer`, `transfer_group`(내부 페어링 식별)
* **추적성**: 원본 파일/행 위치, 행 해시(멱등키)

# 5. 태깅 정책(개념)

* **카테고리 체계**: 2단계 정도(예: `식비:카페`). 너무 세분화하지 않음.
* **태그 체계**: 상황/사람/목적(예: `가족`,`업무`,`주말`,`정기결제`). 복수 허용.
* **룰 예시**: `메트라이프 → 금융:보험`, `관리비 → 주거/통신:관리비`, `GS25 → 생활:편의점`, `맥도날드 → 식비:패스트푸드`, `서울종합병원 + 메모(검진) → 의료/건강:종합병원 + 태그(검진)`.
* **AI 사용 원칙**: 규칙 미적용/저신뢰만 제한적 호출. JSON 스키마 강제, 임계 미달은 검토.

# 6. 리포트 요구사항(개념)

* **월별 총지출**(이체 제외)
* **태그별 합계**(최종 태그 기준, 이체 제외)
* **계정별 순지출**(이체 제외)
* 리포트 파일은 사람이 열어보기 쉬운 **CSV/XLSX** 우선. 이름 규약 예: `reports/monthly_spend.csv`.

# 7. 인터랙션(최소한)

* **CLI**: `import`(자동 초기화 + 전체 처리) → `refresh`(기존 데이터 재처리) → `tag`/`export`(개별 실행)
* **로컬 UI(선택)**: 간단 검색/필터/검토 큐. 사용하지 않아도 전체 파이프라인은 CLI로 동작.

# 8. 비기능 요구사항

* **프라이버시**: 기본은 오프라인. 외부 연동은 명시적 활성화.
* **성능/용량**: 수만~수십만 행 규모에서 수 분 내 완료(로컬 SSD 기준). 청크 처리로 메모리 보호.
* **감사성**: 어떤 규칙/AI 제안이 반영되었는지 **로그와 결과 컬럼**으로 추적 가능.
* **복구/재생성**: 원본과 규칙만 있으면 같은 결과를 재생성 가능.

# 9. 성공 지표

* 첫 실행 시 **10분 내**(환경 의존) master+reports 생성.
* 규칙 히트율 **>60%**, AI 호출 레코드 비율 **<40%**(점진 개선 기대).
* 검토 큐 건수 **지속 감소 추세**.
* 사용자는 월 1회 이하 수동 개입으로도 가시성 확보.

# 10. 리스크 & 완화

* **원본 스키마 변화**: Ingest 단계에서 컬럼 매핑 버전 관리, 누락 컬럼 로그.
* **AI 오태깅**: 임계·검토 큐·수동 확정, 규칙 우선 원칙 유지.
* **이체 오탐/미탐**: 매칭 윈도우/기준을 설정 가능(기본값 제공, 사용자 조정 허용).
* **데이터 유출**: 기본 오프라인, 외부 전송은 익명화/옵트인.

# 11. 확장 로드맵(개념)

* **어댑터**: Google Sheets/Drive, Beancount/Fava, Firefly III
* **자동 룰 제안기**: 최근 확정 사례에서 키워드/정규식 후보 생성
* **혜택 효율 리포트**: 카드 혜택 테이블과 교차
* **알림/추천(옵션)**: 월말 요약, 이상지출 감지, 구독 점검

# 12. 파일/폴더 가이드(개념)

```
~/.finjuice/
  imports/          # Banksalad XLSX 원본
  transactions/
    YYYY/
      MM/
        transactions.csv
  exports/
    master_YYYYMMDD.xlsx
    reports/
      monthly_spend.csv
      by_tag.csv
      by_card.csv
  metadata/
    schema_version.json
  rules.yaml        # 사람이 읽고 수정하기 쉬운 규칙
  config.toml       # 선택적 사용자 설정
```

# 13. 네이밍 & 메타데이터(권장)

* 프로젝트 문서: `banksalad-tools-spec.md`
* 결과 파일: `master_YYYYMMDD.(xlsx|csv|parquet)`
* 리포트: `reports/<name>.csv`
* 실행 로그: `logs/YYYY-MM-DD.txt`(선택)

# 14. 향후 전환 전략

* **PTA 연동**이 필요해지면: `to-beancount` 어댑터를 추가하여 `.beancount` 생성 → Fava로 시각화.
* **PFM 연동**이 필요해지면: Firefly III API 임포터로 전송.
* **클라우드 가시화**가 필요해지면: Google Sheets/Drive 어댑터를 활성화.
  (요약)

```sql
CREATE TABLE IF NOT EXISTS transactions (
  id TEXT PRIMARY KEY,
  date TEXT NOT NULL,
  time TEXT,
  datetime TEXT,           -- ISO8601 (분 단위)
  type_raw TEXT,
  type_norm TEXT,          -- expense|income|transfer|other
  major_raw TEXT,
  minor_raw TEXT,
  merchant_raw TEXT,
  memo_raw TEXT,
  counterparty TEXT,
  account TEXT,
  currency TEXT DEFAULT 'KRW',
  amount NUMERIC NOT NULL, -- 지출 음수, 수입 양수
  is_transfer INTEGER DEFAULT 0,
  transfer_group_id TEXT,
  source_file_path TEXT,
  source_file_mtime TEXT,
  source_row INTEGER,
  row_hash TEXT UNIQUE,
  -- 태깅
  category_rule TEXT,
  tags_rule TEXT,          -- JSON 배열 문자열
  category_ai TEXT,
  tags_ai TEXT,            -- JSON 배열 문자열
  confidence REAL,
  category_final TEXT,
  tags_final TEXT,         -- JSON 배열 문자열
  needs_review INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_dt ON transactions(datetime);
CREATE INDEX IF NOT EXISTS idx_type ON transactions(type_norm);
CREATE INDEX IF NOT EXISTS idx_acct ON transactions(account);
CREATE INDEX IF NOT EXISTS idx_rowhash ON transactions(row_hash);
```

표준화 파생 컬럼:

* `type_norm`: {expense, income, transfer, other}
* `counterparty`: `merchant_raw` 정규화(공백/특수문자 정리)

---

# 5. 규칙 엔진(`rules.yaml`) 기본안

```yaml
version: 1
rules:
  - name: insurance_metlife
    match: "METLIFE|메트라이프"
    fields: [merchant_raw, memo_raw]
    category: "금융:보험"
    tags: ["보험","정기지출"]
    priority: 95

  - name: apartment_fees
    match: "관리비|아파트관리비"
    fields: [merchant_raw, memo_raw]
    category: "주거/통신:관리비"
    tags: ["공과금"]
    priority: 90

  - name: hospital_general
    match: "병원|종합병원|서울종합병원"
    fields: [merchant_raw, memo_raw]
    category: "의료/건강:종합병원"
    tags: ["의료"]
    priority: 88

  - name: convenience_gs25
    match: "GS25|세븐일레븐|CU"
    fields: [merchant_raw]
    category: "생활:편의점"
    tags: ["편의점"]
    priority: 80

  - name: fastfood_mcd
    match: "맥도날드|McDonald"
    fields: [merchant_raw]
    category: "식비:패스트푸드"
    tags: ["패스트푸드"]
    priority: 80

  - name: ecommerce_coupang
    match: "쿠팡|Coupang"
    fields: [merchant_raw]
    category: "온라인쇼핑:인터넷쇼핑"
    tags: ["온라인쇼핑"]
    priority: 80

  - name: investment_transfer
    match: "IRP|연금|투자"
    fields: [merchant_raw, memo_raw]
    category: "이체:투자"
    tags: ["내부이체"]
    priority: 70

  - name: internal_transfer
    match: "내계좌이체|본인계좌"
    fields: [minor_raw, merchant_raw]
    category: "이체:내계좌"
    tags: ["내부이체"]
    priority: 70

  - name: dues_union
    match: "조합비|회비"
    fields: [merchant_raw, memo_raw]
    category: "이체:회비"
    tags: ["정기지출"]
    priority: 70
```

현재 태깅 규칙 적용: priority 내림차순으로 활성 규칙을 평가하고, 매칭된 모든
규칙의 태그를 `tags_rule`에 병합한다. `category_rule`은 카테고리가 있는
가장 높은 우선순위의 매칭 규칙에서 정한다. 메모 키워드(예: `검진`)도
매칭되면 같은 방식으로 `tags_rule`에 병합된다.

조건 기반 rule 구문, 9개 연산자 semantics, `logic: all`/`any`, legacy `match`/`fields`와의 우선순위는 [Conditional Rule Engine Reference](../../reference/rules-conditions.md) 참조.

---

# 6. LLM 보조 태깅(옵션)

대상: 규칙 미적용 혹은 `confidence` 낮은 항목.

프롬프트(요지):

```json
{
  "merchant_raw": "스타벅스 삼성역점",
  "memo_raw": "아메리카노 2잔",
  "amount": -8200,
  "date": "2025-09-13",
  "account": "신한카드"
}
```

응답 스키마(강제):

```json
{"category":"식비:카페","tags":["카페","커피"],"confidence":0.86}
```

정책: `confidence>=0.7` 자동 반영, 미만은 `needs_review=1`로 큐 적재. 배치 크기 50, 동일 상호/메모 그룹화로 비용 절감.

---

# 7. 리포트 뷰(SQL)

```sql
-- 월별 총지출(이체 제외)
CREATE VIEW IF NOT EXISTS monthly_spend AS
SELECT substr(date,1,7) AS ym,
       ROUND(SUM(CASE WHEN type_norm='expense' AND is_transfer=0 THEN amount ELSE 0 END),0) AS spend
FROM transactions
GROUP BY ym
ORDER BY ym DESC;

-- 태그별 합계(이체 제외, 최종 태그)
CREATE VIEW IF NOT EXISTS by_tag AS
SELECT tag, ROUND(SUM(amount),0) AS total
FROM (
  SELECT amount, json_each.value AS tag
  FROM transactions, json_each(COALESCE(NULLIF(tags_final,''),'[]'))
  WHERE is_transfer=0
)
GROUP BY tag
ORDER BY total ASC; -- 지출은 음수

-- 계정(카드/계좌)별 순지출(이체 제외)
CREATE VIEW IF NOT EXISTS by_card AS
SELECT account, ROUND(SUM(CASE WHEN is_transfer=0 THEN amount ELSE 0 END),0) AS total
FROM transactions
GROUP BY account
ORDER BY total ASC;

-- 내부이체 점검
CREATE VIEW IF NOT EXISTS transfers AS
SELECT datetime, amount, account, counterparty, memo_raw
FROM transactions
WHERE is_transfer=1
ORDER BY datetime DESC;
```

---

# 8. 실행/운영

## CLI (Typer)

```
finjuice import <file.xlsx>   # 첫 실행 시 ~/.finjuice 자동 초기화 + 전체 처리
finjuice refresh              # ingest → tag → detect_transfers (자동) → export
finjuice tag                  # rules 재적용
finjuice export               # master + reports 생성
```

**Note**: Transfer detection은 `finjuice refresh` 실행시 자동으로 수행됩니다 (별도 CLI 명령어 없음).

실제 구현 옵션은 `finjuice --help`를 기준으로 확인합니다. 현재 전체 재처리는 `finjuice refresh`,
첫 실행 자동 설정은 `finjuice import`가 담당합니다.

## API(FastAPI)

* `POST /run` `{full?:bool, llm?:bool}`
* `GET /healthz`

## 스케줄링

* cron: 매일 01:00 `finjuice refresh`
* 주 1회 검토: 일요일 02:00 `finjuice status`

---

# 9. 로컬 결과물

* `OUTPUT_DIR/master_YYYYMMDD.xlsx|csv|parquet`
* `OUTPUT_DIR/reports/monthly_spend.csv|by_tag.csv|by_card.csv`
* (선택) `web/` Streamlit 대시보드 로컬 실행: `make ui`

---

# 10. 수용 기준(DoD)

1. 신규 XLSX 추가 시 **중복 없이 업서트**
2. `finjuice refresh` 한 번으로 master + reports 생성
3. 월별/태그/계정 리포트가 기대치와 일치 (이체 제외)
4. 규칙 히트율/LLM 호출 수/실패 재시도 로그가 남음
5. 실패 시 재시도(429/5xx 백오프) 및 명확한 에러 메시지

---

# 11. 품질/보안/운영

* 로깅: 처리 건수/룰 히트/LLM 호출/업서트 수/산출물 경로
* 에러 핸들링: API/파일 I/O/스키마 불일치 예외 처리, 부분 실패 시 롤백/스킵
* PII 최소화: 원본 파일 보관은 로컬 전용, 외부 동기화는 옵트인
* 성능: pandas + pyarrow + DuckDB(옵션) 사용, 대량 파일은 청크 처리

---

# 12. 확장 로드맵(후순위)

* **Google Sheets/Drive** 어댑터(토글로 활성화)
* **Beancount/Fava** Export(PTA 전환 용이)
* **Firefly III** Importer(API)
* 자동 룰 생성기(최근 확정 내역 기반 정규식 제안)
* 혜택 효율 분석(카드별 혜택 테이블 매칭)

---

# 13. 부록

## 13.1 샘플 규칙/데이터 매핑 사례

* `TEST_INSURANCE_A` → `금융:보험`, 태그: `보험,정기지출`
* `아파트관리비` → `주거/통신:관리비`, 태그: `공과금`
* `GS25 강남역3호점` → `생활:편의점`
* `한국맥도날드(유)판교테크노밸리점` → `식비:패스트푸드`
* `서울종합병원` + 메모 `검진` → `의료/건강:종합병원`, 태그: `의료,검진`
* `쿠팡` → `온라인쇼핑:인터넷쇼핑`
* `내계좌이체/IRP/연금/조합비` → `이체:*` → `is_transfer=1`

## 13.2 Makefile 타겟 예시

```
make setup   # venv, deps 설치
make all     # ingest → tag → export
make ui      # streamlit run web/app.py
```

## 13.3 커밋 컨벤션(선택)

* `ingest:`, `rules:`, `tagger:`, `export:`, `ui:` 접두사 권장
