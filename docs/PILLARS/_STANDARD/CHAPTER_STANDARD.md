# Chapter Standard — the fixed skeleton of every pillar chapter

**Applies to:** every chapter file in `docs/PILLARS/**`.
**Governed by:** `docs/000_AI_SUPREME_PROTOCOL.md`.
**Why it exists:** the legacy's documents contradicted each other because each
was written in whatever shape its author felt like that day (defects D-01, D-27).
A fixed skeleton makes a missing section *visible* instead of invisible.

---

## 1. Rules of the standard

1. **The twelve chapters are the pillar's structure.** A pillar holds twelve files,
   always. A chapter that does not apply exists anyway, and its *body* is the single
   line `Not applicable — <reason>`. Never delete a chapter file, never renumber one.
   *(Each file also has a fixed internal frame — see §3.)*
2. **One concern per file.** A chapter that starts needing two concerns is split
   into two files before it is written (the same rule as INV-11, applied to docs).
3. **Specify, do not narrate.** "The grid shows columns X, Y, Z and the filter bar
   has A, B" — not "we thought about the grid".
4. **Name the owner.** Every *rule* names the module that owns it. If two modules
   appear to own the same rule, the boundary is wrong — raise it as an open
   question, do not paper over it.
5. **Every state, field and screen has one meaning.** One word, one meaning, per
   `docs/00` §2. A word that is not in the glossary is added to the glossary first.
6. **Nothing is invented here.** If a fact is needed and no document holds it, it
   becomes an entry in `10_OPEN_QUESTIONS.md` — not an assumption.
7. **Trace, do not copy.** Cite `F-##` / `D-##` from `docs/01` and the invariants
   from `docs/00`. Never paste legacy code into a chapter.
8. **Keep it reviewable.** A chapter should be readable in one sitting. If it
   cannot be, it is two chapters.
9. **Status line at the top of every chapter**, one of the six statuses in
   `docs/PILLARS/README.md` §5.

---

## 2. The twelve sections

### 00_PILLAR_OVERVIEW.md
- Mission in one sentence, and what the pillar is *for*.
- **Owns** — the things only this pillar may decide.
- **Does not own** — the tempting-but-wrong responsibilities, named explicitly,
  with the pillar that does own them.
- Dependencies (which pillars it reads from, which it writes to).
- The glossary slice this pillar relies on.
- The invariants (`INV-##`) this pillar is responsible for keeping.

### 01_FRONTEND_SPEC.md
- Every screen, tab and panel the pillar exposes, as a list.
- For each screen: purpose, entry points, layout blocks (header / filters / grid
  / detail / actions), and the exact columns or fields shown.
- Every control: label, behaviour, what disables it, and what it says on failure.
- Empty, loading, paused and error states — written out.
- The confirmation and undo behaviour of anything destructive.
- Where a long-running action reports progress.

### 02_WORKSPACE_AND_TENANCY_SLOT.md
- Where the workspace context appears in this pillar's screens.
- Which columns carry `workspace_id`, and which unique constraints are scoped by
  it.
- The single access helper used, and the rule that no query bypasses it.
- What is deliberately *not* built in v1 (per Constitution Article 3).

### 03_INTERFACE_CONTRACT.md
- The published surface: `<module>.api`, function by function.
- For each function: purpose, signature, inputs, outputs, raised errors, and side
  effects (which rows it writes).
- Which sibling pillars may call it, and which may not.
- The DTOs that cross the boundary, field by field, with types and nullability.
- A version note: which changes here are breaking.

### 04_LOGIC_AND_RULES.md
- The flow, step by step, including every decision point.
- State machines: states, allowed transitions, and what triggers each.
- Guards and invariants enforced, and *where* they are enforced.
- Limits: rate limits, batch sizes, timeouts, retry counts, backoff shape.
- Edge cases that have bitten us or the legacy, each with expected behaviour.
- Determinism: what the outcome depends on, and what it must never depend on.

### 05_DATA_MODEL.md
- The tables this pillar owns: purpose and lifecycle.
- Columns: name, type, nullability, default, and a one-line meaning.
- Constraints and indexes, and the query each index exists to serve.
- Which columns are `CHECK` constrained, and the exact value list.
- What is append-only, what is current-state, and what is soft-deleted.
- The migration note if this chapter changes an existing column.

### 06_FAILURES_AND_ERRORS.md
- Every failure mode, classified **transient** / **permanent** / **skip**.
- What is retried, how many times, with what backoff.
- What the operator sees for each — exact wording where a message is specified.
- What is *never* silently swallowed, and which invariant protects it.
- Restart and recovery behaviour for anything left mid-flight.

### 07_OBSERVABILITY_AND_AUDIT.md
- The events written, and their fields.
- What the home page or health surface shows for this pillar.
- Which actions support a dry run, and what the dry-run output looks like.
- What is auditable after the fact, from the database alone.

### 08_TESTS_AND_DOD.md
- The assertions that prove the chapter was implemented, phrased as behaviour.
- Which are unit, which integration, which boundary enforcement.
- The definition of done for this pillar, as a checklist.
- What must hold after a fresh install with no configuration.

### 09_LEGACY_TRACEABILITY.md
- Every `F-##` in this pillar's scope with its disposition (v1 / v2 / rejected)
  and one line of reasoning.
- Every `D-##` this pillar exists to prevent, and the mechanism that prevents it.
- Anything found in the legacy code that `docs/01` does not cover — recorded here
  as a **gap in the inventory**, per `LEGACY.md` §4.

### 10_OPEN_QUESTIONS.md
- Each question, the options, the leaning, and what it blocks.
- Nothing here may be silently resolved in code; resolving it means editing the
  chapter that owns it.

### 11_DECISIONS.md
- Pillar-local decisions, numbered `P<#>-D<#>`, each with date, rationale, and the
  document(s) it supersedes.
- A decision changed here but not in the document that cites it is a
  documentation defect — fix both in the same change (`docs/00` §6 rule).

---

## 3. Chapter status line (top of every chapter file)

```markdown
**Pillar:** <number + name> · **Chapter:** <title> · **Status:** scaffolded
**Depends on:** <files this chapter assumes the reader knows>
**Invariants touched:** <INV-## list, or "none">
```

---

## 3. The fixed internal frame of a chapter file

Every chapter file carries the same four parts, in this order:

1. **Status line** — pillar, chapter, status, what it depends on, invariants touched.
2. **Purpose** — two or three sentences: what this chapter decides, and what it
   explicitly does not.
3. **Body** — free structure, but every claim names its owning module and cites a
   source document (`docs/03` §, `docs/05` §, `F-##`, `D-##`, `INV-##`).
4. **Closing two lines** — `Open questions: none` or a pointer to
   `10_OPEN_QUESTIONS.md`, and a one-line change log (date + what moved).

Anything longer than the frame's subject gets its own chapter, not another heading.

---

## 4. Definition of done for a chapter

- [ ] The file exists, is named for its slot, and carries the status line.
- [ ] Every screen, field, rule and error named in the chapter has exactly one
      owner module.
- [ ] Every claim about behaviour is traceable to a document, a decision, an
      `F-##` / `D-##` / `INV-##`, or an entry in this pillar's `11_DECISIONS.md`.
- [ ] No legacy code copied; legacy behaviour cited only.
- [ ] Every open question listed in `10_OPEN_QUESTIONS.md`, not implied in prose.
- [ ] Any new word is in `docs/00` §2.
- [ ] Any interface change is recorded in `docs/04` §6 in the same change.
- [ ] The pillar `README.md` status and the Book index are updated.
- [ ] Nothing in the chapter depends on code that does not exist yet.

