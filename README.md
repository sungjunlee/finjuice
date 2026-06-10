# finjuice

[![CI](https://github.com/sungjunlee/finjuice/actions/workflows/ci.yml/badge.svg)](https://github.com/sungjunlee/finjuice/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

finjuice는 **뱅크샐러드 XLSX/ZIP 내보내기에서 시작하는 AI 에이전트용 개인 금융 스킬 세트**입니다.
뱅크샐러드가 모아준 거래 내역은 편하지만, 내 기준으로 다시 묻고 고치고 오래 쌓아두려면
그냥 파일 더미보다 다루기 쉬운 로컬 데이터셋과 반복 가능한 작업 흐름이 필요합니다.
finjuice는 Claude Code나 Codex가 내보내기 파일을 가져오고, 중복 거래와 이체를 정리하고,
분류와 태그를 다듬고, 리포트를 만들도록 안내하는 스킬 중심 workflow입니다.

그래서 이름이 finjuice입니다. financial data를 juice처럼 짜내고, 뱅크샐러드라는 첫 재료를
한 잔의 읽기 쉬운 데이터로 갈아내는 작은 블렌더라는 뜻입니다.

## 이런 질문을 해볼 수 있어요

finjuice를 설치하면 Claude Code나 Codex에게 이런 식으로 물어볼 수 있습니다.

```text
지난달 지출에서 평소보다 심하게 늘어난 항목이 뭐야?
```

```text
지난 1년 소비 패턴을 분석해서 내가 줄일 수 있는 지출을 알려줘.
```

```text
내가 놓치고 있는 구독 요금이나 매달 새는 돈이 있는지 찾아줘.
```

```text
카드 결제나 계좌 이체 때문에 소비가 중복으로 잡힌 부분이 있는지 정리해줘.
```

```text
내 소비 내역에 맞는 카테고리와 태그 규칙을 제안해줘.
```

## 무엇을 하나요

- 뱅크샐러드 내보내기 파일을 가져와 첫 데이터셋을 만듭니다.
- 카드 결제, 계좌 이체처럼 소비로 잘못 보이기 쉬운 흐름을 정리합니다.
- 내 생활에 맞는 카테고리와 태그 체계를 함께 다듬습니다.
- 새 거래가 들어와도 같은 기준으로 다시 분류할 수 있게 규칙을 쌓습니다.
- "이번 달 어디에 많이 썼지?" 같은 질문에 답할 근거를 리포트로 남깁니다.
- Claude Code/Codex가 이 과정을 단계별로 진행할 수 있는 스킬 workflow를 제공합니다.

## 빠른 시작

필요한 것은 Claude Code 또는 Codex, Node.js/npm의 `npx`, 그리고 뱅크샐러드 XLSX/ZIP
내보내기 파일입니다. Python 런타임 설치가 필요하면 스킬이 안내합니다.

### 1. 스킬 설치

```bash
npx skills add sungjunlee/finjuice -g -a codex -a claude-code --skill '*'
```

한 에이전트에만 설치하려면 필요 없는 `-a` 항목을 빼세요.

### 2. 에이전트에게 온보딩 요청

Claude Code나 Codex에서 이렇게 요청하세요.

```text
finjuice 온보딩 시작해줘.
뱅크샐러드 내보내기 파일은 ~/Downloads/뱅크샐러드_*.xlsx 에 있어.
가져온 뒤 상태를 확인하고, 첫 미분류 거래 정리까지 도와줘.
```

스킬은 실행 환경 확인, 가져오기 미리보기, 상태 점검, 미분류 거래 정리 순서로 온보딩을 진행합니다.

### 3. 설치가 막힐 때

스킬이 `finjuice` 런타임을 찾지 못한다고 하면 아래 명령으로 직접 설치할 수 있습니다.

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv tool install git+https://github.com/sungjunlee/finjuice
uv tool update-shell
finjuice doctor --json
```

Windows PowerShell에서는 `uv` 설치만 다음 명령을 사용하세요.

```bash
irm https://astral.sh/uv/install.ps1 | iex
```

설치 확인에는 다음 명령이 유용합니다.

```bash
finjuice doctor --json
finjuice status --json
```

기본 데이터 위치는 `~/.finjuice/`입니다. 다른 위치를 쓰려면 `--data-dir` 또는
`FINJUICE_DATA_DIR`을 사용하세요.

## AI 에이전트와 함께 쓰기

finjuice의 제품 표면은 `skills/` 아래의 에이전트 workflow입니다. CLI는 이 스킬들이 호출하는
로컬 런타임입니다.

대표 workflow:

| 스킬 | 용도 |
|------|------|
| `finjuice-onboard` | 첫 실행, XLSX/ZIP 가져오기, 초기 상태 확인 |
| `finjuice-curate` | 미분류 가맹점 분석과 태깅 규칙 정리 |
| `finjuice-review` | 주간/월간 소비 리뷰 |
| `finjuice-report` | 근거 파일이 포함된 로컬 리포트 작성 |
| `finjuice-rule-cleanup` | 태그 체계와 규칙 품질 정비 |

종합 재정 진단은 명시적으로 요청할 때 별도 workflow가 돕습니다.

전체 스킬은 [skills/](skills/) 아래에서 확인할 수 있습니다.

## 데이터와 보안

- 개인 금융 데이터는 기본적으로 `~/.finjuice/` 아래에 저장됩니다.
- `data/`, `*.db`, `.env`, 개인 export 파일은 git에 올리지 마세요.
- 이슈나 토론에 raw 금융 데이터를 붙이지 마세요. 필요한 경우 synthetic 또는 redacted 예시를 사용하세요.
- 세금 신고, 대출, 투자 판단처럼 중요한 결정에는 원본 거래 내역을 직접 확인하세요.

별도 비공개 저장소에 데이터 디렉터리를 백업하고 싶다면
[데이터 백업 가이드](docs/guides/setup/data-repository.md)를 참고하세요.

## 더 알아보기

- [사용자 가이드](docs/guides/user_guide.md)
- [문제 해결](docs/guides/troubleshooting.md)
- [분석 워크플로](docs/guides/analyst-workflow.md)
- [AI CLI 통합](docs/guides/setup/ai-cli-setup.md)
- [Public agent smoke workflow](docs/guides/public-agent-smoke.md)
- [규칙 편집 워크플로](docs/workflows/rule-editing-with-claude.md)
- [CLI 레퍼런스](docs/reference/cli.md)

## 커뮤니티와 지원

버그 제보, 문서 개선, 실제 뱅크샐러드 export에서 발견한 케이스 공유를 환영합니다.
기여를 시작하기 전에 [CONTRIBUTING.md](CONTRIBUTING.md)를 확인해 주세요.

- [개발 가이드](CONTRIBUTING.md)
- [CI Gates](docs/development/ci.md)
- [Support policy](SUPPORT.md)
- [Code of Conduct](CODE_OF_CONDUCT.md)
- [Governance](GOVERNANCE.md)
- [Security policy](SECURITY.md)
- [GitHub Issues](https://github.com/sungjunlee/finjuice/issues)
- [GitHub Discussions](https://github.com/sungjunlee/finjuice/discussions)

## 면책

이 프로젝트는 개인 사용을 위해 만든 오픈소스 도구입니다. 금융, 세무, 투자 조언이 아니며
정확성을 보장하지 않습니다. 자동 분류와 리포트는 항상 원본 거래 내역과 함께 검증하세요.

## 라이선스

MIT License
