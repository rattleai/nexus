# PR #48 Product Configurator: Gold Standard Evaluation & Gap Analysis

## Context

PR #48 introduces a product configurator, configurable BOM, and pricing engine into nxs_cp. The goal is to evaluate this implementation against gold standards from best-in-class CPQ systems (Salesforce CPQ, Oracle CPQ, Tacton, PROS, Epicor), PDM/PLM platforms (Siemens Teamcenter, PTC Windchill, Dassault ENOVIA, Arena PLM), and ERP configurators (SAP S/4HANA Variant Configuration, Microsoft Dynamics 365, Infor CloudSuite). This analysis identifies gaps and improvement opportunities to make the platform truly best-in-class -- bridging CPQ and PDM worlds.

---

## What PR #48 Delivers (Strengths)

The implementation is substantial and well-architected for a first iteration:

- **19 database tables** with full RLS tenant isolation, proper FKs, indexes
- **AC-3 constraint propagation engine** (687 lines) -- stateless, queue-based, supporting 6 constraint types (REQUIRES, EXCLUDES, SELECTION_CONDITION, DEFAULT_VALUE, FORMULA, TABLE)
- **JSONB AST expressions** for conditions -- safe, indexable, UI-renderable (not string DSL)
- **150% super BOM -> 100% configured BOM** resolution with phantom flattening, effectivity filtering, and hierarchical traversal
- **Integrated pricing engine** with 7 rule types, profitability analysis, and margin tracking
- **69 API endpoints** across 5 routers with auth, rate limiting, scopes, pagination
- **Domain events** (8 types), Celery async tasks, configuration templates, product versioning
- **Session-based configuration** -- multi-step, resumable, auditable

The architecture follows proven patterns from SAP VC (characteristics, dependency nets, super BOM), Tacton (constraint-based rather than enumeration-based), and Salesforce CPQ (session-based, API-first).

---

## Phase 0: COMPLETED (implemented in this session)

The following critical gaps were fixed:

| Gap | Fix | Files Changed |
|-----|-----|---------------|
| CE-1: Formula eval security | Replaced dynamic code execution with `ast.parse()`-based safe evaluator allowing only BinOp/Constant/Name/UnaryOp nodes | `app/configurator/engine.py` |
| CE-2: Conflict explanation | Track `DomainPruneRecord` per constraint firing; build `ConflictExplanation` on contradiction; exposed in API response | `app/configurator/engine.py`, `app/api/schemas_configurator.py`, `app/api/v1/configurator.py` |
| PA-1: Caching | Added `_ProductDataCache` (TTL=600s) to engine; cache invalidation on constraint/characteristic/vtable CRUD | `app/configurator/engine.py`, `app/api/v1/characteristics.py`, `app/api/v1/constraints.py` |
| PA-2: Prometheus metrics | Added 5 metrics: propagation_seconds, propagation_iterations, bom_resolution_seconds, constraint_evaluations_total, contradictions_total | `app/core/metrics.py`, `app/configurator/engine.py`, `app/configurator/bom_resolver.py` |
| PA-6: Audit trail | Added `emit_audit_event()` to all 38 CRUD mutation endpoints across 5 configurator routers | `app/api/v1/{products,characteristics,constraints,boms,configurator}.py` |

Tests added: 17 new unit tests (15 for formula evaluator, 2 for conflict explanation tracing). All 54 tests pass.

---

## Gap Analysis: 38 Findings Across 3 Dimensions

### Dimension 1: Constraint Engine & Configuration Model

| # | Gap | Severity | Status | Description |
|---|-----|----------|--------|-------------|
| CE-1 | Formula evaluation security | **CRITICAL** | **FIXED** | Replaced dynamic code execution with AST-safe evaluator |
| CE-2 | Conflict explanation | **CRITICAL** | **FIXED** | Full prune history + conflict trace now returned in API |
| CE-3 | Numeric constraint handling | **HIGH** | Pending P1.1 | Numeric/text domains use `__any__` marker, skipped entirely during propagation |
| CE-4 | Multi-level configuration | **HIGH** | Pending P2.3 | `BOMItem.sub_product_id` exists but BOM resolver never follows it |
| CE-5 | Constraint validation/analysis | **HIGH** | Pending P1.4 | No cycle detection, dead value detection, or satisfiability checking |
| CE-6 | Cross-characteristic arithmetic | **HIGH** | Pending P3.3 | Cannot express "sum of option weights <= 500kg" -- FORMULA is one-way derivation only |
| CE-7 | Cardinality constraints | **HIGH** | Pending P1.8 | `is_multi_select` is binary; no `min_select`/`max_select` |
| CE-8 | Multi-target then-clauses | **MEDIUM** | Pending P3 | REQUIRES/EXCLUDES target single characteristic only |
| CE-9 | Solver completeness | **MEDIUM** | Pending P3.6 | AC-3 may show false-available values; no backtracking |
| CE-10 | Guided selling / recommendations | **MEDIUM** | Pending P3.4 | No recommendation rules or preference scoring |
| CE-11 | Configuration comparison | **LOW** | Pending | No endpoint to diff two configurations |

