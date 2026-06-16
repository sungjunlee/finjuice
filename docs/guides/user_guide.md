# 사용자 가이드

> finjuice v0.7.0 기준, 뱅크샐러드 XLSX/ZIP 내보내기를 로컬 CSV 파티션으로 처리하고
> 조회, 태깅, 리포트, AI 에이전트용 읽기 컨텍스트까지 다루는 사용 가이드입니다.

마지막 업데이트: 2026-06-16
버전: v0.7.0

---

## 목차

1. [시작하기](#1-시작하기)
2. [데이터 디렉토리](#2-데이터-디렉토리)
3. [rules.yaml 가이드](#3-rulesyaml-가이드)
4. [CLI 참조](#4-cli-참조)
5. [리포트 이해하기](#5-리포트-이해하기)
6. [일반적인 워크플로우](#6-일반적인-워크플로우)
7. [문제 해결](#7-문제-해결)

---

## 1. 시작하기

### 1.1 설치

전제 조건:

- Python 3.10 이상
- [uv](https://github.com/astral-sh/uv) 패키지 관리자

```bash
git clone https://github.com/sungjunlee/finjuice.git
cd finjuice
uv sync
uv run finjuice --version
```

설치된 실행 파일을 PATH에서 바로 쓰는 환경이라면 이후 예시는 `finjuice`로 실행하면 됩니다.
소스 체크아웃에서 바로 실행할 때는 `uv run finjuice ...` 형식으로 바꿔 실행하세요.

### 1.2 첫 처리

가장 간단한 시작점은 `finjuice import`입니다. 첫 실행이면 데이터 디렉토리를 자동으로
초기화하고, 파일을 `imports/`로 복사한 뒤 전체 파이프라인을 실행합니다.

```bash
finjuice import ~/Downloads/뱅크샐러드_2024-01-01~2024-12-31.xlsx
```

뱅크샐러드 ZIP 내보내기도 지원합니다.

```bash
finjuice import ~/Downloads/이름_2024-01-01~2024-12-31.zip
finjuice import ~/Downloads/*.zip --password 1234
```

이미 `imports/`에 파일을 직접 넣어 둔 경우에는 현재 데이터 상태를 다시 처리합니다.

```bash
finjuice refresh
```

`finjuice all`은 남아 있지만 deprecated alias입니다. 새 문서와 자동화에서는
`finjuice refresh`를 사용하세요.

### 1.3 결과 확인

```bash
finjuice status
finjuice show --limit 10
finjuice export --format html --period 2024-10
finjuice open reports
```

기본 XLSX export는 `exports/master_YYYYMMDD.xlsx`와 `exports/reports/*.csv`를 만듭니다.
HTML/Markdown 리포트는 `finjuice export --format html`, `--format md`, `--format all`로
생성합니다.

---

## 2. 데이터 디렉토리

finjuice는 프로그램 저장소와 사용자 금융 데이터를 분리합니다. 기본 데이터 위치는
`~/.finjuice`입니다.

우선순위:

1. `--data-dir PATH`
2. `FINJUICE_DATA_DIR` 환경 변수
3. `~/.finjuice/config.toml`
4. 기본값 `~/.finjuice`

예시:

```bash
finjuice --data-dir ~/Documents/my-finance-data status
FINJUICE_DATA_DIR=~/Documents/my-finance-data finjuice refresh
```

기본 구조:

```text
~/
├── .finjuice/
│   ├── imports/                    # 가져온 XLSX/ZIP 원본 또는 복사본
│   ├── transactions/               # 런타임 거래 CSV 파티션
│   │   └── YYYY/MM/transactions.csv
│   ├── exports/
│   │   ├── master_YYYYMMDD.xlsx
│   │   └── reports/
│   │       ├── monthly_spend.csv
│   │       ├── by_category.csv
│   │       ├── by_tag.csv              # 태그가 있는 지출이 있을 때 생성
│   │       ├── by_account.csv
│   │       └── transfers.csv
│   ├── metadata/                   # import_history.csv, archives/, schema_version 등
│   ├── rules.yaml                  # 태깅 규칙과 report_filters
│   ├── goals.yaml                  # 선택: 예산 목표
│   └── assets.yaml                 # 선택: 순자산 수동 자산 정의
└── _journal/                       # 선택: journal 명령으로 생성한 회고 노트
```

기본 journal 디렉토리는 데이터 디렉토리 안이 아니라 데이터 디렉토리의 parent 아래
`_journal/`입니다. 기본 `~/.finjuice`를 쓰면 `~/_journal`, `--data-dir
~/Documents/my-finance-data`를 쓰면 `~/Documents/_journal`입니다. 별도 위치를 쓰려면
`FINJUICE_JOURNAL_DIR`을 지정하세요.

고급 사용자가 직접 초기화할 때는 `init`을 씁니다.

런타임 source of truth는 `transactions/YYYY/MM/transactions.csv` 형태의 CSV 파티션입니다.

```bash
finjuice init
finjuice --data-dir ~/Documents/my-finance-data init --save-config
finjuice init --with-agents
```

기존 `./data`나 과거 OS별 위치를 쓰던 경우에는 `migrate`로 옮깁니다.

```bash
finjuice migrate --dry-run
finjuice migrate
```

---

## 3. rules.yaml 가이드

### 3.1 기본 구조

```yaml
version: 1
rules:
  - name: cafe_starbucks
    match: "스타벅스|STARBUCKS"
    fields: [merchant_raw, memo_raw]
    tags: ["카페", "커피"]
    category: "카페"
    priority: 80
    enabled: true
```

주요 필드:

- `name`: 고유 규칙 이름
- `match`: `|`로 나눈 대소문자 무시 substring 패턴
- `fields`: 검색할 거래 필드, 주로 `merchant_raw`, `memo_raw`, `major_raw`, `minor_raw`
- `tags`: 매칭 시 붙일 태그 목록
- `category`: 선택, 집계용 단일 카테고리 후보
- `priority`: 0-100, 높을수록 먼저 평가
- `enabled`: 선택, false면 건너뜀

고급 조건식은 `conditions`를 사용할 수 있고, 조건식에서는 `contains`, `is`,
`starts_with`, `regex`, 금액 비교 연산 등을 지원합니다. 일반적인 규칙은 위의
`match`/`fields` 형태로 충분합니다.

### 3.2 적용 방식

v0.7.0의 태깅은 단일 "첫 매칭만 적용" 방식이 아닙니다.

- 활성화된 모든 매칭 규칙의 태그가 우선순위 순서대로 `tags_rule`에 병합됩니다.
- 중복 태그는 먼저 나온 값만 남습니다.
- `category_rule`은 카테고리가 있는 가장 높은 우선순위 매칭 규칙에서 한 번 정해집니다.
- `category_final`은 수동 카테고리 override, `category_rule`, `minor_raw`, `major_raw`,
  `미분류` 순서로 계산됩니다.

### 3.3 규칙 관리 명령

```bash
finjuice rules validate
finjuice rules list
finjuice rules test cafe_starbucks --limit 10
finjuice rules suggest
finjuice rules suggest --apply
```

CLI로 규칙을 추가하거나 제거할 수도 있습니다.

```bash
finjuice rules add \
  --name cafe_starbucks \
  --match "스타벅스|STARBUCKS" \
  --fields merchant_raw,memo_raw \
  --tags 카페,커피 \
  --category 카페 \
  --priority 80 \
  --dry-run

finjuice rules remove --name cafe_starbucks
```

규칙을 수정한 뒤에는 태그와 리포트를 다시 계산합니다.

```bash
finjuice tag
finjuice export
```

---

## 4. CLI 참조

정확한 옵션은 항상 live help를 우선합니다.

```bash
finjuice --help
finjuice <command> --help
```

### 4.1 공통 옵션

- `--version`: 버전 출력
- `--data-dir, -d PATH`: 데이터 디렉토리 지정
- `--verbose, -v`: DEBUG 로그
- `--no-filter`: 이번 실행에서 `rules.yaml`의 `report_filters` 무시
- `--show-legacy-warnings`: legacy 위치 경고를 다시 표시
- `--interactive, -i`: deprecated legacy interactive menu 옵션

### 4.2 파이프라인 명령

| 명령 | 용도 |
| --- | --- |
| `import` | XLSX/ZIP 파일을 `imports/`로 복사하고 ingest, tag, transfer, export 실행 |
| `ingest` | `imports/*.xlsx`를 CSV 파티션으로 가져오기 |
| `tag` | `rules.yaml` 적용, 수동 태그/카테고리 편집 |
| `transfer` | 내부 이체 쌍 감지, `refresh`에서 자동 실행됨 |
| `export` | XLSX, HTML, Markdown, 세금공제 headroom 리포트 생성 |
| `refresh` | 기존 데이터 기준 ingest, tag, transfer, export 전체 재처리 |
| `all` | deprecated, `refresh`의 별칭 |

주요 예시:

```bash
finjuice import ~/Downloads/export.xlsx
finjuice import ~/Downloads/export.zip --password 1234
finjuice import --dry-run ~/Downloads/*.xlsx

finjuice ingest --archive
finjuice ingest --from-archive 241027_1
finjuice tag --dry-run
finjuice transfer
finjuice refresh

finjuice export
finjuice export --format html --period 2024-10
finjuice export --format md
finjuice export --format all
```

`tag --edit`은 특정 `row_hash`의 수동 태그나 카테고리를 고칠 때 씁니다.

```bash
finjuice tag --edit ac875c7391d4e2f8 --add-tag 업무식대
finjuice tag --edit ac875c7391d4e2f8 --set-category 식비
```

### 4.3 분석 명령

| 명령 | 용도 |
| --- | --- |
| `status` | 거래 수, 기간, import 상태, 규칙 상태, 상세 통계 |
| `show` | 최근/월별/태그별/거래처별 거래 표 보기 |
| `review` | 미태깅 또는 낮은 confidence 거래 검토 |
| `query` | CSV 파티션 위의 `transactions` view에 SELECT/WITH SQL 실행 |
| `template` | 검증된 SQL 템플릿 목록/메타데이터/실행 |
| `explain` | 특정 거래가 어떤 규칙으로 분류됐는지 추적 |
| `context` | 외부 AI 에이전트에 붙여 넣을 읽기 전용 컨텍스트 출력 |
| `checkup` | 에이전트 inspect/decide loop용 런타임 스냅샷 출력 |
| `assets` | 자산 snapshot 원본/보유 포지션 보기 |
| `networth` | 자산 snapshot과 `assets.yaml` 기반 순자산 집계 |
| `budget` | `goals.yaml` 기반 월별 예산 대비 실제 지출 추적 |

예시:

```bash
finjuice status --detailed
finjuice show --month 2024-10 --tag 카페 --limit 30
finjuice review --untagged --all-history
finjuice explain "스타벅스" --date 2024-10-25

finjuice query "SELECT * FROM transactions LIMIT 5"
finjuice query "SELECT strftime(CAST(date AS DATE), '%Y-%m') AS month, SUM(amount) AS total FROM transactions GROUP BY 1" -o markdown
finjuice template list
finjuice template show monthly_spend
finjuice template run monthly_spend --param since=2024-10 --param until=2024-10 --output markdown

finjuice context --json
finjuice context --json --journal 5 --budget 4000
finjuice checkup --json --privacy redacted

finjuice assets status
finjuice assets show
finjuice networth breakdown --by category --date 2026-05-01
finjuice networth history
finjuice budget status
```

`query`는 안전을 위해 `SELECT`와 `WITH`만 허용합니다. `INSERT`, `UPDATE`, `DELETE`,
`DROP`, 파일 읽기 함수, extension load/install 같은 쓰기 또는 외부 접근 키워드는
차단됩니다.

### 4.4 운영/관리 명령

| 명령 | 용도 |
| --- | --- |
| `rules` | 태깅 규칙 검증, 목록, 추가, 제거, 테스트, 제안, gap 분석 |
| `journal` | 스냅샷 front matter가 있는 Markdown 재무 저널 작성/조회 |
| `automation` | 외부 scheduler에서 호출할 one-shot workflow check |
| `doctor` | 환경, 설정, 데이터 디렉토리, 의존성 진단 |
| `history` | import history 조회 |
| `open` | 데이터 디렉토리, imports, reports, rules, master 파일 열기 |
| `workspace` | symlink 기반 작업 디렉토리 생성/검증/제거 |
| `migrate` | legacy 데이터 위치를 `~/.finjuice`로 이전 |
| `manifest` | CLI manifest 출력 |
| `init` | 고급 초기화 |
| `update-agents` | 데이터 디렉토리의 AGENTS.md 템플릿 갱신 |
| `audit` | 실행 audit log 조회/통계/정리 |

예시:

```bash
finjuice doctor
finjuice history
finjuice open imports
finjuice open rules
finjuice workspace create ~/work/finance-review
finjuice automation run
finjuice manifest --commands-only --json
finjuice audit log
```

---

## 5. 리포트 이해하기

### 5.1 기본 XLSX/CSV export

```bash
finjuice export
```

기본 형식은 `xlsx`입니다.

- `exports/master_YYYYMMDD.xlsx`: 감사 가능한 전체 거래 workbook. 기본적으로 unfiltered.
- `exports/reports/monthly_spend.csv`: 월별 지출 요약, 이체 제외.
- `exports/reports/by_category.csv`: 최종 카테고리별 지출 집계, 이체/수입 제외.
- `exports/reports/by_tag.csv`: 태그별 지출 집계, 태그가 있는 지출이 있을 때 생성.
- `exports/reports/by_account.csv`: 계좌/카드별 순 지출, 이체 제외.
- `exports/reports/transfers.csv`: 내부 이체 감사 로그.

`rules.yaml`의 `report_filters`가 있으면 report CSV, HTML, Markdown, `query`,
`template`, `show`, `status`의 사용자용 분석 결과에 기본 반영됩니다. 감사용 원본 관점이
필요한 실행에서는 root 옵션을 붙입니다.

```bash
finjuice --no-filter query "SELECT COUNT(*) FROM transactions"
finjuice --no-filter export
```

### 5.2 HTML/Markdown export

```bash
finjuice export --format html
finjuice export --format html --period 2024-10 --no-auto-open
finjuice export --format md
finjuice export --format all
```

HTML은 Plotly 차트가 포함된 대화형 리포트입니다. Markdown은 GitHub나 노트에 붙이기
좋은 텍스트 리포트입니다.

### 5.3 주요 거래 컬럼

CSV 파티션의 현재 스키마는 v3입니다. 주요 컬럼:

- `row_hash`: 거래 고유 해시
- `date`, `time`, `datetime`: 날짜/시간
- `type_raw`, `type_norm`: 원본/정규화 거래 유형
- `major_raw`, `minor_raw`: 뱅크샐러드 원본 카테고리
- `merchant_raw`, `memo_raw`, `counterparty`: 거래처/메모/상대방
- `amount`, `account`, `currency`: 금액/계좌/화폐
- `category_rule`, `category_final`: 규칙 카테고리와 최종 집계 카테고리
- `tags_rule`, `tags_ai`, `tags_manual`, `tags_final`: 규칙/AI/수동/최종 태그
- `confidence`, `needs_review`: 검토 필요 여부 판단
- `is_transfer`, `transfer_group_id`: 내부 이체 감지 결과
- `file_id`, `source_row`: 원본 import 추적

---

## 6. 일반적인 워크플로우

### 6.1 새 뱅크샐러드 파일 처리

```bash
finjuice import ~/Downloads/뱅크샐러드_2026-04.xlsx
finjuice status --detailed
finjuice show --limit 20
```

`import`는 파일 복사와 전체 파이프라인 실행까지 처리합니다. 이미 `imports/`에 넣은
파일만 다시 처리하려면 `refresh`를 씁니다.

### 6.2 월별 회고

```bash
finjuice refresh
finjuice template list
finjuice template run monthly_spend --output markdown
finjuice export --format html --period 2026-04
finjuice journal new
```

### 6.3 새 규칙 추가 후 재처리

```bash
finjuice rules suggest
finjuice rules add \
  --name cafe_compose \
  --match "컴포즈|compose" \
  --tags 카페,커피 \
  --category 카페 \
  --priority 75
finjuice rules validate
finjuice tag
finjuice export
```

### 6.4 미태깅 거래 줄이기

```bash
finjuice review --untagged --all-history
finjuice rules suggest --top 20
finjuice rules test cafe_compose --month 2026-04
```

### 6.5 AI 에이전트와 함께 분석

finjuice CLI는 외부 LLM을 직접 호출하지 않습니다. 로컬 데이터를 구조화해 출력하고,
사용자가 선택한 에이전트나 LLM에 전달하는 방식입니다.

```bash
finjuice context --json > /tmp/finjuice-context.json
finjuice checkup --json --privacy redacted > /tmp/finjuice-checkup.json
finjuice query "SELECT category_final, SUM(amount) FROM transactions GROUP BY category_final" -o markdown
```

### 6.6 순자산과 예산 확인

```bash
finjuice assets status
finjuice networth breakdown --by category
finjuice networth forecast
finjuice budget status
finjuice budget validate
```

---

## 7. 문제 해결

먼저 진단 명령을 실행합니다.

```bash
finjuice doctor
finjuice status --json
finjuice --help
```

자주 보는 문제는 [Troubleshooting Guide](troubleshooting.md)를 참고하세요. CLI 세부 옵션은
생성 문서인 [CLI Reference](../reference/cli.md)보다 live help가 더 빠릅니다.

---

## FAQ

**Q: `finjuice all`을 써도 되나요?**  
A: 동작은 하지만 deprecated입니다. `finjuice refresh`를 쓰세요.

**Q: 기본 데이터 위치가 `./data`인가요?**  
A: 아닙니다. v0.7.0 기본값은 `~/.finjuice`입니다. 기존 `./data`는 `finjuice migrate`로
옮기거나 repo 밖의 개인 데이터 디렉터리를 `--data-dir`로 명시하세요.

**Q: 이체 시간 창을 CLI에서 바꿀 수 있나요?**  
A: 현재 CLI 옵션으로는 노출되어 있지 않습니다. 기본 감지는 5분 창과 1% 금액 허용치를
사용합니다.

**Q: AI 태깅이 자동으로 외부 모델을 호출하나요?**  
A: 아닙니다. finjuice는 로컬에서 읽기 전용 `context`/`checkup`/`query` 결과를 출력합니다.
외부 모델 사용 여부는 사용자가 별도로 결정합니다.

**Q: 여러 파일을 한 번에 처리할 수 있나요?**  
A: 네. `finjuice import ~/Downloads/*.xlsx` 또는 `finjuice import ~/Downloads/*.zip`처럼
여러 파일을 넘길 수 있고, 중복은 `row_hash`로 제거됩니다.

---

**문서 버전**: v0.7.0
**마지막 업데이트**: 2026-06-16
**문의**: [GitHub Issues](https://github.com/sungjunlee/finjuice/issues)
