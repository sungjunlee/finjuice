# M4 canonical 다음 기능 계약 (#442 / #443 / #444)

기준 HEAD 9ee9d9a4635561d9d44b9f3ee8109ee0e1fd2329. GitHub 세 issue 본문과 현재 코드/테스트를 읽었다. 제품 수정·private 접근·테스트/전체검사 실행 없음.

## 결론: 이미 있는 canonical 기반 위에 명령과 import resolution을 연결한다

ownership/relation/intake를 새 DB나 in-memory store로 다시 구현할 필요가 없다. schema5에 포함된 기존 v2 관계/입력 테이블, MutationService, 검증된 detached reader가 실제 기반이다. 먼저 **안정 계좌에 대한 명시적 source 매핑 + 기간 ownership의 확정·교정·조회 + 실제 다른 XLSX 재수입 + 격리 복원 유지**를 하나의 기능 묶음으로 닫는 것이 적절하다.

다만 현재 schema에는 범용 runtime source alias의 명시적 저장계약이 없다. 기존 legacy_identifiers를 억지로 범용 alias registry로 쓰거나 relation_kind=includes를 identity equivalence로 해석해 'schema 변경 없이 완료'라고 해서는 안 된다. 아래 persistence 결정은 첫 묶음 시작 전에 필요하며, 현재 읽기 작업에서 schema 변경을 구현하지 않았다. Root 통합 결정: runtime source binding은 기존 보존 mapping과 분리한 typed assertion으로 동일 canonical DB에 저장한다. 구현 전 기존 schema 업그레이드와 policy replay/복구 호환성 계약을 함께 정하고, 현재 진행 중인 delivery 기능 묶음과 동시에 schema를 수정하지 않는다.

## 이미 canonical로 구현되어 있으므로 재작성하지 않을 것

### 안정 entity, ownership, relation

- `storage/sqlite/records.py`: PartyRecord / AccountRecord / ResourceRecord에 안정 UUID가 있다. AccountRecord는 unknown ownership을 표현한다.
- OwnershipAssertionRecord/OwnershipShareRecord는 기간·complete/partial/unknown·확인 상태·근거·supersedes를 저장한다. 실제 share는 ExactValue의 ownership_share.v1 unit으로 들어간다.
- `MutationContext.add_ownership_assertion`은 assertion+shares와 감사 entry를 삽입한다. `schema._validate_ownership_assertions`는 정밀 합계/1 초과/complete 합계1/기간 충돌/same-account supersession을 검사한다.
- `add_relation_assertion`과 schema 검증은 includes/overlaps/excludes/unknown, 기간·명시적 supersession·같은 ordered pair·모순 관계를 처리한다.
- `tests/pipeline/test_sqlite_mutations.py`에 실제 120자리 precision ownership, partial/overlap/supersession, 잘못된 unit 전체 rollback, 기간/관계 모순 검증이 이미 있다. 같은 테스트를 새 AccountRegistry만 대상으로 재작성하는 것은 진전이 아니다.

### 입력 lineage와 commit

- AgentIntakeArtifact/Occurrence/Extraction/Proposal/Confirmation/Application이 원본 객체·발생·추출·해석·결정·적용 changeset을 분리한다.
- MutationContext에 각 insert API가 있고 application validator는 실제 확인/제안/request의 generation/revision/scope/key 일치를 검사한다. 원본 객체는 기존 source_artifacts/SourceObjectStore로 보존할 수 있다.
- 기존 테스트: list extraction 허용+mapping proposal 적용, list proposal 거절과 전체 lineage rollback, stale proposal 재제안, 잘못된 application rollback, occurrence/source artifact 및 extraction/proposal policy별 중복 방지가 있다.
- MutationService의 exact request digest/idempotency/revision/감사/receipt 단일 transaction을 그대로 쓴다. agent.ApplyReceipt 또는 메모리 revision으로 대체하지 않는다.

### 조회/복원