### Dimension 2: BOM Management & Pricing

| # | Gap | Severity | Status | Description |
|---|-----|----------|--------|-------------|
| BP-1 | BOM change management | **CRITICAL** | Pending P2.2 | No ECR/ECO process, no approval workflow, no release states |
| BP-2 | Multi-currency | **CRITICAL** | Pending P2.1 | Hardcoded `"EUR"` in resolver, simulation endpoint, model defaults |
| BP-3 | Quantity expressions (dead code) | **HIGH** | Pending P1.2 | `_resolve_quantities()` is a placeholder; quantity_expression never evaluated |
| BP-4 | Alternate/substitute components | **HIGH** | Pending P2.4 | No `BOMItemAlternate` model |
| BP-5 | Effectivity management | **HIGH** | Pending P2.5 | Date-only effectivity; no serial/lot/unit/order effectivity |
| BP-6 | Tiered pricing (stub) | **HIGH** | Pending P1.3 | TIERED rule type exists but falls through to generic handler |
| BP-7 | Contract/agreement pricing | **HIGH** | Pending P2.6 | All pricing is product-level; no customer/contract dimension |
| BP-8 | Cost rollup sophistication | **HIGH** | Pending P3.2 | Simple `unit_cost x quantity` sum; no labor/overhead/scrap |
| BP-9 | Multiple BOM views | **HIGH** | Pending P3.1 | `bom_type` is free-text; resolver hardcoded to `is_primary` |
| BP-10 | BOM lifecycle transformation | **HIGH** | Pending P3.5 | No EBOM -> MBOM -> SBOM transformation workflow |
| BP-11 | BOM comparison/diff | **MEDIUM** | Pending | No diff endpoint for resolved BOMs |
| BP-12 | Where-used depth | **MEDIUM** | Pending P1.5 | Single-level only; N+1 query issue |
| BP-13 | Price waterfall | **MEDIUM** | Pending P3.8 | Flat breakdown list; no running subtotals |
| BP-14 | Historical pricing | **MEDIUM** | Pending P3.9 | Pricing records deleted and recreated on re-resolution |
| BP-15 | Multi-site BOM | **MEDIUM** | Pending | No site/plant concept |
| BP-16 | Bundle/kit pricing | **MEDIUM** | Pending | No group discount rule type |
| BP-17 | Pricing simulation enhancement | **LOW** | Pending | total_cost hardcoded to 0 in simulation; duplicated logic |
| BP-18 | Reference designators | **LOW** | Pending | No PCB position tracking |

### Dimension 3: Platform Architecture & Operations

| # | Gap | Severity | Status | Description |
|---|-----|----------|--------|-------------|
| PA-1 | Caching strategy | **CRITICAL** | **FIXED** | In-memory TTL cache added to engine with CRUD invalidation |
| PA-2 | Performance monitoring | **HIGH** | **FIXED** | 5 Prometheus metrics added and instrumented |
| PA-3 | N+1 query patterns | **HIGH** | Pending P1.5 | Where-used, template application, deep BOM loads |
| PA-4 | Constraint network pre-compilation | **HIGH** | Pending P1.6 | Dependency graph rebuilt on every propagation call |
| PA-5 | Constraint testing/simulation | **HIGH** | Pending P1.7 | Only syntactic validation; no semantic testing or impact analysis |
| PA-6 | Audit trail integration | **HIGH** | **FIXED** | 38 audit events added across all 5 configurator routers |
| PA-7 | Import/export | **HIGH** | Pending P2.7 | No bulk import/export for product definitions or BOMs |
| PA-8 | Webhook event registration | **MEDIUM** | Pending P2.8 | Configurator events not in `VALID_WEBHOOK_EVENTS` |
| PA-9 | Rollback capability | **MEDIUM** | Pending P2.9 | `ProductVersion.snapshot` stores only name/version number |
| PA-10 | Configuration analytics | **MEDIUM** | Pending P3.7 | No aggregation of popular options or constraint hit rates |
| PA-11 | Horizontal scaling | **MEDIUM** | Pending | Missing distributed session locking |
| PA-12 | Product lifecycle guards | **LOW** | Pending | Status machine has no transition validation |

