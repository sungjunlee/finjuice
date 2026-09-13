# 교차 파일 overview 참조를 capture 범위의 별도 근거로 보존

**Status**: proposed
**Date**: 2026-09-13
**Issue**: #435

## Context and Problem Statement

권장안은 **B: 기존 projection FK와 분리된 capture 범위의 참조·파생 근거**다.
이 문서는 계약 선택 제안이며 채택이나 구현 승인을 기록하지 않는다.
기준 코드는 PR #481의 `72164af`다. 선행 PR #463은 열린 상태이며
승인·머지를 전제하지 않는다. 기존 fixture와 리뷰를 다시 실행하지 않았다.

[ADR-0014](0014-sqlite-authoritative-storage.md)와
[보존 계약 §2.2–3](../../development/ssot-migration-recovery-contract.md)은
원본 bytes, 파일별 occurrence, 행좌표, 중복 legacy ID, 정확수치와 원문을 보존하고
첫 이전에서 병합·추론하지 않도록 정한다. 동일 bytes의 파일 두 개는 artifact를
공유해도 occurrence는 별도다. 동결 capture의 digest와 원래 locator가 이전 ID를 정한다.

현재 구현에는 다음 제약이 있다.

- `migration/adapters/model.py:58–69`와 `adapters/__init__.py:35–71`은
  파일별 occurrence와 행별 provenance를 보존한다.
- `storage/sqlite/schema.py:375–380,869–884`는 projection의 fact FK와
  projection/fact의 동일 occurrence를 요구한다. 같은 capture라는 사실로
  이 조건을 대신할 수 없다. provenance를 다른 파일로 옮겨 통과시켜서도 안 된다.
- `entity_relation_assertions`의 관계 종류는 포함·중첩·배제·불명이다
  (`schema.py:601–628`). 중복계상 판단용 의미를 파생 관계로 재해석하지 않는다.
  `transaction_source_links`도 거래 전용이며 overview 계약이 아니다.
- `tests/migration/test_migration_integration.py:133–279`의 고유 ID,
  중복 ID·행·파일, 미존재 ID 사례는 모두 derived 행의 원문과
  `unresolved_source_fact` / `preserved_opaque`를 확인한다.
  고유 ID 일치도 typed 연결 성공을 증명하지 않는다. 사실 행의 정확수치는 typed로,
  미지원 derived 금액은 원문으로 보존한다. 이 차이를 해소한 것으로 보고하지 않는다.

위 코드 경로는 `src/finjuice/pipeline/` 기준이다. 계약은 의도이고,
fixture는 현재 보존 동작의 증거다. capture 전체 ID 탐색은 후보를 찾을 수 있지만
현재 스키마에서 교차 파일 projection을 만들 수 있게 하지는 않는다.

## Considered Options

| 선택안 | 보존성과 typed 의미 | 재실행 | 모호·미존재 참조 | 기존 DB·소비자 영향 |
| --- | --- | --- | --- | --- |
| A. 현재 opaque 보존 유지 | 모든 원문·occurrence 유지. 새 연결 의미 없음 | 현행 ID와 semantic replay 유지 | 기존 unresolved 사유·payload 유지 | 스키마 변화 없음. 구조화된 참조 조회와 typed derived 처리는 계속 미완료 |
| B. capture 범위의 별도 참조·파생 근거 (권장) | 두 파일의 출처를 그대로 두고 관계 근거를 별도 보존. 기존 projection FK 유지 | capture·행 endpoint·버전된 정책으로 결정적 ID와 후보 정렬 | 후보 전체를 보존하고 ambiguous/missing을 명시. 없는 fact를 만들지 않음 | 새 버전의 저장·읽기·검증 계약 필요. 기존 projection 소비자는 자동으로 이 관계를 사용하지 않음 |
| C. projection invariant에 검증된 교차 파일 예외 도입 | 출처를 유지하면서 typed projection 가능. 동일 occurrence만으로 보장하던 제약을 명시적으로 확장 | endpoint·정책·근거를 결정적으로 저장해야 함 | 미검증·모호·미존재 행은 typed projection 금지, 원문 유지 | schema/validator/reader와 모든 projection 소비 의미를 함께 변경해야 함. 잘못된 예외가 typed 금액에 직접 영향 |

