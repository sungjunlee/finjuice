# Legacy overview 보고값과 참조 근거를 분리해 보존

**Status**: accepted (저장·adapter 구현, 소비자·운영 검증 미완료)

**Date**: 2026-09-13

**Issue**: #435, 소비자 검증 #436

## 문제와 근거

첫 이전은 기존 보고값과 출처를 보존해야 한다. 고유한 `source_fact_id` 일치만으로
다른 파일의 fact occurrence를 확정할 수는 없다. `ingest/overview/facts.py`의
`_build_fact_id`는 snapshot/block/kind/label/좌표를 포함하지만 file_id, sheet,
workbook bytes, 값은 포함하지 않는다. `metadata/import_history.py:record_import`는
같은 경로에서 file_id를 재사용하고, `storage/csv_banksalad_overview.py`의 fact dedup도
file_id/sheet/값을 키에 포함하지 않는다. 현행 producer의 한 호출에서 공유된 fact ID가
과거 CSV 전체의 생산 버전·불변 원본을 증명하지는 않는다.

다섯 derived CSV에는 source_fact_id와 file_id가 있지만 sheet/block/source_col은 없다.
Cashflow에는 source_row와 currency도 없다. 보험·투자·대출의 참조는 이름 셀을
가리킬 수 있으므로 참조 확인과 금액 계산 검증도 서로 다르다.
위 경로는 `src/finjuice/pipeline/` 기준이며 공개 생산 코드 조사에 근거한다.
실제 운영 capture의 연결 증거나 typed 보존 완료를 주장하지 않는다.

기존 SQLite native projection은 fact FK 및 동일 occurrence를 요구한다.
이를 통과하려고 provenance를 옮기거나 가짜 fact를 생성하면 출처가 훼손된다.
원문만 보존하는 현행 opaque 방식과 별도 후보 근거만 추가하는 이전 B 제안은
보고값의 typed 보존 공백을 해결하지 못한다.

## 결정

기존 행 observation을 키로 하는 **별도 legacy reported 테이블**에 보고값을 저장하고,
참조 요청·후보·판정은 별도 근거로 보존한다. Native projection의 FK와
동일 occurrence 불변식은 유지한다. 새 entity kind는 추가하지 않는다.
실행 계약의 구조 변경 권한으로 방향을 채택했다. 저장·이전 adapter는 구현했으며,
이 문서는 전체 #435·#436 또는 운영 완료를 뜻하지 않는다.

- `legacy_overview_reports`는 기존 deterministic observation을 PK/FK로 사용하고
  kind와 원래 provenance를 가진다. Balance/cashflow/insurance/investment/loan의
  명시적인 detail 테이블은 해당 kind마다 정확히 하나 존재해야 한다.
- 값·텍스트·날짜·원문 payload와 원래 파일 occurrence/행좌표를 보존한다.
  Exact value의 provenance는 report와 같아야 한다. 기존 observation/migration
  identity를 재사용하고 immutable evidence trigger를 적용한다.
- 수치는 기존 exact lexical 계층으로 먼저 검증한 뒤 삽입한다. 빈 금액을 0으로
  만들지 않는다. Cashflow의 없는 통화나 다른 파일의 빈 통화를 KRW로 추정하지
  않고 unknown currency로 보존한다. Rate는 명시적 legacy 단위와 원문을 보존하며
  퍼센트 변환이나 금융 의미 교정은 하지 않는다.
- Reference assessment는 원문 source_fact_id, capture digest, 고정된 판정 정책을
  보존한다. 같은 capture에서 alias가 일치하는 모든 fact 원본 행이 후보다.
  Typed 변환에 실패한 fact 행도 provenance를 가진 후보 근거로 남는다.
  Nullable typed fact FK를 저장한다면 후보 provenance와 같은 행인지 검증한다.
- 후보가 없으면 missing, 하나면 unverified, 여러 개면 ambiguous다. 이번 정책은
  선택된 fact를 주장하지 않는다. 날짜·금액·file_id나 탐색 순서로 후보를 제거하거나
  선택하지 않는다. 같은 bytes의 파일도 각각의 occurrence로 남긴다.
- 분석과 build는 동일 capture 색인과 판정 함수를 사용한다. 행 생성 후 후보를
  삽입해 파일 순서에 의존하지 않는다. 원문 미해석과 참조 미검증의 issue/disposition을
  구분하며, 참조 미검증 자체가 보고값의 typed 보존을 막지는 않는다.

## 스키마와 과거 후보 재생

새 스키마는 v5, 새 adapter policy는 `legacy_preservation.overview_reports.v4`다. 기존 sealed plan의
legacy v1/config-head v2/manual-state v3는 **정확히 schema v4**로 생성·재생한다.
일반 runtime은 최신 schema를 요구하고, 과거 v4 허용은 migration 내부 경로로 한정한다.

`RepositoryBuilder`, reader/validator와 `semantic_snapshot`에 정책이 요구하는 정확한
스키마를 연결한다. 기존 목록은 `_READ_TABLE_SQL_V4` registry로 고정하고 v5 목록을
확장한다. 기존 digest에 빈 새 테이블을 추가하거나, version을 지우거나, 누락 테이블을
무시해 재검증을 통과시키지 않는다. v4 validator는 v5 테이블에 접근하지 않는다.

일반 v4→v5 upgrade는 기존 snapshot→별도 candidate→source object 복사 흐름을 유지하며
빈 새 테이블만 추가한다. 과거 opaque 자료를 임의로 재해석하지 않는다.
Upgrade 산출물은 기존 sealed migration candidate와 같지 않다. 기존 manifest를
복사해 같은 digest를 주장하지 않으며, 새 typed baseline은 원 capture와 새 정책으로 만든다.

## 구현 순서와 검증

1. 버전별 registry/reader/builder/validator와 정책별 schema 계약을 먼저 구현한다.
   실제 과거 코드로 만든 세 정책의 후보 bytes/hash 불변 검증과 새 build의 schema4를
   확인한다. 일반 v4→v5 upgrade의 원본 불변도 확인한다.
2. 보고값 테이블·정확수치 계약·행 adapter를 구현한다. 다섯 종류 전체 필드, unknown
   통화, 빈 값, 잘못된 수치와 부분 typed 삽입 금지를 검증한다.
3. Capture 색인과 별도 참조 판정을 구현한다. 유일/중복/미존재/invalid fact,
   동일 bytes 다중 occurrence, 파일 순서 독립성과 capture 밖 후보 거부를 검증한다.
4. 새 정책 후보의 결정성, 새 테이블/후보/단위 변조 거부와 기존 native FK를 확인한다.
   #436에서 reported 값과 참조 상태의 소비 및 기존 결과 parity를 검증한다.

스키마 추가만으로 #435 전체 AC를 체크하지 않는다. 실제 동결 자료의 전수 보존 검증,
소비자 parity, 운영 전환과 복원 증거는 실행 계약에 따라 별도로 완료한다.

## 고려한 대안

| 대안 | 판단 |
|---|---|
| Opaque 유지 | 원문 보존은 되지만 보고값 typed 공백이 남음 |
| 별도 참조 근거만 추가(이전 B 제안) | 후보 구조화만으로 보고값을 소비할 수 없음 |
| 기존 projection FK에 교차 파일 예외 추가 | 현재 CSV에 occurrence를 확정할 증거가 부족함 |
| 별도 reported 값 + 독립 참조 판정 | 기존 native 불변식과 원본 의미를 함께 유지하므로 채택 |

관련 계약: [ADR-0014](0014-sqlite-authoritative-storage.md),
[보존·복구 계약](../../development/ssot-migration-recovery-contract.md).