---

## Priority-Ordered Implementation Roadmap

### Phase 0: Security & Correctness -- COMPLETE ✅

| Priority | Gap | Action | Status |
|----------|-----|--------|--------|
| P0.1 | CE-1 | Safe AST arithmetic evaluator | **Done** |
| P0.2 | CE-2 | Conflict explanation tracing | **Done** |
| P0.3 | PA-1 | In-memory product data cache with CRUD invalidation | **Done** |
| P0.4 | PA-2 | Prometheus metrics for propagation + BOM resolution | **Done** |
| P0.5 | PA-6 | Audit events across all 5 routers | **Done** |

### Phase 1: Core Capabilities (Next 2-3 Sprints)

| Priority | Gap | Action | Effort |
|----------|-----|--------|--------|
| P1.1 | CE-3 | Replace `__any__` with `NumericDomain(min, max, step)`. Add `between` operator. Propagate numeric intervals. | M |
| P1.2 | BP-3 | Implement `_resolve_quantities()` using safe JSONB AST formula evaluation | S |
| P1.3 | BP-6 | Implement tiered pricing with bracket logic (all-units and marginal models) | S |
| P1.4 | CE-5 | Build `ConstraintAnalyzer`: cycle detection (DFS), dead value detection, coverage gaps | M |
| P1.5 | PA-3 | Fix N+1 in where-used (join Product), template application (batch), deep BOM (recursive CTE) | S |
| P1.6 | PA-4 | Pre-compile constraint dependency graph at version publish, store in `ProductVersion.snapshot` | M |
| P1.7 | PA-5 | Add `POST /constraints/rules/simulate` and `POST /constraints/impact-analysis` endpoints | M |
| P1.8 | CE-7 | Add `min_select`/`max_select` to `CharacteristicAssignment`, enforce during propagation | S |

### Phase 2: Enterprise Features (Next Quarter)

| Priority | Gap | Action | Effort |
|----------|-----|--------|--------|
| P2.1 | BP-2 | Add `Currency`, `ExchangeRate` tables. Accept `target_currency` in resolver. | L |
| P2.2 | BP-1 | Add `release_state` on BOMHeader, `BOMChangeOrder` model | L |
| P2.3 | CE-4 | Multi-level config: resolver follows `sub_product_id`, creates nested sessions | L |
| P2.4 | BP-4 | Add `BOMItemAlternate` model with priority, type, approval status | M |
| P2.5 | BP-5 | Add `EffectivityType` enum, `BOMItemEffectivity` model, `as_of_date` param on resolver | M |
| P2.6 | BP-7 | Add `customer_id`/`customer_group` to `PricingRule`, `PriceAgreement` model | M |
| P2.7 | PA-7 | CSV/JSON import endpoints for characteristics, constraints, BOM items | M |
| P2.8 | PA-8 | Register configurator events in `VALID_WEBHOOK_EVENTS`, add dispatch handlers | S |
| P2.9 | PA-9 | Comprehensive version snapshots: full product state at publish. Add restore endpoint. | M |

### Phase 3: Platform Maturity (Next Half-Year)

| Priority | Gap | Action | Effort |
|----------|-----|--------|--------|
| P3.1 | BP-9 | Promote `bom_type` to enum, add `BOMMapping` model, accept `bom_type` in resolver | L |
| P3.2 | BP-8 | Add `scrap_percentage`, overhead fields, multi-level bottom-up cost rollup | M |
| P3.3 | CE-6 | Add `RELATION` constraint type for cross-characteristic arithmetic constraints | M |
| P3.4 | CE-10 | Recommendation rules with weight scores, annotating available domains | M |
| P3.5 | BP-10 | BOM lifecycle transformation: EBOM -> MBOM derive endpoint, `Routing` model | XL |
| P3.6 | CE-9 | Optional backtracking completeness check or CP-SAT solver (Google OR-Tools) | L |
| P3.7 | PA-10 | Analytics endpoints: popular options, abandonment rates, constraint hit rates | M |
| P3.8 | BP-13 | Price waterfall with running subtotals and stage grouping | S |
| P3.9 | BP-14 | Historical pricing: keep superseded records, add history endpoint | S |