- `portfolio_reads.portfolio_snapshot`은 실제 reader revision에서 assets/overview/config/evidence를 materialize한다. `_relationships`는 reachable accounts의 ownership assertions/shares와 direct relations를 실제 DB에서 읽는다.
- `read_facade`와 기존 portfolio/analysis 소비는 authority evidence 및 한 reader snapshot을 사용한다. `tests/pipeline/test_sqlite_portfolio_reads.py::test_native_ownership_share_and_direct_relation_evidence`가 실제 ownership/relation 근거 노출을 검증한다.
- 현재 `portfolio_display`는 명시적으로 identity/ownership merge를 하지 않는 보존/표시 adapter다. assertion row를 읽을 수 있다는 것과 개인·가계·기간별 소유분을 실제 집계한다는 것은 다르다.
- 기존 backup/recovery/inactive restore는 canonical DB와 참조 원본을 보존한다. 새로운 별도 account JSON DB를 만들 이유가 없다.

## 실제 공백

### #442: confirmed identity가 다음 import에서 선택되지 않는다

`exact_import/persist_transactions.py::_add_unresolved_account`는 새 거래마다 새로운 unknown 계좌를 만든다. `persist_assets.py::_account_id`는 한 import 작업의 dict에서 source_account_id를 재사용할 뿐, 이전 실행의 confirmed binding을 조회하지 않는다. 따라서 기존 계좌/ownership row가 삭제되지 않아도 새 XLSX의 새 계좌 row가 그 stable identity를 사용한다고 보장할 수 없다.

현재 `legacy_identifiers`는 capture_manifest_digest, provenance, preserved identifier의 table이며 RepositoryBuilder에 add/supersede가 있다. MutationContext에는 범용 alias bind/rebind API가 없다. legacy supersession은 보존 mapping 교정의 유용한 기존 계약이지만 출처 namespace와 안정 외부 key, runtime 확인 상태의 typed alias 계약을 대신하지 않는다.

필요한 결정:

- 과거 보존 capture의 특정 계좌 mapping 교정은 실제 capture/provenance를 유지하며 existing legacy mapping/supersession을 mutation 경계로 노출할 수 있다. 원본 legacy 계좌 identity를 파괴하거나 거래를 이름만으로 합치지 않는다.
- 향후 XLSX/스크린샷/설명까지 동일 계좌를 선택하는 **runtime source binding**에는 source namespace + external key + target account + evidence + confirmation/supersession 계약이 필요하다.
- schema5 legacy table에 없는 namespace를 identifier_value에 ad hoc JSON으로 숨기거나 가짜 capture digest를 넣지 않는다. intake proposal/application payload만을 영구 domain alias truth로 삼는 것도 권하지 않는다. 제안 lineage와 적용 결과의 정본을 다시 섞고 별도 current-selection 규칙을 만들게 된다.
- 우선 기존 schema가 이 의미를 정식으로 표현할 수 있는지 확인한 뒤, 불가능하면 **동일 canonical SQLite에 작은 typed account binding/assertion extension**을 추가하는 것이 정직하다. 새 DB가 아니다. schema6이라는 이름을 먼저 만들 필요는 없지만 'schema5만으로 이미 완결'이라고도 주장하지 않는다. migration·검증·backup coverage를 같은 묶음에 넣는다.

계좌 이름은 표시 속성이고 identity key가 아니다. 새 이름/새 출처는 명시적으로 같은 account UUID에 binding한다. ambiguous alias는 pending mapping으로 남기고 자동 소유자 추정/자동 merge를 하지 않는다. 기존 미확정 observation/account와 새 stable account의 관계를 설명하는 resolution을 추가하되 원본 source identity를 삭제·대량 덮어쓰기하지 않는다.

### #443: raw evidence 노출 다음의 의미 adapter/조회

