# 정본 자산 의미와 명시 범위 보고

`ssot assets list --json`은 원래 source entity, observation, provenance, exact value ID와 의미·관계 이력을 조회한다. 아직 해석하지 않은 legacy 보고는 pending으로 남긴다. 원본 XLSX/관측의 범위·확인 상태·금액을 자동 변경하지 않는다.

`ssot assets confirm REQUEST.json`과 `correct ASSERTION_ID REQUEST.json`은 아래 요청을 실제 MutationService changeset으로 기록한다. 공통 필수 옵션은 `--idempotency-key`, `--expected-generation`, `--expected-revision`이다. 수정하려는 value ID가 원래 source entity에 연결되어 있어야 한다.

```json
{
  "source_entity_id": "<existing-source-entity-uuid>",
  "value_id": "<source-linked-exact-value-uuid>",
  "account_id": "<existing-account-uuid>",
  "resource_id": null,
  "measure_kind": "valuation",
  "source_kind": "institution_export",
  "as_of": "2026-07-01",
  "scope_state": "complete",
  "confirmation_state": "confirmed",
  "original_currency": "USD",
  "net_worth_sign": 1,
  "evidence": {"reason": "사용자가 확인한 의미와 범위 근거"}
}
```

measure_kind는 balance, holding_quantity, valuation, cash_movement, right_obligation, expected_inflow를 구분한다. net_worth_sign은 원래 부호 있는 exact 값에 곱하는 명시적인 +1/-1이다. 계좌명으로 채권·채무를 추정하거나 절댓값을 자동 적용하지 않는다. original_currency는 알려진 원본 통화와 달라질 수 없다. FX가 필요하면 `fx`에 coefficient, scale, quote_currency, as_of, 비어 있지 않은 evidence를 명시한다. 평가 통화·rate·기준일·근거는 보고에 남으며 오래된/미래/누락 FX는 미확정 범위로 보고한다.

`relation-confirm REQUEST.json`과 `relation-correct ASSERTION_ID REQUEST.json`은 container_id, member_id, relation_kind(includes/overlaps), evidence 및 선택적인 confirmation_state/effective_from/effective_to를 기존 canonical relation assertion으로 기록한다. 요약에 포함된 holdings나 기관 잔액과 겹친 수동 자료는 해당 assertion ID와 근거를 표시하며 제외한다. 관계가 미확정이면 중복 가능 항목을 확정 합계에 넣지 않는다.

unconfirmed/rejected 교정은 기존 confirmed 의미나 포함 관계를 제거하지 않는다. 확인된 successor만 연결된 이전 assertion을 supersede한다. 미확정 교정은 보고에 계속 드러나며, 실제 확인이 완료되기 전에는 완전한 합계를 주장하지 않는다. 원본과 이전 변경 이력은 삭제하지 않는다.

```text
finjuice --data-dir <root> ssot assets report \
  --as-of 2026-07-02 --currency USD \
  --party <party-uuid> --source <source-entity-uuid> --json
```

party는 반드시 명시한 기존 UUID 집합이며 옵션을 반복할 수 있다. source를 반복해 선언된 보고 범위를 좁힐 수 있다. 생략하면 보존된 전체 canonical 자산 source 범위에서 미해석·legacy 누락을 보고한다. 동일 snapshot에서 기준일 ownership 지분을 정확히 적용한다. 일부 화면은 최신 전체 관측을 대체하지 않고, 오래된 전체 자료는 이력으로 남긴다. 기본 stale 기준은 30일이며 `--stale-days`로 명시할 수 있다.

의미·소유·포함·통화/FX와 범위 근거가 충분하면 `complete_for_declared_scope`와 exact `net_worth_total`을 반환한다. 불완전하면 total은 null이고 알려진 subtotal, 미확정 잔여와 구체적인 issues를 반환한다. 이는 선언된 source 범위에 대한 합계이며 사용자의 세계 모든 재산을 수집했다는 주장이 아니다. 평가액은 stock 합계에만, cash_movement는 별도 cash_flow_subtotal에만 들어간다. quantity와 expected_inflow를 현금 또는 현재 순자산으로 자동 환산하지 않는다.

runtime schema 7은 `asset_meaning_assertions`만 추가한다. legacy migration policy4/5 pin은 유지하며 raw4/5/6 복원은 원래 schema를 보존한다. 현재 runtime 사용은 명시적인 clone upgrade/activation 계약을 따른다. 새로운 의미 fact는 backup_coverage에 포함되고 실제 recovery graph capture→검증→inactive restore 후 같은 snapshot query로 유지된다.

전체 가계 자산 수집 완료, 장비 밖 백업 운영, 임의 스크린샷의 자동 의미 확정과 과거 관측 소급 재작성은 이 기능의 완료 범위가 아니다.
