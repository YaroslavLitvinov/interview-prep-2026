---
name: constraint-design
description: Mandatory constraints design process - MUST get approval FIRST, MUST show real execution evidence with process numbers, MUST follow verification workflow before adding to spec.k.json
---

# ⛔ MANDATORY CONSTRAINT DESIGN PROCESS

## Core Principles of Constraint Design

### Principle 1: Constraints Enforce Convergence

Constraints are the machine-enforced equivalent of the convergence workflow. They:
- Fail when system is NOT in required state
- Lock once verified (fails_count ≥ 1)
- Block code changes when unverified or failing
- Act as guard rails preventing regression

**Translation:** Constraints prevent shipping incomplete work. They make convergence non-negotiable.

### Principle 2: Zero-State Rule (Constraints Must Fail First)

Every constraint MUST fail on a completely empty or incomplete codebase.

**Why:** If a constraint passes on empty code, it's worthless—it tests nothing. A passing constraint that never failed is unverified and provides no safety.

**How:** Design constraints to fail first, then fix code to make them pass.

---

## CRITICAL RULES (Non-Negotiable)

### Rule 1: APPROVAL FIRST ⛔
**NEVER add constraint without explicit written approval from user.**

- ❌ Propose and assume yes
- ❌ Propose and proceed without answer
- ✅ Propose → Wait for explicit YES/NO → Then add if approved

### Rule 2: REAL EXECUTION EVIDENCE MANDATORY ⛔
**NEVER add constraint without showing REAL test execution with process numbers and exit codes.**

Evidence must include:
- ✅ Actual command execution (not theoretical)
- ✅ Process ID/Number from real test runs
- ✅ Exit code results (0 = PASS, non-zero = FAIL)
- ✅ Real stdout/stderr output
- ✅ Exact same command that will be in spec.k.json

### Rule 3: NO INTERMEDIATE STATES ⛔
**Constraints become LOCKED after first execution. Must verify before adding.**

Once `fails_count ≥ 1`, the constraint is locked:
- `cmd` cannot be changed
- `fails_count` cannot be modified
- Only way to resolve: fix underlying code/knowledge
- This prevents constraint bypass

### Rule 4: TEST IN ISOLATION ⛔
**NEVER test constraints on real workspace files. Use temporary test files only.**

- ❌ Delete real project files during testing
- ❌ Modify project structure for constraint tests
- ✅ Create temp test files → Test → Clean up temp files

### Rule 5: Constraint Immutability After Verification ⛔
**Verified constraints are permanently locked to enforce convergence.**

Once a constraint has failed (`fails_count > 0`):
- It becomes part of the system's guard rails
- It cannot be removed, weakened, or bypassed
- It can only be satisfied by fixing the underlying code/knowledge
- This locks in system state and prevents regression

---

## Process Flow

```
PROPOSE
   ↓
   [Execute FAIL test on TEMPORARY file, capture real output with PID]
   ↓
   [Execute PASS test (cleanup temp), capture real output with PID]
   ↓
   [Present real evidence to user]
   ↓
   [WAIT FOR APPROVAL]
   ↓
APPROVED? 
   ├─ NO → Don't add
   └─ YES → Add to spec.k.json
```

---

## Before Finalizing: Design Checklist

Before proposing ANY constraint to the user, verify:

- [ ] **Command is exact** — Uses `$PROJECT_ROOT`, not hardcoded paths
- [ ] **Exit code logic correct** — 0 = PASS, non-zero = FAIL (not based on echo output)
- [ ] **Zero-State Rule** — Constraint MUST fail on empty/incomplete codebase
- [ ] **Fails for right reason** — Failure message makes sense (grep for specific data, not success strings)
- [ ] **Path rule applied** — All paths use `$PROJECT_ROOT` variable
- [ ] **Category clear** — One of: Structural, Behavioral, Environmental, Negative/Security
- [ ] **Description complete** — Explains WHAT and WHY, not just echoing the code

**Do not propose constraints that fail this checklist.**

---

## Communication Template

When proposing a constraint, use this template:

```
**Constraint Proposal:** [constraint_id]

**Command:**
[exact bash command with $PROJECT_ROOT]

**Description:**
[what this constraint validates and why it matters]

**Category:**
[Structural | Behavioral | Environmental | Negative/Security]

**Testing Evidence:**
[Will show real execution evidence with process numbers and exit codes]

---

**FAIL Test Evidence:**
- Process: [PID from real execution]
- Exit Code: 1
- Output: [actual command output]
- Interpretation: Constraint correctly fails on violation

**PASS Test Evidence:**
- Process: [PID from real execution]
- Exit Code: 0
- Output: [actual command output or "(no output)"]
- Interpretation: Constraint correctly passes on clean state

---

**Awaiting Approval:** Explicit YES/NO required before adding to spec.k.json
```

---

## Evidence Table Format

When presenting test results, use this table structure:

| Test | Process | Exit Code | Output | Result |
|------|---------|-----------|--------|--------|
| FAIL | 3275 | 1 | "Forbidden markdown files found" | ✓ Fails correctly |
| PASS | 3293 | 0 | "(no output)" | ✓ Passes correctly |

**Required fields:**
- **Test** — FAIL or PASS test label
- **Process** — Actual PID from bash execution (not theoretical)
- **Exit Code** — 1 for FAIL, 0 for PASS
- **Output** — Real stdout/stderr from command execution
- **Result** — Interpretation of what the output means

---

## Summary

1. **Propose** constraint to user with exact command
2. **Execute FAIL test** on temp file - show real output, PID, exit code
3. **Execute PASS test** (cleanup temp) - show real output, PID, exit code
4. **Present evidence** in Evidence Table format with real process numbers
5. **Wait** for explicit approval (YES/NO only)
6. **Add** to spec.k.json only if approved
7. **Never** test on real project files
8. **Never** delete project files for testing
9. **Never** assume YES

**This is not optional. Follow exactly.**
