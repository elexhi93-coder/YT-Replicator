# Standard — Pillar Local Instruction File (`000_PILLAR_INSTRUCTIONS.md`)

**Applies to:** every pillar folder in `docs/PILLARS/<Pillar_Name>/`.  
**Governed by:** `docs/000_AI_SUPREME_PROTOCOL.md` and `docs/000_AI_DEEP_SPEC_STANDARD.md`.  
**Purpose:** Provide an unmissable, localized orientation brief at the top of each pillar directory to lock the working agent's focus on that specific pillar's domain, boundary invariants, active leaf chapter, and domain field universe.

---

## 1. Why Local Pillar Instructions Exist

When working inside a specific pillar branch, global repository instructions (`docs/000_*`) provide the law and long-term state, but an agent working inside a pillar needs **immediate, local boundary enforcement**:
1. **Domain Immersion**: Instant context on what this pillar owns and what it does NOT own.
2. **Boundary Defense**: Explicit warnings against crossing into neighboring pillars (e.g., Pillar 1 must NEVER download media; Pillar 5 must NEVER write deliveries).
3. **Local Chapter Frontier**: Concrete tracking of which of the 12 chapters are drafted, in review, or locked.
4. **Leaf-Level Domain Registries**: Direct tracking of platform fields (e.g. YouTube attributes) and UX components specific to this pillar.

---

## 2. Fixed Structure of `000_PILLAR_INSTRUCTIONS.md`

Every `000_PILLAR_INSTRUCTIONS.md` must follow this exact section structure:

```markdown
# 000 — Pillar <N> Instructions & Working Frontier (<Pillar Name>)

**Pillar:** <Number> — <Name>  
**Status:** scaffolded | drafting | in_review | locked  
**Authority:** Local domain directive for Pillar <N>. Governed by root docs/000_*.  

---

## 1. Local Mission & Domain Boundaries

### Core Mission
[1–2 sentences defining the sole purpose of this pillar.]

### What This Pillar Owns
- [Bullet points of exclusive responsibilities]

### STRICT BOUNDARY DEFENSE (What This Pillar NEVER Does)
- [Explicit negative boundaries: what neighboring pillars own that must never be performed here]

---

## 2. Invariants & Non-Negotiable Guards
- [List of INV-## invariants that this pillar is directly responsible for defending]
- [Local failure rules and partial-failure policies (e.g. F-48)]

---

## 3. Active Working Frontier & Chapter Status

| Chapter | Title | Status | Notes |
|---|---|---|---|
| `00` | `00_PILLAR_OVERVIEW.md` | ... | ... |
| `01` | `01_FRONTEND_SPEC.md` | ... | ... |
| ... | ... | ... | ... |
| `11` | `11_DECISIONS.md` | ... | ... |

**Current Active Chapter:** `##_<CHAPTER_NAME>.md`

---

## 4. Leaf-Level Domain Universe (Platform Field Registry & Matrix)
[Tracking of the external platform schema coverage, public vs private attributes, extraction tiers, and lineage.]

---

## 5. Local Open Questions & Blockers
[Questions specific to this pillar that must be resolved before locking.]
```

---

## 3. Authoring & Maintenance Rule

- The `000_PILLAR_INSTRUCTIONS.md` file resides at the root of each pillar directory:
  `docs/PILLARS/<Pillar_Folder>/000_PILLAR_INSTRUCTIONS.md`.
- It sorts first alphabetically due to the `000_` prefix.
- At the start of any session targeting a pillar, the agent **MUST** read `000_PILLAR_INSTRUCTIONS.md` immediately after the root directives.
