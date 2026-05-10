---
name: knowledge-workflow
description: Enforce strict knowledge document workflow - JSON Patch only, no direct markdown creation. ALL code changes MUST follow 3-dimensional verification approach.
---

# Knowledge Document Workflow & Change Management

## 🔴 MANDATORY: Convergence Workflow for All Changes

**Every non-trivial code change follows the Convergence Pattern:**

Convergence = `identify_current_state → determine_required_changes → execute_changes → verify_atomic_state_reached`

### The 3-Dimensional Framework

The system tracks state across three dimensions:

| Dimension | What It Measures | Sources |
|-----------|------------------|---------|
| **Content** | Knowledge document structure, counts, tags, schema | state_machine/knowledge/*.k.json |
| **UI State** | Session state, navigation, selected items, filters | app/ code, Streamlit state |
| **Processing** | Automated workflows, tagging, flagging, cache invalidation | scripts/, processing logic |

### The 5-Phase Convergence Cycle

**Every non-trivial code change MUST follow this workflow:**

1. **Understand impact** — Identify which dimensions are affected (Content, UI State, Processing)
2. **Capture baseline** — Use `SnapshotComparator` to capture pre-change state across all dimensions
3. **Apply changes** — Modify code and knowledge documents
4. **Verify outcomes** — Capture post-change state and compare dimensions
5. **Update knowledge** — Document WHAT changed, WHY it changed, HOW it affects the system

### Key Principle: 7-Dimensional Atomicity

All code changes must verify across **all 7 validation dimensions simultaneously**:

| Dimension | What Changes | Must Verify |
|-----------|--------------|-------------|
| **Structural** | Code organization, modules, layers | No circular deps, clear boundaries |
| **Format/Syntax** | Data formats, serialization, contracts | 100% style compliance, schema valid |
| **Behavioral** | Logic, state machines, algorithms | All state machines valid, errors handled |
| **UX/Design** | User experience, visual interactions | Accessible, responsive, intuitive |
| **Integration** | APIs, dependencies, external systems | All APIs match contracts, messages reliable |
| **Maintenance** | Documentation, testability, coverage | Documented, testable, coverage ≥80% |
| **Mocking** | Test infrastructure, fixtures, isolation | Comprehensive test coverage with proper isolation |

**If any dimension is not PASS or LOCKED, the entire system is not ready.** This is **not optional**.

The 3-dimensional framework (Content, UI State, Processing) tracks *what changes*. But verification must cover all 7 dimensions to ensure the system remains atomic.

---

## Knowledge Format

**The primary knowledge format is `.k.json` — structured, machine-readable, auditable JSON.**

- Knowledge is authored and modified only via `.k.json` files
- `.k.md` files are auto-generated representations (read-only)
- Changes propagate through JSON Patch operations
- Markdown is always regenerated from the source

---

## Correct Workflow

### Creating Knowledge Documents

```bash
# 1. Create base document (generates stub)
/plugin/bin/create-knowledge-document Doc state_machine/knowledge/domain-example.k.json

# 2. Patch with content (auto-generates .k.md)
/plugin/bin/patch-knowledge-document state_machine/knowledge/domain-example.k.json '[
  {"op": "replace", "path": "/type", "value": "DomainKnowledge"}
]'
```

**Result:**
- `domain-example.k.json` — Source (protected, read-only)
- `domain-example.k.md` — Auto-generated (protected, read-only)

### Updating Knowledge Documents

```bash
# Use JSON Patch ONLY
/plugin/bin/patch-knowledge-document state_machine/knowledge/domain-example.k.json '[
  {"op": "add", "path": "/concepts/new_concept", "value": "definition"}
]'
```

The markdown file regenerates automatically.

---

## The Re-balancing Workflow

**Every code change is a re-balancing operation** — you make a change in one area (Content, UI State, or Processing), and you must verify that all 7 validation dimensions remain in PASS or LOCKED state.

If a change causes any dimension to fall into FAIL:
1. **Identify** which dimension(s) failed
2. **Understand** why (missing test? broken API contract? poor UX?)
3. **Fix** the underlying issue (don't skip verification)
4. **Re-verify** all 7 dimensions again
5. **Repeat** until all dimensions are PASS or LOCKED

This is not optional cleanup — it's the core operation. The system stays coherent through constant re-balancing.

---

## MANDATORY: 7-Dimension Approval & Convergence Workflow

**After every code change, follow this workflow using the WorkflowOrchestrator (root component):**

### Using WorkflowOrchestrator (Primary Entry Point)

The `WorkflowOrchestrator` is the main interface for integrating state_machine into project workflows.
It coordinates the entire 7-dimensional approval and convergence cycle in one place.

```python
from state_machine import WorkflowOrchestrator, ApprovalDecision

# Initialize orchestrator
orchestrator = WorkflowOrchestrator()

# Step 1: Begin work (captures baseline automatically)
work = orchestrator.begin_work("Fix critical bug #123")

# Step 2: Agent makes changes (external process)
# ... code changes happen ...

# Step 3: Checkpoint after work (identifies dimension changes)
checkpoint_report = orchestrator.checkpoint_work()
print(checkpoint_report)

# Step 4: User submits approval decisions
approvals = {
    "structural": ApprovalDecision.APPROVED,
    "behavioral": ApprovalDecision.APPROVED,
    "format_syntax": ApprovalDecision.REJECTED,
    "ux_design": ApprovalDecision.APPROVED,
    "integration": ApprovalDecision.APPROVED,
    "maintenance": ApprovalDecision.APPROVED,
    "mocking": ApprovalDecision.APPROVED,
}
result = orchestrator.submit_approvals(approvals)

# Step 5: If mixed approval, convergence runs automatically
if result['status'] == 'mixed':
    convergence = orchestrator.run_convergence()
    # Fix code based on convergence report
    # Re-run checkpoint to verify convergence

# Step 6: Finalize and record in history
final = orchestrator.finalize_work()
# All dimensions converged, changes recorded immutably
```

### Step 1: Capture Dimension Changes
```python
from state_machine.dimension_checkpoint import DimensionCheckpoint

# Or use checkpoint directly (lower-level API)
checkpoint = DimensionCheckpoint()
baseline = checkpoint.capture_current_state()  # Before changes
# ... make code changes ...
current = checkpoint.capture_current_state()   # After changes
changes = checkpoint.identify_changes(baseline, current)
```

### Step 2: Report Changes Per Dimension
```
DIMENSION CHANGES REPORT
==================================================

✓ Structural:      CHANGED
  - Circular dependencies resolved
  - Module boundaries clarified

✓ Behavioral:      CHANGED
  - Error handling added
  - State machines validated

⊘ Format/Syntax:   UNCHANGED
⊘ UX/Design:       UNCHANGED
⊘ Integration:     UNCHANGED
⊘ Maintenance:     UNCHANGED
⊘ Mocking:         UNCHANGED
```

### Step 3: Request User Approval Per Dimension
User approves/rejects each changed dimension:
```
Structural:      APPROVE ✓
Behavioral:      APPROVE ✓
(unchanged):     IMPLICIT APPROVE (no change = no action needed)
```

### Step 4: Handle Mixed Approval State
If user approved some dimensions but not others:

**Mark approved dimensions as LOCKED:**
- These improvements cannot be undone
- Code must continue to satisfy these constraints

**Identify why rejected dimensions failed:**
- What code changes caused the rejection?
- What constraints are not satisfied?

**Run convergence handler:**
```python
from state_machine.convergence_handler import ConvergenceHandler

handler = ConvergenceHandler()
handler.fix_to_converged_state(
    approved=changes['approved'],
    rejected=changes['rejected'],
    baseline=baseline
)
# Makes new code changes to satisfy rejected dimension constraints
# Iterates until all 7 dimensions converge
```

### Step 5: Verify Convergence Achieved
When all 7 dimensions are in the same state (all PASS or all LOCKED):
```
✓ CONVERGENCE ACHIEVED
  Structural:     LOCKED
  Format/Syntax:  LOCKED
  Behavioral:     LOCKED
  UX/Design:      LOCKED
  Integration:    LOCKED
  Maintenance:    LOCKED
  Mocking:        LOCKED
```

---

## System State Machine: 3 Dimensions Framework

The system tracks *what changes* across a **3-dimensional state machine** to predict and verify change impacts:

### What Changes (3 Dimensions)

When you modify code, changes propagate across three dimensions:

1. **Content Dimension** — Knowledge document structure
   - Entity counts, metadata, schema
   - Concepts, patterns, constraints captured

2. **UI State Dimension** — Application state and navigation
   - Session state, selected items, filters
   - URL parameters, navigation position

3. **Processing Dimension** — Automated workflows
   - Tagging, flagging, processing rules
   - Cache invalidation, file watchers

### How Verification Works (7 Dimensions)

For each change across these 3 dimensions, you must verify **all 7 validation dimensions**:
- Are structural changes valid? (D1: Structural)
- Does code style comply? (D2: Format/Syntax)
- Are behaviors correct? (D3: Behavioral)
- Is UX acceptable? (D4: UX/Design)
- Do APIs match contracts? (D5: Integration)
- Is documentation complete? (D6: Maintenance)
- Are tests sufficient? (D7: Mocking)

### Change Impact Estimation - The Mandatory Workflow

When making ANY code changes, follow this REQUIRED workflow:

**Phase 1: Pre-Change Analysis**
- [ ] Read relevant knowledge documents
- [ ] Identify all affected dimensions (Content, UI State, Processing)
- [ ] Plan expected outcomes for each dimension

**Phase 2: Baseline Capture**
- [ ] Capture baseline state before changes

**Phase 3: Code Changes**
- [ ] Apply all code modifications
- [ ] Test locally (if applicable)
- [ ] Ensure changes align with knowledge document specifications

**Phase 4: Outcome Verification**
- [ ] Capture post-change state
- [ ] Compare snapshots
- [ ] Analyze impact assessment
- [ ] Verify all 3 dimensions remain consistent and functional

**Phase 5: Knowledge Update (REQUIRED)**
- [ ] Identify which knowledge documents to update
- [ ] Update knowledge using `/plugin/bin/patch-knowledge-document`
- [ ] Document WHAT changed, WHY it changed, and HOW it affects the system

**Without completing all 5 phases, changes are incomplete.**

---

## ✅ MANDATORY: Agents MUST Update Project Knowledge

**For ANY code change, agents MUST:**

- ✅ Capture baseline snapshot (before changes)
- ✅ Identify which dimensions are affected
- ✅ Make code changes
- ✅ Capture post-change snapshot
- ✅ Compare snapshots and analyze impact
- ✅ Update corresponding knowledge documents
- ✅ Verify all 3 dimensions remain consistent

**This is not optional.** Keeping project knowledge synchronized with code state is REQUIRED because:

1. **State Capture** — Knowledge documents ARE the authoritative system state
2. **Predictable Outcomes** — Every code change must have documented consequences in knowledge
3. **Verification** — ALL outcomes must be validated against captured state in both knowledge and code
4. **State Machine Integrity** — System transitions must form a coherent multidimensional structure
5. **Auditability** — Full traceability of every decision and its rationale is mandatory

---

## ✅ ENCOURAGED: Agents Creating and Refining Project Knowledge

**Agents ARE encouraged and allowed to:**

- ✅ Create new knowledge documents using `/plugin/bin/create-knowledge-document`
- ✅ Update existing knowledge via `/plugin/bin/patch-knowledge-document`
- ✅ Add concepts, patterns, constraints, ADRs as needed
- ✅ Capture discovered patterns, decisions, trade-offs
- ✅ Refine knowledge as code implementation progresses
- ✅ Synchronize knowledge with code state changes

**This is not optional.** Proactive knowledge updates ensure:

- Complete documentation of system state and design decisions
- Clear traceability between code and architectural intent
- Rapid onboarding for future work and debugging
- Prevention of knowledge debt that decays with time

When you modify code, update the corresponding knowledge document:

```bash
# Example: Discovered a new pattern
/plugin/bin/patch-knowledge-document state_machine/knowledge/domain-tag-system.k.json '[
  {"op": "add", "path": "/patterns/new_pattern", "value": "Pattern discovered during implementation"}
]'

# Example: Architecture decision made
/plugin/bin/create-knowledge-document Doc state_machine/knowledge/adr-004-new-decision.k.json
/plugin/bin/patch-knowledge-document state_machine/knowledge/adr-004-new-decision.k.json '[
  {"op": "replace", "path": "/type", "value": "ArchitectureDecision"},
  {"op": "add", "path": "/id", "value": "ADR-004"}
]'
```

This keeps the system state synchronized and verifiable.

---

## Enforcement

Violations of markdown creation rule are enforced via:
- Edit/Write hook rejection
- Explicit error messages
- Prevention of markdown file creation without explicit user request

**If you need to document something:**
- Use the knowledge tool to create/update `.k.json` documents (markdown auto-generates)
- Ask user explicitly if markdown documentation is needed outside the knowledge system
- Never create markdown directly in `state_machine/knowledge/` or project root

---

---

**Commitment:** Keep project knowledge synchronized with code state. Every code change should have a corresponding knowledge update to maintain system integrity and auditability.

---

## ⛔ Consequences of Not Following Workflow

**If changes are made without following the 5-phase workflow:**

- ❌ System state becomes unknown (no baseline/current comparison)
- ❌ Impact on other dimensions is unverified (could break things silently)
- ❌ Knowledge documents diverge from code (lose auditability)
- ❌ Future changes cannot reliably estimate impact (state machine breaks)
- ❌ Code reviews cannot assess correctness (no verified outcomes)
- ❌ Bugs compound because changes aren't traceable to root causes

**The system is designed to prevent this:**

- Agents are EXPECTED to use the workflow
- Knowledge documents guide correct implementation
- Snapshots prove changes are safe
- Skills document the mandatory approach

---

## The State Machine Nature of Changes

Code changes are **state transitions** in a multidimensional system:

- **Content dimension** — Knowledge structures change
- **UI State dimension** — Session state and navigation change
- **Processing dimension** — Workflows and cache states change

**For system integrity:**
- Outcomes must be **predictable and measurable** across all 3 dimensions
- All changes must be **verifiable** against captured baseline state
- Knowledge documents are the **authoritative specification** of what changed and why

**Without the 5-phase workflow, the system state machine becomes incoherent** — you cannot reliably predict or verify outcomes, and the codebase gradually accumulates hidden dependencies and untracked side effects.
