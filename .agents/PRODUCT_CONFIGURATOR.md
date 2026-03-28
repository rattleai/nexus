# Product Configurator & Configurable BOM — Implementation Plan

## Executive Summary

Production-grade product configuration system for manufacturing companies to manage product portfolios, configurable variants, and 150% super BOMs. Features a **constraint propagation engine** (AC-3 variant), **BOM resolution** (150% → 100%), and an integrated **pricing & profitability engine**. Draws from SAP Variant Configuration, Tacton CPQ, Salesforce CPQ, and modern headless CPQ patterns.

---

## Architecture Overview

```
┌──────────────────────────────────────────────────────────────┐
│                        API Layer                              │
│  CRUD  /api/v1/products          (families, products, vers.) │
│  CRUD  /api/v1/characteristics   (groups, chars, values)     │
│  CRUD  /api/v1/constraints       (rules, groups, var.tables) │
│  CRUD  /api/v1/boms              (headers, items, where-used)│
│  /api/v1/configurator/sessions   (create, select, validate)  │
│  /api/v1/configurator/sessions/{id}/resolve-bom              │
│  /api/v1/configurator/sessions/{id}/pricing                  │
│  /api/v1/configurator/pricing/simulate                       │
│  /api/v1/configurator/pricing/rules  (CRUD)                  │
│  /api/v1/configurator/templates  (save/load)                 │
└───────────────┬──────────────────────────────────────────────┘
                │
┌───────────────▼──────────────────────────────────────────────┐
│                  Configurator Service Layer                    │
│  ┌─────────────────┐ ┌────────────────┐ ┌──────────────────┐ │
│  │ ConfiguratorEng. │ │ BOMResolver    │ │ ConfigValidator  │ │
│  │ (AC-3 constraint │ │ (150%→100%     │ │ (completeness +  │ │
│  │  propagation)    │ │  + pricing)    │ │  consistency)    │ │
│  └────────┬─────────┘ └───────┬────────┘ └────────┬─────────┘ │
│           │                   │                    │           │
│  ┌────────▼───────────────────▼────────────────────▼─────────┐│
│  │              Domain Events + Celery Tasks                 ││
│  │  ConfigurationStarted, SelectionMade, BOMResolved,        ││
│  │  PricingResolved, ConfigurationLocked                     ││
│  │  resolve_bom_async, bulk_validate_sessions                ││
│  └───────────────────────────────────────────────────────────┘│
└───────────────────────────────────────────────────────────────┘
                │
┌───────────────▼──────────────────────────────────────────────┐
│                   Data Layer (19 tables)                       │
│  product_families, products, product_versions                 │
│  characteristic_groups, characteristics, characteristic_values│
│  characteristic_assignments, constraint_groups, constraint_   │
│  rules, variant_tables, product_media                         │
│  bom_headers, bom_items                                       │
│  configuration_templates, configuration_sessions,             │
│  configuration_selections, configured_boms                    │
│  pricing_rules, configuration_pricing                         │
│  (All with RLS tenant isolation)                              │
└──────────────────────────────────────────────────────────────┘
```

---

## Files Created

### Models (3 files)
- `app/db/models/product.py` — ProductFamily, Product, ProductVersion, CharacteristicGroup, Characteristic, CharacteristicValue, CharacteristicAssignment, ConstraintGroup, ConstraintRule, VariantTable, ProductMedia
- `app/db/models/bom.py` — BOMHeader, BOMItem (150% super BOM with JSONB selection conditions)
- `app/db/models/configurator.py` — ConfigurationSession, ConfigurationSelection, ConfigurationTemplate, ConfiguredBOM, PricingRule, ConfigurationPricing

### Services (4 files)
- `app/configurator/__init__.py`
- `app/configurator/engine.py` — Constraint propagation engine (AC-3 variant, all 6 constraint types)
- `app/configurator/bom_resolver.py` — 150% → 100% BOM resolution with phantom flattening + pricing
- `app/configurator/validator.py` — Configuration completeness & validity checking

