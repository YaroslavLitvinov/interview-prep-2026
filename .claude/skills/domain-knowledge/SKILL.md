---
name: domain-knowledge
description: Define what the system validates across 7 dimensions. Know exactly when work is complete (convergence OK criteria).
---

# Domain Knowledge: 7-Dimensional System Validation & Convergence OK

## What "Converge" Means

**Converge** is the systematic process of making required state transitions toward atomic system outcomes.

### The Convergence Operation

```
Converge = identify_current_state 
         → determine_required_changes 
         → execute_changes 
         → verify_atomic_state_reached
```

### What "Atomic State" Means

Atomic = **All 7 dimensions are in PASS or LOCKED state simultaneously**

- Partial state (some dimensions PASS, others FAIL) = NOT atomic = NOT converged
- All dimensions PASS or LOCKED = atomic = converged = safe to ship

### How Convergence Happens

**Multiple 5-phase cycles across all 7 dimensions with verified, locked constraints = Convergence to atomic state**

```
Iteration 1: Check all 7 dimensions → Fix failures in D1, D3, D5
Iteration 2: Check all 7 dimensions → Fix failures in D2, D4
Iteration 3: Check all 7 dimensions → All PASS/LOCKED
                                      ✓ CONVERGENCE ACHIEVED
```

Each iteration is a **5-phase cycle:**
1. Understand impact (which dimensions affected?)
2. Capture baseline (snapshot before changes)
3. Apply changes (code + knowledge)
4. Verify outcomes (snapshot after changes)
5. Update knowledge (document the changes)

### The Re-balancing Core Principle

**Systems naturally drift out of balance. Re-balancing is not cleanup — it's the primary operation.**

- When any dimension falls behind others → re-balance immediately
- When constraints fail → re-balance, don't skip
- When knowledge diverges from code → re-balance, don't defer
- When patterns emerge that don't fit the structure → re-balance the structure

**Re-balancing means:**
- Identifying which dimensions are misaligned (PASS vs FAIL vs LOCKED)
- Making changes to bring all 7 dimensions into PASS or LOCKED simultaneously
- Updating knowledge to reflect the new balanced state
- Verifying the system is atomic again

**Anti-pattern:** Ignoring misalignment and letting "good enough" become "broken later." Convergence requires constant re-balancing, not periodic cleanup.

---

## Core Principles (9 Foundational Rules)

All decisions in this system are guided by 9 immutable principles. These are not guidelines — they are constraints on how the system operates:

### 1. CONVERGE: ATOMIC STATE MACHINE
- **Definition:** Systematic process of making required state transitions from current → atomic (complete) state
- **Rule:** System cannot claim readiness while any dimension is PARTIAL. All dimensions must transition to READY together
- **Enforcement:** Dimension audit before every task. No workarounds become permanent. Every gap has a remediation plan with ETA
- **Why:** Non-atomic states hide failures, invite technical debt, and prevent production deployment

### 2. ZERO-STATE RULE: CONSTRAINTS MUST FAIL FIRST
- **Definition:** Every constraint must FAIL on empty codebase before it can be verified
- **Rule:** Constraint verification: fails_count=0 → add constraint → run check (FAIL) → increment fails_count → constraint locked → fix implementation → check (PASS)
- **Enforcement:** Unverified constraints (fails_count < 1) BLOCK all source code edits until first failure occurs
- **Why:** Constraints that never fail are worthless; verification requires at least one failure to prove the constraint works

### 3. KNOWLEDGE EVOLUTION: LIVING DOCUMENTS
- **Definition:** Project knowledge documents MUST evolve with codebase. Knowledge is not static reference — it IS the authoritative system state
- **Rule:** Update knowledge whenever design decisions change, constraints evolve, capability gaps discovered, or architecture patterns shift
- **Enforcement:** Stale knowledge is treated as a bug. No permanent workarounds without documentation in gap-*.k.json
- **Why:** Knowledge drift causes duplicate bugs, broken assumptions, and untrackable technical debt