A는 현재 안전한 대기 상태지만 참조의 구조화가 진전되지 않는다. C는 장기적으로
가능한 선택이나 첫 보존 단계에서 FK 의미와 소비자 동작까지 바꾸는 범위가 크다.
어느 선택도 파일 occurrence 병합, legacy ID 중복 제거, fact 출처 위조를 허용하지 않는다.

## Decision Outcome

**제안: B를 후속 구현의 계약 방향으로 채택한다.** 원본 보존과 참조 판정을
분리할 수 있고, 현재 동일-occurrence projection 제약을 약화하지 않기 때문이다.
B는 typed overview 구현을 완료하지 않는다. 관계가 검증돼도 기존 projection 테이블에
그대로 삽입할 수 없으며, 소비 방식은 후속 공개 계약 검토가 필요하다.
현재 세 fixture는 명시적 참조 locator나 producer namespace의 유효성을 증명하지
않는다. 실제 capture에 그런 증거가 있는지도 이번 공개·합성 검토에서 확인하지 않았다.
따라서 B의 입증 가능한 이득은 **후보집합과 판정 근거의 구조화된 보존**이다.
세 fixture의 참조는 B에서도 미검증·모호·미존재로 남을 수 있다. 이 구조화 자체가
새 schema/reader/복원 비용을 정당화한다는 권고이며, typed 해소를 보장하지 않는다.

채택 시 다음 조건을 하나의 계약으로 적용한다. 아래 상태·필드는 개념 이름이며
새 SQL 컬럼·enum·CLI JSON 명세를 이 문서에서 확정하지 않는다.

1. 참조의 주체는 derived 원본 행의 provenance/observation이다. 동결 capture,
   원문 `source_fact_id`, 파일·행 locator를 보존한다. 상대는 같은 capture에서 찾은
   실제 fact entity와 그 원래 provenance다. 동일 ID 후보가 여러 개여도 합치지 않는다.
2. 고유 alias는 후보가 하나라는 뜻일 뿐이다. 참조 해소에는 원본의 명시적 locator,
   생산자의 버전된 ID namespace/참조 규칙 등 하나의 occurrence를 특정하는 증거가
   필요하다. 단순 값·날짜 일치나 파일 탐색 순서로 선택하지 않는다. 증거가 없으면
   고유 후보도 미검증으로 남긴다. 증거가 있는 중복 후보의 선택은 다른 후보의 삭제가 아니다.
3. 참조 대상 확인과 파생 계산 검증을 구분한다. 파생 검증에는 원본 producer/parser의
   버전된 변환 규칙, 필요한 입력과 정확수치·단위·반올림 정책이 있어야 한다.
   금액 동일성만으로 파생을 추정하지 않는다. 검증되지 않은 식이나 통화는 원문과
   사유로 남긴다. 관계의 검증은 금융 값 재계산·재분류를 승인하지 않는다.
4. 미존재 참조에는 대상 FK를 꾸며 넣지 않는다. 참조 요청 자체와 빈 후보집합을
   보존한다. 참조 요청과 후보 edge를 개념적으로 분리한다. 요청은 항상 실제 derived
   행과 capture를 가리키며, 후보 edge가 존재할 때만 실제 fact FK·endpoint 타입과
   동일 capture membership을 검사한다. missing은 edge 0개인 유효한 미해결 상태다.
   ambiguous는 여러 유효 후보 edge를 갖되 선택된 대상은 없는 상태다. 검증된 대상은
   유효 후보 중 하나와 조건 2의 증거가 있어야 하며, 없거나 다른 capture인 endpoint를
   허용하는 예외는 두지 않는다. 모호한 참조는 후보 전체·각 occurrence와 판정 근거를 남긴다.
   현행 opaque payload와 issue는 삭제하거나 의미를 바꾸지 않는다.