### API (6 files)
- `app/api/v1/products.py` — Product family & product CRUD (13 endpoints)
- `app/api/v1/characteristics.py` — Characteristics, groups, values, assignments CRUD (14 endpoints)
- `app/api/v1/constraints.py` — Constraint rules, groups, variant tables CRUD (12 endpoints)
- `app/api/v1/boms.py` — BOM header & item CRUD, where-used (10 endpoints)
- `app/api/v1/configurator.py` — Sessions, selection, validation, BOM resolution, pricing, templates (20 endpoints)
- `app/api/schemas_configurator.py` — All Pydantic request/response schemas

### Events & Tasks (2 files)
- `app/configurator/events.py` — 8 domain events
- `app/configurator/tasks.py` — Celery tasks (resolve_bom_async, bulk_validate_sessions)

### Migration (1 file)
- `app/db/migrations/versions/0016_product_configurator.py` — 19 tables, 19 RLS policies, 6 enum types

### Tests (5 files)
- `tests/test_products.py` — Auth guards, CRUD, 404 handling
- `tests/test_characteristics.py` — Auth guards, CRUD, assignments
- `tests/test_constraints.py` — Auth guards, expression validation (requires/excludes), 404s
- `tests/test_boms.py` — Auth guards, CRUD, where-used
- `tests/test_configurator.py` — Auth guards, sessions, 25+ engine unit tests (condition evaluation, constraint propagation, contradiction detection, auto-set, selection_condition, char extraction)

### Files Modified
- `app/db/models/__init__.py` — Re-exports for all 24 new model classes/enums
- `app/api/v1/__init__.py` — 5 new routers registered

---

## Data Model

### Layer 1: Product Catalog (`app/db/models/product.py`)

**ProductFamily** — Top-level grouping (e.g. "Trucks", "Electric Motors")
- `id`, `tenant_id`, `name`, `slug`, `description`, `metadata` (JSONB)
- Mixins: SoftDeleteMixin, AuditMixin, VersionMixin, TimestampMixin
- Unique: (tenant_id, slug)

**Product** — A configurable product definition
- `id`, `tenant_id`, `family_id` (FK→product_families), `name`, `slug`, `description`
- `sku_prefix`, `status` (draft/active/deprecated/archived), `metadata` (JSONB)
- Relationships: family, versions, characteristic_assignments, constraint_rules, constraint_groups, variant_tables, bom_headers, pricing_rules
- Unique: (tenant_id, slug)

**ProductVersion** — Immutable snapshot for reproducibility
- `id`, `tenant_id`, `product_id`, `version_number`, `label`
- `snapshot` (JSONB — full config model freeze), `is_active`, `published_at`
- Unique: (product_id, version_number)

**CharacteristicGroup** — Groups related characteristics (SAP "class" / SFDC "feature")
- `id`, `tenant_id`, `name`, `slug`, `description`, `display_order`, `metadata`

**Characteristic** — Individual option/feature (SAP "characteristic")
- `id`, `tenant_id`, `group_id`, `name`, `slug`, `description`
- `char_type` (enum/numeric/boolean/text)
- Numeric fields: `numeric_min`, `numeric_max`, `numeric_step`, `unit`
- `is_required`, `is_multi_select`, `default_value`, `display_order`, `metadata`
- Relationships: group, values

**CharacteristicValue** — Allowed value for enum characteristics
- `id`, `tenant_id`, `characteristic_id`, `value` (internal), `label` (display)
- `description`, `display_order`, `is_default`
- `price_adjustment` (Numeric 12,4) — quick price delta per option
- `image_url`, `metadata`
- Unique: (characteristic_id, value)

**CharacteristicAssignment** — Links characteristic to product with overrides
- `id`, `tenant_id`, `product_id`, `characteristic_id`
- `display_order`, `is_required` (override), `default_value` (override)
- Unique: (product_id, characteristic_id)