### 4. CAPABILITY AUDIT: 7-DIMENSIONAL VERIFICATION
- **Definition:** Every non-trivial task MUST audit all 7 dimensions and report which capabilities are READY vs PARTIAL
- **Rule:** Before code changes identify affected dimensions, verify capabilities, report gaps immediately, track in gap-*.k.json
- **Enforcement:** Tasks cannot proceed without dimension audit. Missing audits block approval
- **Why:** Partial capabilities in one dimension break adjacent dimensions; atomic verification prevents cascading failures

### 5. FORBIDDEN MARKDOWN (Single Source of Truth)
- **Definition:** Knowledge is authored in .k.json (structured, auditable), markdown is auto-generated
- **Rule:** All knowledge changes via `/plugin/bin/patch-knowledge-document` only. No direct markdown editing
- **Enforcement:** Edit/Write hooks reject direct .md file creation in state_machine/knowledge/
- **Why:** Single source of truth ensures auditability, prevents divergence, makes regeneration safe

### 6. KNOWLEDGE DESIGN STANDARDS
- **Definition:** Knowledge documents must follow semantic structure with clear ID, type, relationships
- **Rule:** All documents use knowledge tool's model system. Custom fields extend, don't bypass
- **Enforcement:** Orphaned entities detected via constraint, must be removed or linked
- **Why:** Structured knowledge enables automated verification, cross-linking, and consistency checking

### 7. RE-BALANCING: Self-Correcting Systems
- **Definition:** Systems naturally drift out of balance. Re-balancing is the primary operation, not cleanup
- **Rule:** When any dimension falls behind → re-balance immediately. When constraints fail → re-balance, don't skip
- **Enforcement:** Balance checking integrated into convergence workflow
- **Why:** Ignoring drift creates compounding technical debt; constant re-balancing keeps system coherent

### 8. CAPABILITY ARCHITECTURE: No Fake Features
- **Definition:** Features are only READY when all 7 dimensions support them. No fake implementation
- **Rule:** Capability requirements must cover all dimensions. If dimension not ready, feature is not ready
- **Enforcement:** Constraints map to dimensions. Feature only passes when all mapped dimensions PASS
- **Why:** Partial implementations look done but fail in production under load, concurrency, or edge cases

### 9. ASIMOV'S LAWS: Convergence Safety
- **Definition:** System enforces guardrails automatically; human judgment is fallible
- **Rule:** Constraints are immutable once verified. Verification requires real execution evidence
- **Enforcement:** No exceptions to constraint safety once locked. Only way out is fixing the code
- **Why:** Technical decisions are reversible; safety decisions are not. Guard rails prevent bad choices

### 10. ARCHITECTURAL BOUNDARY: STATE_MACHINE IS SELF-CONTAINED
- **Definition:** `state_machine/` is a standalone, reusable system. Project depends ON state_machine, not vice versa
- **Rule:** NO project-specific knowledge (PROJ-*, project rules, project constraints) in `state_machine/knowledge/`. State machine documents ONLY generic, reusable principles and patterns
- **Enforcement:** `structure.py` validates that `state_machine/knowledge/*.k.json` files do NOT reference project-specific IDs. Any reference to `PROJ-*`, project-specific constraints, or project rules is an ERROR
- **Why:** State machine must be portable, reusable across projects. Project-specific coupling creates unmaintainable, non-transferable code. Clear boundaries enable modularity

**Valid in state_machine/knowledge:**
- Generic architecture principles (convergence, event sourcing, 7 dimensions)
- Reusable patterns (state history, dimension tracking, versioning)
- System-level constraints (no circular references, immutability rules)

**NOT valid in state_machine/knowledge:**
- Project-specific rules: `PROJ-34423`, `PROJ-00001`, etc.
- Project features or knowledge: project requirements, project domain concepts
- Project domain IDs: anything prefixed with the project's prefix

**Project knowledge lives in:**
- `project_knowledge/` (project-specific documents)
- Project-level `.k.json` files using project ID prefix
- NOT in `state_machine/knowledge/`

---

## When to Use This Skill

**Use domain-knowledge models for:**
- Documenting core domain concepts and terminology
- Recording architecture decisions with context and rationale
- Capturing design patterns and constraints used in the project
- Cross-referencing with feature specs and constraint suites
- Building institutional knowledge that persists beyond individual developers

**Alongside y2:features_and_constraints:**
- Use `DomainKnowledge` to provide context for `Spec` documents
- Reference architecture decisions when explaining `Feature` constraints
- Link knowledge documents for comprehensive project understanding