---

## Benchmark Against Specific Platforms

### vs SAP Variant Configuration
| Capability | SAP | This Platform | Assessment |
|-----------|-----|--------------|------------|
| Classification system (class type 300) | Full | Characteristic groups + assignments | Similar -- groups serve analogous purpose |
| Object dependencies (6 types) | Full | 6 constraint types | Comparable scope, different naming |
| Dependency nets | Full | ConstraintGroups exist | Model exists but not used for propagation partitioning (PA-4) |
| Multi-level configuration | Full | Data model ready, engine doesn't follow | CE-4 gap |
| Super BOM | Full | 150% BOM implemented | Comparable |
| Configuration profiles | Full | Product versioning | Similar concept, less mature |
| Procedures (arbitrary computation) | Full | FORMULA (limited) | CE-6 gap |
| Change management (ECR/ECO) | Full | Missing | BP-1 gap |

### vs Microsoft Dynamics 365 Product Configurator
| Capability | D365 | This Platform | Assessment |
|-----------|------|--------------|------------|
| Formal CSP solver | MSF solver | AC-3 variant | CE-9 -- pragmatic tradeoff, adequate for typical products |
| Expression constraints | OML language | JSONB AST | Different approach, both valid for the use case |
| Table constraints | Full | VariantTable | Comparable implementation |
| Conflict explanation | Solver-provided MUS | Full trace (Phase 0) | **Now implemented** |
| Numeric intervals | Full | `__any__` marker | CE-3 gap -- Phase 1 |

### vs Siemens Teamcenter (BOM)
| Capability | Teamcenter | This Platform | Assessment |
|-----------|------------|--------------|------------|
| 150% BOM | Full | Implemented | Comparable |
| Classic + modular variant | Both | Selection conditions | BP-9 gap (less expressive) |
| Multi-effectivity | Date, serial, lot, unit | Date only | BP-5 gap |
| EBOM/MBOM/SBOM | Full lifecycle | Single BOM type | BP-9, BP-10 gaps |
| Release states | Full workflow | Missing | BP-1 gap |
| BOM comparison | Full | Missing | BP-11 gap |

### vs Tacton CPQ (Configurator)
| Capability | Tacton | This Platform | Assessment |
|-----------|--------|--------------|------------|
| Constraint-based (not rule-based) | Core philosophy | Aligns well | **Strength** -- correct architectural choice |
| Parametric design | CAD integration | Media model foundation | Path exists via headless API |
| Numeric constraints | Full intervals | `__any__` | CE-3 gap -- Phase 1 |
| Needs-based configuration | Guided selling | Missing | CE-10 gap |

---

## Overall Assessment

**This platform's strongest differentiator** is bridging CPQ and PDM: it has both the configurator+pricing engine (CPQ territory) and the 150% BOM with phantom assemblies (PDM territory) in a single, API-first, multi-tenant platform. No commercial product does both well in a modern, headless architecture.

**Total gaps: 38** (5 Critical, 17 High, 12 Medium, 4 Low)
**Phase 0 resolved**: 5 gaps (CE-1, CE-2, PA-1, PA-2, PA-6)
**Remaining**: 33 gaps across Phases 1-3

---

## Key Files

- `app/configurator/engine.py` -- Constraint propagation engine
- `app/configurator/bom_resolver.py` -- BOM resolution + pricing
- `app/configurator/validator.py` -- Validation logic
- `app/db/models/product.py` -- Product/characteristic/constraint models
- `app/db/models/bom.py` -- BOM models
- `app/db/models/configurator.py` -- Session/pricing models
- `app/api/v1/configurator.py` -- Main configurator API
- `app/api/v1/boms.py` -- BOM API
- `app/api/v1/webhooks.py` -- Webhook event registry
- `app/core/cache.py` -- Cache infrastructure
- `app/core/metrics.py` -- Prometheus metrics (incl. configurator metrics added in Phase 0)
- `app/core/audit.py` -- Audit infrastructure