**ConstraintGroup** — Dependency net grouping related rules
- `id`, `tenant_id`, `product_id`, `name`, `description`, `is_active`

**ConstraintRule** — Individual constraint (SAP "object dependency")
- `id`, `tenant_id`, `product_id`, `group_id`
- `name`, `description`, `constraint_type` (requires/excludes/selection_condition/default_value/formula/table)
- `expression` (JSONB AST — portable, safe, indexable, UI-renderable)
- `priority`, `is_active`, `effective_from`, `effective_to`

JSONB AST expression examples:
```json
// REQUIRES: If engine=V8 then transmission must be auto_6 or auto_8
{"type": "requires",
 "if": {"char": "engine", "op": "eq", "value": "V8"},
 "then": {"char": "transmission", "op": "in", "value": ["auto_6", "auto_8"]}}

// EXCLUDES: If trim=base then sunroof cannot be panoramic
{"type": "excludes",
 "if": {"char": "trim", "op": "eq", "value": "base"},
 "then": {"char": "sunroof", "op": "eq", "value": "panoramic"}}

// SELECTION_CONDITION: 20" wheels only available with sport suspension
{"type": "selection_condition",
 "target": {"char": "wheel_size", "value": "20_inch"},
 "condition": {"char": "suspension", "op": "eq", "value": "sport"}}

// FORMULA: Value map lookup
{"type": "formula", "target": "weight_kg",
 "input": "engine", "value_map": {"V8": "250", "I4": "180"}}

// FORMULA: Arithmetic with variable substitution
{"type": "formula", "target": "total_weight",
 "expression": "base + extra",
 "variables": {"base": "body_weight", "extra": "engine_weight"}}
```

**VariantTable** — Tabular constraint data for table-based lookups
- `id`, `tenant_id`, `product_id`, `name`, `description`
- `columns` (JSONB), `rows` (JSONB), `input_columns` (JSONB), `output_columns` (JSONB)

**ProductMedia** — Images, videos, 3D models (polymorphic via entity_type+entity_id)
- `id`, `tenant_id`, `entity_type`, `entity_id`, `media_type`, `url`
- `filename`, `mime_type`, `file_size`, `display_order`, `alt_text`, `metadata`

### Layer 2: BOM (`app/db/models/bom.py`)

**BOMHeader** — The 150% super BOM definition
- `id`, `tenant_id`, `product_id`, `name`, `description`
- `bom_type` (manufacturing/engineering/service), `is_primary`
- `effective_from`, `effective_to`, `metadata`
- Relationships: product (back_populates Product.bom_headers), items
- Mixins: SoftDeleteMixin, AuditMixin, VersionMixin, TimestampMixin

**BOMItem** — Single item in 150% BOM with selection condition
- `id`, `tenant_id`, `bom_header_id`, `parent_item_id` (self-FK for hierarchy)
- `item_type` (component/sub_assembly/phantom/reference)
- `part_number`, `part_name`, `description`
- `quantity` (Numeric 12,4), `quantity_expression` (JSONB formula), `unit_of_measure`
- `sub_product_id` (FK→products — multi-level configurable sub-assemblies)
- **`selection_condition`** (JSONB — same AST as constraints; null = always included)
- `effective_from`, `effective_to`, `sort_order`, `is_optional`
- `unit_cost` (Numeric 12,4), `lead_time_days`, `metadata`

### Layer 3: Configuration & Pricing (`app/db/models/configurator.py`)

**ConfigurationSession** — Active/completed configuration
- `id`, `tenant_id`, `product_id`, `product_version_id`, `user_id`
- `name`, `status` (in_progress/complete/invalid/locked)
- `is_valid`, `is_complete`, `validation_errors` (JSONB)
- `available_domains` (JSONB — cached domain state after propagation)
- `template_id`, `external_reference`, `metadata`