ObservationRecord에는 시간/범위/확정/supersedes가 있지만 전체/부분 최신성, summary↔holdings 제외, cash vs valuation, FX 기준이 연결된 canonical report는 raw portfolio snapshot만으로 완료되지 않는다. 새 assets 순수 계산 모델로 변환할 때 source time, exact measure, scope, confirmation, relation, stable account resolution을 실제 DB에서 얻어야 한다.

특히 개인 소유비중과 가계 reporting scope는 다르다. 현재 ownership 테이블을 household 포함 여부로 재해석하지 않는다. household scope 및 asset classification/liquidity의 지속 모델이 없으면 별도 명시적 사실로 설계해야 한다. 첫 묶음에서 소유 조회를 닫고, 가계 scope/전체 networth를 완료라고 표시하지 않는다.

### #444: 실제 명령/Hermes와 domain 적용

현재 canonical lineage API는 테스트 handler에서 사용되지만, 새 agent.IntakeSession/IntakeStore는 별도 dict 모델이다. 기존 CLI manifest에서 계좌 mapping/ownership/intake submit-confirm의 실제 operator 명령을 찾지 못했다. `agent.import_xlsx_source`는 실제 exact XLSX importer가 아니라 메모리 payload submit이다.

공통 evidence submission/단계별 pending 조회, 실제 proposal expected generation/revision, 확인 후 domain effect+application link의 단일 MutationService transaction, typed scope별 correction/replay가 필요하다. 일회 거래 정정은 기존 manual edit, 반복 규칙은 config mutation, 계좌 사실은 account/ownership mutation으로 dispatch한다. 수정 유형을 암묵적으로 바꾸지 않는다.

## 새 main에서 재사용 가능한 정책만

- `accounts/policies.py`: 계좌 성격(deposit/broker/pension/IRP)과 resource asset class/liquidity 분리 원칙 및 closed tokens는 참고 가능하다. pension이라는 이유로 restricted 등의 정책을 자동 추론하지 않는다.
- `accounts/queries.py`의 기간/share 계산은 canonical의 날짜 경계와 exact unit 계약을 대조한 뒤 재사용한다. 기존 schema validators의 정밀 검증을 Decimal 편의 계산으로 대체하지 않는다.
- `assets/current_view.select_current`, `inclusion`, `aggregation`, `issues`는 순수 선택/제외/설명 계산 후보다. canonical snapshot→모델 adapter와 실제 evidence 검증이 먼저다. 모델의 confirmed 값을 caller로부터 신뢰하지 않는다.
- `agent/keys`, `render`의 결정표시/정규화 아이디어는 재사용 가능하나 canonical source digest/idempotency와 일치해야 한다. `IntakeStore`, AccountRegistry, assets changeset 저장 모델은 DB 대체물로 채택하지 않는다.

## 첫 기능 묶음: 명시 계좌 매핑·기간 ownership → 다른 XLSX → 복원

목표 사용 흐름:

1. 실제 authority-bound 계좌/미해결 source 후보를 한 revision에서 조회한다. 표시명·provenance·unknown 소유 상태·mapping ambiguity를 구분한다.
2. 사용자가 계좌 UUID와 source binding을 명시 확인한다. 영향 preview에는 영향을 받을 기존 source occurrence/asset/transaction scope와 before/after resolution을 보여준다.
3. exact 지분/기간/근거로 ownership assertion을 확정한다. 이미 구현된 supersession으로 교정하고 원본 assertion은 유지한다. 철회는 삭제가 아니라 명시적인 successor 상태와 감사로 표현한다.
4. 다른 byte의 실제 XLSX를 import한다. 동일파일 idempotent replay만 확인하는 테스트는 부족하다. importer는 **명시적으로 확정된** namespace/key binding만 사용하고 모호하면 unresolved로 남긴다. 확인된 소유권을 XLSX 표시명/부분 자료가 덮어쓰지 않는다.
5. 개인·계좌·기준일 조회에서 같은 stable identity와 유효 assertion을 읽는다. unknown remainder를 노출하고 inferred household total은 만들지 않는다.
6. 실제 managed graph capture → inactive restore → 같은 조회 → correction mutation → rebackup/second restore로 유지 사실을 확인한다.

