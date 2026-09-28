# 06 — Failures, Errors, and Recovery: Pipelines & Routing

**Pillar:** 3 · Pipelines & Routing · **Chapter:** Failures and Errors · **Status:** `drafting`  
**Governed by:** `docs/PILLARS/_STANDARD/CHAPTER_STANDARD.md` §2 · `docs/000_AI_DEEP_SPEC_STANDARD.md` §7  
**Depends on:** `docs/PILLARS/03_PIPELINES_AND_ROUTING/00_PILLAR_OVERVIEW.md`  
**Invariants enforced:** INV-5, INV-6, INV-9  

---

## 1. Domain Error Taxonomy

```
PipelinesError (base)
├── PipelineNotFoundError
├── InvalidPipelineConfigurationError (e.g., zero enabled destinations)
├── ProfileValidationError (min_duration > max_duration)
├── BrokenChannelBindingError (bound destination channel was deleted)
└── SourceExhaustedWarning (all catalog items backfilled)
```

---

## 2. Exhaustive Error Catalog

| Error Code | Trigger Condition | Classification | System Reaction |
|---|---|---|---|
| `PIPE_ERR_NO_DESTINATIONS` | Pipeline is set to `ACTIVE` but has 0 enabled destinations | **Permanent** | Transition status to `DRAFT`. Alert operator in UI. |
| `PIPE_ERR_BROKEN_BINDING` | Linked source or destination UUID no longer exists in DB | **Permanent** | Mark binding as `INVALID`. Halt candidate generation for that branch. |
| `PIPE_ERR_CONFLICTING_PROFILE`| Duration bounds inverted (`min > max`) | **Configuration** | Reject save in API with HTTP 422. |
| `PIPE_WARN_SOURCE_EXHAUSTED` | Backfill cursor reaches newest video in source catalog | **Informational** | Emit `pipeline.source.backfill_complete`. Cursor remains at newest timestamp. |

---

## 3. Explainability Recovery Loop

Unlike execution errors, candidate evaluation failures do not throw exceptions during batch
generation. Instead, every failed candidate is tagged with an explicit `SkipReason`
(`SHORTS_FILTERED`, `ALREADY_DELIVERED`, etc.) and returned in the candidate explainability
model. This guarantees that background worker polling never crashes due to an unprocessable video.