**ConfigurationSelection** — Individual characteristic value selection
- `id`, `tenant_id`, `session_id`, `characteristic_id`, `value`
- `is_auto_set` (bool — set by constraint, not user), `set_by_rule_id`

**ConfigurationTemplate** — Saved partial/complete config for reuse
- `id`, `tenant_id`, `product_id`, `name`, `description`
- `is_partial`, `is_public`, `selections` (JSONB snapshot), `metadata`

**ConfiguredBOM** — Resolved 100% BOM (immutable snapshot)
- `id`, `tenant_id`, `session_id` (unique), `bom_header_id`
- `resolved_items` (JSONB — denormalized for immutability + fast reads)
- `total_components`, `total_cost` (Numeric 14,4)
- `selection_snapshot` (JSONB), `resolved_at`, `resolution_duration_ms`

**PricingRule** — Complex pricing rules for profitability analysis
- `id`, `tenant_id`, `product_id`, `name`, `description`
- `rule_type` (base_price/option_surcharge/volume_discount/conditional/formula/tiered/margin)
- `expression` (JSONB AST), `priority`, `is_active`, `effective_from`, `effective_to`
- `currency` (default "EUR")

Pricing rule expression examples:
```json
{"type": "base_price", "amount": 25000.00}

{"type": "option_surcharge",
 "condition": {"char": "engine", "op": "eq", "value": "V8"},
 "amount": 8500.00}

{"type": "conditional",
 "condition": {"op": "and", "conditions": [
   {"char": "trim", "op": "eq", "value": "base"},
   {"char": "color", "op": "in", "value": ["white", "black"]}
 ]},
 "adjustment_type": "percentage", "amount": -5.0}

{"type": "margin", "target_margin_pct": 35.0, "min_margin_pct": 20.0}
```

**ConfigurationPricing** — Resolved pricing for a configuration session
- `id`, `tenant_id`, `session_id` (unique), `currency`
- `base_price`, `total_adjustments`, `final_price`, `total_cost` (all Numeric 14,4)
- `margin_amount` (Numeric 14,4), `margin_percentage` (Numeric 8,4)
- `price_breakdown` (JSONB), `is_profitable` (bool), `resolved_at`

---

## Constraint Engine Algorithm (`app/configurator/engine.py`)

Arc-consistency (AC-3 variant) adapted for product configuration. Stateless — all state in DB.

### `ConfiguratorEngine.apply_selection(session_id, characteristic_slug, value)`

1. **Validate** value against characteristic domain (enum allowed values, numeric range)
2. **Upsert** selection in DB (replace for single-select, add for multi-select)
3. **Set domain**: `domains[slug] = {value}`; add slug to `changed_queue`
4. **Propagation loop** (until queue empty or contradiction):
   ```
   while changed_queue not empty:
     char = changed_queue.pop()
     for constraint referencing char:
       REQUIRES: if condition true → intersect target domain with required values
       EXCLUDES: if condition true → subtract excluded values from target domain
       SELECTION_CONDITION: if condition false → remove target value from domain
       DEFAULT_VALUE: if condition true and no selection → auto-set
       FORMULA: evaluate formula → set computed value in target domain
       TABLE: lookup outputs → intersect output domains
       if any domain changed → add affected char to queue
   ```
5. **Post-propagation**: Empty domain = contradiction → invalid. Single-value domain = auto-set. Check completeness. Update session state + emit events.

### `ConfiguratorEngine.remove_selection(session_id, characteristic_id)`

Re-propagation from scratch (correct by construction):
1. Remove user selection + all auto-set selections
2. Reset all domains to full
3. Re-propagate from remaining selections

### Condition Evaluation

Supports operators: `eq`, `neq`, `in`, `not_in`, `gt`, `gte`, `lt`, `lte`, `and`, `or`, `not`

### Formula Evaluation