### 최소 파일 경계 (새 파일명은 제안)

- `storage/sqlite/account_bindings.py` 또는 동등 모듈: typed binding read/resolve 및 확인·교정 handler. 실제 persistence 결정 결과만 구현한다. 출처별 arbitrary query나 메모리 전역 registry를 만들지 않는다.
- `records.py`, `mutations.py`: 필요한 domain mutation API만 노출하고 existing add_ownership_assertion/검증을 재사용한다. account binding 저장계약이 schema extension을 요구할 때만 `schema.py`와 migration tests를 수정한다.
- `storage/mutation_facade.py`: account binding/ownership request의 typed entry point 및 existing MutationService dispatch.
- `exact_import/persist_transactions.py`, `persist_assets.py` 및 필요한 lookup: 실제 확인 binding resolve를 한 writer transaction에서 사용한다. 미확정/미지원 경로는 현재 unknown 정책 유지.
- `storage/sqlite/account_reads.py` 또는 `portfolio_reads` 제한 확장 + `read_facade.py`: reachable portfolio evidence만으로 모든 미연결 계좌를 조회할 수 없으므로 계좌 registry용 실제 detached snapshot이 필요하다. 해당 데이터도 single revision으로 읽는다.
- `cli/commands`의 작은 account 명령군: 후보/impact preview, 명시 confirm/correct, as-of ownership 조회. 기존 semantic output/JSON manifest/schema generator 규칙을 따른다. 전체 screenshot extraction/LLM 자동실행은 첫 묶음에서 불필요하다.
- 필요한 경우 입력 evidence와 canonical proposal/application helper를 붙이되 #444 전체 channel integration을 이 계좌 묶음 하나로 완료했다고 보고하지 않는다.

## 검증 경계와 중복 방지

기존 ownership/relation/intake 전체 validator suite를 재작성하지 않는다. 처음 좁은 회귀는 새로운 연결을 관통해야 한다.

- 실제 confirmed source binding 뒤 **다른 XLSX**의 같은 외부 key/새 표시명/새 출처 확인 → 같은 stable account와 기간 ownership 사용. ambiguity가 있으면 pending이고 implicit merge 없음.
- 같은 mutation key replay/충돌, stale preview 확인 거절, binding rebind/correction의 before/after/근거/영향범위, rollback 때 domain 및 lineage 둘 다 남지 않음.
- 두 명의 exact 공동지분과 기간 경계/unknown remainder를 single-snapshot reader와 human/JSON에서 구분. 가계 범위 미정은 미정으로 표시.
- 계좌 facts 확정 후 원본 XLSX 재수입뿐 아니라 screenshot/설명 evidence 재전송 lineage가 중복 domain effect를 내지 않는지 필요한 한 경로만 실제로 연결.
- 기존 ownership assertions 및 stable ID를 포함한 실제 restore/read/correction/rebackup/secondrestore. 기존 fixture/helper를 재사용하고 fake durable receipt/메모리 registry 테스트로 대체하지 않는다.
- 기존 보호 회귀는 `test_sqlite_mutations.py`의 ownership/intake/relation 선택 범위, `test_sqlite_portfolio_reads.py`, actual exact-import 관련 기존 test 중 변경 경계만 먼저 실행한다. 한 기능 묶음 완료 후 root의 통합 full/build/installed를 한 번 수행한다.

이 첫 묶음이 끝나면 #442의 identity 재수입/ownership/교정 핵심에 실제 증거가 생긴다. #443 전체 자산 의미 집계, household reporting scope, #444 Hermes 모든 채널/변경 유형은 남은 연결별로 계속 추적한다. issue merge/모듈 존재/테이블 존재만으로 체크박스를 닫지 않는다.