5. 동일 capture와 동일 판정 정책의 재실행은 같은 관계 ID·후보집합·판정을 만든다.
   참조 요청 ID는 capture digest + 버전된 record kind + canonical locator를 사용한다.
   locator에는 derived 원래 root/path/행좌표와 참조 필드의 이름·열 ordinal,
   필드 내 여러 참조가 있을 경우 원문 token ordinal, 판정 정책 버전을 포함한다.
   따라서 한 행의 서로 다른 참조 지점도 별도 ID를 갖는다. 후보 edge의 locator는
   요청 식별자와 fact entity 식별자를 함께 포함한다. attempt 시각·output hash·
   단독 alias는 ID 입력이 아니다. 후보는 안정된 fact entity ID 순으로 정렬한다. 정책이 바뀌면 별도 버전의 판정으로
   이전 근거를 보존하며, 기존 관계를 몰래 다시 해석하지 않는다.
6. 관계와 필요한 근거는 DB·불변 source의 백업 그래프에 포함되어야 한다.
   향후 테이블은 reader의 authoritative table 목록과 semantic replay, FK·capture
   membership·endpoint 타입 검증에 포함한다. 일반 관계의 `unknown`이나 자유 JSON에
   성공 관계를 숨겨 기존 검증을 우회하지 않는다.

### 기존 DB 호환과 확인 조건

현재 reader는 지원 버전과 다른 DB를 거부한다(`schema.py:1311–1320`).
따라서 테이블 추가도 구 reader와 자동 호환되지 않는다. 후속 구현은 명시적 schema
버전과 복제 candidate 업그레이드, 새 reader, 구 reader의 명확한 거부, 백업·복원과
semantic replay 범위를 함께 검증해야 한다. 이미 보존된 payload에서 재구성하되
기존 entity ID·원문·occurrence를 보존하고 원래 candidate를 직접 덮어쓰지 않는다.
기존 DB에 관계 행이 없다는 이유로 참조가 없거나 검증됐다고 판단해서는 안 된다.
동일 동결 capture와 동일 정책에 대해 신규 build와 기존 DB의 격리 업그레이드는
동일 요청 ID·후보 edge·판정·근거를 산출해야 한다. 업그레이드의 보존 payload만으로
원본 참조 지점이나 근거를 복구할 수 없으면 해당 입력의 자동 업그레이드를 거부하고,
검증된 원본 capture에서 새 candidate를 재구축한다. 추정한 locator로 parity를 만들지 않는다.

후속 구현의 확인 대상은 현재 세 보존 사례에 더해, 명시적 참조 증거 유무,
다른 capture의 동일 alias 거부, 정책 변경 시 기존 근거 유지, 정확수치·단위와
변환 규칙 검증, 관계가 포함된 복원·재실행, 이전 schema의 격리 업그레이드다.
이는 향후 조건이며 이번에 새 테스트를 작성하거나 실행한 결과가 아니다.

## 채택 전에 필요한 결정 하나

**기존 same-occurrence projection FK를 유지하고, 교차 파일 참조·파생 근거를
위 조건의 독립된 capture 범위 관계로 보존하는 B를 후속 구현 방향으로 채택할 것인가?**

결정 전에는 A의 현행 동작을 유지한다. 이번 변경은 문서뿐이며 schema·공개 CLI·JSON,
R1/R3 의미, 실자료 migration·activation, 선행 PR 머지를 변경하거나 승인하지 않는다.
#435의 수용 조건과 `cutover_ready=false`도 그대로다.

## 검토 기록

Native 읽기 전용 검토로 현행 코드와 fixture 근거를 확인했다. Cursor/Grok 4.6는
workspace trust 단계에서 차단되어 검토 결과가 없으며 우회하지 않았다.
Opus 5 high의 단일 문서 검토는 참조 지점별 ID, 미해결 endpoint 검증,
업그레이드/build 판정 동등성, B의 증거·효용 범위를 지적했다. 작성자가 위 조건에
반영했다. 수정 후 추가 외부 리뷰는 하지 않았으므로 최종 문서의 재승인을 주장하지 않는다.