Two modes:
1. **Value map**: `{"input": "engine", "value_map": {"V8": "250", "I4": "180"}}` — lookup
2. **Arithmetic**: `{"expression": "base + delta", "variables": {"base": "weight", "delta": "extra"}}` — variable substitution + safe eval

---

## BOM Resolution Algorithm (`app/configurator/bom_resolver.py`)

### `BOMResolver.resolve(session_id) → ConfiguredBOM`

1. **Load** session selections + product's primary BOMHeader with all items
2. **Filter**: For each BOM item:
   - `selection_condition is null` → include (unconditional)
   - Evaluate condition against selections → include if true
   - Check effectivity dates
3. **Multi-level**: Recursively include children; handle sub-assemblies
4. **Phantom flattening**: Replace phantom items with children, multiply quantities through
5. **Cost calculation**: Sum `unit_cost × resolved_quantity` → `total_cost`
6. **Pricing**: Evaluate all active PricingRules in priority order → `final_price`
7. **Profitability**: `margin = final_price - total_cost`, check against min_margin threshold
8. **Output**: Create ConfiguredBOM + ConfigurationPricing records with full breakdown

---

## API Endpoints (69 total)

### Products (`/api/v1/products/`) — 13 endpoints
| Method | Path | Description |
|--------|------|-------------|
| POST | `/products/families` | Create product family |
| GET | `/products/families` | List families (cursor paginated) |
| GET/PUT/DELETE | `/products/families/{id}` | Family CRUD |
| POST | `/products/` | Create product |
| GET | `/products/` | List products (filter by family, status) |
| GET/PUT/DELETE | `/products/{id}` | Product CRUD |
| POST | `/products/{id}/versions` | Publish version snapshot |
| GET | `/products/{id}/versions` | List versions |
| POST | `/products/{id}/versions/{vid}/activate` | Set active version |

### Characteristics (`/api/v1/characteristics/`) — 14 endpoints
| Method | Path | Description |
|--------|------|-------------|
| POST/GET | `/characteristics/groups` | Group create + list |
| PUT/DELETE | `/characteristics/groups/{id}` | Group update + delete |
| POST/GET | `/characteristics/` | Characteristic create + list |
| GET/PUT/DELETE | `/characteristics/{id}` | Characteristic CRUD |
| POST | `/characteristics/{id}/values` | Add value |
| PUT/DELETE | `/characteristics/{id}/values/{vid}` | Value update + delete |
| POST | `/characteristics/assign` | Assign to product |
| DELETE | `/characteristics/assign/{id}` | Remove assignment |

### Constraints (`/api/v1/constraints/`) — 12 endpoints
| Method | Path | Description |
|--------|------|-------------|
| POST/GET | `/constraints/groups` | Constraint group CRUD |
| POST/GET | `/constraints/rules` | Rule create + list |
| GET/PUT/DELETE | `/constraints/rules/{id}` | Rule CRUD |
| POST | `/constraints/rules/validate` | Dry-run expression validation |
| POST/GET | `/constraints/tables` | Variant table create + list |
| PUT/DELETE | `/constraints/tables/{id}` | Variant table update + delete |

### BOMs (`/api/v1/boms/`) — 10 endpoints
| Method | Path | Description |
|--------|------|-------------|
| POST/GET | `/boms/` | BOM header create + list |
| GET/PUT/DELETE | `/boms/{id}` | BOM detail (with items tree) |
| POST/PUT/DELETE | `/boms/{id}/items` | BOM item management |
| POST | `/boms/{id}/items/reorder` | Reorder items |
| GET | `/boms/where-used/{part_number}` | Where-used analysis |