---

## Convergence OK Criteria (Complete Definition)

### The 5 Mandatory Criteria

Work is complete when **ALL 5 criteria are satisfied simultaneously**:

#### 1. Constraints PASS
- **Requirement:** All constraints PASS
- **Check:** `/plugin/bin/check --full-report | grep 'PASS'`
- **Why:** No regressions, all features verified and locked
- **Failure:** Any failing constraint = continue work

#### 2. Dimensional Alignment
- **Requirement:** All 7 dimensions at PASS or LOCKED (no FAIL, no BLOCKED)
- **Check:** Verify `state_machine/models/dimension_state_registry.json`
- **Why:** System is balanced, no prerequisite gaps
- **Failure:** Any dimension FAIL/BLOCKED = continue work

#### 3. Knowledge Integrity
- **Requirement:** No orphaned knowledge entities
- **Check:** jq validation on all `*.k.json` files
- **Why:** Documentation is complete and linked
- **Failure:** Orphaned entities = incomplete knowledge

#### 4. Code-Tests Alignment
- **Requirement:** Code and tests both passing
- **Check:** `pytest tests/` passes + app executes cleanly
- **Why:** Implementation matches specification
- **Failure:** Test failures = code doesn't work

#### 5. Impact Reports Locked
- **Requirement:** All dimension changes have locked impact reports
- **Check:** `state_machine/reports/` contains reports for changed dimensions
- **Why:** Improvements are recorded and protected from regression
- **Failure:** Missing reports = changes not documented

---

## Convergence OK Verification Process (8 Steps)

### Step-by-Step Checklist

```
[ ] Step 1: Run all constraints
        Command: /plugin/bin/check --full-report
        Expected: All PASS
        
[ ] Step 2: Verify all 7 dimensions
        Check: state_machine/models/dimension_state_registry.json
        Expected: All PASS or LOCKED
        
[ ] Step 3: Run full test suite
        Command: pytest tests/
        Expected: All tests pass (0 failures)
        
[ ] Step 4: Verify app executes
        Command: python -c 'from app.interview_prep_app import *'
        Expected: No errors
        
[ ] Step 5: Check knowledge integrity
        Validate: All *.k.json files
        Expected: No orphaned entities, all references valid
        
[ ] Step 6: Verify impact reports
        Check: state_machine/reports/ 
        Expected: Reports exist for all changed dimensions
        
[ ] Step 7: Final Decision
        IF all 6 steps pass:
            ✓ CONVERGENCE OK - Task complete, safe to stop
        ELSE:
            ✗ NOT CONVERGED - Continue work, retry after changes
            
[ ] Step 8: Task Completion
        IF CONVERGED_OK: Mark task complete
        IF NOT CONVERGED: Continue working until convergence achieved
```

---

## Convergence OK State Machine

The system operates in 3 states:

```
┌─────────────────┐
│  NOT_CONVERGED  │  Some checks failing, continue working
└────────┬────────┘
         │ (start work on failing checks)
         ▼
┌──────────────────┐
│   IN_PROGRESS    │  Working toward convergence, checking after each change
└────────┬─────────┘
         │ (all checks pass)
         ▼
┌──────────────────┐
│ CONVERGED_OK ✓   │  All checks passing, system aligned, safe to stop
└──────────────────┘
```

**Valid transitions:**
- NOT_CONVERGED → IN_PROGRESS (identify what needs fixing)
- IN_PROGRESS → CONVERGED_OK (all 5 criteria met)
- IN_PROGRESS → NOT_CONVERGED (regression detected, back to fixing)
- CONVERGED_OK → (task complete, mark as done)

---

## Task Completion Rule (Non-Negotiable)

### The Rule
**Never accept task completion without convergence OK state**

### Workflow
```
1. Task work begins
2. Make code changes
3. Check convergence (run 8-step process)
   ├─ If NOT converged: Continue working on failures
   └─ If converged: Task complete
```

### Exception
If explicitly starting convergence-focused work, continuous work continues until CONVERGED_OK achieved (can be multiple iterations).

---

## Automatic Convergence Check Triggers

Convergence verification should run:

