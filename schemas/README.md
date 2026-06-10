# finjuice output schemas

이 디렉터리는 `finjuice ... --json` 출력용 JSON Schema 산출물을 담습니다.
스키마는 Draft 2020-12이며, 명령별 파일명은 `schemas/{command_path}.schema.json`
형식을 따릅니다. 중첩 명령은 `_`로 연결합니다. 예: `journal_list.schema.json`,
`template_run.schema.json`.

공통 `_meta` envelope는 `schemas/_meta.schema.json`에 있으며 명령별 스키마가
`$ref`로 참조합니다. `_error.schema.json`은 `emit_error()`가 출력하는 공통 오류
envelope입니다.

## Python

```python
import json
from pathlib import Path

import jsonschema

schemas_dir = Path("schemas").resolve()
schema = json.load(open(schemas_dir / "checkup.schema.json", encoding="utf-8"))
data = json.load(open("/tmp/checkup.json", encoding="utf-8"))

resolver = jsonschema.RefResolver(
    base_uri=f"{schemas_dir.as_uri()}/",
    referrer=schema,
)
jsonschema.Draft202012Validator(schema, resolver=resolver).validate(data)
```

## JavaScript

```js
import Ajv from "ajv";
import { readFileSync } from "fs";

const ajv = new Ajv({ strict: false });
const meta = JSON.parse(readFileSync("schemas/_meta.schema.json", "utf8"));
const checkup = JSON.parse(readFileSync("schemas/checkup.schema.json", "utf8"));

ajv.addSchema(meta, "_meta.schema.json");
const validate = ajv.compile(checkup);
const data = JSON.parse(readFileSync("/tmp/checkup.json", "utf8"));

if (!validate(data)) {
  throw new Error(JSON.stringify(validate.errors));
}
```

## Version policy

`_meta.schema_version`은 명령 출력 스키마 버전이며 manifest 스키마 버전과 독립적입니다.
같은 major 버전에서는 additive-only 변경만 허용합니다. 새 optional 필드 추가나 enum 값
확장은 가능하지만, required 필드 제거/이름 변경/타입 축소는 새 major 버전으로 올려야
합니다.

스키마 파일을 갱신할 때는 다음 명령을 실행합니다.

```bash
just docs-output-schemas
```