### Configurator (`/api/v1/configurator/`) — 20 endpoints
| Method | Path | Description |
|--------|------|-------------|
| POST | `/configurator/sessions` | Start session (from scratch or template) |
| GET | `/configurator/sessions` | List sessions (filter by product, status) |
| GET | `/configurator/sessions/{id}` | Get state + available domains + selections |
| POST | `/configurator/sessions/{id}/select` | Set value → propagate constraints |
| DELETE | `/configurator/sessions/{id}/select/{char_id}` | Remove selection → re-propagate |
| POST | `/configurator/sessions/{id}/reset` | Reset to initial state |
| GET | `/configurator/sessions/{id}/validate` | Full validation |
| POST | `/configurator/sessions/{id}/resolve-bom` | Resolve 150% → 100% BOM + pricing |
| GET | `/configurator/sessions/{id}/bom` | Get resolved BOM |
| GET | `/configurator/sessions/{id}/pricing` | Get pricing + profitability |
| POST | `/configurator/sessions/{id}/lock` | Finalize configuration |
| POST | `/configurator/sessions/{id}/clone` | Clone session |
| POST/GET | `/configurator/templates` | Template management |
| POST/GET | `/configurator/pricing/rules` | Pricing rule CRUD |
| GET/PUT/DELETE | `/configurator/pricing/rules/{id}` | Pricing rule detail |
| POST | `/configurator/pricing/simulate` | Simulate pricing without session |

---

## Domain Events (`app/configurator/events.py`)

| Event | Emitted When |
|-------|-------------|
| `ConfigurationStarted` | Session created |
| `ConfigurationSelectionMade` | User makes a selection |
| `ConfigurationSelectionRemoved` | User removes a selection |
| `ConfigurationCompleted` | All required chars filled, all constraints valid |
| `ConfigurationLocked` | Session finalized |
| `BOMResolved` | 150% → 100% BOM resolved |
| `PricingResolved` | Pricing calculated with profitability |
| `ProductVersionPublished` | Product version snapshot published |

---

## Reusable Existing Patterns

| Pattern | File | Usage |
|---------|------|-------|
| Base + Mixins | `app/db/base.py` | TimestampMixin, SoftDeleteMixin, VersionMixin, AuditMixin |
| Multi-tenant queries | `app/core/tenant.py` → `tenant_query()` | All queries scoped to tenant |
| Cursor pagination | `app/core/pagination.py` → `paginate()` | All list endpoints |
| Domain events | `app/core/events.py` → `DomainEvent`, `emit()`, `on()` | Configuration lifecycle events |
| Rate limiting | `app/api/rate_limit.py` → `ApiKeyRateLimiter` | All routers |
| Auth deps | `app/api/deps.py` → `get_current_tenant`, `get_db`, `RequireScopes` | All endpoints |

---

## Key Design Decisions

1. **JSONB AST for expressions** (not string DSL): Validates at write time via Pydantic, indexable via PostgreSQL operators, safe evaluation without eval(), UI-renderable
2. **ConfiguredBOM stores denormalized JSONB**: Immutable snapshot — reproducible even if 150% BOM changes later
3. **Re-propagation from scratch on removal**: Correct by construction, avoids complex incremental un-propagation
4. **Inline CRUD in route handlers**: Follows existing codebase pattern (jobs.py, billing.py)
5. **Separate service modules for engine/resolver/validator**: Algorithmic complexity warrants separation
6. **Session-based configuration**: Multi-step, resumable, auditable, foundation for collaborative config
7. **Pricing as first-class citizen**: PricingRule + ConfigurationPricing enable full profitability analysis per configuration
8. **All 19 tables have RLS policies**: Tenant isolation enforced at PostgreSQL level

---

## Verification

1. **Syntax checks**: All 25 new files pass `py_compile`
2. **Unit tests**: 25+ engine tests (condition eval, propagation, contradiction, auto-set)
3. **Auth tests**: All 5 endpoint groups verify 401 on unauthenticated requests
4. **404 tests**: CRUD endpoints return 404 for missing resources
5. **Expression validation**: Constraint validate endpoint tested for requires/excludes
6. **Migration**: `alembic upgrade head` creates 19 tables with FKs, indexes, and RLS