- **After every dimension change is accepted** — Immediate feedback
- **Before marking any task as complete** — Verify before stopping
- **Before pushing code or creating PR** — Ensure PRs are convergent
- **After merging changes** — Detect regressions immediately

**Report format:** Convergence OK Verification Report (JSON + markdown)

---

## The 7 Validation Dimensions

Each dimension defines what must be verified for convergence OK:

| # | Dimension | Validates | Convergence Goal |
|---|-----------|-----------|------------------|
| 1 | **Structural** | Code structure, modules, dependencies | No circular deps, clear boundaries |
| 2 | **Format/Syntax** | Code style, linting, naming | 100% style compliance |
| 3 | **Behavioral** | Runtime logic, state, error handling | All state machines valid, errors handled |
| 4 | **UX/Design** | User experience, accessibility, usability | Accessible, responsive, intuitive |
| 5 | **Integration** | APIs, communication, service boundaries | All APIs match contracts, messages reliable |
| 6 | **Maintenance** | Documentation, testability, coverage | Documented, testable, coverage ≥80% |
| 7 | **Mocking** | Test infrastructure, fixtures, isolation | Comprehensive test coverage with proper isolation |

**Convergence requires:** All 7 dimensions PASS or LOCKED simultaneously

---

## 7 Dimensions as Code State Constraints

### Principle: Every Dimension Describes Actual Code State

Each of the 7 dimensions is a **constraint on the codebase**. They are not abstract readiness levels—they are measurable properties of the code that either satisfy or violate requirements:

| Dimension | Constraint Name | What Code Must Satisfy |
|-----------|-----------------|------------------------|
| **Structural** | `constraint_no_circular_deps` | No circular imports, clear module boundaries, proper layering |
| **Format/Syntax** | `constraint_style_compliance` | Code passes linting, naming conventions followed, consistent formatting |
| **Behavioral** | `constraint_logic_correctness` | State machines valid, error handling present, edge cases handled |
| **UX/Design** | `constraint_ux_compliance` | UI accessible, responsive, intuitive navigation, proper error messages |
| **Integration** | `constraint_api_contracts` | All APIs match defined contracts, messages reliable, proper error propagation |
| **Maintenance** | `constraint_docs_coverage` | Code documented, test coverage ≥80%, maintainability high |
| **Mocking** | `constraint_test_isolation` | Tests isolated with proper mocks, no test interdependencies |

### Workflow: Per-Dimension Checkpoint & Approval

When an agent completes work:

1. **Agent runs dimension checkpoint** → State machine reports changes for EACH dimension separately
2. **User reviews each dimension** → Reports what changed in code for each constraint
3. **User approves or rejects** → Each dimension can be approved/rejected independently
4. **If mixed results** (some approved, some rejected):
   - Mark approved dimensions as LOCKED (verified)
   - Identify what code changes caused rejections
   - Run convergence handler → Fix code to satisfy rejected dimensions
   - Iterate until all dimensions converge to same state
5. **When all converge** → All 7 dimensions PASS or LOCKED simultaneously → Atomic state reached

### Central State Machine Enforcement

All dimension constraints are checked from ONE place: `state_machine/dimension_checkpoint.py`

When agent finishes:
```python
from state_machine.dimension_checkpoint import DimensionCheckpoint

checkpoint = DimensionCheckpoint()
report = checkpoint.capture_current_state()  # Snapshot code state across 7 dimensions
changes = checkpoint.identify_changes(baseline, report)  # What changed per dimension?
checkpoint.report_changes(changes)  # Show user: "D1 changed", "D5 changed", etc.

user_feedback = checkpoint.wait_for_user_approval()  # User: approve/reject per dimension

if user_feedback['approved'] != user_feedback['rejected']:
    # Mixed state - converge
    convergence_handler = ConvergenceHandler()
    convergence_handler.fix_to_converged_state(user_feedback)
else:
    # All same - system stable
    checkpoint.lock_approved_dimensions(user_feedback['approved'])
```

### Example Workflow

**Initial state:** All dimensions PARTIAL
```
Structural:     PARTIAL (some deps unclear)
Format/Syntax:  PARTIAL (some style issues)
Behavioral:     PARTIAL (some error handling missing)
UX/Design:      PARTIAL (navigation incomplete)
Integration:    PARTIAL (API contracts unclear)
Maintenance:    PARTIAL (coverage < 80%)
Mocking:        PARTIAL (test isolation incomplete)
```

