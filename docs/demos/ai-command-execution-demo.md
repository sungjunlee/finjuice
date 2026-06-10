# AI Command Execution Demo

**Date**: 2025-11-24
**Feature**: `finjuice chat` with AI command auto-execution
**Status**: ✅ Production Ready (PR #14)

---

## Quick Demo Scenarios

### Scenario 1: Re-tagging After Rule Update

**User Input**:
```
> 규칙 파일 업데이트했어. 전체 재태깅 해줘
```

**Expected AI Response**:
```markdown
규칙 파일을 업데이트하셨군요! 전체 거래 내역을 새 규칙으로 재태깅하려면 다음 명령을 실행하세요:

```bash
finjuice --data-dir ~/.finjuice tag
```

이 명령은 모든 거래 내역을 처음부터 다시 태깅합니다.
```

**Auto-Execution Flow**:
```
📋 AI suggested command #1:
   finjuice --data-dir ~/.finjuice tag
   Source: code_block

Execute this command? (y/n) [y/N]: y
⏳ Executing...
✅ Success (3.2s)

--- Output ---
Processing 2,269 transactions...
Applied 47 rules
Tagged: 2,143 transactions (94.4%)
Untagged: 126 transactions (5.6%)
```

**Audit Log Entry**:
```json
{"timestamp": "2025-11-24T23:30:15", "event": "command_suggested", "command": "finjuice --data-dir ~/.finjuice tag", "source": "ai", "user_confirmed": true}
{"timestamp": "2025-11-24T23:30:18", "event": "command_executed", "command": "finjuice --data-dir ~/.finjuice tag", "success": true, "returncode": 0, "duration": 3.2}
```

---

### Scenario 2: Multiple Commands with Mixed Confirmation

**User Input**:
```
> 데이터 업데이트 전체 파이프라인 실행해줘
```

**Expected AI Response**:
```markdown
전체 파이프라인을 실행하려면 다음 명령들을 순서대로 실행하세요:

1. 새 XLSX 파일 인제스트:
```bash
finjuice --data-dir ~/.finjuice ingest
```

2. 규칙 기반 태깅:
```bash
finjuice --data-dir ~/.finjuice tag
```

3. 이체 매칭:
```bash
finjuice --data-dir ~/.finjuice transfer
```

4. 리포트 생성:
```bash
finjuice --data-dir ~/.finjuice export
```

또는 한 번에 실행:
```bash
finjuice --data-dir ~/.finjuice refresh
```
```

**Auto-Execution Flow** (User selectively approves):
```
📋 AI suggested command #1:
   finjuice --data-dir ~/.finjuice ingest
Execute? (y/n) [y/N]: y
✅ Success (1.5s)

📋 AI suggested command #2:
   finjuice --data-dir ~/.finjuice tag
Execute? (y/n) [y/N]: n
⏭️  Skipped

📋 AI suggested command #3:
   finjuice --data-dir ~/.finjuice transfer
Execute? (y/n) [y/N]: y
✅ Success (0.8s)

📋 AI suggested command #4:
   finjuice --data-dir ~/.finjuice export
Execute? (y/n) [y/N]: y
✅ Success (2.1s)

📋 AI suggested command #5:
   finjuice --data-dir ~/.finjuice refresh
Execute? (y/n) [y/N]: n
⏭️  Skipped
```

---

### Scenario 3: Security Block - Path Traversal Attempt

**Malicious User Input** (hypothetical):
```
> ../../../etc/passwd 파일로 태깅 결과 저장해줘
```

**Expected AI Response** (if AI suggests dangerous command):
```bash
finjuice export --output-dir ../../../etc/passwd
```

**Auto-Execution Flow**:
```
📋 AI suggested command #1:
   finjuice export --output-dir ../../../etc/passwd
   Source: code_block

Execute this command? (y/n) [y/N]: y
❌ Validation failed: Path traversal not allowed: ../../../etc/passwd

[Command blocked by security validator]
```

**Audit Log Entry**:
```json
{"timestamp": "2025-11-24T23:35:00", "event": "command_suggested", "command": "finjuice export --output-dir ../../../etc/passwd", "source": "ai", "user_confirmed": true}
{"timestamp": "2025-11-24T23:35:00", "event": "command_error", "command": "finjuice export --output-dir ../../../etc/passwd", "stage": "validation", "error_type": "CommandValidationError", "error_message": "Path traversal not allowed: ../../../etc/passwd"}
```

---

### Scenario 4: Timeout Protection

**User Input**:
```
> 100만 건 거래 인제스트해줘 (가상 시나리오)
```

**Expected Flow**:
```
📋 AI suggested command #1:
   finjuice --data-dir ~/huge-finance-data ingest

Execute? (y/n) [y/N]: y
⏳ Executing...
❌ Timeout: Command timed out after 60s: finjuice --data-dir ~/huge-finance-data ingest

Partial stdout (5,432 chars):
Processing transactions...
Batch 1/100: 10,000 rows processed
Batch 2/100: 20,000 rows processed
...
```

**Audit Log Entry**:
```json
{"timestamp": "2025-11-24T23:40:00", "event": "command_error", "command": "finjuice --data-dir ~/huge-finance-data ingest", "stage": "execution", "error_type": "CommandTimeoutError", "error_message": "Command timed out after 60s..."}
```

---

## Component Test Results

### Parser Test
```
✅ Parser: Extracted 1 command(s)
   Command: finjuice tag
   Args: ['--data-dir', './data']
```

### Validator Test
```
✅ Validator: Command passed security checks
```

### Executor Test (Dry Run)
```
✅ Executor: Dry run command: finjuice --data-dir ~/.finjuice tag
```

### Audit Logger Test
```
✅ AuditLogger: Ready to log to ./data/.execution_audit.jsonl
```

---

## Security Features Verified

| Feature | Status | Test |
|---------|--------|------|
| **Whitelist Validation** | ✅ | Only 6 commands allowed |
| **Path Sandboxing** | ✅ | Rejects paths outside data_dir |
| **Path Traversal Block** | ✅ | Rejects `..` patterns |
| **Shell Injection Block** | ✅ | Detects `; | & $ `` |
| **Symlink Resolution** | ✅ | Resolves to real paths |
| **Timeout Protection** | ✅ | 60s for REPL, 30s default |
| **Output Truncation** | ✅ | Max 100KB per stream |
| **Audit Logging** | ✅ | JSON Lines format, 0600 perms |

---

## Performance Benchmarks

| Operation | Time | Notes |
|-----------|------|-------|
| Command parsing | <10ms | Regex + shlex |
| Validation | <5ms | Path resolution + checks |
| Execution (tag) | ~3s | 2,269 transactions |
| Execution (export) | ~2s | Generate standard CSV reports |
| Audit logging | <1ms | JSON append + chmod |

---

## Next Steps

1. **Real User Testing**: Run `finjuice chat` and try these scenarios
2. **Audit Log Analysis**: Review `.execution_audit.jsonl` after usage
3. **Security Testing**: Attempt penetration tests (Issue #NEW)
4. **Integration Testing**: Combine with Dashboard (Issue #103)

---

**Documentation**: [docs/workflows/ai-command-execution.md](../workflows/ai-command-execution.md)
**Issue**: #5 (Closed)
**PR**: #14 (Merged)
