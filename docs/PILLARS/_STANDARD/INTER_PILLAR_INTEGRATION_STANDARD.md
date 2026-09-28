# Standard — Inter-Pillar Integration Ledger (`INTER_PILLAR_INTEGRATION.md`)

**Applies to:** every pillar folder in `docs/PILLARS/<Pillar_Name>/`.  
**Governed by:** `docs/000_AI_SUPREME_PROTOCOL.md` and `docs/PILLARS/_STANDARD/CHAPTER_STANDARD.md`.  
**Purpose:** Formally track all communication surfaces, data flows, and upstream/downstream change obligations between pillars so that an improvement or adjustment in one pillar never leaves its partner pillars broken or uninformed.

---

## 1. The Cross-Pillar Coordination Problem

In a modular architecture, pillars do not exist in isolation:
- **Pillar 1 (Sources)** feeds catalog items to **Pillar 3 (Pipelines)**.
- **Pillar 3 (Pipelines)** instructs **Pillar 4 (Jobs)** to run downloads in **Pillar 5 (Media)** and uploads in **Pillar 6 (Delivery)**.
- **Pillar 2 (Destinations)** provides credentials and quotas to **Pillar 6 (Delivery)**.

When an engineer or AI enhances a pillar (e.g., adding a new field to a source DTO, changing an error code, or modifying a state machine transition):
1. **The Blast Radius**: Neighboring pillars that consume or trigger those workflows may break or become outdated.
2. **Context Loss**: When an agent switches to work on the sibling pillar weeks later, it lacks the explicit memo of what adjustments are pending.

To solve this, **every pillar maintains an active `INTER_PILLAR_INTEGRATION.md` file**.

---

## 2. The Bi-Directional Integration Rule

Whenever a change in **Pillar A** affects **Pillar B**:
1. **Pillar A** records an outbound downstream obligation in its own `INTER_PILLAR_INTEGRATION.md`:
   - Target pillar, specific file/section, required adjustment, and sets status to `PENDING_ADJUSTMENT`.
2. **Pillar B**'s `INTER_PILLAR_INTEGRATION.md` is updated in the **same pull request / commit** under its Inbound Obligations with status `PENDING_ADJUSTMENT`.
3. When work shifts to Pillar B, the agent/engineer is **strictly required** to inspect `INTER_PILLAR_INTEGRATION.md` first, resolve all `PENDING_ADJUSTMENT` items, and flip them to `ALIGNED`.

---

## 3. Fixed Structure of `INTER_PILLAR_INTEGRATION.md`

Every `INTER_PILLAR_INTEGRATION.md` must follow this structure:

```markdown
# Inter-Pillar Integration Ledger: Pillar <N> (<Pillar Name>)

**Pillar:** <Number> — <Name>  
**Status:** active  
**Last Synchronized:** <Date>  

---

## 1. Direct Neighbor Topology

| Sibling Pillar | Interaction Nature | Inbound (What We Receive) | Outbound (What We Provide) |
|---|---|---|---|
| Pillar 0 (Contracts) | Port implementations & DTOs | Interface protocols | Concrete adapter implementations |
| Pillar <X> | ... | ... | ... |

---

## 2. Inbound Integrations (What Sibling Pillars Expect From Us)

For each sibling pillar that calls or relies on this pillar:
### Sibling Pillar <X>: <Name>
- **Contract Boundary**: [Which port or API is used]
- **Data Exchanged**: [DTOs or IDs passed]
- **Guarantees We Provide**: [Invariants or SLAs we must honor for Sibling X]
- **Pending Adjustments From Upstream Changes**:
  - `[ID]` `[Date]` `[STATUS: PENDING_ADJUSTMENT | ALIGNED]` <Description of required adjustment>

---

## 3. Outbound Integrations (What We Expect From Sibling Pillars)

For each sibling pillar that this pillar calls or relies on:
### Sibling Pillar <Y>: <Name>
- **Contract Boundary**: [Which port or API we call]
- **Data Exchanged**: [DTOs or IDs received]
- **Guarantees We Expect**: [Invariants or error handling expected from Sibling Y]
- **Pending Adjustments Required in Sibling Y (Downstream Blast Radius)**:
  - `[ID]` `[Date]` `[STATUS: PENDING_ADJUSTMENT | ALIGNED]` <Description of work Sibling Y must do>

---

## 4. Cross-Pillar Change Log & Blast Radius Audit Trail

A chronological log of all cross-pillar changes:
- `YYYY-MM-DD`: [Pillar A ➔ Pillar B] <Description of contract adjustment>. Status: <ALIGNED | PENDING_ADJUSTMENT>.
```

---

## 4. Agent Operational Directives

- **Before Starting Work on a Pillar**:
  Read `000_PILLAR_INSTRUCTIONS.md` AND `INTER_PILLAR_INTEGRATION.md`. If any item is marked `PENDING_ADJUSTMENT`, review its scope before implementing new features.
- **When Altering an Interface or Data Schema**:
  You are strictly forbidden from committing the change without documenting the downstream blast radius in `INTER_PILLAR_INTEGRATION.md` of both the modified pillar and the affected sibling pillars.