**Agent makes changes** to improve Structural and Behavioral

**Checkpoint reports:**
```
Structural:     CHANGED (circular deps resolved)  → User: APPROVE
Behavioral:     CHANGED (error handling added)    → User: APPROVE
(other dims):   UNCHANGED
```

**Mixed approval state detected** → Convergence handler:
- Structural → move to LOCKED
- Behavioral → move to LOCKED
- Others still PARTIAL → Code must now satisfy those constraints too

**Agent runs again** to fix Format/Syntax, UX/Design, Integration, Maintenance, Mocking

**Final checkpoint:**
```
All 7 dimensions → PASS/LOCKED → ATOMIC STATE → ✓ Convergence achieved
```

---

## Knowledge Linkage for Convergence

For convergence OK to be meaningful, knowledge must be complete:

```
Feature X
  ├─ References Dimension 1-7: Which dimensions does this touch?
  ├─ References Constraint_Y: What must be validated?
  ├─ References ADR_Z: Why this design?
  └─ References Test_file: How is it tested?

Dimension N
  ├─ Contains entities: Specific things to validate
  ├─ Referenced by constraints: How validation happens
  ├─ Referenced by features: What uses this dimension
  └─ References tests: Proof that validation works
```

**Convergence principle:** If knowledge is complete and linked, convergence checking is automated and trustworthy.

---

## Why Convergence OK Matters

**Without convergence checking:**
- ❌ You don't know if system is actually ready
- ❌ Ship incomplete features (missing docs, untested code)
- ❌ Dimensions gradually fall out of sync
- ❌ Regressions go undetected
- ❌ System becomes unreliable

**With convergence checking:**
- ✅ Objective definition of "done" (all 5 criteria)
- ✅ Complete, verified features (all 7 dimensions)
- ✅ Dimensions stay synchronized
- ✅ Regressions caught immediately
- ✅ System remains reliable and maintainable

---

---

## Knowledge Layering Structure (4 Tiers)

Domain knowledge is organized hierarchically in 4 tiers. Each tier builds on the previous one:

### Tier 1: Principles & Methodology (Foundation)

Immutable principles guiding all decisions:

- **principles** — 9 core principles (Converge, Zero-State, Knowledge Evolution, Capability Audit, etc.)
- **converge** — The systematic convergence operation definition
- **converge-integration** — How convergence integrates with skills and workflows
- **principles-in-skills** — How each skill implements the principles

**Purpose:** Answer "What are the unchanging rules governing this system?"

**Depends on:** Nothing (foundation)

### Tier 2: Strategy & Constraints (Planning)

Strategic guidance for implementing Tier 1 principles:

- **constraints-7d-strategy** — 37 constraints fragmented across 7 dimensions
- **dimension-capability-status** — Current gaps & workarounds per dimension
- **approach-dimension-[1-7]** — Detailed approach for each dimension

**Purpose:** Answer "How do we achieve the principles in practice?"

**Depends on:** Tier 1 (principles guide strategy)

### Tier 3: Policies & Rules (Enforcement)

Policies and rules that enforce Tier 1 & 2:

- **knowledge-evolution-policy** — How knowledge documents evolve
- **constraint-verification** — Verification patterns and workflows
- **capability-audit** — Mandatory 7-dimension audit procedures
- **forbidden-markdown** — Single source of truth enforcement

**Purpose:** Answer "What rules must be followed to stay aligned?"

**Depends on:** Tier 2 (strategy informs policy)

### Tier 4: Domain & Architecture (Implementation)

Concrete domain knowledge and architectural decisions:

- **domain-*** — Domain concepts, terminology, patterns
- **adr-*** — Architecture Decision Records
- **gap-*** — Current capability gaps and workarounds

**Purpose:** Answer "What are the concrete facts about this system?"

**Depends on:** Tier 3 (policies guide domain choices)

### Hierarchical Dependency

```
Tier 1: Principles
   ↓ (guides)
Tier 2: Strategy
   ↓ (informs)
Tier 3: Policies
   ↓ (enforces)
Tier 4: Domain & Architecture
   ↑ (feeds back)
   
(Feedback loop: Domain facts discovered → Strategy updates → Policies refined → Principles validated)
```

### The Self-Balancing Principle

**All principles are self-balancing:** If knowledge structure needs rebalancing for clarity, rebalance immediately without hesitation.

- Domain facts feed back to validate Tier 1 principles
- Strategy adapts as gaps are discovered in implementation
- Policies evolve to match emerging constraints
- Everything stays coherent and synchronized

---

## Knowledge Document Structure

All knowledge in this system is stored as structured JSON documents with auto-generated markdown representations:

```
/workspace/
├── knowledge_config.yaml              # Configuration
├── state_machine/models/              # Custom model classes
│   ├── __init__.py
│   ├── domain_knowledge.py            # DomainKnowledge model
│   └── architecture_decision.py       # ArchitectureDecision model
└── state_machine/knowledge/           # Knowledge documents
    ├── domain-tag-system.k.json
    ├── domain-tag-system.k.md         # Auto-generated
    ├── domain-auth-flow.k.json
    ├── domain-auth-flow.k.md          # Auto-generated
    ├── adr-001-tag-hierarchy.k.json
    └── adr-001-tag-hierarchy.k.md     # Auto-generated
```

### Document Types

**DomainKnowledge** — Describes domain concepts, patterns, and terminology:
- Core concepts and definitions
- Patterns used in the project
- Terminology and naming conventions
- Cross-references to architecture decisions

**ArchitectureDecision** — Records design decisions with context and rationale:
- Decision statement (what was decided)
- Context (why it was needed)
- Alternatives considered
- Consequences and tradeoffs
- Related decisions

### File Organization

- `.k.json` files are the **authoritative source** (structured, machine-readable)
- `.k.md` files are **auto-generated** from `.k.json` (read-only, regenerated on every patch)
- All documents live in `state_machine/knowledge/` for discoverability
- No other markdown files permitted in this directory (maintains purity)

---

## Creating and Editing Knowledge Documents

Knowledge documents are created and modified via JSON Patch operations:

```bash
# 1. Create base document
/plugin/bin/create-knowledge-document Doc state_machine/knowledge/domain-tag-system.k.json

# 2. Patch with content (auto-generates .k.md)
/plugin/bin/patch-knowledge-document state_machine/knowledge/domain-tag-system.k.json '[
  {"op": "replace", "path": "/type", "value": "DomainKnowledge"},
  {"op": "add", "path": "/id", "value": "domain-tag-system"},
  {"op": "add", "path": "/title", "value": "Tag System Domain"}
]'
```

### JSON Patch Operations

All modifications use RFC 6902 JSON Patch:

```bash
# Add a concept
/plugin/bin/patch-knowledge-document state_machine/knowledge/domain.k.json '[
  {
    "op": "add",
    "path": "/concepts/new_concept",
    "value": "definition here"
  }
]'

# Update a pattern
/plugin/bin/patch-knowledge-document state_machine/knowledge/domain.k.json '[
  {
    "op": "replace",
    "path": "/patterns/existing_pattern",
    "value": "updated description"
  }
]'

# Add alternatives to decision
/plugin/bin/patch-knowledge-document state_machine/knowledge/adr-001.k.json '[
  {
    "op": "add",
    "path": "/alternatives/-",
    "value": "Consider this alternative"
  }
]'

# Change ADR status
/plugin/bin/patch-knowledge-document state_machine/knowledge/adr-001.k.json '[
  {
    "op": "replace",
    "path": "/status",
    "value": "deprecated"
  }
]'
```

The markdown representation regenerates automatically on every patch operation.

---

## Best Practices

1. **Keep focused** — One document per concept/decision, not monolithic knowledge bases
2. **Use meaningful IDs** — Reflect content in identifiers (e.g., "ADR-001-tag-hierarchy", "domain-auth-flow")
3. **Link documents** — Use `related_decisions`, tags, and constraint descriptions to cross-reference
4. **Update regularly** — Sync knowledge documents when code changes significantly
5. **Render before committing** — Always run patch commands to regenerate `.k.md` files
6. **Version control** — Commit both `.k.json` and `.k.md` files for audit trail

---

## Single Source of Truth

**Knowledge has one authoritative source: `.k.json` files.**

- All knowledge is structured, auditable JSON
- Changes happen through JSON Patch operations
- Markdown (`.k.md`) is auto-generated and read-only
- The principle: modify the JSON source, never the markdown representation

**Why:** Ensures auditability (all changes via `patch-knowledge-document`), consistency (markdown always matches JSON), and safety (can regenerate at any time).

---

## Capability Gap Documentation

System tracks capability gaps explicitly as `CapabilityGap` documents in `gap-*.k.json` files:

### Gap Fields
- **type:** "CapabilityGap"
- **dimension:** Which of 7 dimensions has the gap
- **capability:** Specific capability name (e.g., "visual_snapshot_regression_testing")
- **status:** "temporary" (will be fixed) or "permanent" (accepted workaround)
- **description:** What is missing and why it matters
- **why_temporary:** Timeline and blockers for fixing (e.g., "Waiting for Playwright setup")
- **impact:** Consequences of this gap (e.g., "Visual regressions may slip through")
- **remediation_plan:** Multi-step plan to close the gap
  - step_1, step_2, step_3... (ordered remediation steps)
  - Estimated effort (e.g., "3-5 days")
  - Deadline (e.g., "Q2 2026")
  - Dependencies on other tasks
- **workaround:** How the system currently handles this gap

### Gap Status Rules
- **Every gap is tracked** — No silent workarounds
- **Temporary gaps have remediation plans** — Not indefinite
- **Gaps block convergence** — Cannot reach READY state with unplanned gaps
- **Remediation plans are binding** — Deadlines are enforced

---

## Methodology Documents

System documents how to achieve convergence via **Methodology** documents:

### The 3-Phase Convergence Methodology

**PHASE 1: ASSESS CURRENT STATE**
- Run dimension audit across all 7 dimensions
- Identify which are READY vs PARTIAL
- Catalog all capability gaps with workarounds
- Document remediation requirements for each partial dimension
- Record current coverage %, missing tools, incomplete test scenarios

**PHASE 2: PLAN REQUIRED CHANGES**
- For each PARTIAL dimension, determine:
  - What must be implemented to reach READY
  - What constraints need to be added/updated
  - What tests must be written
  - What knowledge documents require updates
  - Effort estimate and timeline
- Prioritize changes by criticality and effort
- Identify dependencies between convergence tasks

**PHASE 3: EXECUTE & VERIFY ATOMIC STATE**
- Execute required changes in priority order
- For each change:
  - Capture baseline snapshot (before)
  - Apply code/constraint/test changes
  - Capture post-change snapshot (after)
  - Compare snapshots; verify impact is expected
  - Update corresponding knowledge documents
- Once all dimensions reach READY: **Atomic state achieved**

### Key Principle: Atomicity
- **All 7 dimensions must reach READY simultaneously**
- No partial states allowed
- Non-atomic states hide failures and create technical debt

---

## Dimension Capability Tracking

Each dimension has explicit capability status:

### Dimension Status States
- **READY:** All required capabilities present, constraints passing
- **PARTIAL:** Some capabilities present, gaps with workarounds
- **BLOCKED:** Cannot progress without external dependency

### Capability Status Example
```
✅ Dimension 1 (Structural) - READY
✅ Dimension 2 (Format/Syntax) - READY  
✅ Dimension 3 (Behavioral) - READY
⚠️  Dimension 4 (UX/Design) - PARTIAL (visual snapshot gap)
⚠️  Dimension 5 (Integration) - PARTIAL (API contract gap)
⚠️  Dimension 6 (Maintenance) - PARTIAL (coverage <80%)
⚠️  Dimension 7 (Mocking) - PARTIAL (isolation gap)
```

### Each Dimension Document Contains
- **id:** "dimension-capability-status"
- **label:** "Dimension Capability Status Dashboard"
- **current_status:** Overview of all 7 dimensions
- **capability_gaps:** List of all gaps with remediation plans
- **remediation_timeline:** When each gap will be closed
- **convergence_deadline:** Target date for atomic state
- **progress_tracking:** What's been done, what remains

---

## See Also

- **knowledge-workflow:** The 5-phase cycle that maintains convergence
- **constraint-design:** How to write constraints verified by convergence checks
- **y2:features_and_constraints:** How to spec features that satisfy convergence criteria
