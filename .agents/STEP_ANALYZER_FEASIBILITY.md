# STEP File Analyzer: Feasibility & Architecture Analysis

**Date:** 2026-02-19
**Status:** Decision document — awaiting strategic direction
**Scope:** End-to-end assessment of automated should-costing from STEP files and PDF drawings

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Current State Analysis](#2-current-state-analysis)
3. [Value Chain Gap Analysis](#3-value-chain-gap-analysis)
4. [The Cost Formula Problem](#4-the-cost-formula-problem)
5. [Drawing Intelligence: OCR & AI Extraction](#5-drawing-intelligence-ocr--ai-extraction)
6. [Build vs. Buy Assessment](#6-build-vs-buy-assessment)
7. [Technical Implementation Plan](#7-technical-implementation-plan)
8. [Phased Roadmap](#8-phased-roadmap)
9. [Decision Framework](#9-decision-framework)
10. [External Provider & RFQ Market Landscape](#10-external-provider--rfq-market-landscape)
11. [AI-Driven Approach: Learning Cost from Data](#11-ai-driven-approach-learning-cost-from-data)
12. [The API Business Opportunity: Manufacturing Intelligence as a Service](#12-the-api-business-opportunity-manufacturing-intelligence-as-a-service)
13. [The Paradigm Shift: Manufacturing Intelligence Middleware](#13-the-paradigm-shift-manufacturing-intelligence-middleware)
14. [CADPrice — Implementation Plan](#14-cadprice--implementation-plan)
15. [Platform Architecture: Two Pillars, One Intelligence Layer](#15-platform-architecture-two-pillars-one-intelligence-layer)
16. [AI Tech Stack & Training Strategy (Consolidated Reference)](#16-ai-tech-stack--training-strategy-consolidated-reference)

**Appendices:**
- [A: Luminarity API Quick Reference](#appendix-a-luminarity-api-quick-reference)
- [B: Existing Extension Points in RattleApp](#appendix-b-existing-extension-points-in-rattleapp)
- [C: Drawing Intelligence Framework References](#appendix-c-drawing-intelligence-framework-references)
- [D: External Provider Quick Reference Table](#appendix-d-external-provider-quick-reference-table)
- [E: Open CAD Dataset Reference](#appendix-e-open-cad-dataset-reference)
- [F: Market Data Sources](#appendix-f-market-data-sources)
- [G: aPriori & Classmate Cloud Technical Reference](#appendix-g-apriori--classmate-cloud-technical-reference)
- [H: PLM/ERP Integration Reference](#appendix-h-plmerp-integration-reference)

---

## 1. Executive Summary

**The question:** Should RattleApp build a self-hosted STEP file geometry extraction microservice to enable automated manufacturing cost estimation?

**The answer:** Not yet. Geometry extraction (whether self-hosted or via Luminarity) is only an **input layer**. The critical missing piece is a **cost formula engine** that maps geometry parameters to manufacturing costs. Without it, extracted geometry data has no user-facing value.

### Key Findings

| Finding | Impact |
|---------|--------|
| No cost formulas exist anywhere in RattleApp | Geometry extraction has zero standalone value |
| Luminarity API is fully documented but unintegrated | Spec exists at `/api/luminarity_shouldcosting_1.0.0.json` |
| Current pricing is sales-side only (CPQ) | `Part.part_cost` is a manual integer field — no calculation logic |
| Connector framework could integrate Luminarity today | But geometry data would sit unused without cost formulas |
| Cost formula engine is domain-specific and hard | Requires machine databases, hourly rates, cycle times, material costs |
| PDF drawings contain critical cost-driving data | Material specs, tolerances, surface finishes — not in STEP files |
| Existing AI + PDF infrastructure is ready to combine | PyMuPDF, LLM providers, PartDocument all exist — no new dependencies needed |

**Recommendation:** Build the cost formula engine first (Phase 0). Only then does geometry extraction — whether via Luminarity API or a self-hosted service — deliver user value. In parallel, a **Drawing Intelligence** layer using OCR + LLM extraction from PDF drawings can supply the metadata that STEP files lack (material, tolerances, surface finish, GD&T) — dramatically improving cost estimate accuracy.

**The AI-driven alternative (Section 11):** Recent research reveals a fundamentally different path — instead of hand-crafting cost formulas, **train AI models on open CAD datasets and customer production data** to learn cost patterns directly. Open datasets (1M+ models with machining feature labels) solve the pre-training problem; customer historical costs solve the fine-tuning problem. This approach also unlocks capabilities far beyond cost estimation: similar part search, automatic process routing, DFM feedback, and cost driver visualization. The long-term architecture should be AI-first, with Phase 0 formulas serving as a bootstrapping mechanism.

**The API business opportunity (Section 12):** A critical market gap exists — **no platform offers a stateless REST API for manufacturing cost calculation or master data enrichment on a per-call basis.** aPriori is enterprise-only ($50K+/yr), Xometry returns market prices (not should-costs), and everyone else lacks APIs entirely. Two API products — CostAPI (should-cost from STEP files) and EnrichAPI (master data enrichment) — could address a $1.5-2.1B direct TAM growing to $3-5B, with embedded potential in the $26-70B PLM market. The recommended path is hybrid: build the technology inside RattleApp first, then expose as a standalone API once validated. The technology assessed in Sections 4-11 forms the foundation for both paths.

**The paradigm shift (Section 13):** Section 12's standalone API model inherited a critical weakness from Section 11 — the cold-start problem (no open dataset contains manufacturing cost labels, forcing a +/-30% accuracy ceiling at launch). Section 13 resolves this by using **industrial-grade deterministic cost engines (aPriori and simus Classmate Cloud) as AI training data factories**: run 150K+ curated open STEP files through these engines to generate **9M+ high-quality labeled (geometry, detailed_cost_breakdown) pairs** before launch. This is the AlphaGo pattern — learn from the expert system first, then surpass it with real-world production data. Simultaneously, the business model shifts from standalone API to **manufacturing intelligence middleware** — an event-driven intelligence layer that sits between PLM systems (Teamcenter, Windchill, 3DEXPERIENCE) and ERP systems (SAP, Oracle), enriching every part as it flows from engineering to production. Pre-built connectors for 8 PLM/ERP systems, seven intelligence capabilities per enrichment event, and connector-based recurring revenue create astronomical switching costs. This reframing changes the venture-scale outcome from plausible ($200-400M ARR) to structurally achievable ($1B+ ARR).

**Two Pillars architecture (Section 15):** The capabilities described in Sections 11-14 naturally decompose into **two distinct architectural pillars**: a **Deterministic Data Enhancement Engine (DDE)** — geometry extraction, formula costing, rule-based DFM checks, material matching (capabilities D1-D7) — and an **AI Feature Set (AFS)** — learned cost prediction, geometric encoding, similar part search, process routing (capabilities A1-A9). Section 15 defines the formal interface contract between the pillars, the parallel enrichment pipeline (5-21s typical), three end-to-end user workflows (middleware, API, interactive), the ensemble/confidence pattern for blending deterministic and AI estimates, and a **usage-based pricing model** (per-call, no plans, no tiers) that supersedes the plan-based models in Sections 13.5 and 14.10. The pricing architecture follows the OpenAI/Stripe pattern: sign up, get an API key, pay per call, volume discounts kick in automatically.

---

## 2. Current State Analysis

### 2.1 Luminarity API (Documented, Not Integrated)

The Luminarity Shouldcosting API (`https://api2.shouldcosting.com`) is fully documented and live-tested. It provides **geometry mining** — not cost calculation.

**Workflow:**
```
POST /api/costchecker          → Upload base64-encoded STEP file
GET  /api/costchecker/{id}     → Poll status (IN_QUEUE → MINING → DONE)
GET  /api/costchecker/miningresult/{id}  → Retrieve 47+ geometry parameters
```

**What it returns (per component):**

| Category | Fields |
|----------|--------|
| Classification | `master_material_group` (molding/milling/turning/assembly), confidence score |
| Volume | `pd_volume`, `pd_volume_raw`, `pd_cutting_volume` (mm³) |
| Surface | `pd_surface_full_part`, `pd_isc_surfaces`, `master_machined_areas_percentage` |
| Bounding box | Length, depth, height, volume (mm) |
| Hole features | Radial/angular bore counts, thread counts (3 methods), thread diameter |
| Bore detail | `master_bore_collection`: type, count, diameter, depth per bore |
| Turning profile | Min/max diameter, profile start/end geometry strings |
| Sheet metal | Material thickness, bend count |
| Assembly | Component count, per-component breakdown |

**What it does NOT return:** Cost, price, material selection, machine allocation, cycle time, hourly rates — none of the data needed to produce a cost estimate.

**Observed performance:**

| File | Size | Type | Processing Time |
|------|------|------|-----------------|
| block.stp | 10 KB | Molding | 2.5s |
| 4pinplug.stp | 57 KB | Assembly (7 parts) | 1.9s |
| Pump Manifold v3.step | 493 KB | Turning | 12.6s |
| eMG1-110-G4.stp | 590 KB | Assembly (8 parts) | 36.4s |

**Integration status:** Zero lines of code in RattleApp call the Luminarity API. The spec file is documentation only.

### 2.2 Connector Framework (Ready for Integration)

RattleApp has a mature HTTP integration framework that could integrate Luminarity without new infrastructure:

- **`ExternalConnector`** — base URL, auth, proxy, TLS settings
- **`ExternalEndpoint`** — per-endpoint URL/method/body templates (Jinja2)
- **`ExchangeTask`** — orchestrated multi-step flows or webhook calls
- **Slot system** — UI binding points with rich context injection
- **Post-success actions** — `upsert_part` / `bulk_upsert_parts` can write results back to Part records
- **Vendor adapters** — `register_vendor_adapter("luminarity", ...)` for custom logic

**Gap for Luminarity:** The polling pattern (IN_QUEUE → MINING → DONE) doesn't fit the standard connector request-response model. Would need either a Celery polling task or a connector `steps` flow with retry/delay logic.

### 2.3 Current Pricing Model (Sales CPQ Only)

**Sales pricing** — fully built, no gaps:
```
Product.product_price + Area.area_price + Σ(Option.option_price × qty)
  → with quantity scaling, price list overrides, advanced conditional pricing
```

Implemented in `app/utils/pricing.py` (757 lines), supporting price lists, currency overrides, `OptionPriceOverride` with conditional rules, and snapshot-based locked pricing.

**Manufacturing cost** — effectively absent:
- `Part.part_cost` — single `Integer` column (cents), manually entered
- `rollup_cost()` in `app/utils/cost_rollup.py` — bottom-up BOM aggregation:
  ```
  child_total = child.own_cost + child.material_cost
  extended = child_total × quantity × (1 + scrap_percent/100)
  total_cost = own_cost + Σ(extended for all children)
  ```
- No cost breakdown by manufacturing process
- No machine rate, hourly rate, cycle time, setup time, or overhead fields
- No cost history or date-effective costing
- No standard vs. actual vs. target cost distinction

### 2.4 Part Data Model (Extension Points Exist)

```python
class Part(db.Model):
    part_number     String(100)
    part_name       String(255)
    part_cost       Integer         # manually entered, cents
    custom_fields   JSON_TYPE       # ← extension point for geometry data
    # ... plus documents, revisions, BOM relationships
```

`Part.custom_fields` (JSON column) is the zero-migration path for storing geometry analysis results. Example:
```json
{
  "geometry_analysis": {
    "source": "luminarity",
    "material_group": "turning",
    "pd_volume": 276903.15,
    "pd_cutting_volume": 0.0,
    "master_machined_areas_percentage": 63.4,
    "pd_number_of_radial_bore": 6,
    "bounding_box": [120.5, 80.0, 45.2],
    "analyzed_at": "2026-02-19T17:03:10"
  }
}
```

### 2.5 Existing PDF & AI Infrastructure (Ready to Combine)

RattleApp already has all the building blocks for document intelligence — they just haven't been wired together for this use case.

**PDF processing (installed):**
- `PyMuPDF 1.26.5` (`fitz`) — currently used only for TOC page-number detection in rendered PDFs, but fully capable of text extraction, page rendering to image, and annotation parsing on *uploaded* PDFs
- `pypdf 5.1.0` — PDF merging/metadata; available for structural analysis
- `Pillow 12.0.0` — image manipulation, already used for upload validation and variant generation
- `Playwright 1.55.0` — headless Chromium rendering with semaphore-controlled concurrency

**LLM infrastructure (production-ready):**
- Multi-provider factory (`llm_provider.py`): OpenAI, Anthropic, DeepSeek, Groq, Mistral, Gemini, OpenRouter
- Per-company, per-feature provider/model resolution (`resolve_llm_for_feature()`)
- Structured JSON output via OpenAI Responses API (proven in `ai_rewrite.py`)
- Rate limiting (`ai_rate_limiter.py`), prompt security (`prompt_security.py`), token tracking
- Vision-capable models available: GPT-4o, Claude 3.5 Sonnet, Gemini — all support image input

**File storage (production-ready):**
- `PartDocument` / `CadFile` models with protected uploads, signed URLs, SHA-256 hashing
- `Derivative` model (defined but unused) — designed for derived formats (`"glb"`, `"thumbnail"`, `"step"`, `"svg-pdf"`) with status tracking
- Upload pipeline with MIME validation, size limits, optional AV scanning

**What's NOT installed:** No dedicated OCR library (pytesseract, EasyOCR, PaddleOCR). But for the LLM-based approach (recommended), none is needed — vision models handle OCR natively.

---

## 3. Value Chain Gap Analysis

The full pipeline from uploaded files to user-visible cost estimate has **two parallel input channels**:

```
                    ┌───────────────────┐
                    │ STEP File Upload  │
                    │ (3D CAD geometry) │
                    └────────┬──────────┘
                             │
                             ▼
                    ┌───────────────────┐
                    │ Geometry          │
                    │ Extraction        │    ┌──────────────────┐    ┌───────────────────┐    ┌──────────────┐
                    │ (47+ parameters)  │───→│ Process          │───→│ Cost Formula      │───→│ User-Facing  │
                    │ Volume, surface,  │    │ Classification   │    │ Engine            │    │ Cost Estimate│
                    │ bores, threads    │    │ (mfg method +    │    │ (geometry × rates │    │ (per-part    │
                    └───────────────────┘    │  operations)     │    │  + material +     │    │  breakdown)  │
                         AVAILABLE           │                  │    │  tolerances       │    │              │
                                        ┌───→│                  │───→│  → cost)          │───→│              │
                    ┌───────────────────┐│   └──────────────────┘    └───────────────────┘    └──────────────┘
                    │ Drawing           ││        PARTIAL                 MISSING                 MISSING
                    │ Intelligence      ││
                    │ (OCR + AI)        │┘
                    │ Material, tol.,   │
                    │ GD&T, surface Ra  │
                    └────────┬──────────┘
                             │
                    ┌────────┴──────────┐
                    │ PDF Drawing Upload│
                    │ (2D engineering   │
                    │  drawings)        │
                    └───────────────────┘
```

**Two complementary input channels:**
- **STEP files** provide *geometry* (volumes, surfaces, features) — what the part looks like
- **PDF drawings** provide *specifications* (material, tolerances, surface finish, GD&T) — how the part must perform

Neither alone is sufficient for accurate cost estimation. Together, they cover 80-90% of the data needed.

### What's Built vs. What's Missing

| Layer | Status | What Exists | What's Missing |
|-------|--------|-------------|----------------|
| **File Upload** | Partial | `PartDocument` model, file upload utilities | No STEP-specific upload UI on part detail page |
| **Geometry Extraction** | Available | Luminarity API fully specced and tested | No integration code; self-hosted alternative not built |
| **Drawing Intelligence** | **Infrastructure ready** | PyMuPDF, LLM providers, PartDocument, Derivative model | No extraction pipeline; no OCR/AI wiring for uploaded drawings |
| **Process Classification** | Partial | Luminarity returns `master_material_group` (molding/milling/turning) | Operation-level classification (drilling, threading, surface finishing) not automated |
| **Cost Formula Engine** | **Missing** | Nothing | Machine rate tables, cycle time estimation, material cost lookup, overhead allocation |
| **Cost Storage** | Minimal | `Part.part_cost` (single integer) | No multi-dimensional cost breakdown, no cost components |
| **Cost Display** | **Missing** | `rollup_cost()` shows simple tree | No per-operation cost breakdown UI, no "what-if" scenarios |
| **BOM Auto-Population** | **Missing** | BOM explosion engine exists | No assembly → BOM mapping from STEP analysis |

---

## 4. The Cost Formula Problem

This is the hard, valuable, domain-specific part that neither Luminarity nor a self-hosted STEP analyzer solves.

### 4.1 What Cost Formulas Need

To convert geometry into a manufacturing cost estimate, you need **all** of the following:

#### Machine Database
```
Machine:
  - type: CNC_3AXIS_MILL | CNC_5AXIS_MILL | CNC_LATHE | INJECTION_MOLD | ...
  - hourly_rate: €85/hr (includes operator, depreciation, overhead)
  - setup_time_base: 30 min
  - max_workpiece_size: [500, 400, 300] mm
  - capabilities: [milling, drilling, threading, ...]
```

#### Material Database
```
Material:
  - type: ALUMINUM_6061 | STEEL_1045 | ABS_PLASTIC | ...
  - density: 2.71 g/cm³
  - cost_per_kg: €8.50
  - machinability_factor: 1.0  (relative to reference)
  - minimum_order_qty: 1 kg
```

#### Cycle Time Estimation (the hardest part)
```python
def estimate_cycle_time(geometry, material, machine):
    """This is where domain expertise lives."""

    # Rough turning time
    volume_to_remove = geometry.pd_cutting_volume  # from Luminarity
    material_removal_rate = machine.mrr * material.machinability_factor
    rough_time = volume_to_remove / material_removal_rate

    # Finishing time (depends on surface area requiring machining)
    finish_area = geometry.pd_surface_full_part * (geometry.master_machined_areas_percentage / 100)
    finish_time = finish_area / machine.finish_rate

    # Drilling time (per bore)
    drill_time = sum(
        bore.depth / machine.drill_feed_rate(bore.diameter)
        for bore in geometry.master_bore_collection
    )

    # Threading time
    thread_time = geometry.thread_count * machine.thread_time_per_unit

    return rough_time + finish_time + drill_time + thread_time
```

#### Cost Assembly
```python
def calculate_part_cost(geometry, material, machine_pool):
    machine = select_machine(geometry, machine_pool)  # capability + size matching

    material_cost = geometry.pd_volume_raw * material.density * material.cost_per_kg
    setup_cost = machine.setup_time * machine.hourly_rate / 60
    cycle_cost = estimate_cycle_time(geometry, material, machine) * machine.hourly_rate / 60
    overhead = (material_cost + setup_cost + cycle_cost) * company.overhead_rate

    return {
        "material": material_cost,
        "setup": setup_cost,
        "machining": cycle_cost,
        "overhead": overhead,
        "total": material_cost + setup_cost + cycle_cost + overhead,
        "per_unit_at_qty": lambda qty: (material_cost * qty + setup_cost + cycle_cost * qty + overhead) / qty
    }
```

### 4.2 Why This Is Hard

1. **Domain-specific knowledge**: Cycle time estimation requires manufacturing engineering expertise. Feed rates, cutting speeds, tool changes, fixture requirements — these vary by material, machine, and geometry complexity.

2. **Company-specific rates**: Every manufacturer has different machine hourly rates, overhead allocation methods, and margin expectations. The formula engine must be configurable per tenant.

3. **Accuracy expectations**: A rough estimate (±30%) is useful for quoting. A precise estimate (±5%) requires deep process planning. The system must be clear about its accuracy level.

4. **Material selection**: Luminarity doesn't detect material from geometry alone. The user must specify material, or the system must infer from part context/naming conventions. **This is where Drawing Intelligence becomes critical** — PDF drawings typically contain explicit material callouts in the title block or notes.

5. **Quantity dependence**: Setup costs amortize over batch size. A part costing €50 at qty 1 might cost €12 at qty 100. The formula must support quantity-based cost curves.

### 4.3 What Exists in the Market

| Solution | What It Does | Cost Model |
|----------|-------------|------------|
| **aPriori** | Full should-costing platform | Built-in cost models for 50+ manufacturing processes |
| **Costimator** | Parametric cost estimation | Process-based templates with customizable rates |
| **Seer Manufacturing** | Analogy-based estimation | Historical data + parametric models |
| **Luminarity** | Geometry extraction only | None — you bring your own cost formulas |
| **Custom build** | Whatever you implement | Whatever you implement |

The commercial platforms (aPriori, Costimator) have invested years in refining their cost models. This is their core IP, not the geometry extraction.

---

## 5. Drawing Intelligence: OCR & AI Extraction

STEP files provide geometry but are silent on material, tolerances, surface finish, and GD&T — the specifications that drive 30-60% of manufacturing cost. These live on **2D engineering drawings** (PDF, TIFF, scanned paper). A Drawing Intelligence layer extracts this structured data automatically.

### 5.1 What Needs to Be Extracted from Drawings

| Data Category | Examples | Cost Impact |
|---------------|----------|-------------|
| **Material** | "AL 6061-T6", "S355J2", "ABS Ultramid" | Determines raw material cost, machinability factor, density |
| **Dimensional tolerances** | ±0.05 mm, H7/g6 fit class | Tighter tolerances → slower feeds, more passes, higher cost |
| **GD&T (Geometric Dimensioning & Tolerancing)** | Flatness 0.02, Position ⌀0.1 M | Additional operations (grinding, lapping), inspection cost |
| **Surface finish** | Ra 0.8, Ra 3.2, N6 | Dictates finishing operations (grinding vs. milling vs. polishing) |
| **Heat treatment** | "Hardened to 58-62 HRC", "Annealed" | Adds outsourced process cost + lead time |
| **Surface coating** | "Anodize Type III", "Zinc plated", "Powder coat RAL 7035" | Outsourced process cost based on surface area |
| **Thread specifications** | M8×1.25-6H, 1/4"-20 UNC-2B | Validates geometry-detected threads, adds tapping cost |
| **Weld symbols** | Fillet weld, groove weld, spot weld | Assembly cost driver |
| **Part list / BOM table** | Item, qty, material, part number | Auto-populate BOM from drawing BOM table |
| **Title block** | Drawing number, revision, weight, scale | Metadata for traceability |

### 5.2 Approach: Vision LLM (Recommended over Traditional OCR)

Traditional OCR pipelines (Tesseract, EasyOCR) struggle with engineering drawings because:
- Text is mixed with dimension lines, leaders, and symbols
- GD&T uses special symbols (⌀, ⊥, ∥, ○, △) not in standard OCR training sets
- Orientation varies (rotated text along dimensions, mirrored in section views)
- Scanned drawings add noise, skew, and resolution issues

**Modern vision-language models (VLMs)** handle this natively:
- GPT-4o, Claude 3.5 Sonnet, Gemini Pro Vision can directly interpret engineering drawings
- No OCR preprocessing needed — the model "reads" the image holistically
- Can understand context: "the material callout is in the title block, bottom right"
- Can be prompted for structured JSON output
- Already integrated in RattleApp via `llm_provider.py`

### 5.3 Framework Options Assessment

| Framework | Type | Accuracy | Key Strengths | Effort to Integrate |
|-----------|------|----------|---------------|---------------------|
| **VLM-based (GPT-4o / Claude)** | API | High for structured data; context-aware | Zero new dependencies; uses existing `llm_provider.py`; handles scanned drawings | **Low** — prompt engineering + JSON schema |
| **Werk24** | Commercial API | >95% PMI accuracy | Purpose-built for engineering drawings; normalized JSON output; no training needed | Medium — new vendor integration |
| **eDOCr2** | Open-source | 93.75% recall, <1% CER | Segments drawings into regions (title block, dimensions, FCF); VLM post-processing | High — Python library, requires Qwen2-VL or GPT-4o |
| **YOLOv11 + Donut** | Research | 97.3% F1 (GD&T) | 9 extraction categories; best accuracy on GD&T specifically | Very High — requires training data, GPU, model hosting |
| **Mistral OCR** | API | Good for documents | Strong on structured documents, tables, multilingual | Low — API call, but not specialized for engineering drawings |
| **PyMuPDF text extraction** | Library | Varies | Already installed; works well on vector PDFs (not scanned) | **Minimal** — 3 lines of code for text-based PDFs |

**Recommended two-tier approach:**

1. **Tier 1 (fast, cheap):** PyMuPDF text extraction for vector PDFs → regex/rule-based parsing for title block, material, basic dimensions. Handles 60-70% of modern CAD-generated drawings.

2. **Tier 2 (powerful, slower):** VLM-based extraction (GPT-4o or Claude) for scanned drawings, complex GD&T, or when Tier 1 extraction confidence is low. Render PDF pages to images via PyMuPDF, send to vision model with structured output prompt.

### 5.4 What the Extraction Pipeline Produces

```json
{
  "drawing_analysis": {
    "source": "vlm_gpt4o",
    "confidence": 0.87,
    "analyzed_at": "2026-02-19T17:30:00",

    "title_block": {
      "drawing_number": "DRW-2024-0847",
      "revision": "C",
      "scale": "1:2",
      "material": "AL 6061-T6",
      "weight_kg": 0.34,
      "surface_treatment": "Anodize Type III Black",
      "general_tolerance": "ISO 2768-mK"
    },

    "material": {
      "designation": "AL 6061-T6",
      "standard": "AMS-QQ-A-250/11",
      "matched_material_code": "AL_6061"
    },

    "tolerances": {
      "general_class": "ISO 2768-mK",
      "tightest_linear": 0.02,
      "tightest_angular": 0.5,
      "critical_dimensions": [
        {"feature": "bore diameter", "nominal": 25.0, "tolerance": "H7 (+0.021/+0.000)"},
        {"feature": "length", "nominal": 120.0, "tolerance": "±0.05"}
      ]
    },

    "gdt_frames": [
      {"type": "position", "value": 0.1, "modifier": "MMC", "datum_refs": ["A", "B", "C"]},
      {"type": "flatness", "value": 0.02, "feature": "top surface"}
    ],

    "surface_finish": {
      "default_ra": 3.2,
      "critical_surfaces": [
        {"feature": "bore ID", "ra": 0.8},
        {"feature": "mounting face", "ra": 1.6}
      ]
    },

    "secondary_processes": [
      {"type": "heat_treatment", "spec": "Hardened to 58-62 HRC"},
      {"type": "coating", "spec": "Anodize Type III Black per MIL-A-8625"}
    ],

    "bom_table": [
      {"item": 1, "part_number": "PIN-0012", "material": "AISI 304", "qty": 4},
      {"item": 2, "part_number": "SEAL-0089", "material": "NBR 70 Shore", "qty": 2}
    ]
  }
}
```

### 5.5 How Drawing Data Improves Cost Estimates

| Without Drawing Intelligence | With Drawing Intelligence | Cost Impact |
|------------------------------|--------------------------|-------------|
| User manually selects material | Auto-detected from title block → matched to MaterialType table | Correct material cost; correct machinability factor |
| Default tolerance assumptions | Actual tolerance class extracted → tolerance cost multiplier | ±30% cost swing on tight-tolerance parts |
| No surface finish data | Ra values extracted per surface → finishing operation selection | Adds/removes grinding, lapping, polishing operations |
| No secondary processes | Heat treatment, coating detected → outsourced process costs added | 10-40% of total cost for treated parts |
| No GD&T awareness | GD&T frames → additional inspection cost + tighter machining | 5-15% cost adder for complex GD&T |
| Manual BOM entry | BOM table extracted from drawing → auto-populate BomItems | Time savings; prevents data entry errors |

### 5.6 Implementation: VLM-Based Drawing Analyzer

```python
# app/utils/drawing_analyzer.py

import pymupdf as fitz
from app.utils.llm_provider import resolve_llm_for_feature

DRAWING_EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "title_block": { ... },
        "material": { ... },
        "tolerances": { ... },
        "gdt_frames": { ... },
        "surface_finish": { ... },
        "secondary_processes": { ... },
        "bom_table": { ... },
    }
}

DRAWING_SYSTEM_PROMPT = """You are an expert manufacturing engineer analyzing a 2D engineering drawing.
Extract ALL of the following structured information from the drawing image(s).
Return ONLY valid JSON matching the provided schema.
If a field is not visible or not applicable, use null.
Pay special attention to:
- Title block (usually bottom-right): material, drawing number, revision, tolerances
- GD&T feature control frames: geometric tolerance symbols and values
- Surface finish symbols (Ra/Rz values or N-class)
- Notes section: heat treatment, coating, special instructions
- BOM/parts list table if present"""


def analyze_drawing_pdf(file_path: str, company) -> dict:
    """Extract structured manufacturing data from a PDF engineering drawing."""

    doc = fitz.open(file_path)
    extraction_result = {}

    # Tier 1: Try text extraction first (fast, cheap, works for vector PDFs)
    full_text = ""
    for page in doc:
        full_text += page.get_text()

    tier1_result = _extract_from_text(full_text)
    if tier1_result and tier1_result.get("confidence", 0) > 0.8:
        return tier1_result

    # Tier 2: VLM-based extraction (for scanned drawings or low-confidence text)
    page_images = []
    for page_num in range(min(len(doc), 4)):  # limit to first 4 pages
        pix = doc[page_num].get_pixmap(dpi=200)  # 200 DPI balances quality vs. token cost
        img_bytes = pix.tobytes("png")
        page_images.append(img_bytes)

    provider, model = resolve_llm_for_feature(company, "drawing_analysis")
    result = _call_vlm(provider, model, page_images, DRAWING_SYSTEM_PROMPT)

    # Match extracted material to company's MaterialType table
    if result.get("material", {}).get("designation"):
        result["material"]["matched_material_code"] = _match_material(
            result["material"]["designation"], company.id
        )

    return result


def _extract_from_text(text: str) -> dict | None:
    """Tier 1: Regex/rule-based extraction from PDF text layer."""
    import re

    result = {"source": "text_extraction", "confidence": 0.0}
    found_fields = 0

    # Material detection (common patterns)
    mat_patterns = [
        r"(?:Material|Werkstoff|Mat\.?)[\s:]+([A-Z0-9][A-Za-z0-9\s\-/\.]+)",
        r"((?:AISI|AMS|DIN|EN)\s*[\w\-\.]+)",
        r"(AL\s*\d{4}[\-\w]*)",
        r"(S\d{3}\w*)",
        r"(1\.\d{4})",  # DIN material numbers
    ]
    for pat in mat_patterns:
        m = re.search(pat, text)
        if m:
            result["material"] = {"designation": m.group(1).strip()}
            found_fields += 1
            break

    # General tolerance class
    tol_match = re.search(r"ISO\s*2768[\-\s]*([fmcv]?[HKLM]?)", text, re.IGNORECASE)
    if tol_match:
        result["tolerances"] = {"general_class": f"ISO 2768-{tol_match.group(1)}"}
        found_fields += 1

    # Surface finish
    ra_matches = re.findall(r"Ra\s*([\d.,]+)", text)
    if ra_matches:
        ra_values = [float(v.replace(",", ".")) for v in ra_matches]
        result["surface_finish"] = {"default_ra": min(ra_values)}
        found_fields += 1

    result["confidence"] = min(found_fields / 3, 1.0)  # 3 fields = full confidence
    return result if found_fields > 0 else None


def _call_vlm(provider: str, model: str, images: list[bytes], prompt: str) -> dict:
    """Call a vision-language model with drawing page images."""
    # Implementation depends on provider (OpenAI vs Anthropic vs Gemini)
    # All support image input in their chat/messages API
    # Returns parsed JSON matching DRAWING_EXTRACTION_SCHEMA
    ...


def _match_material(designation: str, company_id: int) -> str | None:
    """Fuzzy-match extracted material designation to company's MaterialType table."""
    from app.models import MaterialType
    # Try exact match first, then normalized match, then similarity
    ...
```

---

## 6. Build vs. Buy Assessment

### 6.1 Geometry Extraction Layer

| Factor | Self-Hosted (PythonOCC/OpenCascade) | Luminarity API |
|--------|--------------------------------------|----------------|
| **Setup effort** | High — C++ bindings, Docker, GPU optional | Zero — HTTP API, already tested |
| **Maintenance** | Ongoing — CAD kernel updates, format support | Vendor-managed |
| **Supported formats** | STEP, IGES (with effort: BREP, others) | STEP only (confirmed) |
| **Feature extraction quality** | Must implement all 47+ features yourself | 47+ features out of the box, battle-tested |
| **Assembly handling** | Must implement BOM decomposition | Built-in multi-component extraction |
| **Processing speed** | ~2-12s depending on hardware | 2-37s (tested, cloud-hosted) |
| **Cost** | Server hosting (~€50-200/mo) | Per-query API pricing (TBD with vendor) |
| **Data sovereignty** | Full control — files never leave your infra | Files sent to third-party server |
| **Offline capability** | Yes | No — requires internet |
| **Vendor dependency** | None | Single vendor risk |

**Recommendation:** Start with Luminarity API. It's already tested, returns rich data, and requires zero geometry processing expertise. Consider self-hosted only if: (a) data sovereignty is a hard requirement, (b) API costs become prohibitive at scale, or (c) you need formats beyond STEP.

### 6.2 Cost Formula Engine

| Factor | Build In-House | Integrate aPriori/Commercial |
|--------|----------------|------------------------------|
| **Time to value** | 3-6 months for rough estimates | Weeks (integration work only) |
| **Accuracy** | Low initially, improves with tuning | High out of the box |
| **Customizability** | Full control | Limited to vendor's model |
| **Cost** | Engineering time | License fees (€50K-200K+/year) |
| **Domain expertise required** | Significant | Minimal |
| **Competitive moat** | Yes, if well-built | No — commodity capability |

**Recommendation:** Build a simple, configurable formula engine in-house. Start with rough estimates (±30%) using basic formulas. This gives immediate value for quoting and can be refined over time. The formulas themselves become a competitive advantage.

### 6.3 Drawing Intelligence Layer

| Factor | VLM-Based (GPT-4o / Claude) | Werk24 (Commercial API) | eDOCr2 + VLM (Open Source) |
|--------|------------------------------|------------------------|----------------------------|
| **Setup effort** | Minimal — prompt + JSON schema | Medium — vendor integration | High — install library, configure pipeline |
| **New dependencies** | None — existing `llm_provider.py` | New vendor | eDOCr2 + OpenCV + optional YOLO model |
| **Cost per drawing** | ~$0.02-0.08 (1-4 pages × GPT-4o vision) | Per-query API pricing (TBD) | Free (compute only) |
| **Accuracy: material** | Good (90%+) — text-based, context-aware | Excellent (>95%) | Good — depends on VLM post-processing |
| **Accuracy: GD&T** | Good for simple, moderate for complex FCFs | Excellent — purpose-built | Best research accuracy (97.3% F1 with YOLO+Donut) |
| **Accuracy: tolerances** | Good — can read dimension text | Excellent — normalized + classified | Good — segmentation helps |
| **Scanned drawings** | Yes — vision models handle noise | Yes | Partial — needs clean input |
| **Multilingual** | Yes — all major VLMs are multilingual | Yes (EN/DE confirmed) | Limited |
| **Data sovereignty** | Data sent to LLM provider | Data sent to Werk24 | Fully self-hosted possible |
| **Maintenance** | Model updates automatic | Vendor-managed | Self-maintained |

**Recommendation:** Start with VLM-based extraction (Tier 1 text + Tier 2 GPT-4o vision). Zero new dependencies, leverages existing AI infrastructure, handles both vector and scanned PDFs. Evaluate Werk24 if GD&T accuracy becomes critical for a specific customer segment.

---

## 7. Technical Implementation Plan

### 7.1 Architecture (When Ready to Build)

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                           RattleApp (Flask)                                   │
│                                                                              │
│  ┌─────────────┐  ┌───────────────────┐  ┌────────────────────┐             │
│  │ Part Detail  │  │ Celery Tasks      │  │ Cost Formula       │             │
│  │ UI          │  │                   │  │ Engine             │             │
│  │             │  │ analyze_step_     │  │                    │             │
│  │ [Upload     │──│ file()            │──│ calculate_cost()   │             │
│  │  STEP]      │  │                   │  │                    │             │
│  │             │  │ 1. Upload         │  │ Machine DB         │             │
│  │ [Upload     │──│ 2. Poll           │  │ Material DB        │             │
│  │  Drawing]   │  │ 3. Store geometry │  │ Rate Tables        │             │
│  │             │  │                   │  │ Cycle Time Est.    │             │
│  │ [View       │  │ analyze_drawing() │  │ Tolerance Factors  │             │
│  │  Analysis]  │──│                   │──│ Surface Finish     │             │
│  │             │  │ 1. Text extract   │  │ Secondary Process  │             │
│  │ [Cost       │  │ 2. VLM fallback   │  │ Overhead Rules     │             │
│  │  Breakdown] │  │ 3. Store specs    │  │                    │             │
│  └─────────────┘  │ 4. Match material │  └────────────────────┘             │
│                   │ 5. Re-calculate   │                                      │
│                   └────────┬──────────┘                                      │
│                            │                                                 │
│              ┌─────────────┴─────────────┐                                   │
│              │                           │                                   │
│              ▼                           ▼                                   │
│  ┌──────────────────────┐   ┌──────────────────────┐                        │
│  │ Geometry Provider    │   │ Drawing Analyzer     │                        │
│  │ (interface)          │   │ (interface)          │                        │
│  ├──────────────────────┤   ├──────────────────────┤                        │
│  │ LuminarityProvider   │   │ Tier 1: PyMuPDF text │                        │
│  │ SelfHostedProvider   │   │ Tier 2: VLM vision   │                        │
│  └──────────────────────┘   │ (Werk24 optional)    │                        │
│                             └──────────────────────┘                        │
└──────────────────────────────────────────────────────────────────────────────┘
```

### 7.2 Data Model Extensions

```python
# New: Machine rate table (per company)
class MachineType(db.Model):
    company_id      = db.Column(db.Integer, db.ForeignKey('companies.id'))
    name            = db.Column(db.String(100))       # "CNC 3-Axis Mill"
    machine_code    = db.Column(db.String(50))         # "CNC_3AXIS_MILL"
    hourly_rate     = db.Column(db.Numeric(10, 2))     # €/hr
    setup_time_min  = db.Column(db.Integer)             # minutes
    max_dimensions  = db.Column(JSON_TYPE)              # [x, y, z] mm
    capabilities    = db.Column(JSON_TYPE)              # ["milling", "drilling", ...]

# New: Material cost table (per company)
class MaterialType(db.Model):
    company_id      = db.Column(db.Integer, db.ForeignKey('companies.id'))
    name            = db.Column(db.String(100))        # "Aluminum 6061"
    material_code   = db.Column(db.String(50))          # "AL_6061"
    density         = db.Column(db.Numeric(8, 4))       # g/cm³
    cost_per_kg     = db.Column(db.Numeric(10, 2))      # €/kg
    machinability   = db.Column(db.Numeric(4, 2))       # factor (1.0 = reference)

# New: Geometry analysis result (per part)
class PartGeometryAnalysis(db.Model):
    part_id         = db.Column(db.Integer, db.ForeignKey('parts.id'), unique=True)
    source          = db.Column(db.String(50))          # "luminarity" | "self_hosted"
    source_ref      = db.Column(db.String(255))         # filenameServer or job ID
    material_group  = db.Column(db.String(50))          # "turning", "milling", etc.
    confidence      = db.Column(db.Numeric(4, 2))
    raw_parameters  = db.Column(JSON_TYPE)              # full 47+ field response
    # Denormalized key fields for query/formula use:
    volume_mm3      = db.Column(db.Numeric(14, 2))
    surface_mm2     = db.Column(db.Numeric(14, 2))
    cutting_volume  = db.Column(db.Numeric(14, 2))
    machined_pct    = db.Column(db.Numeric(5, 2))
    bore_count      = db.Column(db.Integer)
    thread_count    = db.Column(db.Integer)
    bbox_x          = db.Column(db.Numeric(10, 2))
    bbox_y          = db.Column(db.Numeric(10, 2))
    bbox_z          = db.Column(db.Numeric(10, 2))
    analyzed_at     = db.Column(db.DateTime)
    status          = db.Column(db.String(20))          # "pending", "done", "error"

# New: Cost estimate result (per part + material + quantity)
class PartCostEstimate(db.Model):
    part_id         = db.Column(db.Integer, db.ForeignKey('parts.id'))
    material_id     = db.Column(db.Integer, db.ForeignKey('material_types.id'))
    quantity        = db.Column(db.Integer)
    material_cost   = db.Column(db.Numeric(10, 2))
    setup_cost      = db.Column(db.Numeric(10, 2))
    machining_cost  = db.Column(db.Numeric(10, 2))
    overhead_cost   = db.Column(db.Numeric(10, 2))
    total_cost      = db.Column(db.Numeric(10, 2))
    unit_cost       = db.Column(db.Numeric(10, 2))
    machine_type_id = db.Column(db.Integer, db.ForeignKey('machine_types.id'))
    estimated_at    = db.Column(db.DateTime)
    formula_version = db.Column(db.String(20))          # track formula changes

# New: Drawing analysis result (per part document)
class PartDrawingAnalysis(db.Model):
    part_id         = db.Column(db.Integer, db.ForeignKey('parts.id'))
    document_id     = db.Column(db.Integer, db.ForeignKey('part_documents.id'))
    source          = db.Column(db.String(50))          # "text_extraction" | "vlm_gpt4o" | "werk24"
    confidence      = db.Column(db.Numeric(4, 2))
    raw_extraction  = db.Column(JSON_TYPE)              # full extraction result
    # Denormalized key fields for cost formula use:
    material_designation = db.Column(db.String(100))    # "AL 6061-T6"
    matched_material_id  = db.Column(db.Integer, db.ForeignKey('material_types.id'))
    general_tolerance    = db.Column(db.String(50))     # "ISO 2768-mK"
    tightest_tolerance   = db.Column(db.Numeric(8, 4))  # mm
    default_surface_ra   = db.Column(db.Numeric(6, 2))  # µm
    tightest_surface_ra  = db.Column(db.Numeric(6, 2))  # µm
    has_heat_treatment   = db.Column(db.Boolean, default=False)
    has_coating          = db.Column(db.Boolean, default=False)
    secondary_processes  = db.Column(JSON_TYPE)          # [{"type": "...", "spec": "..."}]
    gdt_complexity_score = db.Column(db.Integer)         # 0-10 composite score
    analyzed_at     = db.Column(db.DateTime)
    status          = db.Column(db.String(20))           # "pending", "done", "error"
```

### 7.3 Celery Task (Geometry + Cost Pipeline)

```python
# app/tasks.py — new task
@celery.task(bind=True, max_retries=10, default_retry_delay=5)
def analyze_step_file(self, part_id: int, file_path: str, material_id: int = None):
    """Upload STEP file to geometry provider, poll for results, calculate cost."""

    part = Part.query.get(part_id)
    company = part.company

    # Step 1: Upload to geometry provider
    provider = get_geometry_provider(company)  # Luminarity or self-hosted
    job_id = provider.upload(file_path)

    # Step 2: Poll for completion (with exponential backoff via Celery retry)
    status = provider.check_status(job_id)
    if status in ("IN_QUEUE", "MINING"):
        raise self.retry(countdown=min(5 * (2 ** self.request.retries), 60))

    if status != "DONE":
        # Store error state
        update_analysis_status(part_id, "error", error=status)
        return

    # Step 3: Fetch and store geometry results
    geometry = provider.get_result(job_id)
    store_geometry_analysis(part_id, geometry)

    # Step 4: Calculate cost (if material specified and formulas configured)
    if material_id and company_has_cost_formulas(company.id):
        estimate = calculate_manufacturing_cost(part_id, material_id)
        store_cost_estimate(part_id, material_id, estimate)

        # Step 5: Optionally update Part.part_cost with the estimate
        if company.ai_settings.get("auto_update_part_cost"):
            part.part_cost = int(estimate["unit_cost"] * 100)  # cents
            db.session.commit()
```

### 7.4 Celery Task (Drawing Analysis Pipeline)

```python
# app/tasks.py — new task
@celery.task(bind=True, max_retries=3, default_retry_delay=10)
def analyze_drawing(self, part_id: int, document_id: int):
    """Extract structured manufacturing specs from a PDF engineering drawing."""

    from app.utils.drawing_analyzer import analyze_drawing_pdf

    part = Part.query.get(part_id)
    doc = PartDocument.query.get(document_id)
    cad_file = doc.links[0].cad_file  # get the actual file

    file_path = protected_upload_path(part.company_id, cad_file.filename)

    try:
        result = analyze_drawing_pdf(file_path, part.company)

        # Store analysis
        analysis = PartDrawingAnalysis(
            part_id=part_id,
            document_id=document_id,
            source=result.get("source", "vlm"),
            confidence=result.get("confidence"),
            raw_extraction=result,
            material_designation=result.get("material", {}).get("designation"),
            general_tolerance=result.get("tolerances", {}).get("general_class"),
            tightest_tolerance=result.get("tolerances", {}).get("tightest_linear"),
            default_surface_ra=result.get("surface_finish", {}).get("default_ra"),
            has_heat_treatment=any(
                p["type"] == "heat_treatment"
                for p in result.get("secondary_processes", [])
            ),
            has_coating=any(
                p["type"] == "coating"
                for p in result.get("secondary_processes", [])
            ),
            secondary_processes=result.get("secondary_processes"),
            status="done",
            analyzed_at=datetime.utcnow(),
        )
        db.session.add(analysis)

        # Auto-match material to company's MaterialType table
        if result.get("material", {}).get("matched_material_code"):
            mat = MaterialType.query.filter_by(
                company_id=part.company_id,
                material_code=result["material"]["matched_material_code"],
            ).first()
            if mat:
                analysis.matched_material_id = mat.id

        db.session.commit()

        # Re-calculate cost if geometry analysis also exists
        geo = PartGeometryAnalysis.query.filter_by(part_id=part_id).first()
        if geo and analysis.matched_material_id:
            recalculate_with_drawing_data.delay(part_id)

    except Exception as exc:
        db.session.rollback()
        PartDrawingAnalysis.query.filter_by(
            part_id=part_id, document_id=document_id
        ).update({"status": "error"})
        db.session.commit()
        raise self.retry(exc=exc)
```

### 7.5 Geometry Provider Interface

```python
# app/utils/geometry_provider.py
class GeometryProvider(Protocol):
    def upload(self, file_path: str) -> str: ...          # returns job_id
    def check_status(self, job_id: str) -> str: ...       # returns status string
    def get_result(self, job_id: str) -> dict: ...        # returns geometry dict

class LuminarityProvider:
    """Wraps the Luminarity Shouldcosting API."""
    BASE_URL = "https://api2.shouldcosting.com"

    def __init__(self, customer_id: str, cm_xml: str = "luminarity_rsa"):
        self.customer_id = customer_id
        self.cm_xml = cm_xml

    def upload(self, file_path: str) -> str:
        with open(file_path, "rb") as f:
            file_b64 = base64.b64encode(f.read()).decode()
        ext = Path(file_path).suffix  # ".stp" or ".step"
        resp = requests.post(f"{self.BASE_URL}/api/costchecker", json={
            "cmXml": self.cm_xml,
            "customerID": self.customer_id,
            "fileExtension": ext,
            "file": file_b64,
        })
        return resp.json()["filenameServer"]

    def check_status(self, job_id: str) -> str:
        resp = requests.get(f"{self.BASE_URL}/api/costchecker/{job_id}")
        return resp.json()["status"]

    def get_result(self, job_id: str) -> dict:
        resp = requests.get(f"{self.BASE_URL}/api/costchecker/miningresult/{job_id}")
        data = resp.json()
        # Normalize to internal format
        return self._normalize(data)
```

### 7.6 Cost Formula Engine (Configurable Per Tenant)

```python
# app/utils/cost_formula_engine.py
def calculate_manufacturing_cost(
    part_id: int,
    material_id: int,
    quantity: int = 1,
) -> dict:
    """Calculate estimated manufacturing cost from geometry + rates."""

    analysis = PartGeometryAnalysis.query.filter_by(part_id=part_id).first()
    material = MaterialType.query.get(material_id)
    company_id = Part.query.get(part_id).company_id

    # Select appropriate machine based on material_group + dimensions
    machine = select_machine(
        company_id=company_id,
        material_group=analysis.material_group,
        bbox=[analysis.bbox_x, analysis.bbox_y, analysis.bbox_z],
    )

    # Material cost
    volume_cm3 = float(analysis.volume_mm3) / 1000  # mm³ → cm³
    raw_volume_cm3 = float(analysis.raw_parameters.get("pd_volume_raw", analysis.volume_mm3)) / 1000
    weight_kg = raw_volume_cm3 * float(material.density) / 1000  # g → kg
    mat_cost = weight_kg * float(material.cost_per_kg)

    # Setup cost (fixed per batch, amortized over quantity)
    setup_cost = float(machine.setup_time_min) / 60 * float(machine.hourly_rate)

    # Machining cost (rough estimate from cutting volume + surface finishing)
    cutting_vol_cm3 = float(analysis.cutting_volume or 0) / 1000
    base_mrr_cm3_per_min = 5.0  # configurable: material removal rate
    adjusted_mrr = base_mrr_cm3_per_min * float(material.machinability)

    rough_time_min = cutting_vol_cm3 / adjusted_mrr if adjusted_mrr > 0 else 0

    # Surface finishing (proportional to machined surface area)
    machined_area_cm2 = float(analysis.surface_mm2 or 0) * float(analysis.machined_pct or 0) / 100 / 100
    finish_rate_cm2_per_min = 20.0  # configurable
    finish_time_min = machined_area_cm2 / finish_rate_cm2_per_min

    # Hole operations
    hole_time_min = float(analysis.bore_count or 0) * 0.5  # configurable: min per bore
    thread_time_min = float(analysis.thread_count or 0) * 1.0  # configurable: min per thread

    total_cycle_min = rough_time_min + finish_time_min + hole_time_min + thread_time_min
    machining_cost = total_cycle_min / 60 * float(machine.hourly_rate)

    # ── Drawing-derived cost adjustments (when drawing analysis exists) ──
    drawing = PartDrawingAnalysis.query.filter_by(part_id=part_id, status="done").first()
    tolerance_multiplier = 1.0
    surface_finish_cost = 0.0
    secondary_process_cost = 0.0

    if drawing:
        # Tolerance cost multiplier (tighter = more expensive)
        if drawing.tightest_tolerance:
            tol = float(drawing.tightest_tolerance)
            if tol <= 0.01:
                tolerance_multiplier = 1.8   # grinding/lapping territory
            elif tol <= 0.05:
                tolerance_multiplier = 1.3   # precision machining
            elif tol <= 0.1:
                tolerance_multiplier = 1.1   # standard CNC

        # Surface finish cost (additional operations)
        if drawing.tightest_surface_ra:
            ra = float(drawing.tightest_surface_ra)
            if ra <= 0.4:
                surface_finish_cost = float(machine.hourly_rate) * 0.5  # lapping
            elif ra <= 0.8:
                surface_finish_cost = float(machine.hourly_rate) * 0.25  # grinding
            elif ra <= 1.6:
                surface_finish_cost = float(machine.hourly_rate) * 0.1   # fine milling

        # Secondary process costs (outsourced, area-based)
        for proc in (drawing.secondary_processes or []):
            if proc["type"] == "heat_treatment":
                secondary_process_cost += weight_kg * 8.0   # configurable €/kg
            elif proc["type"] == "coating":
                area_m2 = float(analysis.surface_mm2 or 0) / 1e6
                secondary_process_cost += area_m2 * 45.0    # configurable €/m²

    # Apply tolerance multiplier to machining cost
    machining_cost *= tolerance_multiplier

    # Overhead
    overhead_rate = 0.15  # configurable per company
    subtotal = mat_cost + machining_cost + surface_finish_cost + secondary_process_cost
    overhead_cost = subtotal * overhead_rate

    # Batch economics
    per_unit = mat_cost + machining_cost + surface_finish_cost + secondary_process_cost + overhead_cost
    total_batch = (per_unit * quantity) + setup_cost
    unit_cost = total_batch / quantity

    return {
        "material_cost": round(mat_cost, 2),
        "setup_cost": round(setup_cost, 2),
        "machining_cost": round(machining_cost, 2),
        "surface_finish_cost": round(surface_finish_cost, 2),
        "secondary_process_cost": round(secondary_process_cost, 2),
        "tolerance_multiplier": tolerance_multiplier,
        "overhead_cost": round(overhead_cost, 2),
        "cycle_time_min": round(total_cycle_min, 2),
        "total_batch_cost": round(total_batch, 2),
        "unit_cost": round(unit_cost, 2),
        "quantity": quantity,
        "machine_type": machine.name,
        "material": material.name,
        "drawing_data_used": drawing is not None,
    }
```

---

## 8. Phased Roadmap

### Phase 0: Cost Formula MVP (Prerequisite)
**Goal:** Enable cost calculation from manually entered geometry parameters.
**Effort:** 2-3 weeks
**Value:** Immediate — users can estimate costs for parts without CAD automation.

| Task | Details |
|------|---------|
| Create `MachineType` model + migration | Per-company machine rate table |
| Create `MaterialType` model + migration | Per-company material cost table |
| Build cost formula engine | `calculate_manufacturing_cost()` with configurable rates |
| Admin UI for machine/material tables | CRUD pages under company settings |
| Part detail: manual geometry input | Form fields for key parameters (volume, surface area, bore count) |
| Part detail: cost estimate display | Show breakdown (material + setup + machining + overhead) |
| Update `rollup_cost()` | Use formula-based `part_cost` in BOM rollup |

**Exit criteria:** A user can enter machine rates, material costs, and part geometry, and see a cost breakdown. No CAD file required.

### Phase 1: Luminarity Integration
**Goal:** Automate geometry extraction from STEP files.
**Effort:** 1-2 weeks
**Dependency:** Phase 0 complete (formulas exist to consume geometry data).

| Task | Details |
|------|---------|
| Create `PartGeometryAnalysis` model + migration | Store extracted geometry per part |
| Implement `LuminarityProvider` | HTTP client wrapping the 3 API calls |
| Celery task: `analyze_step_file()` | Upload → poll → store → calculate pipeline |
| Part detail: STEP upload button | File upload triggering async analysis |
| Part detail: analysis status display | Show pending/done/error + geometry summary |
| Company settings: Luminarity config | API key (`customerID`), auto-cost toggle |
| Connector alternative | Optionally implement as ExchangeTask with steps |

**Exit criteria:** User uploads a STEP file, geometry is extracted automatically, cost estimate updates within seconds.

### Phase 1B: Drawing Intelligence (Can Run in Parallel with Phase 1)
**Goal:** Extract material, tolerances, surface finish, and secondary processes from PDF drawings.
**Effort:** 2-3 weeks
**Dependency:** Phase 0 complete (material/machine tables exist to match against).

| Task | Details |
|------|---------|
| Create `PartDrawingAnalysis` model + migration | Store extracted specs per part/document |
| Implement Tier 1: PyMuPDF text extraction | `fitz.open()` + regex parsing for material, tolerance class, Ra values |
| Implement Tier 2: VLM-based extraction | Page → image → GPT-4o/Claude vision with structured JSON output |
| Drawing extraction prompt engineering | JSON schema + system prompt optimized for engineering drawings |
| Material matching engine | Fuzzy-match extracted designations (e.g., "AL 6061-T6") to `MaterialType` table |
| Celery task: `analyze_drawing()` | Upload → extract → match → store → re-calculate pipeline |
| Part detail: drawing upload trigger | Button on PartDocument list to "Analyze this drawing" |
| Part detail: drawing specs display | Show extracted material, tolerances, surface finish, processes |
| Company settings: drawing analysis config | LLM provider/model selection, auto-analyze toggle |
| Cost formula: tolerance/finish multipliers | Integrate `PartDrawingAnalysis` into `calculate_manufacturing_cost()` |

**Exit criteria:** User uploads a PDF drawing, system extracts material + tolerances + surface finish, cost estimate improves by incorporating tolerance multipliers and secondary process costs.

**Why parallel with Phase 1:** Drawing intelligence requires zero external geometry APIs — only PyMuPDF (installed) and the existing LLM infrastructure. It can be built and tested independently. When both Phase 1 (STEP) and 1B (Drawing) are complete, the cost formula engine automatically combines both data sources.

### Phase 2: Enrichment & Accuracy
**Goal:** Improve cost estimate accuracy and usability.
**Effort:** 2-4 weeks
**Dependency:** Phase 1 complete (geometry data flowing).

| Task | Details |
|------|---------|
| Quantity-based cost curves | Show cost at qty 1, 10, 100, 1000 |
| Material auto-suggestion | Infer from part name/category or let user select |
| Assembly → BOM auto-population | Multi-component STEP → create child Parts + BomItems |
| Cost comparison view | Side-by-side: manual vs. calculated vs. quoted price |
| Formula refinement UI | Let users tune rates and see impact in real-time |
| Audit trail | Track formula version, parameter changes, re-estimates |
| `PartCostEstimate` model | Store estimates per material+quantity combination |
| Drawing: GD&T complexity scoring | Composite score from feature control frames → inspection cost adder |
| Drawing: BOM table extraction | Auto-populate BomItems from parts list table in drawing |
| Drawing: batch analysis | Analyze all existing PartDocuments of type "Drawing"/"PDF" for a product |
| Drawing: Werk24 integration (optional) | Commercial API for higher GD&T accuracy if needed |
| Xometry RFQ API integration | External instant quotes via `developer.xometry.com` REST API for make-or-buy comparison |
| Make-or-buy comparison view | Side-by-side: internal should-cost vs. Xometry external quote on Part detail page |

### Phase 3: Self-Hosted Option (Optional)
**Goal:** Remove Luminarity dependency for data-sovereign customers.
**Effort:** 4-8 weeks
**Dependency:** Phases 0-1 complete; proven demand for self-hosted.

| Task | Details |
|------|---------|
| Docker microservice with PythonOCC | STEP → geometry extraction via OpenCascade |
| Feature parity with Luminarity fields | Extract volume, surface area, bounding box, bore detection |
| `SelfHostedProvider` implementation | Same interface as `LuminarityProvider` |
| Company settings: provider selection | Toggle between Luminarity and self-hosted |
| Performance benchmarking | Compare accuracy and speed against Luminarity |

---

## 9. Decision Framework

### When to Start Building

Start **Phase 0** (cost formula MVP) when:
- [ ] At least 2-3 customers have expressed need for automated cost estimation
- [ ] You have access to manufacturing engineering knowledge (internal or consultant) to validate formulas
- [ ] The manual cost entry workflow (`Part.part_cost`) is a confirmed bottleneck for customers

Start **Phase 1** (Luminarity integration) when:
- [ ] Phase 0 is complete and formula-based costs are delivering value
- [ ] Customers are entering geometry parameters manually and want automation
- [ ] Luminarity pricing terms are acceptable

Start **Phase 1B** (drawing intelligence) when:
- [ ] Phase 0 is complete (material/machine tables exist)
- [ ] Customers have PDF drawings attached to parts and want auto-extraction
- [ ] Material selection is a frequent manual step that could be automated
- [ ] Note: Can start *before* Phase 1 — drawing intelligence has zero external dependencies

Start **Phase 3** (self-hosted) when:
- [ ] Data sovereignty is a deal-breaker for target customers (e.g., defense/aerospace)
- [ ] Luminarity API costs exceed self-hosting costs at current volume
- [ ] You need formats beyond STEP (IGES, native CAD)

Start **Phase 2 — Xometry RFQ integration** when:
- [ ] Phase 0 cost formula engine is live and producing internal should-costs
- [ ] Customers ask "should we make this or buy it?" — need external benchmark pricing
- [ ] Volume of RFQ-eligible parts justifies API integration over manual quoting
- [ ] See [Section 10.4](#104-integration-architecture-make-or-buy-decision-support) for the integration architecture

Start **AI-driven approach** (Section 11 phases) when:
- [ ] Customer has 500+ historical parts with known production costs (sufficient training data)
- [ ] Phase 0 formula engine is running but accuracy plateaus or maintenance burden grows
- [ ] Customers request "find me similar parts" or part reuse features (Similar Part Search needs zero cost data)
- [ ] Multiple customers need cost estimation but have very different manufacturing processes (per-tenant AI models scale better than per-tenant formula tuning)
- [ ] Note: Similar Part Search (Phase A) can start independently — requires only open CAD data, no cost labels

### Build vs. Skip Decision

| Signal | Action |
|--------|--------|
| Customers say "I need automated quoting from CAD files" | Start Phase 0 → 1 + 1B |
| Customers say "I want to extract data from my drawings" | Start Phase 0 → 1B (drawing intelligence alone has value) |
| Customers say "I want to import part geometry" (no cost mentioned) | Store geometry in `custom_fields` via connector — no formula engine needed |
| Customers say "I need aPriori-level accuracy" | Evaluate commercial integration instead of building |
| Customers have lots of PDFs but no STEP files | Phase 1B is the priority — skip Phase 1 initially |
| Customers say "should we make or buy this part?" | Phase 0 + Xometry RFQ integration (Section 10.4) |
| Customers say "find me parts like this one" | Section 11 Phase A — Similar Part Search (no cost data needed) |
| Formula accuracy plateaus despite tuning | Section 11 Phase C — AI cost estimation from customer data |
| Customer has 1000+ parts with production costs | Section 11 Phase C — sufficient data for per-tenant AI model |
| No customer demand for cost estimation | Don't build any of this |

### Risk Assessment

| Risk | Mitigation |
|------|------------|
| Cost formulas are inaccurate | Start with "rough estimate" framing (±30%); let users calibrate per machine/material |
| Luminarity API goes away | Provider interface pattern allows swapping to self-hosted |
| Drawing extraction hallucinations | Confidence scoring + human review flag; Tier 1 text extraction as ground truth for vector PDFs |
| VLM cost per drawing too high | Tier 1 (PyMuPDF text) handles 60-70% of vector PDFs for free; VLM only for scanned/complex |
| GD&T extraction inaccuracy | Start with simple tolerance classes (ISO 2768); add GD&T detail incrementally |
| Scope creep into full MES/ERP | Strict boundary: estimate only, not production planning |
| Low adoption | Phase 0 tests demand with minimal investment before Phase 1/1B |

---

## 10. External Provider & RFQ Market Landscape

Section 4.3 identified the cost formula engine as the critical missing piece and briefly listed commercial alternatives (aPriori, Costimator, Seer). This section provides a comprehensive market review of platforms that either (a) include built-in should-costing models or (b) provide instant RFQ / external production quotes — both relevant to RattleApp's make-or-buy decision support strategy.

*Research date: February 2026. Pricing and API availability subject to change.*

### 10.1 Should-Costing Platforms (Built-In Cost Models)

These platforms have invested years building proprietary cost models that map geometry + process parameters to manufacturing costs. They solve the exact "cost formula engine" problem identified in Section 4.

#### aPriori

**Category:** Enterprise digital twin simulation
**API:** `aP Generate` REST API — triggers analysis from PLM/ERP events; `aP Design` for CAD-embedded feedback
**Cost models:** 50+ manufacturing process models (casting, machining, sheet metal, plastics, composites, additive)
**Pricing:** Enterprise license, typically €50K–200K+/year; claims 600% ROI
**Integration effort:** High — enterprise sales cycle, complex API surface, requires process library configuration
**Key strength:** Deepest cost model library in the market; digital twin approach simulates entire manufacturing process
**Key weakness:** Overkill for RattleApp's initial needs; pricing excludes SMB customers

#### Costimator (MTI Systems)

**Category:** Parametric cost estimation
**API:** Limited — primarily desktop application; `3DFX` add-on for geometry feature recognition from CAD files
**Cost models:** 2M+ validated cycle times in knowledge base; process-based templates with customizable rates
**Pricing:** Starts ~$15K perpetual license + 20% annual maintenance
**Integration effort:** Medium-High — on-premise software, no cloud API; would need wrapper service
**Key strength:** Decades of validated manufacturing data; trusted in aerospace/defense
**Key weakness:** On-premise architecture; no modern REST API; 3DFX geometry recognition is limited compared to Luminarity

#### Spanflug MAKE

**Category:** AI-powered CNC costing
**API:** ERP export interface (CSV/XML); no public REST API; machine hourly rate calculator tool is web-based
**Cost models:** AI algorithm trained on 1M+ manufactured parts; auto-calculates manufacturing times, machine selection, tooling, and stock requirements; separate machine hourly rate calculator (manufacturing rate, setup rate, programming rate)
**Pricing:** Free tier (5 parts/month); subscription plans for higher volume
**Integration effort:** Medium — no REST API means file-based integration or screen scraping; ERP export could feed into RattleApp via import
**Key strength:** Closest analog to what RattleApp's Phase 0 formula engine aims to do — calculates cycle times from geometry using learned models; machine hourly rate calculator is a direct reference for our `MachineType` model design
**Key weakness:** German/European CNC focus; no public API for programmatic integration; limited to CNC turning/milling
**Strategic value:** Study Spanflug's machine hourly rate calculator (manufacturing rate + setup rate + programming rate breakdown) as a design reference for `MachineType.hourly_rate` decomposition

#### 3D Spark

**Category:** Automated costing for additive + conventional manufacturing
**API:** Unknown (SaaS platform; likely has integration options for enterprise customers)
**Cost models:** 15+ manufacturing technologies; ±5% accuracy claimed (Deutsche Bahn case study at 10K+ parts scale); AI-based 2D→3D conversion for parts without CAD models
**Pricing:** SaaS subscription (contact for pricing)
**Integration effort:** Medium — would need to negotiate API access
**Key strength:** Make-or-buy screening at scale (conventional vs. additive); CO₂ footprint calculation; handles both 3D CAD and 2D drawings
**Key weakness:** Accuracy claims need independent validation; limited public documentation on API

#### CloudNC CAM Assist

**Category:** AI-generated toolpaths + cycle time estimation
**API:** CAM plugin (Fusion 360, Mastercam); not a standalone REST API
**Cost models:** Calculates per-operation cycle times from AI-generated toolpaths; `Cycle Time Estimator` claims 20x faster than manual estimation
**Pricing:** $99/month for CAM Assist
**Integration effort:** Low-Medium for cycle time data, but requires CAM environment — not suitable as a headless API
**Key strength:** Actual toolpath-based cycle times (most accurate approach possible); per-operation breakdown
**Key weakness:** Requires CAM software in the loop; can't be called as a simple API; calculates machining time but not full cost (no material, overhead, secondary processes)

#### Should-Costing Platform Comparison

| Platform | API Availability | Cost Model Depth | Processes Covered | Pricing | Integration Effort |
|----------|-----------------|------------------|-------------------|---------|-------------------|
| **aPriori** | REST (`aP Generate`) | 50+ processes, digital twin | All major manufacturing | €50K–200K+/yr | High |
| **Costimator** | Desktop only (`3DFX` add-on) | 2M+ validated cycle times | CNC, fabrication, assembly | ~$15K + 20% maint. | High |
| **Spanflug MAKE** | ERP export only | AI-trained on 1M+ parts | CNC turning/milling | Free tier → subscription | Medium |
| **3D Spark** | Unknown (SaaS) | 15+ technologies, ±5% | AM + conventional | SaaS subscription | Medium |
| **CloudNC** | CAM plugin only | Per-operation cycle times | CNC milling | $99/mo | Low (but needs CAM) |

### 10.2 Instant RFQ Marketplaces (External Production Quotes)

These platforms provide instant or near-instant manufacturing quotes. For RattleApp, they serve as the **external benchmark** in make-or-buy decisions: "what would it cost to outsource this part?"

#### Xometry — The Primary Integration Target

**Category:** On-demand manufacturing marketplace with public developer API
**API:** `developer.xometry.com` — **the only platform with a documented public REST API** for instant quoting
- Instant Quote API: upload CAD file → receive price, lead time, DFM feedback
- Workcenter API: webhooks for order status updates
- DFM Feedback API: manufacturability analysis
**Processes:** CNC machining, sheet metal fabrication, 3D printing (7+ technologies), injection molding, tube bending, die casting, stamping
**Network:** 10,000+ vetted manufacturers globally
**Pricing:** Free to get quotes; pay per order (market-rate pricing with AI-driven optimization)
**Integration effort:** Low-Medium — standard REST API; can be implemented as an `ExternalConnector` + `ExchangeTask` in RattleApp's existing connector framework
**Key strength:** Only viable RFQ API integration partner today; covers the broadest range of manufacturing processes; AI-driven pricing reflects actual market rates
**Key weakness:** Pricing is market-based (not should-costing); quotes reflect Xometry's margin; primarily serves as external benchmark, not internal cost calculation

#### Protolabs / Protolabs Network (formerly Hubs)

**Category:** ML-based quoting marketplace
**API:** No public developer API; Fusion 360 CAD add-in for in-tool quoting
**Processes:** CNC machining, injection molding, 3D printing, sheet metal
**Quoting:** ML model trained on millions of previously manufactured parts; instant web-based quotes
**Pricing:** Premium pricing (speed/quality premium over typical job shops)
**Integration effort:** High — no API means manual web interaction or unauthorized scraping (not recommended)
**Key strength:** Fast turnaround (1-day express options); guaranteed quality; ML-based pricing is sophisticated
**Key weakness:** No API for programmatic integration; premium pricing makes it a poor baseline for cost benchmarking

#### Fictiv

**Category:** AI-powered manufacturing marketplace
**API:** No public developer API; `Materials.AI` (ChatGPT-powered) for material selection guidance
**Processes:** CNC machining, sheet metal, injection molding, 3D printing
**Quoting:** AI-powered instant quotes with DFM feedback
**Note:** Acquired by MISUMI (2025) — future API strategy may change
**Pricing:** Competitive with Xometry; positioned as premium quality
**Integration effort:** High — no API; would require manual or browser-automation approach
**Key strength:** Strong DFM feedback; MISUMI acquisition may lead to catalog + manufacturing integration
**Key weakness:** No public API; post-acquisition direction uncertain

#### DigiFabster

**Category:** Manufacturing quoting SaaS for job shops
**API:** Documented API (gated behind customer login at `digifabster.com/api/`)
**Processes:** CNC machining, 3D printing, sheet metal, laser cutting
**Quoting:** Configurable pricing rules; AI pricing calibration; instant web widget quotes
**Pricing:** From $350/month; integrates with Xero, QuickBooks, HubSpot, Salesforce
**Integration effort:** Medium — API exists but requires customer account; designed for job shops to white-label, not for RFQ aggregation
**Key strength:** If RattleApp customers are also DigiFabster users, could pull their configured pricing; good for job shop customers who want to expose their own quoting
**Key weakness:** Not a marketplace — reflects individual shop pricing, not market rates; API access requires commercial relationship

#### Fractory

**Category:** On-demand metal fabrication platform
**API:** No public API
**Processes:** Sheet metal (laser cutting, bending, welding), CNC machining, tube cutting
**Quoting:** Instant online quotes; European supplier network
**Pricing:** Market-rate; strong in sheet metal
**Integration effort:** High — no API
**Key strength:** Strong sheet metal focus; competitive European pricing
**Key weakness:** No API; narrower process coverage than Xometry

#### PCBWay

**Category:** PCB + CNC + 3D printing marketplace
**API:** API cooperation page exists (`pcbway.com/cooperation.html`) — suggests partner API access is possible
**Processes:** PCB manufacturing, CNC machining, 3D printing, injection molding
**Quoting:** Instant online quotes; primarily electronics-focused
**Integration effort:** Medium — API may be available through partnership
**Key strength:** If RattleApp serves electronics manufacturers, covers PCB + mechanical in one platform
**Key weakness:** Primarily electronics-focused; CNC/3DP is secondary; API details unclear

#### RFQ Marketplace Comparison

| Platform | Public API | Processes | Quote Speed | Geography | Integration Effort |
|----------|-----------|-----------|-------------|-----------|-------------------|
| **Xometry** | REST + webhooks | CNC, SM, 3DP, IM, tube, die cast | Instant | Global (US/EU) | **Low-Medium** |
| **Protolabs** | No (CAD add-in only) | CNC, IM, 3DP, SM | Instant | Global | High |
| **Fictiv** | No | CNC, SM, IM, 3DP | Instant | US/Asia | High |
| **DigiFabster** | Yes (gated) | CNC, 3DP, SM, laser | Configurable | Per-shop | Medium |
| **Fractory** | No | SM, CNC, tube | Instant | Europe | High |
| **PCBWay** | Partnership API | PCB, CNC, 3DP, IM | Instant | Asia/Global | Medium |

### 10.3 Sourcing & Matchmaking Platforms

These platforms focus on connecting buyers with manufacturers rather than providing instant quotes. Less relevant for direct API integration but worth monitoring for strategic context.

#### Orderfox (Partfox + Gieni AI)

**Category:** Swiss B2B CNC matching platform
**Valuation:** €1B+ (2025 funding round)
**AI:** `Gieni AI` — presented as an MCP (Model Context Protocol) reference case at Microsoft BUILD 2025; AI-powered supplier matching from part specifications
**API:** No public API yet; advisory board process for integration partners; Autodesk Forge integration exists
**Key insight:** Orderfox/Gieni represents the AI-native approach to supplier matching — could become an API-accessible RFQ platform in the future
**Relevance to RattleApp:** Monitor; if Gieni AI exposes an MCP-based API, it could be integrated via the connector framework

#### partZpro

**Category:** AI-driven cost analysis + supplier matching
**Capability:** AI Cost-Driver Analysis Engine — identifies design features that drive cost and suggests optimization before quoting; vetted supplier network with escrow-backed accountability
**API:** No public API
**Relevance to RattleApp:** The "cost-driver analysis" concept (identifying which geometry features contribute most to cost) is valuable for Phase 2 formula refinement UI

### 10.4 Integration Architecture: Make-or-Buy Decision Support

The highest-value integration pattern for RattleApp combines internal should-costing with external RFQ benchmarking:

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                        Part Detail Page                                       │
│                                                                              │
│  ┌─────────────────────────────┐    ┌──────────────────────────────────┐     │
│  │ INTERNAL SHOULD-COST        │    │ EXTERNAL RFQ QUOTE               │     │
│  │ (Phase 0 formula engine)    │    │ (Xometry API)                    │     │
│  │                             │    │                                  │     │
│  │ Material:     €12.40        │    │ Xometry Quote:  €38.50/unit      │     │
│  │ Setup:        €42.50        │    │ Lead time:      8 business days  │     │
│  │ Machining:    €18.75        │    │ Process:        CNC milling      │     │
│  │ Finishing:     €3.20        │    │ Material:       AL 6061          │     │
│  │ Overhead:     €11.53        │    │ DFM issues:     None             │     │
│  │ ─────────────────────       │    │                                  │     │
│  │ Unit cost:    €45.88        │    │ Qty 10:  €32.10/unit             │     │
│  │ (at qty 1)                  │    │ Qty 100: €24.80/unit             │     │
│  │                             │    │                                  │     │
│  │ Qty 10:  €41.63/unit        │    │ [Request Full Quote →]           │     │
│  │ Qty 100: €39.46/unit        │    │                                  │     │
│  └─────────────────────────────┘    └──────────────────────────────────┘     │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐    │
│  │ MAKE-OR-BUY RECOMMENDATION                                          │    │
│  │                                                                      │    │
│  │ At qty 1:   BUY (external €38.50 < internal €45.88) — save 16%     │    │
│  │ At qty 10:  MAKE (internal €41.63 > external €32.10) — but         │    │
│  │             consider: internal has 2-day lead vs. 8-day external    │    │
│  │ At qty 100: MAKE (internal €39.46 < external €24.80) — ⚠ external  │    │
│  │             is cheaper; review internal rates                       │    │
│  └──────────────────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────────────────┘
```

#### Data Flow

```
STEP file upload ──→ Geometry Extraction (Luminarity) ──→ PartGeometryAnalysis
                                                              │
PDF drawing upload ──→ Drawing Intelligence (VLM) ──→ PartDrawingAnalysis
                                                              │
                                                              ▼
                                              ┌───────────────────────────────┐
                                              │ Internal Should-Cost          │
                                              │ (cost_formula_engine.py)      │
                                              │ geometry + material + rates   │
                                              │ → cost breakdown              │
                                              └───────────────┬───────────────┘
                                                              │
                     ┌────────────────────────────────────────┤
                     │                                        │
                     ▼                                        ▼
        ┌────────────────────────┐            ┌───────────────────────────────┐
        │ Xometry RFQ API        │            │ PartCostEstimate              │
        │ (connector framework)  │            │ (internal cost stored)        │
        │                        │            │                               │
        │ POST /quotes           │            │ material_cost, setup_cost,    │
        │ + STEP file + material │            │ machining_cost, overhead...   │
        │ + quantity             │            │                               │
        │ → instant quote        │            └───────────────────────────────┘
        │ → DFM feedback         │                        │
        └────────────┬───────────┘                        │
                     │                                    │
                     ▼                                    ▼
        ┌─────────────────────────────────────────────────────────────────┐
        │ Make-or-Buy Comparison                                          │
        │ Internal should-cost vs. Xometry quote at each quantity         │
        │ + lead time comparison + DFM feedback display                   │
        └─────────────────────────────────────────────────────────────────┘
```

#### Implementation via Connector Framework

The Xometry integration fits naturally into RattleApp's existing connector architecture:

```
ExternalConnector (Xometry)
  ├── base_url: "https://api.xometry.com/v1"
  ├── auth: API key header
  │
  ├── ExternalEndpoint: "instant_quote"
  │   ├── method: POST
  │   ├── url: "/quotes"
  │   ├── body: { file, material, quantity, process }
  │   └── response → store in Part.custom_fields["xometry_quote"]
  │
  ├── ExternalEndpoint: "dfm_check"
  │   ├── method: POST
  │   ├── url: "/dfm"
  │   └── response → display DFM feedback on Part detail
  │
  └── Webhook: "order_status"
      ├── url: "/webhooks/xometry"
      └── events: quote_ready, order_placed, order_shipped
```

### 10.5 Strategic Recommendation

#### Don't License aPriori — Build Simple + Benchmark Externally

aPriori's €50K–200K+/year licensing is designed for large enterprises with dedicated cost engineering teams. For RattleApp's multi-tenant SaaS model, the economics don't work:
- Per-tenant licensing would price out SMB customers
- A pooled license would require complex cost allocation
- The 50+ process models are overkill when most customers need CNC + sheet metal

Instead: Build the Phase 0 formula engine (simple, configurable, per-tenant) and use **Xometry's free API** as the external accuracy benchmark.

#### Spanflug MAKE Is the Closest Design Reference

Spanflug's approach — AI-trained cycle time estimation + machine hourly rate calculator — is the closest analog to what RattleApp's Phase 0 aims to build. Key design takeaways:
- **Decompose hourly rates** into manufacturing rate + setup rate + programming rate (extends our `MachineType.hourly_rate` to `MachineType.manufacturing_rate`, `.setup_rate`, `.programming_rate`)
- **Machine selection logic** from part geometry (bounding box + material group → appropriate machine)
- **Stock material calculation** from raw volume → standard stock sizes → material cost
- Spanflug's free tier (5 parts/month) can be used for manual validation of RattleApp's formula outputs during development

#### Xometry Is the Only Viable RFQ API Partner Today

Of all platforms reviewed, Xometry is the only one with:
- A documented, public developer API (`developer.xometry.com`)
- Instant quoting across the broadest process range
- DFM feedback as a separate API call
- Webhook support for async order tracking

No other marketplace (Protolabs, Fictiv, Fractory) offers public API access. DigiFabster has an API but serves a different use case (job shop quoting tool, not marketplace pricing).

**Recommended integration sequence:**
1. **Phase 0:** Build internal formula engine (no external dependencies)
2. **Phase 2:** Add Xometry RFQ connector for make-or-buy comparison
3. **Future:** Monitor Orderfox/Gieni AI for MCP-based API access; evaluate DigiFabster if job shop customers need quoting widget integration

#### The "Make or Buy" Integration Requires Only Two Things

The make-or-buy decision support shown in Section 10.4 requires:
1. **Internal should-costing** — the Phase 0 cost formula engine (already planned)
2. **One external API** — Xometry instant quote (standard REST, fits connector framework)

This is a high-value, low-complexity integration. The Xometry API call can be triggered alongside the internal cost calculation, and results displayed side-by-side on the Part detail page. No new infrastructure is needed beyond what the connector framework already provides.

---

## 11. AI-Driven Approach: Learning Cost from Data

Sections 1-10 assume a **deterministic** path: extract geometry → apply hand-crafted cost formulas → output estimate. This section challenges that assumption and asks: **what if we train models to learn cost patterns directly from data, instead of writing formulas by hand?**

This is not speculation. The academic literature and open dataset landscape show that:
1. Large open CAD datasets exist with rich machining feature labels (though not cost labels)
2. Graph neural networks on B-Rep geometry achieve state-of-the-art results for manufacturing feature recognition and process classification
3. ML-based cost estimation has been validated with 3.9-18.5% MAPE on real production data
4. The entire field is moving toward foundation models for CAD understanding

The practical question is not "can AI learn manufacturing cost?" but "where do the training labels come from?"

### 11.1 The Paradigm Shift

**Formula-based approach (Sections 4-8):**
- Requires manual setup per customer: machine rates, material costs, cycle time parameters
- Accuracy depends on engineering expertise baked into formulas
- Every new manufacturing process needs new formula development
- Maintenance burden grows linearly with process/material combinations

**AI-driven approach:**
- Pre-train geometric understanding on large open CAD datasets (self-supervised — no labels needed)
- Fine-tune cost prediction on each customer's actual production data
- The model learns the customer's cost structure implicitly — no formula authoring
- Accuracy improves with more data, not more engineering effort
- Enables capabilities impossible with formulas: similarity search, clustering, DFM feedback

**Key insight:** Phase 0 (formula engine) is still valuable as a bootstrapping mechanism and training data generator. But the long-term architecture should plan for AI-first cost estimation, with formulas as a fallback and calibration tool.

### 11.2 Open CAD Dataset Landscape

Seven major open CAD datasets were evaluated for their potential to bootstrap AI-driven manufacturing intelligence. **Critical finding: none contain cost labels.** They provide geometry + machining feature annotations, not production costs or prices.

| # | Dataset | Size | Format | Labels | License | Cost Data? |
|---|---------|------|--------|--------|---------|------------|
| 1 | **CADSynth** (Beihang Univ.) | 100K models, 6.2 GB | STEP + JSON + B-Rep graph (.bin) | Machining feature per-face (24 types: holes, slots, steps, fillets...) | CC-BY 4.0 | No |
| 2 | **1M Synthetic CAD** (Beihang) | 1M models, 113.7 GB | STEP + JSON + B-Rep graph + images | Parametric feature modeling sequences | CC-BY 4.0 | No |
| 3 | **ABC Dataset** (Onshape/NYU) | 1M models | STEP, STL, OBJ, features, stats | Parametric curves/surfaces, ground truth normals/curvature | Onshape ToS | No |
| 4 | **NIST MBE PMI** | ~20 test cases | STEP AP242, native CAD | Full GD&T (tolerances, datums, PMI), multi-CAD | Public domain | No |
| 5 | **MFCAD++** (Queen's Belfast) | 59,665 models | STEP | Per-face machining feature class labels | Academic | No |
| 6 | **MFInstSeg** | 60,000+ | STEP | Instance-level machining feature labels | Academic | No |
| 7 | **HybridCAD** | Hybrid AM/CNC | STEP | Additive + subtractive feature labels | Academic (Zenodo) | No |

**What these datasets provide (and why it matters):**
- **Geometric representation training data** — 2M+ STEP models for learning what 3D parts "look like"
- **Machining feature recognition labels** — per-face annotations for holes, slots, pockets, chamfers (24+ types in CADSynth)
- **Parametric design sequences** — how parts were designed, enabling design intent understanding
- **Standardized B-Rep graph format** — ready for graph neural network training

**What they don't provide:** Manufacturing cost, production time, material selection, machine allocation, supplier pricing — the data needed to actually predict cost. See Section 11.3 for how to solve this.

Full dataset details with download links in [Appendix E](#appendix-e-open-cad-dataset-reference).

### 11.3 The Training Data Problem — and Solutions

The fundamental challenge: **open datasets have geometry but no cost labels. Cost estimation requires labeled training data that pairs geometry with actual production cost.**

The only published work with real cost labels is [ArXiv 2508.12440](https://arxiv.org/html/2508.12440v1) (2025), which used 13,684 proprietary automotive DWG drawings with historical production costs, achieving 3.9-18.5% MAPE with XGBoost on 200 extracted geometric features. This proves ML cost estimation works — but the cost labels came from a proprietary ERP system, not an open dataset.

**Three approaches to obtaining cost training labels for RattleApp:**

#### a) Customer's Own Production Data

The most valuable and accurate source. Each RattleApp tenant's historical `Part.part_cost` values — combined with STEP geometry — become per-tenant training data.

```
Part.part_cost (manually entered over time)  +  STEP geometry (extracted via Luminarity)
    → training pair: (geometry_features, actual_cost)
    → per-tenant model that learns THIS customer's cost structure
```

**Requirement:** Customer needs ~500+ parts with known costs and associated STEP files. Many manufacturing companies have this data in their ERP but haven't connected it to CAD geometry.

#### b) Xometry API as Cost Oracle

Use the Xometry instant quote API (Section 10.2) to generate market-price labels for arbitrary STEP files:

```
Upload STEP to Xometry → receive instant quote (price, lead time, process)
    → training pair: (geometry_features, market_price)
    → bootstrap model with market-rate pricing before customer data exists
```

**Advantage:** Infinite label generation — upload any STEP file, get a price. **Limitation:** Xometry prices reflect market rates + their margin, not the customer's internal cost structure.

#### c) Phase 0 Formula Engine as Synthetic Label Generator

The formula engine from Phase 0 itself becomes a training data source:

```
Phase 0 formula output (material + setup + machining + overhead)
    → training pair: (geometry_features, formula_estimated_cost)
    → AI model learns to approximate the formula — then surpass it with real data
```

**Advantage:** Generates unlimited labeled data from day one. **Limitation:** The AI model can only be as good as the formula initially — but it can be fine-tuned with real data to surpass it.

#### The "Cold Start → Warm Model" Progression

```
Stage 1 (Cold Start):     Formula engine only — no AI
                           ↓ customer enters 100+ Part.part_cost values
Stage 2 (Bootstrap):      Pre-train on open CAD data + fine-tune on formula outputs
                           ↓ formula + Xometry labels provide initial training signal
Stage 3 (Learning):       AI model trained on customer's actual production costs
                           ↓ customer corrects AI estimates → model improves
Stage 4 (Warm Model):     AI model outperforms formula engine for this customer
                           ↓ formula engine becomes calibration/sanity check
```

### 11.4 Architecture: Pre-train on Open Data, Fine-tune on Customer Data

The state-of-the-art approach follows a **foundation model** pattern: learn general geometric understanding from large unlabeled datasets, then specialize for cost prediction using small labeled datasets.

**Step 1: Pre-train geometric embeddings (one-time, shared across all tenants)**

Train a self-supervised encoder on 1M+ open CAD models (ABC + CADSynth + 1M Synthetic CAD). The model learns to produce a dense vector (embedding) that captures a part's geometric essence — shape, complexity, feature types — without any labels.

Approaches validated in literature:
- **Point cloud encoder** (PointNet++, Point-MAE) — convert STEP → point cloud → self-supervised pre-training. Simplest to implement; proven transfer learning results ([3D Foundation Models Survey](https://arxiv.org/html/2501.18594v1), Jan 2025).
- **B-Rep graph encoder** (BRepGAT, HG-CAD) — operate directly on the boundary representation graph (faces, edges, vertices as nodes). Higher fidelity but requires B-Rep parsing. [HG-CAD](https://www.research.autodesk.com/app/uploads/2024/05/hg-cad.pdf) (Autodesk) demonstrates material prediction and cost estimation from hierarchical B-Rep graphs.
- **Multi-view image encoder** — render STEP from multiple angles, encode with vision transformer. Leverages existing VLM infrastructure. [LLM4CAD Survey](https://arxiv.org/html/2505.08137v1) (May 2025) shows multimodal LLMs can understand 3D geometry from renderings.

**Step 2: Per-tenant fine-tuning on customer cost data**

Freeze the geometric encoder, add a cost prediction head (small MLP), fine-tune on the customer's `(geometry_embedding, actual_cost)` pairs. With a good pre-trained encoder, as few as 200-500 labeled parts can produce useful predictions.

```
┌─────────────────────────────┐
│ Pre-trained Geometric       │  ← Trained once on 1M+ open CAD models
│ Encoder (frozen)            │     (self-supervised, no labels needed)
│                             │
│ STEP → embedding vector     │
└──────────────┬──────────────┘
               │ 512-dim embedding
               ▼
┌─────────────────────────────┐
│ Cost Prediction Head        │  ← Fine-tuned per tenant on
│ (small MLP, trainable)      │     customer's Part.part_cost history
│                             │
│ embedding → estimated cost  │
└──────────────┬──────────────┘
               │
               ▼
         Predicted Cost
         (customer corrects → model improves)
```

**Step 3: Active learning loop**

When the model predicts a cost, the user can accept or correct it. Corrections become new training data, creating a flywheel:

```
AI predicts €42.50  →  User says "actually €38.00"  →  (embedding, €38.00) added to training set
                                                        →  model re-trained nightly
                                                        →  next prediction is closer
```

**"The model learns YOUR cost structure, not generic rates."** Each tenant's model diverges based on their specific machines, labor rates, overhead allocation, and material costs — without them ever having to configure formula parameters.

### 11.5 Beyond Cost: Features Enabled by CAD Intelligence

Once you have a geometric embedding model that understands manufacturing parts, cost estimation is just one application. The same infrastructure enables features that are **impossible** with formula-based approaches:

#### a) Similar Part Search

> *"Find me parts in our catalog that look like this STEP file"*

Geometric embeddings enable nearest-neighbor search across a company's entire part catalog. Upload a STEP file → compute embedding → find the 10 closest parts by cosine similarity.

**Value:** Reuse existing tooling and fixtures, avoid designing duplicate parts, find existing quotes for similar geometry. Part reuse typically saves 15-30% of engineering time in manufacturing companies.

**Technical basis:** Self-supervised pre-training on open CAD datasets produces embeddings where geometrically similar parts cluster together. No cost data needed — this is pure geometry.

**Implementation:** Index `Part` embeddings in pgvector (already available in PostgreSQL) or a dedicated vector database. Search is a single SQL query.

#### b) Automatic Process Routing

> *"This part should be turned, then milled, then anodized"*

Graph neural networks on B-Rep geometry achieve state-of-the-art manufacturing process classification. [MaProNet](https://www.sciencedirect.com/science/article/pii/S0278612525000469) (2025) demonstrates automatic process selection (turning, milling, drilling, grinding, etc.) directly from part geometry using graph attention networks.

**Value:** Auto-populate manufacturing process plans for new parts. Pre-fill the sequence of operations, reducing manual process planning from hours to seconds.

**Technical basis:** Fine-tune the pre-trained geometric encoder on MFCAD++/CADSynth machining feature labels → predict required manufacturing operations per part.

#### c) DFM (Design for Manufacturability) Feedback

> *"This wall is too thin for milling — consider 2mm minimum"*
> *"This bore depth-to-diameter ratio exceeds 10:1 — difficult to machine"*

Combining geometry analysis with manufacturing rules produces actionable design feedback before a part enters production.

**Value:** Catch costly design issues early. DFM problems discovered during production cost 10-100x more to fix than those caught at design time. This is the exact feedback that Xometry's DFM API provides externally — but generated internally from the company's own manufacturing capabilities.

**Technical basis:** Rule-based checks on extracted geometry features (wall thickness, bore ratios, undercuts, thin webs) combined with learned models for process-specific constraints.

#### d) Cost Driver Visualization

> *"70% of this part's cost comes from the 3 deep bores on axis B"*

Explainable AI techniques (Grad-CAM, SHAP) applied to the cost prediction model can highlight which geometric features contribute most to the predicted cost — visualized directly on a 3D rendering of the part.

**Value:** Design optimization guidance. Engineers can see exactly where cost originates and make informed trade-offs: "if we remove this feature, cost drops 22%." [XAI Manufacturing Cost](https://www.sciencedirect.com/science/article/abs/pii/S0957417421008472) demonstrates 3D CNN + Grad-CAM for this exact use case.

**Technical basis:** Standard XAI techniques applied to the cost prediction model. The geometric encoder provides per-face/per-feature attribution scores.

#### e) Material Recommendation

> *"Based on geometry + requirements, AL 6082-T6 is optimal"*

Given a part's geometry and intended use, predict the optimal material from the company's material database. [HG-CAD](https://www.research.autodesk.com/app/uploads/2024/05/hg-cad.pdf) (Autodesk) demonstrates material prediction from geometry using hierarchical graph learning.

**Value:** Automated material selection for new parts; flag non-optimal material choices on existing parts. Combined with Drawing Intelligence (Section 5) material extraction, this creates a verification loop: extracted material vs. AI-recommended material.

#### f) Supplier Matching

> *"This part matches the capability profile of 3 suppliers in your network"*

Geometric embeddings can be compared against supplier capability profiles (machine types, max dimensions, material capabilities, process expertise) to automatically identify qualified suppliers for a given part.

**Value:** Automatic RFQ routing to qualified suppliers. Reduces manual supplier qualification from hours to seconds. Similar to what Orderfox/Gieni AI does (Section 10.3) but internal to the customer's supplier network.

#### g) Quotation Quality Scoring

> *"Supplier X's quote is 40% above predicted cost — investigate"*

Use the AI-predicted cost as an objective benchmark for incoming supplier quotes. Flag quotes that deviate significantly from the predicted range.

**Value:** Procurement leverage. Data-driven negotiation: "our model predicts this part should cost €38-42; your quote of €58 needs justification." Also catches underquoting that might indicate quality shortcuts.

#### h) Part Family Clustering

> *"Your catalog has 47 parts that could share tooling setups"*

Unsupervised clustering of geometric embeddings reveals natural part families — groups of parts that share geometric characteristics and could benefit from shared tooling, group scheduling, or standardized processes.

**Value:** Reduce setup costs through group technology. Manufacturing companies typically save 10-25% on setup time by identifying and scheduling similar parts together. This is classic group technology, but automated through AI rather than manual classification.

### 11.6 Practical Architecture for RattleApp

```
┌──────────────────────────────────────────────────────────────────────────────────────┐
│                              RattleApp AI-Driven Architecture                          │
│                                                                                       │
│  ┌─────────────────────────────────────────────────────────────────────────────────┐  │
│  │                        Geometry Embedding Service                                │  │
│  │                                                                                  │  │
│  │  STEP Upload → Point Cloud / B-Rep Graph → Pre-trained Encoder → 512-dim vector │  │
│  │                                                                                  │  │
│  │  Options:                                                                        │  │
│  │  • Point cloud path: STEP → Open3D/trimesh → PointNet++ (simplest to start)     │  │
│  │  • B-Rep graph path: STEP → OCC B-Rep → BRepGAT (highest fidelity)             │  │
│  │  • Multi-view path: STEP → rendered images → ViT encoder (leverages VLM infra) │  │
│  └──────────────────────────────────────┬──────────────────────────────────────────┘  │
│                                          │                                             │
│                                          ▼                                             │
│  ┌──────────────────────────────────────────────────────────────────────────────────┐ │
│  │                           Vector Store (pgvector / Qdrant)                        │ │
│  │                                                                                   │ │
│  │  Per-Part embedding indexed for:                                                  │ │
│  │  • Similarity search (k-NN)        • Part family clustering (HDBSCAN)            │ │
│  │  • Supplier capability matching     • Anomaly detection                           │ │
│  └──────────────────────────────────────┬────────────────────────────────────────────┘ │
│                                          │                                             │
│              ┌───────────────────────────┼───────────────────────────┐                 │
│              │                           │                           │                 │
│              ▼                           ▼                           ▼                 │
│  ┌───────────────────┐    ┌──────────────────────┐    ┌──────────────────────┐        │
│  │ Cost Prediction    │    │ Similar Part Search  │    │ Process Classifier   │        │
│  │ Head (per-tenant)  │    │ (shared model)       │    │ (shared model)       │        │
│  │                    │    │                      │    │                      │        │
│  │ embedding + meta   │    │ embedding → k-NN     │    │ embedding → process  │        │
│  │ → predicted cost   │    │ → ranked results     │    │ → operations list    │        │
│  │                    │    │                      │    │                      │        │
│  │ Fine-tuned on:     │    │ No training needed   │    │ Fine-tuned on:       │        │
│  │ Part.part_cost     │    │ (pure similarity)    │    │ MFCAD++/CADSynth    │        │
│  └───────────────────┘    └──────────────────────┘    └──────────────────────┘        │
│                                                                                       │
│  ┌─────────────────────────────────────────────────────────────────────────────────┐  │
│  │                        LLM Integration Layer                                     │  │
│  │                                                                                  │  │
│  │  "Explain this cost estimate":                                                   │  │
│  │  geometry features + cost breakdown + similar parts → LLM → natural language     │  │
│  │  explanation: "This part is expensive because of the 3 deep bores requiring      │  │
│  │  special tooling. Similar part P-2847 was produced for €38 — consider reusing   │  │
│  │  that tooling setup."                                                            │  │
│  └─────────────────────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────────────────────┘
```

**Technology choices:**

| Component | Recommended | Alternative | Notes |
|-----------|------------|-------------|-------|
| STEP → geometry | trimesh + Open3D (point cloud) | PythonOCC (B-Rep graph) | Point cloud is simpler; B-Rep is more accurate |
| Pre-trained encoder | Point-MAE or PointNet++ | BRepGAT, HG-CAD | Pre-train on ABC + CADSynth datasets |
| Vector store | pgvector (PostgreSQL extension) | Qdrant, Milvus | pgvector avoids new infrastructure; sufficient to ~1M parts |
| Cost prediction head | PyTorch MLP (2-3 layers) | XGBoost on embeddings | MLP for end-to-end training; XGBoost for quick experiments |
| Clustering | HDBSCAN on embeddings | K-means | HDBSCAN finds natural clusters without specifying k |
| Explanation | Existing LLM providers | SHAP values | LLM generates natural language; SHAP provides feature attribution |

### 11.7 Build Sequence: What's Realistic Now

The AI-driven features should be built incrementally, with each phase delivering standalone value:

#### Phase A: Similar Part Search (Lowest Risk, Highest Novelty)

**No cost data needed.** Pure geometry — the quickest win.

| Step | What | How |
|------|------|-----|
| 1 | Pre-train point cloud encoder | Download ABC/CADSynth → STEP to point cloud → train Point-MAE (self-supervised) |
| 2 | Build embedding pipeline | STEP upload → point cloud → encoder → 512-dim vector |
| 3 | Index existing catalog | Batch-embed all Parts with STEP files → store in pgvector |
| 4 | Build search UI | "Upload STEP → find similar parts" on Part detail page |
| 5 | Expose via API | `POST /api/parts/similar` with STEP file → ranked results |

**Effort:** 3-4 weeks. **Dependency:** None (can start before Phase 0). **Value:** Part reuse, duplicate detection, design exploration.

#### Phase B: Process Classification

**Fine-tune on open dataset labels.** No customer data needed.

| Step | What | How |
|------|------|-----|
| 1 | Fine-tune on MFCAD++/CADSynth | Train classifier on per-face machining feature labels (24 types) |
| 2 | Aggregate to part level | Per-face features → part-level process prediction (turning/milling/etc.) |
| 3 | Auto-suggest on upload | STEP upload → process classification → pre-fill Part metadata |
| 4 | Feed into cost formula | Predicted process type → select correct formula/machine type |

**Effort:** 2-3 weeks (after Phase A encoder exists). **Dependency:** Phase A encoder. **Value:** Automated process planning, faster Part setup.

#### Phase C: AI Cost Estimation (Requires Customer Data)

**The payoff phase.** Replaces or augments the formula engine.

| Step | What | How |
|------|------|-----|
| 1 | Bootstrap with Xometry labels | Upload sample STEPs to Xometry API → get market prices → initial training set |
| 2 | Train initial model | Embedding + basic features (volume, surface area) → cost prediction |
| 3 | Customer fine-tuning pipeline | Customer uploads Part with actual cost → added to training set |
| 4 | Active learning UI | AI predicts → user corrects → model improves |
| 5 | Per-tenant model management | Nightly re-training per tenant; model versioning; A/B testing vs. formula engine |
| 6 | Confidence scoring | Model outputs confidence interval; low-confidence → fall back to formula engine |

**Effort:** 4-6 weeks (after Phase B). **Dependency:** Phase A encoder + customer data (or Xometry bootstrap). **Value:** Cost estimation that improves with use, requires no formula maintenance.

#### Phase D: DFM + Optimization (Advanced)

**The "mindblowing" features.** Requires phases A-C as foundation.

| Step | What | How |
|------|------|-----|
| 1 | Rule-based DFM checks | Geometry features → manufacturing rules (min wall thickness, bore ratios, undercuts) |
| 2 | Cost driver visualization | XAI attribution on cost model → highlight expensive features on 3D rendering |
| 3 | "What-if" analysis | Remove/modify feature in embedding space → predict cost delta |
| 4 | Part family clustering | HDBSCAN on embeddings → group technology recommendations |
| 5 | Supplier matching | Part embedding vs. supplier capability vectors → qualified supplier list |

**Effort:** 6-8 weeks (after Phase C). **Dependency:** Phases A-C + mature embedding model. **Value:** Design optimization, procurement intelligence, group technology.

### 11.8 Revised Strategic Recommendation

The analysis across Sections 1-11 reveals a clear architectural trajectory:

| Timeframe | Approach | Role |
|-----------|----------|------|
| **Now** | Phase 0: Formula engine | Delivers immediate value; generates synthetic training data; validates customer demand |
| **Near-term** | Phase A: Similar Part Search | Zero cost data needed; highest novelty; demonstrates AI capability to customers |
| **Mid-term** | Phases B+C: Process classification + AI cost estimation | Augments formula engine; per-tenant models learn from customer corrections |
| **Long-term** | Phase D: DFM + optimization | Full CAD intelligence platform; cost driver visualization; supplier matching |

**Key strategic points:**

1. **Phase 0 is not wasted work.** Even in an AI-first future, the formula engine serves as: bootstrapping mechanism (synthetic labels), sanity check (flag AI predictions that diverge wildly from formula), and fallback (new customers with no training data).

2. **Open datasets solve pre-training, not fine-tuning.** The 2M+ open CAD models provide geometric understanding. Cost prediction accuracy comes from customer-specific data — which RattleApp is uniquely positioned to collect through its existing Part/BOM/cost workflow.

3. **Similar Part Search is the gateway feature.** It requires zero cost data, delivers immediate value (part reuse, duplicate detection), and builds the geometric embedding infrastructure that all subsequent AI features depend on.

4. **Per-tenant AI models are a competitive moat.** Unlike commercial platforms (aPriori, Costimator) that offer generic cost models, RattleApp's per-tenant fine-tuning means each customer's model gets better the more they use it. This creates switching costs and network effects at the tenant level.

5. **The "explain this cost" capability differentiates.** Combining geometric feature attribution (which features drive cost) with LLM-generated explanations creates a user experience that no formula-based system can match: "This part costs €42 because the 3 deep bores require a 5-axis setup (€18), the tight Ra 0.8 bore finish adds grinding (€8), and the AL 7075 material is 40% more expensive than 6061."

### 11.9 Academic References

| Paper | Year | Approach | Key Finding | Relevance |
|-------|------|----------|-------------|-----------|
| [ArXiv 2508.12440](https://arxiv.org/html/2508.12440v1) | 2025 | XGBoost on 200 geometric features from 2D DWG (13,684 automotive parts) | 3.9-18.5% MAPE across 24 product groups | **Proves ML cost estimation works** — but needs proprietary cost labels |
| [ConvGNN Cost Estimation](https://www.sciencedirect.com/science/article/abs/pii/S0278612522001789) | 2022 | Graph NN on B-Rep with precision info | Improved over prior 3D CNN approaches | GD&T/tolerance info significantly improves cost accuracy |
| [HG-CAD](https://www.research.autodesk.com/app/uploads/2024/05/hg-cad.pdf) | 2024 | Hierarchical graph learning on B-Rep (Autodesk) | Material prediction + cost estimation + similarity search | **Foundation model** approach for CAD — learns transferable representations |
| [BRepGAT](https://academic.oup.com/jcde/article/10/6/2384/7453688) | 2023 | Graph attention network on B-Rep faces | State-of-art machining feature segmentation | Works directly on B-Rep (no voxelization loss) |
| [MaProNet](https://www.sciencedirect.com/science/article/pii/S0278612525000469) | 2025 | Graph attention NN for manufacturing process selection | Process classification from geometry | **Process routing is a solved problem** with GNNs |
| [XAI Manufacturing Cost](https://www.sciencedirect.com/science/article/abs/pii/S0957417421008472) | 2021 | 3D CNN + Grad-CAM visualization | Cost prediction with explainability | Shows which geometry features drive cost — user-facing value |
| [LLM4CAD Survey](https://arxiv.org/html/2505.08137v1) | 2025 | Survey of LLMs for CAD understanding | Multi-task CAD comprehension | Multimodal LLMs can understand 3D geometry from renderings |
| [3D Foundation Models Survey](https://arxiv.org/html/2501.18594v1) | 2025 | Self-supervised pre-training on point clouds | Transfer learning to downstream tasks | Pre-train on large unlabeled CAD datasets, fine-tune on small labeled sets |

---

## 12. The API Business Opportunity: Manufacturing Intelligence as a Service

Sections 1-11 evaluate STEP analysis and cost estimation as **features within RattleApp**. This section asks a fundamentally different question: **could the underlying technology — manufacturing cost calculation and master data enrichment exposed as simple REST APIs — be a standalone, billion-dollar business?**

The answer emerges from a striking gap in the competitive landscape: **no platform offers a pure REST API for "calculate manufacturing cost on request" or "enhance master data on request."** This section presents the full business case.

### 12.1 The Two API Products

#### CostAPI — "Calculate on Request"

```
POST /v1/cost/estimate
Body: { step_file, material, quantity, [machine_config] }

→ Returns: {
    material_cost: €12.40,
    setup_cost: €42.50,
    machining_cost: €18.75,
    finishing_cost: €3.20,
    secondary_processes: €8.00,
    overhead: €11.53,
    total_unit_cost: €96.38,
    cycle_time_min: 14.2,
    confidence: 0.82,
    process_route: ["CNC 3-axis milling", "drilling", "anodize Type III"],
    quantity_breaks: { 1: €96.38, 10: €54.20, 100: €41.80 }
  }
```

**What this replaces:** Manual cost engineering (hours per part), aPriori licenses ($50K+/yr), spreadsheet-based estimating. Every manufacturer, procurement team, and design engineer needs this.

#### EnrichAPI — "Enhance Master Data on Request"

```
POST /v1/enrich/part
Body: { step_file, [drawing_pdf] }

→ Returns: {
    classification: "CNC turning + milling",
    material_group: "aluminum",
    bounding_box: [120.5, 80.0, 45.2],
    volume_cm3: 276.9,
    weight_kg: 0.75,
    suggested_stock: "Ø85 × 130mm round bar",
    feature_count: { bores: 6, threads: 3, pockets: 2 },
    surface_area_cm2: 412.3,
    machined_percentage: 63.4,
    // From drawing (if provided):
    material: "AL 6061-T6",
    tolerances: { general: "ISO 2768-mK", tightest: 0.02 },
    surface_finish: { default_ra: 3.2, tightest_ra: 0.8 },
    secondary_processes: ["anodize Type III", "passivate"],
    gdt_complexity: 4,
    suggested_material_code: "AL_6061"
  }
```

**What this replaces:** Manual part classification, manual data entry in PLM/ERP, master data cleanup projects (which cost €100K-500K per engagement). Every company with a parts database needs this.

### 12.2 Market Size Analysis

#### Direct TAM (The APIs Themselves)

| Market Segment | Size (2024) | CAGR | Projected (2033) | Source |
|----------------|-------------|------|-------------------|--------|
| Manufacturing cost estimation software | $1.5–2.1B | 9–10% | $3.2–5.5B | OpenPR, Dataintelo, Insight Partners |
| Cost estimating software (all industries) | $8.5B | 8.8% | $19.8B | OpenPR |

#### Adjacent TAM (Where the APIs Get Embedded)

| Market Segment | Size (2024) | CAGR | Projected (2032) | Source |
|----------------|-------------|------|-------------------|--------|
| PLM software | $26–35B | 6–9% | $46–70B | PS Market Research |
| Master Data Management | $13.3B | 10.5% | $32.5B | Market Reports World |
| AI in manufacturing | — | — | $47.9B (2030) | Grand View Research |
| Smart manufacturing (broadest) | $233–394B | 14–15.5% | $479–900B | Mordor, Precedence, Fortune BI |

#### The API Economy in Manufacturing

| Metric | Value | Source |
|--------|-------|--------|
| Global API management market | $7.5B (2023) → $35.3B (2032) | Business Research Insights |
| AI API market | $3.3B (2024) → $30.9B (2032), CAGR 32.2% | Multiple |
| Manufacturing edge API deployment growth | 42% YoY (2024) | Nordic APIs |
| Traditional integration cost | $500K–$2M, 6–12 months | Industry benchmarks |
| API-first integration cost | $50K–$200K, 2–4 weeks | Industry benchmarks |

**Bottom line:** The direct TAM for manufacturing cost estimation is $1.5–2.1B today growing to $3–5B. But the real opportunity is becoming infrastructure embedded in the $26–70B PLM market and $13–32B MDM market — where every part record flowing through the system could call CostAPI or EnrichAPI.

### 12.3 Competitive Gap Analysis: Why No One Has Built This

#### What Exists vs. What's Missing

| Company | Revenue/Valuation | Has Cost Models | Has REST API | API-First | The Gap |
|---------|-------------------|----------------|--------------|-----------|---------|
| **aPriori** | ~$64M rev, $109M funding | Yes (50+ processes) | Yes (`aP Generate`) | No (enterprise SW) | API exists but requires $50K+ license; not per-call |
| **Xometry** | $545M rev (2024), public | Market-based (not should-cost) | Yes (`developer.xometry.com`) | Partial | Returns **buy price**, not **make cost** |
| **Spanflug MAKE** | Private, CERATIZIT invested | Yes (AI-trained) | ERP export only | No | No REST API; CNC only |
| **Costimator** | Private | Yes (2M+ cycle times) | No | No | Desktop software only |
| **3D Spark** | Private | Yes (15+ technologies) | Unknown | No | No documented API |
| **CloudNC** | Private | Cycle times only | CAM plugin | No | Requires CAM environment |
| **Protolabs** | Public | ML-based | No | No | No programmatic access |
| **Orderfox** | €1B+ valuation | No (matchmaking) | No | No | Matchmaking, not calculation |

**The gap is real:** No one offers a stateless, per-call, REST API where you POST a STEP file and GET back a cost breakdown. aPriori is closest but locked behind enterprise licensing. Xometry is closest on the API side but returns market prices, not should-costs.

#### Why Hasn't Someone Built This?

1. **Domain expertise barrier** — Cost formula engines require deep manufacturing engineering knowledge (cycle times, feed rates, machine capabilities). Software engineers can't build this alone.
2. **Data barrier** — Training ML cost models requires proprietary production cost data that no one publishes. Open CAD datasets (ABC, CADSynth, MFCAD++) have geometry but zero cost labels (see Section 11.2).
3. **aPriori's moat** — They've had 23 years to build 50+ process models. But they chose enterprise licensing over API monetization.
4. **Spanflug chose vertical** — They built the technology but used it to run a CNC marketplace, not sell API access.
5. **Market timing** — The API economy in manufacturing is just now maturing (42% growth in edge API deployment, 2024). Three years ago, manufacturers weren't API-ready.

### 12.4 Billion-Dollar API Business Patterns

#### What Made Them Work

| Company | Revenue | Model | Key Pattern |
|---------|---------|-------|-------------|
| **Twilio** | $4.46B (2024) | Per-message/call | Usage-based; grows with customer volume |
| **Stripe** | $600B+ processed | Per-transaction fee | Embedded in checkout; impossible to remove |
| **Plaid** | $390M ARR | Per-connection + usage | Banking data enrichment; 80% gross margin |
| **Checkr** | $700M (2023) | Per-background-check | Started gig economy → expanded enterprise |
| **ZoomInfo** | $5B+ valuation | Subscription data | 321M+ profiles; data moat |
| **Clearbit** | Acquired by HubSpot | Credit-based enrichment | Embedded in CRM workflows |

#### The 5 Requirements for a $1B API Business

| # | Requirement | CostAPI/EnrichAPI | Assessment |
|---|-------------|-------------------|------------|
| 1 | **Low friction entry** — Free tier or developer sandbox | Free tier (50 calculations/month); pay per call above | Strong — mirrors Spanflug's 5/mo free tier |
| 2 | **Usage-based scaling** — Revenue grows as customers succeed | $0.50–5.00 per cost calc; $0.10–1.00 per enrichment | Strong — scales with parts volume |
| 3 | **Deep embedding** — Once integrated, switching cost is enormous | PLM/ERP systems call API on every new part or revision | Very strong — becomes part of engineering workflow |
| 4 | **Data flywheel** — Each customer's usage improves the product | Corrections improve ML models; more customers → better predictions | Strong — but takes 12–18 months to kick in |
| 5 | **DBNE >100%** — Customers naturally increase spend | Companies add more parts, more users, more frequent calculations | Likely strong — manufacturing data grows monotonically |

### 12.5 Revenue Model & Path to $1B

#### Pricing Architecture

```
Free Tier:       50 cost calculations/month + 200 enrichments/month
                 (enough for evaluation; hooks developers)

Professional:    $500/month + $2.00/cost calculation + $0.50/enrichment
                 (SMB manufacturers, 500–5,000 parts)

Enterprise:      $5,000/month + volume-discounted per-call
                 (large manufacturers, PLM integrators, 50,000+ parts)

Platform:        Custom pricing for PLM/ERP vendors embedding the API
                 (Siemens, PTC, SAP, Autodesk reseller agreements)
```

#### Revenue Scenarios

| Scenario | Year | Customers | Avg. Annual Spend | Platform Revenue | Total ARR |
|----------|------|-----------|-------------------|-----------------|-----------|
| **Conservative** | Year 5 | 2,000 | $12K | 10 partnerships × $500K = $5M | **~$29M** |
| **Growth** | Year 5 | 10,000 | $24K | 25 partnerships × $1M = $25M + $35M data/insights | **~$300M** |
| **Venture Scale** | Year 7-8 | 50,000 | $30K | Top 5 PLMs embedded + international | **$1B+ ARR** |

The conservative scenario achieves aPriori-comparable revenue ($64M). The growth scenario follows the Xometry trajectory ($545M). The venture scale requires international expansion, platform embedding in top 5 PLMs, and a mature data flywheel.

#### Critical Mass Metrics

| Milestone | Metric | Significance |
|-----------|--------|-------------|
| Product-market fit | 100 paying customers, <5% monthly churn | Validates the API gap is real demand |
| Flywheel ignition | 500 customers, 1M+ calculations processed | ML models start outperforming formulas |
| Platform embedding | 3+ PLM/ERP vendors integrating natively | Distribution moat; API becomes infrastructure |
| Pricing power | DBNE >120% | Customers expanding; product is sticky |
| $100M ARR | 5,000+ customers across 3+ regions | Credible path to $1B at 3-5x multiple |

### 12.6 Technology Readiness Assessment

The technology required maps directly to the components assessed in Sections 4, 5, 7, and 11. Here is the readiness matrix for API delivery:

| Component | Feasibility | Accuracy | Evidence |
|-----------|-------------|----------|----------|
| Geometry extraction from STEP | Solved | N/A | Luminarity API (tested, Section 2.1), OpenCascade (open-source), GNNs (95%+ accuracy) |
| Drawing intelligence (PDF) | Solved | 90%+ material, 97.3% F1 for annotations | VLMs (GPT-4o, Claude) + eDOCr2 + YOLOv11 (Section 5) |
| Process classification | Solved | State-of-art | MaProNet (2025): GNN-based from geometry (Section 11.5b) |
| Material detection from drawings | Solved | 90%+ | VLMs + regex fallback (Section 5) |
| Cost estimation ±30% | **Feasible now** | ±30% | Parametric formulas + customer rates (Phase 0, Section 8) |
| Cost estimation ±15% | Feasible in 3-6 months | ±15% | Add drawing intelligence (tolerances, surface finish multipliers) |
| Cost estimation ±8-12% | Feasible in 12-18 months | ±8-12% | GNNs fine-tuned on 500+ customer parts (Section 11.4) |
| Cost estimation ±5% | Aspirational | ±5% | Requires toolpath-level analysis or massive training data |

**Key insight:** The API can launch at ±30% accuracy with explicit confidence bands, and improve over time. Early adopters accept wider ranges when the alternative is "no data at all" or "hours of manual estimation." The confidence score in the API response makes the accuracy level transparent.

### 12.7 Cold-Start Strategy

The hardest part: you need cost data to train models, but customers come to you *because* they don't have good cost data. This is addressed in detail in Section 11.3, but here is the API-specific bootstrapping approach:

#### Three-Source Bootstrapping

```
Source 1: Customer-provided rates (Day 1)
          Every manufacturer knows their machine hourly rates and material costs.
          Parametric formulas give ±30% from geometry + rates.

Source 2: Xometry as oracle (Month 1)
          Upload STEP files to Xometry API → get market prices → use as training labels.
          Not should-costs, but a useful proxy. Free to query.

Source 3: Customer corrections (Month 3+)
          Users adjust estimates ("actual cost was €42, not €55")
          → correction data feeds ML training pipeline.
          → each correction makes the model smarter.
```

**The flywheel:** More customers → more corrections → better models → more accurate estimates → more customers.

#### Parallel Track: Open Dataset Pre-Training

Pre-train geometric embeddings on 1M+ open CAD models (ABC, CADSynth — see Section 11.2 and Appendix E). The embeddings don't need cost labels — they learn "what parts look like." Fine-tune the cost prediction head on sources 1-3 above.

### 12.8 Defensibility & Moat Analysis

| Moat Type | Strength at 6 months | Strength at 18+ months | Notes |
|-----------|---------------------|----------------------|-------|
| **Data flywheel** | Weak — insufficient data | **Strong** — 500+ customers, millions of data points | Customer corrections compound over time |
| **Integration depth** | Medium — early adopters | **Very strong** — switching costs are enormous | Once embedded in PLM/ERP, ripping out is a project |
| **Domain expertise** | Medium — parametric formulas | **Strong** — ML models trained on real production data | Combines software + manufacturing knowledge |
| **Network effects** | Weak — per-tenant models | **Medium** — cross-tenant patterns improve baseline | Anonymized aggregate data benefits all |
| **Brand/trust** | Weak — unproven | **Strong** — track record builds slowly but deeply | Manufacturing is a conservative industry |

**Key insight:** The defensibility is not just data — it's **data + domain expertise + integration depth + trust in a conservative industry**. Competitors can replicate one of these; replicating all four takes years. However, synthetic data and few-shot learning could lower barriers, so the window for building the moat is finite.

### 12.9 Risk Matrix

#### Why This Could Fail

| Risk | Severity | Likelihood | Mitigation |
|------|----------|------------|------------|
| **aPriori launches API pricing** | Critical | Medium | They've had 23 years and chose enterprise. But a startup threat could change this. First-mover advantage matters. |
| **Accuracy too low for trust** | High | Medium | Frame as "estimate" not "quote." Show confidence bands. Let users override. Accuracy improves with data. |
| **Manufacturing is slow to adopt APIs** | High | Medium-Low | 42% YoY growth in edge APIs says the tide is turning. Target digitally-native manufacturers first. |
| **PLM vendors build it themselves** | High | Low | Siemens, PTC, SAP are platform companies, not ML companies. They'd rather embed than build. (Like Salesforce embeds Clearbit, not builds it.) |
| **Small market** | Medium | Low | $1.5-2.1B direct TAM is real, but the embedded TAM ($26-70B PLM) is the prize. |
| **Customer acquisition cost too high** | High | Medium | Manufacturing sales cycles are 6-12 months for enterprise. PLM partnerships accelerate this — one Siemens deal = 10,000 endpoints. |

#### Why This Could Win Big

1. **The gap is glaringly obvious** — Everyone in manufacturing knows cost estimation is broken. No one has built the API.
2. **Timing is right** — API economy in manufacturing hit inflection point (2024-2025). Industry 4.0 budgets are flowing.
3. **AI changes the economics** — VLMs make drawing intelligence possible for $0.05/drawing. GNNs make cost prediction possible without 23 years of formula engineering.
4. **PLM embedding is the distribution hack** — One partnership with Siemens Teamcenter or PTC Windchill distributes the API to tens of thousands of manufacturers overnight.
5. **Xometry proved the market** — $545M revenue (2024) proves manufacturers will pay for digital cost intelligence. CostAPI is the should-costing complement to Xometry's market pricing.
6. **Data flywheel compounds** — Unlike aPriori (static models), an ML-driven API gets better with every customer. Year 3 accuracy >>> Year 1 accuracy.

### 12.10 Strategic Options for RattleApp

#### Option A: Build as RattleApp Features (Current Path)

CostAPI and EnrichAPI as features within RattleApp's CPQ/PDM platform. Value accrues to RattleApp's existing customer base.

| Pros | Cons |
|------|------|
| Lower risk; incremental development | Lower ceiling; limited to RattleApp's TAM |
| Direct value for existing customers | No external API revenue |
| No separate team/funding needed | Competitors could build the API first |
| Reinforces RattleApp's CPQ value prop | Doesn't capture the PLM embedding opportunity |

#### Option B: Spin Out as Standalone API Company

Separate company/product focused purely on the API. RattleApp becomes the first customer.

| Pros | Cons |
|------|------|
| Billion-dollar ceiling | Higher risk; requires dedicated team |
| API-first architecture from day one | Needs separate funding |
| Can pursue PLM partnerships independently | Distracts from RattleApp core business |
| Attracts developer ecosystem | Longer time to revenue |

#### Option C: Build Inside, Expose Outside (Hybrid) — Recommended

Build the technology inside RattleApp first (Phase 0-2 of the feasibility roadmap). Once proven, expose as a standalone API product that any PLM/ERP can consume. RattleApp gets the feature advantage; the API company gets the TAM.

| Pros | Cons |
|------|------|
| De-risks by proving technology internally first | Slower to market than pure API play |
| RattleApp customers provide early training data | Architecture must be API-ready from the start |
| Natural progression from feature to product | Organizational complexity of dual focus |
| **This is the Shopify → Stripe pattern** | Requires conscious architectural decisions now |

**The Shopify → Stripe analogy:** Stripe started as Shopify's payment processor, then became infrastructure for everyone. CostAPI starts as RattleApp's cost engine, then becomes infrastructure for every PLM/ERP system.

**Recommended approach:** Option C. Build the cost engine and enrichment pipeline as modular, API-first services within RattleApp's architecture (as outlined in Sections 7-8). Design them from day one as stateless services with clean REST interfaces. Once validated with RattleApp customers (6-12 months), expose the same services as a public API with independent pricing.

### 12.11 Comparable Valuations

| Company | Model | Revenue | Valuation | Multiple |
|---------|-------|---------|-----------|----------|
| aPriori | Enterprise SW | ~$64M | ~$300-500M (est.) | 5-8x |
| Xometry | Marketplace | $545M | ~$1.5-2B (market cap) | 3-4x |
| Orderfox | Matchmaking + AI | Undisclosed | €1B+ (2025) | — |
| Plaid | Data enrichment API | $390M ARR | $5.3B (Visa offer) | 13x |
| Clearbit | Data enrichment API | ~$50-80M (est.) | Acquired by HubSpot | ~5-10x |

**An API-first manufacturing intelligence company at $300M ARR would likely command a $2-4B valuation** based on SaaS multiples for high-growth, high-margin API businesses. At $100M ARR with strong growth, $1B valuation is achievable.

### 12.12 Verdict: Can This Be a Billion-Dollar Business?

**Yes, but with conditions.**

#### The Thesis Is Sound

- Real, measurable gap (no API-first should-costing exists)
- Large TAM ($1.5B direct, $26B+ embedded)
- Proven patterns (Twilio, Plaid, Clearbit all started with "one API call for something that was previously complex")
- Technology is ready (geometry extraction solved, VLMs for drawings, GNNs for cost prediction — Sections 4, 5, 11)
- Timing is right (manufacturing API adoption inflecting)

#### The 5 Conditions for $1B

1. **Must achieve PLM platform embedding.** The volume comes from being called on every part in Teamcenter/Windchill/SAP, not from direct SMB customers alone. This is the Stripe-in-Shopify playbook.

2. **Must solve cold start within 6 months.** If early customers don't see useful results quickly (even at ±30%), they churn. The three-source bootstrapping approach (Section 12.7) is essential.

3. **Must go international early.** Manufacturing is global. CNC shops in Germany, India, China, USA all need this. Multi-currency, multi-language, regional material standards (DIN, ASTM, JIS).

4. **Must build the data flywheel before aPriori reacts.** aPriori could launch API pricing in 18-24 months if they see traction. The window is now.

5. **Must expand beyond cost.** CostAPI is the wedge. EnrichAPI adds retention. But the long-term play is becoming the "manufacturing intelligence layer" — cost, DFM feedback, similar part search, supplier matching, quotation benchmarking. Each feature increases switching costs.

#### The Spanflug Counterpoint

Spanflug built essentially this technology (AI cycle time prediction from CAD geometry) but chose to be a CNC marketplace, not an API company. Why?

- Marketplace captures more value per transaction (they take a cut of the manufacturing order, not just $2 per calculation)
- But marketplace requires fulfillment operations, supplier management, quality control — much heavier than API
- **The API play is higher margin, lower revenue per customer, but vastly higher customer count potential**
- Spanflug chose depth (one vertical, one geography); the API play chooses breadth (every PLM, every ERP, every manufacturer globally)

#### Final Assessment

The question is not whether a manufacturing intelligence API *could* be a billion-dollar business — the market size, competitive gap, and technology readiness all support it. The question is **execution**: can the cold-start problem be solved fast enough, can PLM partnerships be secured, and can accuracy improve quickly enough to build trust in a conservative industry?

The recommended path (Option C: hybrid) de-risks this by proving the technology inside RattleApp first while maintaining the architectural optionality to expose it as a standalone API. The Phase 0 formula engine (Section 8) and AI-driven approach (Section 11) become the foundation — the decision of whether to pursue the API business can be made once the technology is validated, with real accuracy numbers from real customers.

> **Note:** Section 13 supersedes several key assumptions in this section. Specifically: the cold-start accuracy projection (+/-30% at launch) is replaced by +/-5-15% via deterministic engine labeling; the standalone API business model is expanded to event-driven PLM/ERP middleware; and the revenue model is restructured around connector licensing and per-event pricing. The five conditions identified above remain valid but are substantially strengthened. See Section 13 for the revised analysis.

---

## 13. The Paradigm Shift: Manufacturing Intelligence Middleware

Section 12 built a compelling case for two standalone APIs (CostAPI + EnrichAPI) but inherited a fundamental weakness from Section 11: **no open dataset contains manufacturing cost labels.** The three cold-start solutions proposed — customer data (requires 500+ parts per tenant), Xometry scraping (returns market prices, not should-costs), and a simple formula engine (+/-30% accuracy ceiling) — were all compromised. This section presents a paradigm shift that resolves the cold-start problem from day one and repositions the business from standalone API to manufacturing intelligence middleware.

### 13.1 The Paradigm Shift — Deterministic Engines as AI Training Oracles

#### The Cold-Start Problem Restated

Section 11.3 identified the core obstacle: training an AI cost model requires labeled data — (geometry, cost) pairs — but no such dataset exists publicly. The three proposed solutions each carried severe limitations:

| Solution | Accuracy | Volume | Problem |
|----------|----------|--------|---------|
| **Formula engine** (Section 8) | +/-30% | Unlimited synthetic | Not good enough for production; customers need +/-10-15% to trust |
| **Xometry API** | Market prices (+/-20-40% vs. should-cost) | ~50K via scraping | Returns *market prices* (margin-loaded), not *should-costs*; legally questionable |
| **Customer production data** | +/-5-10% (ideal) | Requires 500+ parts per tenant | 12-18 month ramp; most SMBs don't have 500 priced parts |

Section 12 accepted this limitation and projected a slow accuracy ramp: +/-30% at launch → +/-15% in 3-6 months → +/-8-12% in 12-18 months. This timeline is too slow — customers in a conservative industry won't wait 18 months for useful accuracy, and competitors could close the gap.

#### The Breakthrough: Industrial-Grade Engines as Training Data Factories

The insight is simple but transformative: **use existing deterministic cost engines — specifically aPriori and simus Classmate Cloud — not as competitors to replace, but as oracles to learn from.**

These engines represent decades of accumulated manufacturing knowledge encoded as physics-based process models. aPriori alone has 440+ manufacturing process models built over 23 years. Rather than trying to replicate this knowledge from scratch (Section 11's approach) or accepting crude formulas (Section 8's approach), we can:

1. **Feed open STEP datasets** (150K+ curated files from ABC, CADSynth, MFCAD++) through these engines
2. **Collect detailed cost breakdowns** (material, machining, setup, finishing, overhead, cycle time, process route, DFM warnings, CO2e)
3. **Train AI models on the resulting labeled dataset** (9M+ labeled pairs after multi-configuration expansion)
4. **Fine-tune with real customer production data** as it becomes available

This is the **AlphaGo pattern**: AlphaGo first learned from expert human games (supervised learning from the "oracle"), then surpassed human play through self-play reinforcement learning. Similarly, CADPrice first learns from expert deterministic engines (aPriori/Classmate labels), then surpasses them by incorporating real-world production data, regional cost variations, and customer-specific factors that deterministic engines cannot model.

#### Two Specific Engines

**aPriori** (already in contact):
- 440+ manufacturing process models (CNC machining, sheet metal, casting, forging, injection molding, additive, composites, etc.)
- **aP Generate**: REST API for programmatic costing — submit STEP geometry + process/material/production parameters, receive fully burdened cost breakdown
- **Bulk Costing & Analysis (BCA)**: Batch mode for processing thousands of parts against multiple scenarios
- Returns: fully burdened cost, cycle times per operation, process route selection, DFM warnings, CO2e estimate, material utilization
- 23 years of process model development; used by BMW, Caterpillar, John Deere, Airbus
- Revenue ~$64M from ~500-1000 enterprise customers at $50K-500K+/yr

**simus Classmate Cloud / costing24**:
- Cloud API for parametric cost estimation
- ~€200/month for 200 calculations (~€1/calc), with volume discounts
- **Partner Module**: Free for integrators who embed costing24 in their products
- 95% accuracy for 80% of standard parts (turning, milling, drilling, sheet metal)
- Simpler process coverage than aPriori but excellent for validation subset
- German engineering heritage; strong in EU manufacturing

#### The Economics of Oracle-Based Labeling

**aPriori route** (primary oracle):
- Enterprise license: $200K-500K/yr for unlimited API access via aP Generate
- At 9M labels over 12 months: **~$0.02-0.06 per label**
- One-time investment that produces a permanent training asset (the labeled dataset and trained model weights persist indefinitely)

**simus route** (validation oracle):
- Partner Module: Free integration access
- Additional volume: €1/calc at standard rates, negotiable for bulk
- 10K parts × 6 configurations = 60K labels at €60K (or less via partnership)
- Primary value: cross-validation, not primary labeling

**Cross-engine validation**: Parts where aPriori and Classmate Cloud agree within 10% = **high-confidence labels** (~80% of standard parts). Disagreements flag edge cases for manual review or exclusion from training data. This dual-oracle approach produces a labeled dataset with built-in quality scoring.

#### What Changes vs. Section 11

| Metric | Section 11 Projection | With Oracle Labeling |
|--------|----------------------|---------------------|
| **Launch accuracy** | +/-30% (formula bootstrap) | +/-5-15% (aPriori-grade labels) |
| **Cold-start timeline** | 12-18 months to useful accuracy | Day one (pre-trained on 9M labels) |
| **Training data volume** | Hundreds (customer data) | 9M+ labeled pairs |
| **Data quality** | Mixed (formulas + scraping + customer) | Industrial-grade (aPriori + cross-validated) |
| **Process coverage** | 3-5 basic processes | 440+ processes (inherited from aPriori) |
| **DFM feedback** | Not available at launch | Available from day one (aPriori DFM labels in training data) |

### 13.2 Training Data Architecture

#### Open Dataset Inventory

The open CAD dataset landscape (detailed in Appendix E) provides ample raw geometry:

| Dataset | Size | Format | Manufacturing Relevance |
|---------|------|--------|------------------------|
| **ABC Dataset** | 1M models | STEP + mesh | ~5% directly manufacturable (~50K parts after filtering) |
| **CADSynth** | 100K parametric | STEP | High — generated from manufacturing-typical primitives |
| **1M Synthetic CAD** | 1M | STEP | Variable — needs heavy filtering |
| **MFCAD++** | 59.7K | STEP | Very high — labeled with machining feature annotations |
| **Fusion 360 Gallery** | 20K | STEP available | Moderate — design-focused but many are manufacturable |

**Curation target**: ~50K from ABC (filtered for machinable geometry) + 100K from CADSynth (parametric, highly relevant) + selected from MFCAD++ and Fusion 360 = **~150K high-quality input STEP files**.

#### Multi-Configuration Labeling

Each STEP file is labeled not once but across **60 manufacturing configurations**:

- **5 material families**: Aluminum 6061-T6, Steel 1018, Stainless 304, Titanium Ti-6Al-4V, ABS (plastic)
- **4 quantity levels**: 1 pc (prototype), 10 pcs (small batch), 100 pcs (medium), 1000 pcs (production)
- **3 regional cost profiles**: US Midwest ($85/hr shop rate), Germany (€95/hr), China (¥350/hr, ~$48)

5 × 4 × 3 = **60 labels per STEP file**

150K files × 60 configs = **9,000,000 labeled (geometry, detailed_cost_breakdown) pairs**

This is orders of magnitude more training data than any competitor possesses. For context, the best published academic result (ArXiv 2508.12440) used ~1,000 real production parts. We would have 9,000× more data.

#### Label Schema

Each label contains a rich cost breakdown, not just a total price:

```json
{
  "step_file_hash": "sha256:...",
  "geometry_features": {
    "bounding_box": [120.0, 85.0, 45.0],
    "volume_cm3": 234.5,
    "surface_area_cm2": 1876.3,
    "feature_count": 12,
    "hole_count": 4,
    "pocket_count": 2,
    "fillet_count": 8,
    "min_wall_thickness_mm": 2.1,
    "max_aspect_ratio": 4.2,
    "material_removal_ratio": 0.62
  },
  "configuration": {
    "material": "aluminum_6061_t6",
    "quantity": 100,
    "region": "us_midwest",
    "shop_rate_per_hour": 85.00
  },
  "cost_breakdown": {
    "material_cost": 12.45,
    "setup_cost_per_unit": 2.80,
    "machining_cost": 34.20,
    "finishing_cost": 5.60,
    "secondary_processes": 8.30,
    "overhead": 6.75,
    "total_unit_cost": 70.10
  },
  "process_data": {
    "cycle_time_seconds": 1452,
    "process_route": ["3-axis_milling", "drilling", "deburring", "anodizing"],
    "machine_type": "3-axis_vmc",
    "fixture_complexity": "moderate"
  },
  "dfm_warnings": [
    {"type": "thin_wall", "severity": "warning", "detail": "Wall thickness 2.1mm below recommended 3mm for aluminum"},
    {"type": "deep_pocket", "severity": "info", "detail": "L/D ratio 4.2 — consider step-down toolpath"}
  ],
  "sustainability": {
    "co2e_kg": 2.34,
    "material_utilization_pct": 38.0,
    "scrap_weight_kg": 0.89
  },
  "oracle_metadata": {
    "engine": "apriori",
    "engine_version": "2025.1",
    "confidence": "high",
    "cross_validated": true,
    "cross_validation_delta_pct": 7.2
  }
}
```

#### Quality Assurance via Cross-Engine Consensus

| Confidence Tier | Criteria | Expected % | Use in Training |
|-----------------|----------|-----------|-----------------|
| **High** | aPriori and Classmate agree within 10% | ~80% | Full weight in training |
| **Moderate** | Agreement within 10-25% | ~15% | Reduced weight; flagged for review |
| **Low** | Disagreement >25% or single-engine only | ~5% | Excluded from training; queued for manual review |

#### Labeling Pipeline

```
Open STEP datasets
    → Geometry validation (OpenCascade: watertight, manufacturable, sane dimensions)
    → Feature extraction (bounding box, volume, surface area, feature recognition)
    → aPriori aP Generate API (60 configs per part)
    → simus costing24 API (6 configs per part — validation subset)
    → Cross-engine consensus scoring
    → Structured label (JSON schema above)
    → Training dataset (Parquet + vector embeddings)
```

**Throughput estimate**: aPriori BCA processes ~100 parts per batch. At 9M API calls, ~90K batches. With parallelization across 10 concurrent workers: ~9K batches per worker. At ~1 minute per batch: **~62 days continuous processing**, or ~3 weeks with 20 workers. This is a one-time pipeline run.

**Storage**: 9M labels at ~2KB each = ~18GB structured data. Geometry embeddings at ~1KB each (150K unique parts) = ~150MB. Total pipeline storage: ~50GB including intermediate files.

### 13.3 The aPriori Partnership Model

#### Current Status

aPriori contact has been initiated. They are a ~$64M revenue company with ~$109M total funding, serving 500-1000 enterprise customers at $50K-500K+/yr. Their technology is unmatched in process model depth (440+ models, 23 years of development), but their go-to-market is exclusively enterprise: long sales cycles, on-premise deployments, dedicated implementation teams.

#### Partnership Structures

| Structure | What We Get | What aPriori Gets | Risk Level |
|-----------|-------------|-------------------|-----------|
| **OEM License** | API access to aP Generate for labeling + runtime | License revenue ($200-500K/yr) | Low — standard commercial deal |
| **Revenue Share** | Discounted/free API access | 10-20% of CADPrice revenue | Medium — requires revenue before value flows |
| **Training Data Partnership** | Free labeling access for research | Validated AI approach to extend their market | Low-Medium — mutual R&D benefit |
| **Strategic Investment** | Capital + technology access | Equity stake in AI-first cost estimation | High — deep commitment required |

**Recommended path**: Start with **Training Data Partnership** (frame as R&D collaboration to validate AI cost estimation approaches using their engines as ground truth). Transition to **Revenue Share** as API revenue materializes. This minimizes upfront cost and aligns incentives.

#### Win-Win Analysis

aPriori's current market is structurally limited:
- ~500-1000 customers at $50K-500K+/yr = ~$64M revenue
- Enterprise sales cycles: 6-12 months
- Implementation requires dedicated teams
- SMB market ($500-5,000/mo) is unreachable with their cost structure

CADPrice as middleware could serve **10,000+ SMBs** at $500-5,000/mo — a market aPriori cannot reach:
- 10,000 customers × $2,500/mo average = **$300M ARR** addressable
- At 10-20% revenue share to aPriori: **$30-60M** — potentially matching or exceeding their current total revenue
- aPriori gets SMB market access without changing their sales model
- We get 440+ process models without 23 years of development

This is not a zero-sum relationship. We expand their total addressable market, they provide the knowledge base that makes expansion possible.

#### Risk: aPriori Builds Their Own API

aPriori already has aP Generate (REST API) and could theoretically launch a self-serve API product. Why haven't they?

- **23 years of enterprise DNA.** Their entire organization — sales, support, implementation, pricing — is built for enterprise. Launching a $500/mo self-serve product would cannibalize their $200K/yr contracts and require fundamentally different operations. This is the Innovator's Dilemma.
- **Precedent: Salesforce Essentials.** Salesforce launched a $25/user/mo SMB product in 2017. Nine years later, enterprise still drives >90% of revenue. Enterprise companies struggle to serve SMBs even when they try.
- **The middleware value proposition is different.** aPriori costs geometry. CADPrice sits between PLM and ERP, enriching parts as they flow through the engineering-to-production pipeline. Even if aPriori launches an API, they don't have PLM/ERP connectors, event-driven middleware architecture, or master data enrichment capabilities.

**Critical mitigation**: Once AI models are trained on 9M aPriori-labeled pairs, **the model weights are ours**. aPriori can revoke API access, but the trained models, fine-tuned on customer data, continue to operate independently. The partnership produces a permanent asset — the labeled dataset and trained weights — not a runtime dependency.

#### Backup Oracles

If the aPriori partnership fails or becomes too expensive:
- **simus costing24**: Partner Module (free for integrators) covers turning, milling, drilling, sheet metal at 95% accuracy for 80% of standard parts. Sufficient for initial training, though narrower process coverage.
- **Siemens Teamcenter Product Cost Management**: REST API available (developer.siemens.com). Enterprise licensing required but provides another industrial-grade oracle path.
- **Hybrid approach**: Use simus as primary oracle (free Partner Module), supplement with customer data, and negotiate aPriori access for complex/exotic processes only.

### 13.4 Manufacturing Intelligence Middleware — The Business Model

#### Strategic Repositioning

Section 12 positioned CADPrice as a **standalone API** — upload a STEP file, get a cost estimate back. This is the Twilio/Plaid model: stateless, per-call, developer-first.

Section 13 repositions CADPrice as **manufacturing intelligence middleware** — an event-driven intelligence layer that sits between PLM and ERP systems, enriching every part as it flows from engineering to production. This is the MuleSoft/Informatica model, but with embedded AI intelligence rather than simple data transformation.

The difference is fundamental:
- **API**: Customer calls us when they need a cost estimate. We're a tool.
- **Middleware**: We're embedded in the customer's most critical data pipeline (engineering→production). We process every part automatically. We're infrastructure.

#### Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                    CADPrice Intelligence Layer                       │
│                                                                     │
│  ┌─────────┐  ┌──────────┐  ┌──────────┐  ┌─────────┐  ┌────────┐ │
│  │Geometry │  │ Drawing  │  │ Master   │  │  Cost   │  │  DFM   │ │
│  │Extract  │  │ Intel    │  │ Data     │  │ Estim.  │  │Feedback│ │
│  └────┬────┘  └────┬─────┘  └────┬─────┘  └────┬────┘  └───┬────┘ │
│       │            │             │              │            │      │
│  ┌────┴────┐  ┌────┴─────┐                                        │
│  │Similar  │  │ Process  │        AI Models (9M+ pre-trained)      │
│  │Part     │  │ Route    │        Per-Tenant LoRA Fine-Tuning      │
│  │Search   │  │ Suggest  │        Active Learning Loop             │
│  └─────────┘  └──────────┘                                        │
│                                                                     │
├──────────────────────┬──────────────────────────────────────────────┤
│   PLM Connectors     │              ERP Connectors                  │
│                      │                                              │
│  ┌──────────────┐    │    ┌──────────────┐                         │
│  │ Teamcenter   │    │    │ SAP S/4HANA  │                         │
│  ├──────────────┤    │    ├──────────────┤                         │
│  │ Windchill    │    │    │ Oracle Mfg   │                         │
│  ├──────────────┤    │    ├──────────────┤                         │
│  │ 3DEXPERIENCE │    │    │ Dynamics 365 │                         │
│  ├──────────────┤    │    ├──────────────┤                         │
│  │ Fusion/Vault │    │    │ Infor Cloud  │                         │
│  └──────────────┘    │    └──────────────┘                         │
│                      │                                              │
│    Design Data ▼     │     ▼ Production Data                       │
│    (STEP, drawings,  │     (Actual costs, cycle times,             │
│     BOMs, ECOs)      │      production orders)                     │
└──────────────────────┴──────────────────────────────────────────────┘
         │                              │
         ▼                              ▼
   PLM Systems                    ERP Systems
   (Source of Truth                (Source of Truth
    for Design)                    for Cost)
```

#### Event-Driven Integration

Rather than waiting for API calls, CADPrice subscribes to PLM/ERP events and enriches data as it flows:

| Event Source | Event Type | CADPrice Action | Output |
|--------------|-----------|-----------------|--------|
| **PLM** | New Part Release | Full enrichment: geometry extraction + classification + cost estimate + DFM feedback + similar part search | Enriched part record pushed to ERP |
| **PLM** | Engineering Change Order (ECO) | Delta analysis: what changed in geometry, cost impact assessment, DFM re-evaluation | Change impact report + updated cost |
| **PLM** | BOM Update | BOM-level cost rollup, make-or-buy recommendation per line item, alternative material suggestions | BOM cost summary + recommendations |
| **ERP** | Cost Roll-Up Complete | Capture actual cost data for model training feedback loop | Model fine-tuning trigger |
| **ERP** | Production Order Completion | Capture actual cycle times and process data for model validation | Accuracy tracking + LoRA update |
| **ERP** | Purchase Order for Outsourced Part | Capture supplier pricing for market price benchmarking | Supplier cost database update |

**Bidirectional data flow**: PLM pushes design data down (geometry, BOMs, ECOs) → CADPrice enriches → pushes to ERP. ERP pushes production data up (actual costs, cycle times, supplier prices) → CADPrice uses for model improvement. This creates a **continuous learning loop** that compounds over time.

#### Pre-Built Connector Framework

Eight PLM/ERP systems cover >80% of the manufacturing enterprise market:

| System | API Type | Event Mechanism | Market Share | Companies |
|--------|----------|----------------|-------------|-----------|
| **Siemens Teamcenter** | REST API | T4EA gateway, Teamcenter Events | ~22.9% PLM | ~6,158 |
| **PTC Windchill** | OData REST | ESI (Enterprise Systems Integration) with TIBCO | ~10.5% PLM | ~3,500 |
| **Dassault 3DEXPERIENCE** | REST + GraphQL | JMS event bus, webhook notifications | ~12.8% PLM | ~4,200 |
| **SAP S/4HANA** | OData V2/V4 | BOM APIs, Material Master, Event Mesh | ~24% ERP | ~37,500 |
| **Oracle Mfg Cloud** | REST | FBDI (File-Based Data Import), Business Events | ~5% ERP | ~7,500 |
| **Microsoft Dynamics 365** | REST | MES Integration API, Dataverse webhooks | ~6% ERP | ~9,000 |
| **Infor CloudSuite** | ION API Gateway | ION Connect (50B+ API calls/yr across platform) | ~6% ERP | ~68,000 |
| **Autodesk Fusion/Vault** | REST | Vault Connector, Fusion event hooks | ~5% PLM | ~3,000 |

Each connector implements a standardized `EventReceiver` / `DataPublisher` interface that normalizes events into CADPrice's internal schema. This pattern leverages the existing RattleApp connector framework (`app/connectors/engine.py`, `app/connectors/slots.py`) as architectural inspiration — the same connector abstraction scaled to enterprise PLM/ERP systems.

#### Seven Intelligence Capabilities Per Enrichment Event

When a part flows through CADPrice, it receives up to seven enrichment capabilities in a single event — not seven separate API calls:

| # | Capability | Input | Output | Value |
|---|-----------|-------|--------|-------|
| 1 | **Geometry Extraction** | STEP file | Bounding box, volume, surface area, features, complexity score | Foundation for all other capabilities |
| 2 | **Drawing Intelligence** | PDF drawing | Material spec, tolerances, surface finish, GD&T, notes | Cost-critical metadata not in STEP files |
| 3 | **Master Data Enrichment** | Part number + geometry | eCl@ss/UNSPSC classification, material group, commodity code | Clean master data for ERP/procurement |
| 4 | **Cost Estimation** | Geometry + material + qty + region | Detailed cost breakdown (material, machining, setup, finishing, overhead) | Should-cost for make-or-buy, negotiation, budgeting |
| 5 | **DFM Feedback** | Geometry + process | Manufacturability warnings, design improvement suggestions | Reduce manufacturing cost before production |
| 6 | **Similar Part Search** | Geometry embedding | Top-N similar parts from company's history + global database | Prevent duplicate designs, reuse tooling, benchmark costs |
| 7 | **Process Route Suggestion** | Geometry + material + qty | Recommended manufacturing process sequence + machine selection | Automate process planning for standard parts |

This bundled approach creates **extraordinary switching costs**: removing CADPrice means losing all seven capabilities simultaneously, across every part in the engineering-to-production pipeline. No single-capability replacement exists.

#### Why Switching Costs Are Astronomical

PLM-ERP integration projects typically cost **$150K-2M+** and take 6-18 months. CADPrice as middleware becomes embedded in this pipeline:

- Removing CADPrice = removing the intelligence layer from the most sensitive data flow in manufacturing
- Every downstream process (procurement, production planning, cost accounting) depends on CADPrice-enriched data
- Master data classifications, cost estimates, and process routes become the source of truth in ERP
- Retraining users, rebuilding integrations, and finding replacement capabilities for all seven functions = 6-12 month project
- **Net Revenue Retention expectation: 130-150%** (enterprise middleware benchmark: MuleSoft achieved 140%+)

### 13.5 Revised Revenue Model

> **Note:** The plan-based tier model below is superseded by the usage-based per-call pricing architecture in **Section 15.6**. The revenue projections and TAM analysis remain valid — only the pricing *mechanism* changes from plan tiers to per-call usage. The connector license becomes a flat monthly pipe fee ($500-2,000/mo) plus per-call enrichment pricing. See Section 15.6 for the definitive pricing model.

#### Four-Tier Pricing Architecture

**Tier 1: Connector License** (Recurring)
| Connector Type | Monthly Price | Annual | Notes |
|----------------|-------------|--------|-------|
| PLM Connector (Teamcenter, Windchill, etc.) | $3,000-8,000 | $36K-96K | Per PLM instance connected |
| ERP Connector (SAP, Oracle, etc.) | $2,000-6,000 | $24K-72K | Per ERP instance connected |
| Bidirectional Bundle (PLM + ERP) | $4,000-10,000 | $48K-120K | Discount for full pipeline |

**Tier 2: Per-Event Pricing** (Usage-Based)
| Event Type | Price Per Event | Typical Volume/Month | Monthly Revenue |
|------------|----------------|---------------------|-----------------|
| Full enrichment (all 7 capabilities) | $2-10 | 500-5,000 parts | $1K-50K |
| Cost estimation only | $1-5 | 1,000-10,000 | $1K-50K |
| Similar part search | $0.10-0.50 | 5,000-50,000 | $500-25K |
| Drawing intelligence | $1-3 | 200-2,000 | $200-6K |
| Master data enrichment | $0.50-2 | 1,000-10,000 | $500-20K |

**Tier 3: Platform Embedding** (OEM/White-Label)
| Model | Pricing | Target | Revenue Potential |
|-------|---------|--------|-------------------|
| PLM vendor embedding | 15-25% revenue share or $50K-500K/yr per vendor | Siemens, PTC, Dassault | One Teamcenter deal = 6,158 companies |
| ERP vendor embedding | $100K-300K/yr per vendor | SAP, Oracle, Infor | Access to tens of thousands of manufacturers |
| ISV embedding | Per-call pricing at volume discount | CAD/CAM, MES, QMS vendors | Extends reach into adjacent workflows |

**Tier 4: Data Products** (Subscription)
| Product | Annual Price | Target Buyer |
|---------|-------------|-------------|
| Manufacturing Cost Index (by process, material, region) | $5,000-15,000/yr | Procurement teams, consultants |
| Supplier Cost Benchmarking | $10,000-25,000/yr | Strategic sourcing, OEMs |
| Industry DFM Analytics | $5,000-10,000/yr | Design engineering teams |

#### Revenue Projections (Supersedes Section 12.5)

**Conservative Scenario — Year 5:**

| Revenue Stream | Volume | Avg. Revenue | Annual Revenue |
|----------------|--------|-------------|----------------|
| Connector licenses | 500 customers × 1.5 connectors avg | $5,000/mo | $45M |
| Per-event pricing | 300 usage-only customers | $1,500/mo avg | $5.4M |
| Platform embedding | 2 PLM/ERP vendor deals | $250K/yr avg | $0.5M |
| **Total Conservative** | | | **$50.9M ARR** |

**Growth Scenario — Year 5:**

| Revenue Stream | Volume | Avg. Revenue | Annual Revenue |
|----------------|--------|-------------|----------------|
| Connector licenses | 2,000 customers × 1.8 connectors avg | $5,500/mo | $237.6M |
| Per-event pricing | 5,000 usage-only customers | $1,000/mo avg | $60M |
| Platform embedding | 5 vendor deals | $500K/yr avg | $2.5M |
| Data products | 2,000 subscriptions | $12,000/yr avg | $24M |
| **Total Growth** | | | **$324.1M ARR** |

**Venture Scale — Year 7-8:**

| Revenue Stream | Volume | Annual Revenue |
|----------------|--------|----------------|
| Connector licenses | 5,000 customers × 2 connectors | $720M |
| Per-event pricing | 10,000 customers | $180M |
| Platform embedding | 10 vendor deals | $25M |
| Data products | 10,000 subscriptions | $120M |
| **Total Venture Scale** | | **$1.045B ARR** |

**Key difference vs. Section 12**: Connector revenue (Tier 1) is entirely new and dominates the model. 2,000 connectors × $5,500/mo = $132M ARR from connectors alone — this revenue stream didn't exist in Section 12's standalone API model.

**Unit economics**: ~$0.03 marginal cost per enrichment event (inference compute + storage) vs. $1-10 revenue = **90%+ gross margin**. Connector licenses are essentially pure software margin.

### 13.6 Revised Competitive Analysis

#### How the Paradigm Shift Changes the Landscape

**aPriori: From competitor to partner.** Section 12 identified aPriori as the primary competitive threat. With the oracle partnership model, aPriori becomes the training data source rather than the competitor. Their 440+ process models train our AI; we distribute their knowledge to the SMB market they can't reach.

**PLM/ERP embedding changes go-to-market entirely.** Section 12's GTM was developer-first (Twilio model): documentation → sandbox → self-serve signup → usage growth. Section 13 adds an enterprise GTM channel: **sell to one PLM vendor → distribute to their entire installed base.** One Teamcenter partnership deal = access to 6,158 companies. One SAP deal = access to 37,500 companies. This is the Stripe-in-Shopify play at manufacturing scale.

#### Updated Moat Analysis

| Moat Dimension | Section 12 (Standalone API) | Section 13 (Middleware) | Why Stronger |
|---------------|---------------------------|------------------------|-------------|
| **Data Flywheel** | Medium — grows slowly from customer data | **Strong from day one** — 9M aPriori-labeled pairs + customer feedback loop | 9M labels vs. zero at launch |
| **Integration Depth** | Low — stateless API, easy to switch | **Very Strong** — embedded in PLM→ERP pipeline | Removing middleware = 6-18 month project |
| **Domain Expertise** | Medium — formulas + AI learning over time | **Strong** — inherited from aPriori's 23 years of process models | Day-one accuracy of +/-5-15% |
| **Accuracy** | +/-30% at launch, improving | **+/-5-15% at launch**, improving to +/-3-8% | Competitive with aPriori from day one |
| **Network Effects** | Weak — per-tenant data silos | **Moderate** — cross-customer benchmarking, shared part libraries | More customers = better cost indices |
| **Switching Costs** | Low — API-level switching | **Very High** — 7 capabilities × PLM/ERP integration | Only increases over time |

#### New Threat: PLM/ERP Vendors Build Internally

The most credible threat in the middleware model is that Siemens, PTC, or SAP build cost estimation internally.

**Why this is unlikely:**
- **Platform companies embed, they don't build.** Salesforce acquired and embedded Einstein (AI), MuleSoft (integration), Tableau (analytics) rather than building from scratch. Siemens acquired Polarion (ALM), Camstar (MES), Mendix (low-code). The pattern is acquire or partner, not build.
- **Manufacturing cost estimation is deeply specialized.** aPriori spent 23 years and ~$109M building 440+ process models. No PLM vendor will replicate this as a side project.
- **Vendor neutrality matters.** A Siemens-built cost estimation tool wouldn't be trusted by PTC Windchill customers, and vice versa. CADPrice as an independent middleware layer serves all PLM vendors neutrally — this is the same reason MuleSoft (vendor-neutral integration) succeeded alongside Salesforce's own integration tools.

### 13.7 Technology Readiness (Revised)

#### Updated Readiness Assessment

| Component | Section 12 Status | Section 13 Status | Change |
|-----------|-------------------|-------------------|--------|
| **Launch accuracy** | +/-30% (formula bootstrap) | +/-5-15% (oracle labeling) | Major improvement |
| **Cold-start timeline** | 12-18 months to useful | Solved from day one | Eliminated |
| **Training data volume** | ~1K synthetic labels | 9M labeled pairs | 9,000× increase |
| **Pre-training pipeline** | Feature extraction + formula labels | Feature extraction + oracle labels | Same pipeline, better labels |
| **Per-tenant LoRA** | Same | Same | Unchanged |
| **Active learning loop** | Same | Same | Unchanged |
| **Vector store (similarity)** | Same | Same | Unchanged |
| **Drawing intelligence** | Same | Same | Unchanged |
| **PLM/ERP connectors** | Not planned | New component (8 systems) | New |
| **Bidirectional pipeline** | Not planned | New component | New |
| **Event-driven architecture** | Not planned | New component | New |

#### What Stays the Same

The core AI pipeline from Sections 11-12 is unchanged in architecture — only the data quality improves:

1. **Geometry feature extraction** (OpenCascade + PythonOCC) — pre-trained on STEP files
2. **Drawing intelligence** (PyMuPDF + LLM extraction) — extracts material, tolerances, GD&T from PDFs
3. **Cost estimation model** — now trained on 9M oracle labels instead of formula-generated labels
4. **Per-tenant LoRA fine-tuning** — adapts base model to each customer's cost structure
5. **Active learning loop** — identifies high-uncertainty predictions for human review
6. **Vector store** (Qdrant/Pinecone) — geometry embeddings for similar part search

#### New Components

**PLM/ERP Connector Framework:**
```
EventReceiver (standardized interface)
  ├── TeamcenterConnector (REST API + T4EA)
  ├── WindchillConnector (OData + ESI)
  ├── ThreeDExperienceConnector (REST + JMS)
  ├── SAPConnector (OData V2/V4 + Event Mesh)
  ├── OracleConnector (REST + FBDI)
  ├── DynamicsConnector (REST + Dataverse)
  ├── InforConnector (ION API Gateway)
  └── FusionVaultConnector (REST)

DataPublisher (standardized interface)
  ├── Enriched part records → ERP
  ├── Cost estimates → ERP cost centers
  ├── DFM feedback → PLM notifications
  ├── Classification codes → ERP material master
  └── Similar part alerts → PLM workflow
```

This leverages the architectural pattern from RattleApp's existing connector framework (`app/connectors/engine.py`) — the `EventReceiver`/`DataPublisher` abstraction is a scaled version of the existing `ExchangeTask`/`slots.py` pattern.

**Bidirectional Data Pipeline:**
```
PLM → [New Part Event] → EventReceiver → Enrichment Pipeline → DataPublisher → ERP
                                                                      │
ERP → [Production Complete] → EventReceiver → Training Pipeline ──────┘
                                                    │
                                              LoRA Fine-Tune
                                                    │
                                              Model Update
```

#### Infrastructure Requirements

| Component | Technology | Effort Estimate | Priority |
|-----------|-----------|-----------------|----------|
| Oracle labeling pipeline | Python + aPriori API + Airflow/Prefect | 6-8 weeks | P0 (enables everything) |
| Training pipeline (9M labels) | PyTorch + distributed training | 4-6 weeks | P0 |
| PLM connector (Teamcenter first) | Python + REST client + event handling | 8-12 weeks per connector | P1 |
| ERP connector (SAP first) | Python + OData client + Event Mesh | 8-12 weeks per connector | P1 |
| Event-driven middleware | FastAPI + Celery + Redis + event schema | 6-8 weeks | P1 |
| Bidirectional feedback pipeline | Celery + model retraining scheduler | 4-6 weeks | P2 |
| Data products infrastructure | Analytics DB + dashboard + API | 8-12 weeks | P3 |

### 13.8 Revised Risk Matrix

#### Risks Mitigated by the Paradigm Shift

| Risk (from Sections 11-12) | Previous Rating | New Rating | Why Changed |
|---------------------------|----------------|-----------|-------------|
| **Accuracy too low at launch** | High severity / High likelihood | High / **Low** | 9M oracle-labeled training pairs produce +/-5-15% from day one |
| **Cold start too slow** | High / High | High / **Very Low** | Pre-trained on oracle data; no customer data required for launch |
| **Data flywheel takes too long** | Medium / Medium | Medium / **Low** | Flywheel starts with 9M labels, not zero; customer data accelerates, doesn't bootstrap |
| **Customer trust in AI accuracy** | High / Medium | High / **Low-Medium** | +/-5-15% is competitive with aPriori enterprise; builds trust faster |

#### New Risks Introduced

| Risk | Severity | Likelihood | Mitigation |
|------|----------|-----------|------------|
| **aPriori partnership fails** | Critical | Medium | simus costing24 Partner Module as backup; Siemens TCM API as tertiary option. Labeled data from even partial aPriori access has permanent value. |
| **aPriori license cost prohibitive** | High | Medium | Negotiate Training Data Partnership (mutual R&D, not commercial license). Frame value: we open their SMB market. Worst case: simus Partner Module (free) covers 80% of parts. |
| **aPriori builds competing API** | High | Low-Medium | 23 years of enterprise DNA makes API/PLG pivot difficult (Salesforce Essentials precedent). Once 9M labels are collected, trained model weights are independent. Middleware value prop is orthogonal to pure costing API. |
| **PLM vendor builds internally** | High | Low | Platform companies embed/acquire, not build (Salesforce-Einstein pattern). 440+ process models too specialized. Vendor neutrality matters — Siemens-built tool won't serve PTC customers. |
| **Integration complexity underestimated** | High | Medium | Start with one PLM (Teamcenter) + one ERP (SAP) — prove the pattern before expanding. Leverage existing RattleApp connector framework for architectural patterns. Budget 8-12 weeks per connector. |
| **PLM partnership takes too long** | Medium | High | Launch standalone API (Section 12 model) in parallel. Middleware is the destination; API is the viable starting point. Don't block revenue on partnership timelines. |
| **Oracle labeling takes longer than estimated** | Medium | Medium | Start with simus (faster API, simpler integration) for initial 60K labels. Parallelize with aPriori onboarding. 60K labels sufficient for MVP model. |

#### Unchanged Risks

| Risk | Rating | Notes |
|------|--------|-------|
| **Manufacturing slow to adopt** | Medium severity / Medium likelihood (decreasing) | Conservative industry, but AI adoption accelerating post-2024. PLM embedding reduces adoption friction. |
| **Market too small** | Low / Low | $1.5-2.1B direct TAM + $26-70B PLM embedding TAM. Middleware model addresses larger TAM than standalone API. |
| **CAC too high** | Medium / Medium (reduced) | PLM vendor embedding distributes acquisition cost across installed base. One partnership deal = thousands of customers. |

### 13.9 Revised Verdict

#### How Section 12's Five Conditions Are Strengthened

Section 12.12 identified five conditions that must be true for a billion-dollar outcome. Each is now substantially stronger:

**1. PLM embedding: From aspiration to core business.**
Section 12 mentioned PLM embedding as a growth lever. Section 13 makes it **the business model** — pre-built connectors for 8 systems, event-driven architecture, bidirectional data flow. One Teamcenter deal doesn't just help growth; it's how the business fundamentally works.

**2. Cold start: From 12-18 month ramp to day-one capability.**
Section 12 projected +/-30% accuracy at launch, requiring 12-18 months to reach useful levels. With 9M oracle-labeled training pairs, CADPrice launches at **+/-5-15%** — competitive with aPriori enterprise from day one. Customers see value immediately.

**3. International: From future expansion to built-in capability.**
Multi-region labeling (US Midwest, Germany, China) is built into the 9M-label training data. The model understands regional cost variations from day one, not as a future localization project.

**4. Beat aPriori's reaction time: From months-of-acquisition head start to 9M-label structural moat.**
Section 12 worried about aPriori launching an API within 18-24 months. With 9M oracle labels + trained model weights + PLM/ERP middleware integration, the head start is structural, not temporal. Even if aPriori launches an API, they lack the middleware, the multi-system connectors, and the seven-capability enrichment bundle.

**5. Expand beyond cost: From multiple APIs to single enrichment event.**
Section 12 proposed separate CostAPI and EnrichAPI products. Section 13 delivers all seven capabilities in a **single enrichment event** triggered automatically by PLM/ERP activity. This is not seven products; it's one intelligence layer with seven outputs.

#### The Salesforce-Einstein Analogy

The most accurate analogy for this business is **Salesforce Einstein** — AI intelligence embedded directly in the workflow platform, not offered as a standalone AI tool.

- Salesforce Einstein doesn't ask users to upload data and wait for predictions. It enriches CRM records automatically as they flow through Salesforce.
- CADPrice doesn't ask users to upload STEP files and wait for cost estimates. It enriches part records automatically as they flow from PLM to ERP.
- Einstein's value compounds with usage (more CRM data = better predictions). CADPrice's value compounds with usage (more parts processed = better cost models + richer similar-part database).

#### Revised Path to $1B

| Phase | Timeline | Milestone | Revenue |
|-------|----------|-----------|---------|
| **Technology Validation** | Months 0-6 | Oracle labeling pipeline complete, base model trained on 9M labels, accuracy validated at +/-5-15% | $0 (investment) |
| **Standalone API Launch** | Months 6-12 | API product live (Section 12 model), first 50 paying customers, accuracy tracking | $150K ARR |
| **First PLM Connector** | Months 12-18 | Teamcenter connector live, first 5 middleware customers, event-driven enrichment proven | $1M ARR |
| **First ERP Connector** | Months 15-21 | SAP S/4HANA connector, bidirectional pipeline, production data feedback loop active | $3M ARR |
| **100 Connector Customers** | Months 18-30 | Second PLM + ERP connectors (Windchill, Oracle), connector revenue surpasses API revenue | $15-25M ARR |
| **First Platform Deal** | Months 24-36 | PLM vendor embedding (white-label in Teamcenter/Windchill marketplace) | $50-80M ARR |
| **Data Products Launch** | Months 30-42 | Manufacturing cost indices, supplier benchmarking, DFM analytics | $100-200M ARR |
| **Venture Scale** | Months 48-72 | 5,000+ connectors, 10+ platform deals, data products at scale | $500M-1B+ ARR |

#### Why This Is a Different Business

Section 12 described an **API company** — the Twilio/Plaid of manufacturing. High volume, low touch, developer-first.

Section 13 describes a **manufacturing intelligence middleware company** — MuleSoft/Informatica with embedded AI. The differences are critical:

| Dimension | API Company (Section 12) | Middleware Company (Section 13) |
|-----------|------------------------|---------------------------------|
| **Revenue model** | Per-call usage | Connector license + usage + platform + data |
| **ACV** | $500-5,000/mo | $5,000-20,000/mo |
| **Switching costs** | Low (API-level) | Very high (PLM/ERP pipeline) |
| **Sales motion** | Self-serve + PLG | Enterprise sales + PLM vendor partnerships |
| **NRR** | 110-120% | 130-150% |
| **Gross margin** | 80-85% | 85-92% (connector licenses = pure software) |
| **Path to $1B** | 50,000+ customers needed | 5,000 connectors + platform deals |

#### Revised Six Conditions for $1B

1. **Secure aPriori training data partnership** within 6 months (or simus as backup). The oracle labeling pipeline is the foundation — without it, Section 13 reverts to Section 12's slower path.

2. **Ship Teamcenter connector** within 18 months. The first PLM connector proves the middleware model. If enterprise integration is too slow or too expensive, pivot back to standalone API.

3. **Achieve +/-10% accuracy** within 12 months (for pre-trained processes). Oracle-labeled base model should achieve +/-5-15%; customer data fine-tuning pushes toward +/-5-8%. If accuracy stalls above +/-15%, the value proposition weakens.

4. **Land one platform embedding deal** within 36 months. A single PLM vendor deal (Teamcenter marketplace, Windchill extension, etc.) transforms unit economics and proves the distribution model.

5. **Build bidirectional feedback loop** with at least 100 customers within 24 months. The production-data-to-model-improvement pipeline is what enables accuracy to surpass aPriori long-term. Without it, we remain dependent on the oracle.

6. **Resist marketplace pull.** As with Section 12's Spanflug counterpoint, the temptation to become a CNC marketplace (higher per-transaction revenue) must be resisted. The middleware model is higher margin, more defensible, and has a clearer path to $1B than marketplace operations.

#### The Spanflug Counterpoint Revisited

Spanflug built AI cycle time prediction from CAD geometry — essentially capability #4 (cost estimation). They chose to become a marketplace. In the middleware model, the counterpoint is even stronger:

- Marketplace requires fulfillment operations for one capability (cost → order → manufacture)
- Middleware monetizes seven capabilities across thousands of companies through software alone
- Marketplace gross margin: 20-30%. Middleware gross margin: 85-92%.
- Marketplace defensibility: network effects (strong but geographically limited). Middleware defensibility: integration depth + data flywheel + seven-capability bundle (compounds globally).

The middleware path is not just higher margin — it's structurally more defensible and scalable.

### 13.10 CAD Format Translation Strategy — Solving the Native Format Gap

#### The Problem

CADPrice's API accepts STEP files. But real-world users have native CAD formats (.sldprt, .catpart, .prt, .ipt, .3dmodel, etc.). For the platform to work as a **background enrichment and cost calculation service** — especially when embedded in PDM/PLM/ERP systems — users cannot be expected to manually export STEP. The format barrier kills adoption at scale.

**The core problem:** Native CAD formats (SolidWorks, CATIA, NX, Creo, Inventor) are proprietary. You cannot read them without either the original CAD software or a commercial translation library that has licensed/reverse-engineered the format specs.

#### The Four Strategic Options

##### Option A: Thin CAD Plugins (Export STEP + Call API)

Build lightweight add-ins for each major CAD tool that export the current part to STEP and POST it to the CADPrice API.

| CAD System | Market Share | Plugin API | Language | Effort |
|-----------|-------------|-----------|----------|--------|
| SolidWorks | ~28% mechanical CAD | SolidWorks API | C#/.NET, VBA | 2-3 weeks |
| CATIA V5/V6 | ~15% (aerospace/auto) | CAA RADE / Automation | C++, VBA | 4-6 weeks |
| Siemens NX | ~13% | NXOpen | C++, Python, .NET, Java | 3-4 weeks |
| PTC Creo | ~10% | Toolkit / J-Link | C/C++, Java | 3-4 weeks |
| Inventor | ~12% | Inventor API | .NET | 2-3 weeks |
| Fusion 360 | ~8% (growing fast) | Fusion API | Python, JavaScript | 2-3 weeks |
| Onshape | ~3% (cloud-native) | REST API (built-in!) | Any (HTTP calls) | 1 week |

**Best for:** Real-time design feedback ("cost while you design"). Plugin becomes a distribution channel via CAD app marketplace listings. Zero server-side translation cost — the CAD system's own exporter handles STEP conversion natively with highest fidelity.

**Limitation:** 5-7 separate codebases. Cannot process files already in a vault/PDM without the CAD tool running. Doesn't solve the "batch process 10,000 legacy parts" use case.

##### Option B: Server-Side Commercial Translation Library

Deploy a commercial CAD translation SDK on the server that reads native formats and outputs STEP — no CAD licenses required.

| Library | Vendor | Formats | Language | Licensing |
|---------|--------|---------|----------|-----------|
| **CAD Exchanger SDK** | CAD Exchanger (OCCT-based) | 30+ (SW, CATIA, NX, Creo, Inventor, JT, Parasolid) | C++, Python, C#, Java | Per-machine distribution fee |
| **HOOPS Exchange** | Tech Soft 3D | 30+ | C++ | OEM license (~$50K-200K/yr) |
| **3D InterOp** | Spatial (Dassault) | 30+ | C++ | OEM license (enterprise) |
| **Datakit CrossManager** | Datakit | 40+ | C++/CLI batch | Per-seat or OEM |
| **3D_Kernel_IO** | CoreTechnologie | 30+ | C++ | OEM license |

**CAD Exchanger is the recommended choice** because: built on OpenCascade (same kernel as PythonOCC — consistent geometry), has Python bindings, Docker-friendly, transparent per-machine pricing, Cloud API available as fallback, no CAD software dependency.

**Best for:** API-first use case (accept any format → return results). Also enables batch processing and legacy vault migration. Single solution handles ALL native formats headless.

##### Option C: PLM/PDM-Side Translation (Let the Vault Do It)

Major PLM systems already have built-in format translation. Configure the PLM to auto-export STEP on part release/check-in, then trigger the CADPrice API via webhook.

```
Designer saves in NX → checks into Teamcenter
  → Teamcenter Dispatcher auto-generates STEP derivative
  → Workflow fires webhook to CADPrice API
  → CADPrice returns enrichment/cost → written back to Teamcenter attributes
```

Teamcenter has a Dispatcher service supporting automatic STEP translation as a workflow action. Windchill has CAD Worker nodes. 3DEXPERIENCE has built-in translators.

**Best for:** Enterprise PLM integration deals. Zero translation infrastructure to build. Only works for companies WITH a PLM system (excludes SMBs).

##### Option D: Managed Cloud Translation (CAD Exchanger Cloud API)

Use CAD Exchanger's Cloud API as a managed service — upload native file via REST, get STEP back. Pay-per-conversion. Zero infrastructure to operate.

**Best for:** MVP / early-stage when volume is low. Adds per-conversion cost and external data transfer (IP sensitivity concern for defense/aerospace).

#### Recommended Strategy: Layered Ingestion Architecture

The answer is all four options, deployed in sequence as a **layered strategy matching each integration pattern:**

```
┌─────────────────────────────────────────────────────────────────────┐
│                    CADPrice Format Ingestion Layer                   │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  Layer 1: STEP/IGES Pass-Through (Phase 1 — Day 1)                 │
│  ├── Accept STEP/IGES directly — zero translation needed            │
│  └── Covers: API developers, existing STEP workflows               │
│                                                                     │
│  Layer 2: Server-Side Translation (Phase 2-3)                       │
│  ├── CAD Exchanger SDK (self-hosted, Docker container)              │
│  ├── Accept ANY native format → auto-convert to STEP → process     │
│  ├── Unified API: POST /v1/cost/estimate with format auto-detect   │
│  └── Covers: Web uploads, batch processing, vault migrations       │
│                                                                     │
│  Layer 3: CAD Plugins (Phase 3-4)                                   │
│  ├── SolidWorks add-in (C# — largest market share)                 │
│  ├── Fusion 360 add-in (Python — fastest growing)                  │
│  ├── Onshape integration (REST API — trivial, ~1 week)             │
│  ├── NX, Creo, Inventor, CATIA (by customer demand)               │
│  └── Covers: Real-time "cost while you design" feedback            │
│                                                                     │
│  Layer 4: PLM Connectors (Phase 7)                                  │
│  ├── Teamcenter: webhook on release + Dispatcher STEP generation   │
│  ├── Windchill: CAD Worker + REST webhook                          │
│  ├── 3DEXPERIENCE: 3DSpace API integration                        │
│  └── Covers: Enterprise automated enrichment of entire part vaults │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

##### Who Uses Which Layer

| User Type | Need | Layer |
|-----------|------|-------|
| Developer integrating via API | Sends STEP (already converted) | Layer 1 |
| Purchasing engineer uploads file from email | Drops .sldprt into web portal | Layer 2 |
| Designer wants instant cost feedback | Clicks button in SolidWorks | Layer 3 |
| PLM admin wants all parts auto-enriched | Configures Teamcenter webhook | Layer 4 |
| Company migrating 50K legacy parts from file share | Batch upload via API | Layer 2 |

#### Impact on CADPrice Architecture

##### API Schema Change

Rename `step_file` to `cad_file` in all API endpoints (do this NOW, before launch, to avoid breaking changes):

```
POST /v1/cost/estimate
{
  "cad_file": "<base64 or presigned URL>",   // ANY format (auto-detected)
  "format_hint": "solidworks",               // optional, helps routing
  "drawing_pdf": "<optional>",
  "material": "AL_6061_T6",
  "quantity": 10
}
```

##### Internal Pipeline Change

```
Upload → S3 → [Format Detection by extension + magic bytes] →
  ├── STEP/IGES → directly to geometry worker
  └── Native format → translator worker (CAD Exchanger) → STEP in S3 → geometry worker
```

##### Docker Addition

```yaml
# docker-compose.yml
translator:
  build: ./Dockerfile.translator     # CAD Exchanger SDK + Python bindings
  volumes:
    - shared-files:/data/files
  environment:
    - CAD_EXCHANGER_LICENSE_KEY=...
```

##### Database Changes

```sql
ALTER TABLE jobs ADD COLUMN original_format VARCHAR(20);   -- 'step', 'solidworks', 'catia'
ALTER TABLE jobs ADD COLUMN translated_file_key TEXT;       -- S3 key of converted STEP
ALTER TABLE jobs ADD COLUMN translation_time_ms INTEGER;    -- duration tracking
```

##### New Project Structure Additions

```
cadprice/
├── cadprice/
│   ├── core/
│   │   ├── translation/
│   │   │   ├── detector.py          # Format detection (extension + magic bytes)
│   │   │   ├── cad_exchanger.py     # CAD Exchanger SDK wrapper
│   │   │   └── registry.py          # Format → translator routing
│   ├── workers/
│   │   ├── translation_tasks.py     # Celery tasks for format conversion
│   │
│   ├── plugins/                     # CAD plugin source code
│   │   ├── solidworks/              # C# SolidWorks add-in
│   │   ├── fusion360/               # Python Fusion 360 add-in
│   │   └── onshape/                 # Onshape REST integration
```

#### Phase Mapping

| Layer | Ships In | Extra Effort | Cost |
|-------|----------|-------------|------|
| Layer 1: STEP pass-through | Phase 1 (already planned) | 0 | $0 |
| Layer 2: Server translation | Phase 2-3 | 3-4 weeks | CAD Exchanger license |
| Layer 3: SolidWorks plugin | Phase 3-4 | 2-3 weeks | $0 (SW API is free) |
| Layer 3: Fusion 360 plugin | Phase 3-4 | 2-3 weeks | $0 (Fusion API is free) |
| Layer 3: Onshape integration | Phase 3 | 1 week | $0 (REST API built-in) |
| Layer 4: PLM connectors | Phase 7 (already planned) | Per-connector | Enterprise sales |

#### Sources

- [CAD Exchanger SDK](https://cadexchanger.com/products/sdk/) — 30+ formats, Python bindings, Docker deployment
- [CAD Exchanger SDK Pricing](https://cadexchanger.com/products/sdk/pricing/) — per-machine distribution fee model
- [HOOPS Exchange](https://www.techsoft3d.com/products/hoops/exchange/) — enterprise CAD translation, 30+ formats
- [3D InterOp](https://www.spatial.com/solutions/cad-translation/3d-interop) — Dassault subsidiary, enterprise pricing
- [Datakit Cross CAD](https://trimech.com/datakit-cross-cad/) — 40+ format support
- [CoreTechnologie SDK](https://coretechnologie.com/find-out-more/cad-translation-sdk/) — CAD translation SDK
- [Onshape REST API](https://onshape-public.github.io/docs/api-intro/) — built-in STEP export via HTTP
- [Teamcenter STEP Export](https://community.plm.automation.siemens.com/t5/Teamcenter-Administrators-Forum/Automatic-STEP-export-in-Teamcenter-8-3/td-p/276441) — Dispatcher-based auto translation

---

## Appendix A: Luminarity API Quick Reference

**Base URL:** `https://api2.shouldcosting.com`

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/costchecker` | POST | Upload file (base64 + customerID + fileExtension) |
| `/api/costchecker/{filenameServer}` | GET | Poll status |
| `/api/costchecker/miningresult/{filenameServer}` | GET | Get structured results |
| `/api/cadminer/progress/{fileName}` | GET | Detailed progress (assemblies) |
| `/api/cadminer/{fileName}` | GET | Full entry with preview PNG |

**Authentication:** `customerID` field in POST body (format: `lum-{hash}-{tenant}`)
**File formats:** STEP only (`.stp`, `.step`). PDF, IPT, native CAD → rejected as `INVALID_DATATYPE`.

## Appendix B: Existing Extension Points in RattleApp

| Extension Point | How It Helps |
|-----------------|-------------|
| `Part.custom_fields` (JSON) | Zero-migration geometry storage |
| `PartDocument` model | Already tracks file attachments per part |
| Connector framework | Could wrap Luminarity as an ExchangeTask with `upsert_part` action |
| `rollup_cost()` | Already performs BOM cost aggregation — formula-based `part_cost` flows through automatically |
| Celery infrastructure | Async task execution for upload/poll/calculate pipeline |
| `Company.ai_settings` (JSON) | Natural home for Luminarity config and cost formula settings |
| Slot system | UI trigger points for "Analyze STEP" button on part detail |
| `Derivative` model | Unused but designed for derived analysis artifacts — natural home for drawing analysis |

## Appendix C: Drawing Intelligence Framework References

| Framework | Type | Link | Notes |
|-----------|------|------|-------|
| **eDOCr2** | Open-source | [github.com/javvi51/edocr2](https://github.com/javvi51/edocr2) | Segments drawings into regions; 93.75% text recall, <1% CER; integrates Qwen2-VL/GPT-4o |
| **YOLOv11 + Donut** | Research | [arxiv.org/abs/2505.01530](https://arxiv.org/abs/2505.01530) | 9 categories (GD&T, tolerances, materials, threads, etc.); 97.3% F1 |
| **Werk24** | Commercial API | [werk24.io](https://werk24.io) | >95% PMI accuracy; structured JSON; no training data required |
| **Mistral OCR** | API | [mistral.ai/news/mistral-ocr](https://mistral.ai/news/mistral-ocr) | Strong on structured documents; not specialized for engineering drawings |
| **Infrrd IDP** | Commercial | [infrrd.ai](https://www.infrrd.ai) | Adaptive deep learning platform for engineering drawings |
| **iCaptur** | Commercial | [icaptur.ai](https://icaptur.ai) | AI-powered OCR specifically for CAD engineering drawings |

### Key Research Insight

Traditional OCR fails on engineering drawings because text is interspersed with dimension lines, GD&T symbols (⌀, ⊥, ∥, ○), and rotated annotations. The state-of-the-art approach combines:
1. **Object detection** (YOLO) to segment the drawing into regions (title block, dimension, FCF, note)
2. **Document understanding models** (Donut, VLMs) to interpret each region contextually
3. **Domain normalization** to map extracted text to canonical values (e.g., "Al 6061" → "AL_6061")

For RattleApp, the VLM approach (GPT-4o/Claude vision) approximates steps 1-3 in a single API call, trading maximum accuracy for zero infrastructure overhead.

## Appendix D: External Provider Quick Reference Table

*Comprehensive reference for all providers reviewed in Section 10. Research date: February 2026.*

| Provider | Category | API | Cost Model | Processes | Pricing | Integration Effort | RattleApp Relevance |
|----------|----------|-----|------------|-----------|---------|-------------------|---------------------|
| **aPriori** | Should-cost | REST (`aP Generate`) | 50+ processes, digital twin simulation | All major manufacturing | €50K–200K+/yr | High | Design reference only; too expensive for multi-tenant SaaS |
| **Costimator** | Should-cost | Desktop only (`3DFX` add-on) | 2M+ validated cycle times | CNC, fabrication, assembly | ~$15K + 20% maint. | High | Benchmark data source; no integration path |
| **Spanflug MAKE** | Should-cost | ERP export only | AI-trained on 1M+ parts; machine hourly rate calculator | CNC turning/milling | Free tier (5/mo) → subscription | Medium | **Closest design reference** for Phase 0 formula engine; use free tier for validation |
| **3D Spark** | Should-cost | Unknown (SaaS) | 15+ technologies, ±5% accuracy | AM + conventional | SaaS subscription | Medium | Interesting for AM make-or-buy; monitor for API availability |
| **CloudNC** | Cycle time | CAM plugin only | Per-operation AI toolpath analysis | CNC milling | $99/mo | Low (needs CAM env) | Not suitable for headless API integration |
| **Xometry** | RFQ marketplace | **REST + webhooks** (`developer.xometry.com`) | Market-based AI pricing | CNC, SM, 3DP, IM, tube, die cast, stamping | Free (per quote) | **Low-Medium** | **Primary integration target** — only viable RFQ API |
| **Protolabs** | RFQ marketplace | No (Fusion 360 add-in) | ML on millions of prior parts | CNC, IM, 3DP, SM | Premium | High | No integration path; premium pricing |
| **Fictiv** | RFQ marketplace | No | AI quoting + Materials.AI | CNC, SM, IM, 3DP | Competitive | High | Acquired by MISUMI (2025); monitor for API |
| **DigiFabster** | Quoting SaaS | Yes (gated) | Configurable shop pricing + AI calibration | CNC, 3DP, SM, laser | From $350/mo | Medium | Relevant if customers are job shops using DigiFabster |
| **Fractory** | RFQ marketplace | No | Market-based | SM, CNC, tube | Market-rate | High | No integration path; sheet metal focus |
| **PCBWay** | RFQ marketplace | Partnership API | Market-based | PCB, CNC, 3DP, IM | Market-rate | Medium | Relevant only for electronics manufacturers |
| **Orderfox** | Matchmaking | No (advisory board) | AI supplier matching | CNC (primary) | Platform fees | High | Monitor Gieni AI for MCP-based API; €1B+ valuation signals market importance |
| **partZpro** | Matchmaking | No | AI cost-driver analysis | Various | Platform fees | High | Cost-driver analysis concept valuable for Phase 2 UI |
| **Luminarity** | Geometry only | REST (tested, documented) | **None** — geometry extraction only | STEP file analysis | Per-query (TBD) | Low | Already assessed in Sections 2.1 and 6.1; provides input to formula engine |

### Key Takeaways

1. **Only Xometry has a public REST API** for instant manufacturing quotes — making it the sole viable external RFQ integration partner
2. **No platform offers a licenseable cost formula engine as an API** — aPriori, Costimator, and Spanflug all require their own UI or desktop environment; this validates the "build your own" approach for Phase 0
3. **Spanflug MAKE is the closest conceptual match** to RattleApp's planned formula engine — study their machine hourly rate decomposition and cycle time estimation approach
4. **The make-or-buy pattern** (internal should-cost + Xometry external quote) delivers high value with minimal integration complexity — requires only the Phase 0 engine + one connector
5. **Monitor Orderfox/Gieni AI** — their MCP-based AI approach and €1B+ valuation suggest this space is evolving rapidly; an MCP API could be integrated via the connector framework in the future

## Appendix E: Open CAD Dataset Reference

*Full reference for all datasets evaluated in Section 11.2. Research date: February 2026.*

### E.1 Datasets with Machining Feature Labels

These datasets provide per-face or per-feature machining annotations — directly useful for training manufacturing feature recognition and process classification models.

#### CADSynth (Beihang University)

| Property | Value |
|----------|-------|
| **Size** | 100,000 models, 6.2 GB |
| **Format** | STEP + JSON metadata + B-Rep graph (.bin) |
| **Labels** | Per-face machining feature class (24 types: through holes, blind holes, slots, steps, chamfers, fillets, pockets, bosses, etc.) |
| **Generation** | Algorithmically synthesized from parametric rules — not real-world parts |
| **License** | CC-BY 4.0 |
| **Download** | [Hugging Face: SolidGen/CADSynth](https://huggingface.co/datasets/SolidGen/CADSynth) |
| **Paper** | SolidGen: Synthesizing CAD Models with Machining Features (2024) |
| **RattleApp use** | Pre-train machining feature classifier (Phase B); face-level feature labels for process routing |

#### MFCAD++ (Queen's University Belfast)

| Property | Value |
|----------|-------|
| **Size** | 59,665 models |
| **Format** | STEP |
| **Labels** | Per-face machining feature class labels |
| **Generation** | Extended from original MFCAD dataset; focused on single machining features per model |
| **License** | Academic use |
| **Download** | Available via paper authors |
| **Paper** | MFCAD++: Multi-view Feature Recognition (2022) |
| **RattleApp use** | Fine-tune feature recognition; simpler models than CADSynth (good for validation) |

#### MFInstSeg

| Property | Value |
|----------|-------|
| **Size** | 60,000+ models |
| **Format** | STEP |
| **Labels** | Instance-level machining feature segmentation (distinguishes individual feature instances, not just classes) |
| **Generation** | Extends MFCAD++ with instance-level annotations |
| **License** | Academic use |
| **Download** | Available via paper authors |
| **Paper** | Machining Feature Instance Segmentation (2023) |
| **RattleApp use** | Instance-level features enable counting (e.g., "this part has 6 through-holes and 2 pockets") — feeds directly into cost formula parameters |

#### HybridCAD

| Property | Value |
|----------|-------|
| **Size** | Hybrid AM/CNC dataset (size varies by subset) |
| **Format** | STEP |
| **Labels** | Additive + subtractive manufacturing feature labels (dual annotation) |
| **Generation** | Designed for hybrid manufacturing process planning |
| **License** | Academic (Zenodo) |
| **Download** | [Zenodo](https://zenodo.org) (search: HybridCAD) |
| **Paper** | HybridCAD: Benchmark for hybrid manufacturing feature recognition |
| **RattleApp use** | Relevant if customers use both CNC and additive manufacturing; enables make-or-buy decisions between AM and CNC |

### E.2 Large-Scale Geometry Datasets (No Manufacturing Labels)

These datasets provide raw CAD geometry at scale — ideal for self-supervised pre-training of geometric encoders.

#### ABC Dataset (Onshape / NYU)

| Property | Value |
|----------|-------|
| **Size** | 1,000,000 models |
| **Format** | STEP, STL, OBJ, feature files, statistics |
| **Labels** | Parametric curves/surfaces, ground truth normals, curvature, sharp features |
| **Source** | Real Onshape models (user-created parametric CAD) |
| **License** | Onshape Terms of Service |
| **Download** | [deep-geometry.github.io/abc-dataset](https://deep-geometry.github.io/abc-dataset/) |
| **Paper** | ABC: A Big CAD Model Dataset For Geometric Deep Learning (CVPR 2019) |
| **RattleApp use** | **Primary pre-training dataset** for geometric embeddings; 1M real-world parametric CAD models; diverse geometry |

#### 1M Synthetic CAD (Beihang University)

| Property | Value |
|----------|-------|
| **Size** | 1,000,000 models, 113.7 GB |
| **Format** | STEP + JSON + B-Rep graph (.bin) + rendered images |
| **Labels** | Parametric feature modeling sequences (design history) |
| **Generation** | Algorithmically synthesized with parametric variation |
| **License** | CC-BY 4.0 |
| **Download** | [Hugging Face: SolidGen/1M-SyntheticCAD](https://huggingface.co/datasets/SolidGen/1M-SyntheticCAD) |
| **Paper** | SolidGen (2024) |
| **RattleApp use** | Augments ABC for pre-training; includes B-Rep graph format ready for GNN training; parametric sequences enable design intent understanding |

### E.3 Specialized Reference Datasets

#### NIST MBE PMI Test Cases

| Property | Value |
|----------|-------|
| **Size** | ~20 test cases |
| **Format** | STEP AP242, native CAD (Creo, NX, CATIA, SolidWorks) |
| **Labels** | Full GD&T annotations (tolerances, datums, PMI), multi-CAD format coverage |
| **Source** | NIST (National Institute of Standards and Technology) |
| **License** | Public domain (US Government work) |
| **Download** | [NIST MBE PMI Validation](https://www.nist.gov/el/systems-integration-division-73400/mbe-pmi-validation-and-conformance-testing) |
| **RattleApp use** | **Validation and testing only** — too small for training; gold-standard GD&T reference for validating Drawing Intelligence extraction accuracy (Section 5); STEP AP242 with embedded PMI for testing tolerance-aware cost estimation |

### E.4 Dataset Comparison Summary

| Dataset | Models | Machining Labels | Cost Labels | B-Rep Graph | License | Best For |
|---------|--------|-----------------|-------------|-------------|---------|----------|
| **ABC** | 1M | No | No | No (but STEP available) | Onshape ToS | Pre-training geometric encoder |
| **1M Synthetic CAD** | 1M | No | No | Yes (.bin) | CC-BY 4.0 | Pre-training + GNN training |
| **CADSynth** | 100K | Yes (24 types) | No | Yes (.bin) | CC-BY 4.0 | Feature recognition fine-tuning |
| **MFCAD++** | 59.7K | Yes | No | No | Academic | Feature recognition validation |
| **MFInstSeg** | 60K+ | Yes (instance) | No | No | Academic | Instance counting for cost params |
| **HybridCAD** | Varies | Yes (AM+CNC) | No | No | Academic | Hybrid manufacturing classification |
| **NIST MBE PMI** | ~20 | No | No | No | Public domain | GD&T validation reference |

### E.5 The Cost Label Gap

**No open dataset contains manufacturing cost labels.** This is the central challenge for AI-driven cost estimation (Section 11.3).

The only published work with real cost labels is:
- **[ArXiv 2508.12440](https://arxiv.org/html/2508.12440v1)** (2025): 13,684 automotive DWG drawings with historical production costs from ERP. Achieved 3.9-18.5% MAPE with XGBoost on 200 geometric features. **This data is proprietary and not publicly available.**

**Implication for RattleApp:** Cost labels must come from one of three sources:
1. Customer's own `Part.part_cost` history (most accurate, per-tenant)
2. Xometry API instant quotes (market-rate proxy, unlimited generation)
3. Phase 0 formula engine output (synthetic, bootstrapping only)

See Section 11.3 for the full "cold start → warm model" progression strategy.

## Appendix F: Market Data Sources

*All market data referenced in Section 12. Research date: February 2026. All figures are from published reports or public filings.*

### F.1 Manufacturing Cost Estimation Software Market

| Source | Report Title | Market Size | CAGR | Forecast Period |
|--------|-------------|-------------|------|-----------------|
| OpenPR / Dataintelo | Cost Estimating Software Market | $1.5B (2024) → $3.2B (2033) | 9% | 2024-2033 |
| Insight Partners | Manufacturing Cost Estimation Software Market | $2.1B (2024) → $5.5B (2033) | 10% | 2024-2033 |
| OpenPR | Cost Estimating Software (All Industries) | $8.5B (2024) → $19.8B (2033) | 8.8% | 2024-2033 |

### F.2 Adjacent Markets

| Source | Market | Size | CAGR | Forecast Period |
|--------|--------|------|------|-----------------|
| PS Market Research | PLM Software | $26–35B (2024) → $46–70B (2032) | 6–9% | 2024-2032 |
| Market Reports World | Master Data Management | $13.3B (2024) → $32.5B (2032) | 10.5% | 2024-2032 |
| Grand View Research | AI in Manufacturing | $47.9B (2030) | — | — |
| Mordor Intelligence | Smart Manufacturing | $233B (2024) → $479B (2032) | 14% | 2024-2032 |
| Precedence Research | Smart Manufacturing | $394B (2024) → $900B (2032) | 15.5% | 2024-2032 |
| Fortune Business Insights | Smart Manufacturing | Various estimates | 14-15% | 2024-2032 |

### F.3 API Economy Data

| Source | Metric | Value |
|--------|--------|-------|
| Business Research Insights | Global API Management Market | $7.5B (2023) → $35.3B (2032) |
| Multiple (aggregated) | AI API Market | $3.3B (2024) → $30.9B (2032), CAGR 32.2% |
| Nordic APIs | Manufacturing Edge API Deployment Growth | 42% YoY (2024) |
| Industry benchmarks (aggregated) | Traditional Integration Cost | $500K–$2M, 6–12 months |
| Industry benchmarks (aggregated) | API-First Integration Cost | $50K–$200K, 2–4 weeks |

### F.4 Competitor Revenue & Valuation Data

| Company | Data Point | Source | Date |
|---------|-----------|--------|------|
| **aPriori** | ~$64M revenue, $109M total funding | Tracxn, Crunchbase | 2024-2025 |
| **Xometry** | $545M revenue (2024) | SEC 10-K filing | FY 2024 |
| **Orderfox** | €1B+ valuation | Press release (funding round) | 2025 |
| **Twilio** | $4.46B revenue (2024) | SEC 10-K filing | FY 2024 |
| **Plaid** | $390M ARR | Published reports | 2024 |
| **Checkr** | $700M revenue (2023) | Published reports | 2023 |
| **ZoomInfo** | $5B+ valuation | Market cap / published | 2024 |
| **Stripe** | $600B+ processed volume | Published reports | 2024 |

### F.5 API Business Pattern References

| Company | Pattern | Key Metric | Source |
|---------|---------|-----------|--------|
| Twilio | Usage-based (per-message/call) | Revenue grows with customer volume | SEC filings |
| Stripe | Per-transaction fee (2.9% + $0.30) | Embedded in checkout; impossible to remove | Published pricing |
| Plaid | Per-connection + usage | 80% gross margin | Published reports |
| Clearbit | Credit-based enrichment | Embedded in CRM workflows | Pre-acquisition reports |
| Marqeta | Interchange on volume | Small margin × massive scale | SEC filings |

### F.6 Academic & Technology References

| Reference | Key Finding | Relevance to Section 12 |
|-----------|-------------|------------------------|
| MaProNet (2025) | GNN-based process selection from geometry | Process classification is solved (Section 12.6) |
| ArXiv 2508.12440 (2025) | 3.9-18.5% MAPE on real production costs | ML cost estimation validated (Section 12.6) |
| eDOCr2 + YOLOv11 | 97.3% F1 on engineering drawing annotation detection | Drawing intelligence is solved (Section 12.6) |
| HG-CAD (Autodesk, 2024) | Material prediction + cost estimation from B-Rep | Foundation model approach works (Section 12.6) |

*Note: Full academic references with links are provided in Section 11.9. Market data figures may vary across reports due to different methodologies and definitions. Ranges are provided where multiple sources disagree.*

---

## Appendix G: aPriori & Classmate Cloud Technical Reference

*Technical reference for the two deterministic cost engines used as AI training oracles in Section 13. Research date: February 2026.*

### G.1 aPriori — Platform Overview

| Attribute | Detail |
|-----------|--------|
| **Company** | aPriori Technologies, Inc. (Concord, MA) |
| **Founded** | 2002 (23 years of process model development) |
| **Revenue** | ~$64M (2024, Tracxn) |
| **Total Funding** | ~$109M (Crunchbase) |
| **Customers** | ~500-1000 enterprise (BMW, Caterpillar, John Deere, Airbus, GE, Honeywell) |
| **Pricing** | $50K-500K+/yr enterprise license |
| **Core Technology** | Physics-based parametric cost models + digital factories |

### G.2 aPriori Process Model Coverage (440+ Models)

| Process Family | Example Processes | Model Depth |
|---------------|-------------------|-------------|
| **CNC Machining** | 3-axis milling, 5-axis milling, turning, mill-turn, Swiss-type | Cycle time, toolpath estimation, fixture complexity, tool wear |
| **Sheet Metal** | Laser cutting, punching, bending, stamping, progressive die, deep drawing | Nesting, bend deductions, die complexity, springback |
| **Casting** | Sand casting, investment casting, die casting (HPDC, LPDC, gravity) | Mold complexity, gating, solidification analysis |
| **Forging** | Open die, closed die, ring rolling | Flash estimation, die life, press tonnage |
| **Injection Molding** | Thermoplastic, thermoset, overmolding, insert molding | Mold cavity count, cooling time, runner design |
| **Additive Manufacturing** | FDM, SLA, SLS, DMLS/SLM, binder jetting | Build orientation, support structures, post-processing |
| **Composites** | Hand layup, RTM, prepreg autoclave, filament winding | Ply count, layup time, cure cycle, tooling |
| **Welding/Joining** | MIG, TIG, spot welding, friction stir | Joint design, weld volume, fixture time |
| **Surface Treatment** | Anodizing, plating, painting, heat treatment | Surface area, bath chemistry, cycle time |
| **Assembly** | Manual, semi-automated, fully automated | Part count, fastener count, orientation difficulty |

### G.3 aP Generate REST API

**aP Generate** is aPriori's programmable costing API, enabling batch and on-demand cost estimation without the desktop application.

| API Attribute | Detail |
|--------------|--------|
| **Protocol** | REST over HTTPS |
| **Authentication** | OAuth 2.0 / API key (enterprise tenant-scoped) |
| **Input** | STEP file (binary upload) + costing scenario (JSON: material, process group, annual volume, batch size, plant location) |
| **Output** | Fully burdened cost breakdown (JSON) |
| **Batch Mode** | Bulk Costing & Analysis (BCA) — submit batches of 100+ parts with multiple scenarios |
| **Throughput** | ~100 parts per batch, ~1 minute per batch (varies by geometry complexity) |
| **Webhooks** | Callback on job completion for async workflows |

**Output Schema (simplified):**
```json
{
  "part_id": "string",
  "scenario": { "material": "...", "process_group": "...", "volume": 100 },
  "cost_breakdown": {
    "material_cost": 12.45,
    "direct_labor": 8.30,
    "machine_cost": 22.60,
    "setup_cost": 3.20,
    "tooling_cost": 1.50,
    "secondary_process_cost": 5.40,
    "overhead": 6.75,
    "total_piece_cost": 60.20,
    "fully_burdened_cost": 70.10
  },
  "process_route": {
    "primary_process": "3-axis_milling",
    "machine_type": "VMC_40x20",
    "operations": [
      {"name": "rough_mill", "cycle_time_sec": 420, "tool": "50mm_face_mill"},
      {"name": "finish_mill", "cycle_time_sec": 310, "tool": "12mm_end_mill"},
      {"name": "drilling", "cycle_time_sec": 180, "tool": "8mm_carbide_drill"}
    ],
    "total_cycle_time_sec": 910,
    "setup_time_min": 25
  },
  "dfm_analysis": {
    "manufacturability_score": 0.78,
    "warnings": [
      {"type": "thin_wall", "severity": "warning", "location": "pocket_3", "detail": "2.1mm wall, recommend 3mm+"},
      {"type": "deep_pocket", "severity": "info", "detail": "L/D=4.2, step-down toolpath recommended"}
    ]
  },
  "sustainability": {
    "co2e_kg": 2.34,
    "material_utilization_pct": 38.0,
    "energy_kwh": 4.7
  }
}
```

### G.4 simus Classmate Cloud / costing24

| Attribute | Detail |
|-----------|--------|
| **Company** | simus systems GmbH (Karlsruhe, Germany) |
| **Product** | Classmate Cloud (classification + costing), costing24 (standalone cost API) |
| **Heritage** | German engineering; strong in EU manufacturing |
| **Pricing** | ~€200/month for 200 calculations (~€1/calc standard rate) |
| **Partner Module** | Free for integrators who embed costing24 in their products |
| **Accuracy** | 95% for 80% of standard parts |
| **API** | Cloud REST API with JSON input/output |

**Process Coverage:**

| Process | Coverage Level | Notes |
|---------|---------------|-------|
| **Turning** | Excellent | Full parametric: diameter, length, features, tolerances |
| **Milling** | Excellent | 3-axis, some 5-axis support |
| **Drilling** | Excellent | Hole patterns, tapping, reaming |
| **Sheet Metal** | Good | Laser, bending, punching — standard operations |
| **Casting** | Limited | Basic sand/die casting |
| **Additive** | Limited | Basic FDM/SLS |
| **Assembly** | Minimal | Manual assembly time estimation |

**costing24 API (simplified):**

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/cost` | POST | Submit STEP file + parameters, receive cost estimate |
| `/api/v1/cost/{id}` | GET | Poll result for async jobs |
| `/api/v1/materials` | GET | List available materials and prices |
| `/api/v1/processes` | GET | List available process models |

### G.5 Engine Comparison for Oracle Labeling

| Dimension | aPriori | simus costing24 |
|-----------|---------|-----------------|
| **Process models** | 440+ | ~50 (focused on machining + sheet metal) |
| **Accuracy (standard parts)** | +/-5-10% | +/-5% for 80% of parts, +/-15-20% for edge cases |
| **API maturity** | Production-grade (aP Generate) | Cloud API (newer, simpler) |
| **Batch processing** | BCA (100+ parts/batch) | Sequential (1 part per call) |
| **Throughput** | ~6,000 parts/hour (parallelized) | ~200 parts/hour (standard tier) |
| **Cost for 9M labels** | $200-500K (enterprise license) | ~€9M at standard rate (prohibitive); free via Partner Module for subset |
| **Best use** | Primary oracle — all 9M labels | Validation oracle — 60K cross-validation labels |
| **DFM analysis** | Comprehensive (warnings + suggestions) | Basic (pass/fail) |
| **CO2e estimation** | Yes (per operation) | No |

---

## Appendix H: PLM/ERP Integration Reference

*Technical reference for the eight PLM/ERP connector targets identified in Section 13.4. Research date: February 2026.*

### H.1 Siemens Teamcenter

| Attribute | Detail |
|-----------|--------|
| **PLM Market Share** | ~22.9% (largest) |
| **Estimated Companies** | ~6,158 |
| **API Type** | REST API (Active Workspace), SOA (Integration Toolkit) |
| **Event Mechanism** | Teamcenter for Enterprise Applications (T4EA) gateway; Teamcenter Events (pub/sub) |
| **Authentication** | SSO (SAML/OIDC), Service Account tokens |
| **Key APIs** | Item/ItemRevision CRUD, BOM management, Dataset operations, Workflow triggers |
| **Marketplace** | Siemens Xcelerator Marketplace — third-party apps can be listed and distributed |
| **Integration Effort** | 10-14 weeks (T4EA standardized; REST well-documented) |
| **Notes** | Largest PLM install base. T4EA gateway provides standardized event interface. Active Workspace REST API is modern and well-maintained. |

### H.2 PTC Windchill

| Attribute | Detail |
|-----------|--------|
| **PLM Market Share** | ~10.5% |
| **Estimated Companies** | ~3,500 |
| **API Type** | OData REST API (Windchill REST Services) |
| **Event Mechanism** | ESI (Enterprise Systems Integration) with TIBCO middleware; Windchill Events |
| **Authentication** | OAuth 2.0, WCToken |
| **Key APIs** | Part/Document CRUD, BOM navigation, Change Management, File download/upload |
| **Marketplace** | PTC Marketplace |
| **Integration Effort** | 10-14 weeks (OData well-standardized; ESI adds complexity) |
| **Notes** | Strong in aerospace and defense. OData API is clean but some features still require Info*Engine tasks. ESI integration via TIBCO adds middleware cost. |

### H.3 Dassault 3DEXPERIENCE

| Attribute | Detail |
|-----------|--------|
| **PLM Market Share** | ~12.8% |
| **Estimated Companies** | ~4,200 |
| **API Type** | REST + GraphQL (3DEXPERIENCE Platform Services) |
| **Event Mechanism** | JMS event bus, webhook notifications, 3DSwym notifications |
| **Authentication** | 3DPassport (OAuth 2.0), CAS tokens |
| **Key APIs** | Engineering Item CRUD, Physical Product/Representation, BOM services, Change Action |
| **Marketplace** | 3DEXPERIENCE Marketplace (Make for manufacturing) |
| **Integration Effort** | 12-16 weeks (complex API surface; multiple data models) |
| **Notes** | Most complex API landscape. 3DEXPERIENCE platform spans CATIA, ENOVIA, DELMIA. GraphQL API is powerful but steep learning curve. Strong automotive presence. |

### H.4 SAP S/4HANA

| Attribute | Detail |
|-----------|--------|
| **ERP Market Share** | ~24% (largest) |
| **Estimated Companies** | ~37,500 |
| **API Type** | OData V2/V4 (SAP API Business Hub), RFC/BAPI (legacy) |
| **Event Mechanism** | SAP Event Mesh (cloud), ALE/IDoc (on-premise), SAP BTP (Business Technology Platform) |
| **Authentication** | OAuth 2.0, X.509 certificates, SAP Passport |
| **Key APIs** | Material Master (MARA), BOM (STPO), Routing (PLPO), Cost Center, Production Order |
| **Marketplace** | SAP Store / SAP BTP |
| **Integration Effort** | 10-14 weeks for cloud (OData); 14-20 weeks for on-premise (RFC + IDoc) |
| **Notes** | Largest ERP install base. Critical for capturing actual production costs (CO module), purchase prices (MM module), and production order data. S/4HANA Cloud has modern OData APIs; ECC on-premise requires BAPI/RFC wrappers. |

### H.5 Oracle Manufacturing Cloud

| Attribute | Detail |
|-----------|--------|
| **ERP Market Share** | ~5% |
| **Estimated Companies** | ~7,500 |
| **API Type** | REST API (Oracle Fusion Cloud) |
| **Event Mechanism** | FBDI (File-Based Data Import), Business Events, Oracle Integration Cloud (OIC) |
| **Authentication** | OAuth 2.0, JWT |
| **Key APIs** | Item Master, BOM, Work Order, Cost Management, Manufacturing Execution |
| **Marketplace** | Oracle Cloud Marketplace |
| **Integration Effort** | 10-14 weeks (clean REST API; FBDI for bulk operations) |
| **Notes** | Strong in process manufacturing and large discrete manufacturers. REST APIs are modern and well-documented. FBDI is the standard for bulk data operations. |

### H.6 Microsoft Dynamics 365

| Attribute | Detail |
|-----------|--------|
| **ERP Market Share** | ~6% |
| **Estimated Companies** | ~9,000 |
| **API Type** | REST (Dataverse Web API, Supply Chain Management API) |
| **Event Mechanism** | Dataverse webhooks, Azure Service Bus integration, Business Events |
| **Authentication** | Azure AD (OAuth 2.0), Application User |
| **Key APIs** | Released Products, BOM Versions, Production Orders, Cost Calculation |
| **Marketplace** | Microsoft AppSource |
| **Integration Effort** | 8-12 weeks (Azure ecosystem well-documented; Dataverse is standardized) |
| **Notes** | Growing fast in mid-market manufacturing. Azure integration makes event-driven architecture natural. MES Integration API provides shop floor connectivity. Lowest integration effort due to Microsoft's developer ecosystem. |

### H.7 Infor CloudSuite

| Attribute | Detail |
|-----------|--------|
| **ERP Market Share** | ~6% |
| **Estimated Companies** | ~68,000 (across all Infor products) |
| **API Type** | ION API Gateway (REST), Mongoose (M3 API) |
| **Event Mechanism** | ION Connect (50B+ API calls/yr across platform), BODs (Business Object Documents) |
| **Authentication** | ION API OAuth 2.0, Service Account |
| **Key APIs** | Item Master (M3), BOM, Routing, Cost Accounting, Shop Floor Control |
| **Marketplace** | Infor Marketplace |
| **Integration Effort** | 12-16 weeks (ION Connect is powerful but complex; BOD schemas require mapping) |
| **Notes** | Massive install base (68K companies across products). ION API Gateway processes 50B+ API calls/year. Strong in specific verticals (fashion, food & beverage, aerospace). M3/LN products dominant in discrete manufacturing. |

### H.8 Autodesk Fusion/Vault

| Attribute | Detail |
|-----------|--------|
| **PLM Market Share** | ~5% (growing, especially SMB) |
| **Estimated Companies** | ~3,000 (Vault/Fusion PLM users) |
| **API Type** | REST (Forge/APS platform for Vault), Fusion 360 API (local + cloud) |
| **Event Mechanism** | Vault Connector (file/lifecycle events), Fusion event hooks, Design Automation API |
| **Authentication** | APS (Autodesk Platform Services) OAuth 2.0, 3-legged for user context |
| **Key APIs** | Vault file lifecycle, Fusion 360 design data, Design Automation (headless processing) |
| **Marketplace** | Autodesk App Store |
| **Integration Effort** | 8-12 weeks (well-documented cloud APIs; strong developer ecosystem) |
| **Notes** | Primary target for SMB market. Fusion 360's integrated CAD/CAM/CAE + cloud PLM is growing rapidly. Design Automation API enables headless STEP processing in the cloud. Lower ACV per customer but large volume opportunity. |

### H.9 Connector Priority Matrix

| Priority | System | Rationale |
|----------|--------|-----------|
| **P1** | Siemens Teamcenter | Largest PLM market share (22.9%); enterprise anchor customer potential |
| **P1** | SAP S/4HANA | Largest ERP market share (24%); critical for production cost feedback |
| **P2** | PTC Windchill | Strong aerospace/defense presence; enterprise budget for middleware |
| **P2** | Oracle Mfg Cloud | Clean REST APIs; large discrete manufacturers |
| **P2** | Autodesk Fusion/Vault | SMB volume play; aligns with self-serve API GTM |
| **P3** | Dassault 3DEXPERIENCE | Complex integration but large automotive presence |
| **P3** | Microsoft Dynamics 365 | Growing fast; lowest integration effort |
| **P3** | Infor CloudSuite | Massive install base but fragmented product line |

### H.10 Event Schema Normalization

All PLM/ERP connectors normalize events into a standard CADPrice internal schema:

```json
{
  "event_type": "part_released | eco_created | bom_updated | production_complete | purchase_order_created",
  "source_system": "teamcenter | windchill | 3dexperience | sap | oracle | dynamics | infor | fusion",
  "source_version": "string",
  "timestamp": "ISO-8601",
  "tenant_id": "string",
  "payload": {
    "part_number": "string",
    "revision": "string",
    "step_file_url": "string (presigned URL or blob reference)",
    "drawing_url": "string (optional)",
    "material_spec": "string (optional, from PLM attributes)",
    "quantity_hint": "number (optional, from production order)",
    "bom_structure": "object (optional, for BOM events)",
    "cost_data": "object (optional, for production/PO events)",
    "metadata": "object (system-specific attributes passed through)"
  }
}
```

This normalization layer ensures that the enrichment pipeline processes events identically regardless of source system — the same AI models, the same enrichment logic, the same output schema. Connector-specific code is confined to the `EventReceiver` and `DataPublisher` implementations.

---

## 14. CADPrice — Implementation Plan

**Status:** Approved for development as a standalone application
**Repository:** New standalone repo (`cadprice`), separate from RattleApp
**Decision:** Build an API-first manufacturing intelligence platform — no existing platform offers a stateless REST API for manufacturing cost estimation and CAD enrichment

---

### 14.1 Technology Stack

| Layer | Choice | Why |
|-------|--------|-----|
| **API Framework** | FastAPI + Uvicorn (ASGI) | Async-native; auto-generated OpenAPI docs; Pydantic validation; ML-serving standard |
| **Frontend** | HTMX + Tailwind CSS + Alpine.js (Jinja2 templates) | Server-rendered admin dashboard, developer portal, tenant configuration UI — no JS build step for most pages; Alpine.js for interactive components |
| **Database** | PostgreSQL 16 + pgvectorscale | Relational + vector embeddings in one DB; multi-tenant isolation; proven at scale |
| **Task Queue** | Celery + Redis | Long-running STEP processing + ML inference; horizontal scaling; retry with backoff |
| **Cache/Broker** | Redis | Message broker for Celery + response caching + rate limiting |
| **STEP Processing** | PythonOCC-core (OpenCascade) | Industry-standard CAD kernel; full B-Rep extraction; conda-forge Docker images |
| **3D Geometry** | trimesh + Open3D | Mesh analysis/validation; point cloud ops + GPU features |
| **Feature Recognition** | BRepFormer (2025 SOTA) | Transformer-based B-Rep processing; preserves topology; beats BRepGAT on machining features |
| **Point Cloud Encoder** | Point-MAE | Self-supervised masked autoencoder; 94% ModelNet40; pre-trains without labels |
| **ML Serving** | Triton Inference Server | Multi-framework (PyTorch + ONNX); dynamic batching; concurrent models; A/B testing |
| **Object Storage** | S3-compatible (AWS S3 / MinIO) | STEP file storage; model artifacts; training datasets |
| **Multi-tenant ML** | Base model + per-tenant LoRA adapters | 2-5% parameter overhead; fast fine-tuning; customer isolation |
| **Drawing Intelligence** | PyMuPDF (Tier 1) + VLM vision (Tier 2) | Text extraction for vector PDFs; GPT-4o/Claude vision for scanned drawings |
| **Infrastructure** | Docker + Docker Compose | Container-based deployment; docker-compose for service orchestration; horizontal scaling via Docker Swarm or managed container services |
| **Monitoring** | OpenTelemetry + Prometheus + Grafana | End-to-end tracing; queue depth metrics; inference latency tracking |
| **Language** | Python 3.12 | Entire ML ecosystem is Python; PythonOCC, PyTorch, FastAPI all native |

---

### 14.2 The Three Core APIs

#### 13.2.1 CostAPI — "Calculate Manufacturing Cost on Request"

```
POST /v1/cost/estimate
{
  "step_file": "<base64 or presigned URL>",
  "drawing_pdf": "<optional base64>",
  "material": "AL_6061_T6",
  "quantity": 10,
  "process_hint": "cnc_milling",          // optional
  "machine_config_id": "cfg_abc123",       // optional tenant config
  "include_quantity_breaks": true
}

→ 200 OK
{
  "estimate_id": "est_7f3a2b",
  "material_cost": 12.40,
  "setup_cost": 42.50,
  "machining_cost": 18.75,
  "finishing_cost": 3.20,
  "secondary_process_cost": 8.00,
  "overhead_cost": 11.53,
  "total_unit_cost": 41.63,
  "cycle_time_min": 14.2,
  "confidence": 0.82,
  "model_version": "v2.3.1",
  "process_route": ["CNC 3-axis milling", "drilling x6", "tapping x3", "anodize Type III"],
  "cost_drivers": [
    {"feature": "deep_bores_axis_b", "cost_share": 0.32, "suggestion": "reduce depth-to-diameter ratio"},
    {"feature": "tight_tolerance_bore", "cost_share": 0.18, "suggestion": "relax to +/-0.05 if possible"}
  ],
  "quantity_breaks": {
    "1": 96.38, "10": 41.63, "100": 39.46, "1000": 38.12
  },
  "drawing_data_used": true,
  "tolerance_multiplier": 1.3
}
```

#### 13.2.2 EnrichAPI — "Enhance Part Master Data on Request"

```
POST /v1/enrich/part
{
  "step_file": "<base64 or presigned URL>",
  "drawing_pdf": "<optional base64>"
}

→ 200 OK
{
  "enrichment_id": "enr_9c4d1e",
  "classification": "CNC turning + milling",
  "material_group": "aluminum",
  "bounding_box_mm": [120.5, 80.0, 45.2],
  "volume_cm3": 276.9,
  "surface_area_cm2": 412.3,
  "weight_kg": 0.75,
  "machined_percentage": 63.4,
  "features": {
    "bores": [{"type": "through", "diameter": 12.0, "depth": 45.0, "count": 4},
              {"type": "blind", "diameter": 8.0, "depth": 20.0, "count": 2}],
    "threads": [{"spec": "M8x1.25", "count": 3}],
    "pockets": 2,
    "chamfers": 8,
    "fillets": 4
  },
  "suggested_stock": "dia85 x 130mm round bar, AL 6061",
  "process_route": ["turning", "milling", "drilling", "tapping", "anodize"],
  "embedding": [0.123, -0.456, ...],     // 512-dim for similarity search
  "drawing_extracted": {                   // if drawing_pdf provided
    "material": "AL 6061-T6",
    "general_tolerance": "ISO 2768-mK",
    "tightest_tolerance_mm": 0.02,
    "surface_finish_ra": {"default": 3.2, "tightest": 0.8},
    "secondary_processes": ["anodize Type III black", "passivate"],
    "gdt_complexity_score": 4
  }
}
```

#### 13.2.3 SimilarityAPI — "Find Parts Like This One"

```
POST /v1/parts/similar
{
  "step_file": "<base64>",
  "top_k": 10,
  "filters": {"material_group": "aluminum"}   // optional
}

→ 200 OK
{
  "query_embedding": [0.123, -0.456, ...],
  "results": [
    {"part_id": "prt_abc", "similarity": 0.94, "classification": "CNC turning", "thumbnail_url": "..."},
    {"part_id": "prt_def", "similarity": 0.87, "classification": "CNC milling", "thumbnail_url": "..."}
  ]
}
```

---

### 14.3 Async Job Pattern

STEP files take 2-30 seconds to process. All processing endpoints use an async job pattern:

```
POST /v1/cost/estimate → 202 Accepted { "job_id": "job_abc", "status": "processing" }
GET  /v1/jobs/job_abc  → 200 { "status": "completed", "result": { ... } }
```

- Optional webhook callback: `"webhook_url": "https://customer.com/hooks/cadprice"`
- For small/simple parts (<50KB STEP), synchronous response path with 15s timeout
- Job status progression: `queued` → `processing` → `completed` | `failed`

---

### 14.4 Data Model (Core Tables)

```sql
-- Multi-tenancy
tenants (id, name, plan, api_key_hash, created_at, settings JSONB)
api_keys (id, tenant_id, key_hash, name, rate_limit, scopes, active, created_at)

-- Machine & material config (per-tenant, with curated defaults)
machine_configs (id, tenant_id, name, code, hourly_rate, setup_rate,
                 programming_rate, setup_time_min, max_dims_mm JSONB,
                 capabilities JSONB, is_default BOOLEAN)
material_library (id, tenant_id, code, name, density, cost_per_kg,
                  machinability, standard, aliases JSONB, is_default BOOLEAN)

-- Jobs & results
jobs (id, tenant_id, type, status, input_hash, webhook_url,
      step_file_key, drawing_file_key, created_at, started_at,
      completed_at, error, result JSONB)
geometry_results (id, job_id, volume_mm3, surface_mm2, cutting_volume_mm3,
                  machined_pct, bore_count, thread_count, bbox_x, bbox_y, bbox_z,
                  material_group, classification, confidence,
                  features JSONB, raw_parameters JSONB)
drawing_results (id, job_id, material_designation, matched_material_code,
                 general_tolerance, tightest_tolerance_mm, default_surface_ra,
                 tightest_surface_ra, secondary_processes JSONB,
                 gdt_complexity_score, extraction_tier, raw_extraction JSONB)
cost_estimates (id, job_id, tenant_id, material_code, quantity,
                material_cost, setup_cost, machining_cost, finishing_cost,
                secondary_cost, overhead_cost, total_unit_cost,
                cycle_time_min, confidence, model_version,
                formula_estimate JSONB, ai_estimate JSONB,
                source, cost_drivers JSONB, quantity_breaks JSONB)

-- Embeddings & similarity
part_embeddings (id, tenant_id, embedding vector(512), geometry_result_id,
                 classification, metadata JSONB, created_at)
-- pgvectorscale HNSW index on embedding column

-- Training data & model management
training_samples (id, tenant_id, geometry_result_id, actual_cost,
                  formula_cost, xometry_price, label_source, created_at)
model_versions (id, tenant_id, version, base_model, adapter_path,
                mape_score, training_samples_count, created_at, active)

-- Usage metering
usage_events (id, tenant_id, api_key_id, endpoint, timestamp,
              input_size_bytes, processing_time_ms, model_version, billed)
```

---

### 14.5 Project Structure

```
cadprice/
├── docker-compose.yml              # Local dev: API + Redis + PostgreSQL + worker + MinIO
├── docker-compose.gpu.yml          # GPU override for ML inference
├── Dockerfile                      # Multi-stage: API server
├── Dockerfile.worker               # Worker with PythonOCC (conda-based)
├── Dockerfile.gpu                  # GPU worker for Triton inference
├── pyproject.toml                  # Python project config (dependencies, tools)
├── alembic.ini                     # Database migration config
├── .env.example                    # Environment variable template
│
├── cadprice/
│   ├── __init__.py
│   ├── main.py                     # FastAPI app factory
│   ├── config.py                   # Settings from env vars (Pydantic BaseSettings)
│   │
│   ├── api/                        # API layer
│   │   ├── v1/
│   │   │   ├── cost.py             # POST /v1/cost/estimate, /v1/cost/what-if
│   │   │   ├── enrich.py           # POST /v1/enrich/part, /v1/enrich/drawing
│   │   │   ├── similar.py          # POST /v1/parts/similar, GET /v1/parts/clusters
│   │   │   ├── config.py           # CRUD /v1/config/machines, /materials, /overhead
│   │   │   ├── jobs.py             # GET /v1/jobs/{id}, webhooks
│   │   │   ├── suppliers.py        # POST /v1/suppliers/match
│   │   │   └── quotes.py          # POST /v1/quotes/score
│   │   ├── deps.py                # Dependency injection (DB session, current tenant, etc.)
│   │   ├── auth.py                 # API key validation, tenant resolution
│   │   ├── middleware.py           # Rate limiting, usage metering, idempotency
│   │   └── schemas.py             # Pydantic request/response models
│   │
│   ├── core/                       # Business logic
│   │   ├── geometry/
│   │   │   ├── extractor.py        # PythonOCC STEP -> 47+ geometry parameters
│   │   │   ├── brep_graph.py       # B-Rep -> graph representation for GNNs
│   │   │   ├── point_cloud.py      # STEP -> point cloud via trimesh/Open3D
│   │   │   └── classifier.py       # Rule-based + ML process classification
│   │   │
│   │   ├── cost/
│   │   │   ├── formula_engine.py   # Deterministic cost formulas (Section 7.6 logic)
│   │   │   ├── ai_predictor.py     # ML-based cost prediction (Phase 5)
│   │   │   ├── ensemble.py         # Formula + AI blending with confidence
│   │   │   └── what_if.py          # What-if cost analysis
│   │   │
│   │   ├── drawing/
│   │   │   ├── text_extractor.py   # Tier 1: PyMuPDF + regex (Section 5.6 logic)
│   │   │   ├── vlm_extractor.py    # Tier 2: VLM vision (GPT-4o/Claude)
│   │   │   └── material_matcher.py # Fuzzy match designations -> canonical codes
│   │   │
│   │   ├── intelligence/
│   │   │   ├── similarity.py       # Embedding-based part search
│   │   │   ├── clustering.py       # HDBSCAN part family discovery
│   │   │   ├── dfm.py             # DFM rules + checks
│   │   │   ├── cost_drivers.py     # SHAP/Grad-CAM attribution
│   │   │   ├── supplier_match.py   # Capability vector matching
│   │   │   └── quote_scorer.py     # Benchmark quotes vs predicted cost
│   │   │
│   │   └── embedding/
│   │       ├── point_mae.py        # Point-MAE encoder
│   │       ├── brepformer.py       # BRepFormer encoder
│   │       └── registry.py         # Model loading, LoRA adapter management
│   │
│   ├── db/                         # Database & storage
│   │   ├── models.py              # SQLAlchemy models
│   │   ├── session.py             # Async session factory
│   │   ├── migrations/            # Alembic migration versions
│   │   │   └── versions/
│   │   └── vector_store.py        # pgvectorscale index management
│   │
│   ├── storage/                    # File storage abstraction
│   │   ├── base.py                # Storage protocol
│   │   ├── s3.py                  # S3/MinIO implementation
│   │   └── local.py              # Local filesystem (dev)
│   │
│   ├── workers/                    # Celery task definitions
│   │   ├── celery_app.py          # Celery instance configuration
│   │   ├── geometry_tasks.py       # STEP extraction pipeline
│   │   ├── drawing_tasks.py        # PDF analysis pipeline
│   │   ├── cost_tasks.py           # Cost calculation pipeline
│   │   ├── embedding_tasks.py      # Embedding generation
│   │   └── training_tasks.py       # LoRA fine-tuning, dataset preparation
│   │
│   └── training/                   # ML training pipelines (offline)
│       ├── pretrain_point_mae.py
│       ├── pretrain_brepformer.py
│       ├── finetune_features.py
│       ├── generate_formula_labels.py   # Run formula engine on 100K STEPs
│       ├── generate_xometry_labels.py   # Batch Xometry API for market prices
│       └── train_cost_model.py          # Cost prediction from multi-signal labels
│
├── templates/                      # Jinja2 + HTMX server-rendered UI
│   ├── base.html                  # Base layout (Tailwind CSS, HTMX, Alpine.js CDN)
│   ├── dashboard/
│   │   ├── index.html             # Usage analytics, model performance
│   │   ├── api_keys.html          # Key management
│   │   ├── machine_config.html    # Machine rate configuration (Alpine.js inline editing)
│   │   ├── material_config.html   # Material library management
│   │   ├── jobs.html              # Job history + status (HTMX polling)
│   │   └── playground.html        # Interactive API testing (upload STEP, see results)
│   ├── docs/
│   │   └── api.html               # Embedded API documentation
│   ├── components/                # Reusable Jinja2 partials (HTMX fragments)
│   │   ├── cost_breakdown.html
│   │   ├── job_status.html
│   │   └── data_table.html
│   └── auth/
│       └── login.html
├── static/
│   ├── css/
│   │   ├── input.css              # Tailwind CSS input
│   │   └── output.css             # Tailwind CSS compiled output
│   └── js/                        # Minimal JS — only Alpine.js component definitions
│       └── components.js
├── tailwind.config.js             # Tailwind CSS configuration
├── package.json                   # Tailwind CSS build dependency only
│
├── tests/
│   ├── conftest.py                 # Fixtures: test DB, test client, sample files
│   ├── test_geometry_extractor.py
│   ├── test_formula_engine.py
│   ├── test_cost_api.py
│   ├── test_enrich_api.py
│   ├── test_drawing_extractor.py
│   ├── test_auth.py
│   ├── test_jobs.py
│   └── fixtures/                   # Sample STEP files, PDF drawings
│       ├── simple_block.step
│       ├── turned_part.step
│       ├── milled_part.step
│       ├── assembly.step
│       └── sample_drawing.pdf
│
└── infra/
    ├── docker/                     # Per-service Dockerfiles and compose overrides
    ├── nginx/                      # Reverse proxy config (SSL termination, static files)
    └── scripts/                    # Dataset download, model training launch, deploy scripts
```

---

### 14.6 Development Phases

#### Phase 1: API Foundation + Geometry Extraction (Weeks 1-8)

**Goal:** Working API that accepts STEP files and returns rich geometry data (EnrichAPI v1).

| # | Task | Details |
|---|------|---------|
| 1.1 | **Project scaffolding** | FastAPI app, Docker Compose (API + Redis + PostgreSQL + Celery worker + MinIO), pyproject.toml, CI pipeline, OpenAPI spec |
| 1.2 | **Database setup** | SQLAlchemy async models, Alembic migrations, core tables (tenants, api_keys, jobs, geometry_results) |
| 1.3 | **Auth & tenancy** | API key auth middleware, tenant isolation, rate limiting (Redis-based), usage metering |
| 1.4 | **File upload pipeline** | STEP file upload → S3/MinIO storage → validation (size, format, STEP header check) → Celery job queue |
| 1.5 | **STEP geometry extraction** | PythonOCC-core: load STEP → extract B-Rep → compute 47+ parameters (volume, surface area, bounding box, bore collection, thread count, machined %) |
| 1.6 | **Async job system** | POST returns `job_id` with 202 → poll `GET /v1/jobs/{id}` → optional webhook callback |
| 1.7 | **EnrichAPI v1 endpoint** | Return geometry parameters + classification (rule-based: bounding box ratios → turning/milling/sheet metal) |
| 1.8 | **Monitoring** | OpenTelemetry tracing, Prometheus metrics endpoint, structured JSON logging |

**Key dependency:** PythonOCC-core in Docker (conda-forge base image for worker).

**Exit criteria:** `POST /v1/enrich/part` with a STEP file → returns geometry parameters within 5-15 seconds.

#### Phase 2: Cost Formula Engine — CostAPI v1 (Weeks 6-12, overlaps Phase 1)

**Goal:** Deterministic cost estimation from geometry + configurable rates. Also generates synthetic training data.

| # | Task | Details |
|---|------|---------|
| 2.1 | **Machine type database** | Per-tenant machine configs: hourly_rate (decomposed: manufacturing/setup/programming rate), setup_time, max dimensions, capabilities. Curated defaults for common machine types (3-axis CNC, 5-axis, lathe, wire EDM, etc.) |
| 2.2 | **Material database** | Curated default library (50+ common materials: AL 6061, Steel 1045, ABS, etc.) + per-tenant overrides. Fields: density, cost/kg, machinability factor, standard, aliases |
| 2.3 | **Cost formula engine** | Port logic from Section 7.6: material cost + setup cost + machining cost (cutting volume / MRR) + surface finishing + hole/thread operations + overhead |
| 2.4 | **Tolerance/finish multipliers** | When drawing data available: tolerance → cost multiplier (±0.01mm = 1.8x), surface finish Ra → additional operation cost |
| 2.5 | **Secondary process costing** | Heat treatment (EUR/kg), coating (EUR/m2), plating — configurable per tenant |
| 2.6 | **Quantity break calculation** | Setup cost amortization: unit_cost(qty) = (per_unit * qty + setup_cost) / qty |
| 2.7 | **CostAPI v1 endpoint** | `POST /v1/cost/estimate` → returns full cost breakdown with confidence score |
| 2.8 | **Tenant configuration API** | `CRUD /v1/config/machines`, `/v1/config/materials`, `/v1/config/overhead` |
| 2.9 | **Admin UI** | Machine config, material library, overhead settings management pages (HTMX + Tailwind + Alpine.js) |
| 2.10 | **Synthetic label generation** | Run formula engine against CADSynth 100K STEP files → generate (geometry, cost) training pairs for every material x quantity combination |

**Dual purpose:** The formula engine provides immediate customer value AND generates labeled training data for AI models in Phase 4.

**Exit criteria:** `POST /v1/cost/estimate` with STEP + material + quantity → returns cost breakdown. Tenant can configure their own machine rates via API and admin UI.

#### Phase 3: Drawing Intelligence (Weeks 10-16, overlaps Phase 2)

**Goal:** Extract material, tolerances, surface finish, GD&T from PDF engineering drawings.

| # | Task | Details |
|---|------|---------|
| 3.1 | **Tier 1: PyMuPDF text extraction** | Vector PDF → text layer → regex patterns for material designations, ISO tolerance classes, Ra values (Section 5.6 logic) |
| 3.2 | **Tier 2: VLM vision extraction** | Scanned/complex PDFs → render pages at 200 DPI → send to GPT-4o/Claude vision with structured JSON schema → extract title block, GD&T, surface finish, BOM table |
| 3.3 | **Material matching engine** | Fuzzy-match extracted designations ("Al 6061-T6", "Aluminium 6061") to canonical material codes in database |
| 3.4 | **Drawing extraction endpoint** | Combined with `/v1/enrich/part` when `drawing_pdf` is provided; also standalone `POST /v1/enrich/drawing` |
| 3.5 | **Cost formula integration** | Drawing data → tolerance multipliers + surface finish costs + secondary process costs feed into CostAPI |
| 3.6 | **Multi-provider LLM support** | Configurable VLM provider (OpenAI, Anthropic, Gemini) per tenant for data sovereignty preferences |

**Architecture:** Two-tier approach — Tier 1 handles 60-70% of modern CAD-generated vector PDFs (free, fast); Tier 2 activates for scanned drawings or low-confidence text extraction.

**Exit criteria:** Upload PDF drawing → extracted material + tolerances + surface finish. Combined with CostAPI, cost accuracy improves via tolerance multipliers.

#### Phase 4: AI Foundation — Pre-training + Synthetic Labels (Weeks 14-24)

**Goal:** Pre-train geometric encoders on open datasets; generate massive synthetic labeled dataset; build embedding infrastructure.

This phase solves the cold-start problem using the bootstrapping strategy from Section 12.7.

| # | Task | Details |
|---|------|---------|
| 4.1 | **Download & prepare open datasets** | ABC (1M models), CADSynth (100K, STEP + B-Rep), 1M Synthetic CAD, MFCAD++ (59.7K). Total: ~120 GB |
| 4.2 | **STEP → point cloud pipeline** | Batch-convert STEP → point clouds (trimesh/Open3D); standardize to 2048/4096 points per model |
| 4.3 | **STEP → B-Rep graph pipeline** | Extract B-Rep topology from STEP (PythonOCC) → face/edge/vertex adjacency graphs with geometric features |
| 4.4 | **Pre-train Point-MAE encoder** | Self-supervised masked autoencoder on 2M+ point clouds. Output: 512-dim embedding per part. No labels needed. |
| 4.5 | **Pre-train BRepFormer encoder** | Transformer on B-Rep graphs from CADSynth + 1M Synthetic CAD |
| 4.6 | **Fine-tune machining feature classifier** | Train on CADSynth (24 feature types per face) + MFCAD++ → per-face feature recognition |
| 4.7 | **Synthetic cost label generation (Strategy 1)** | Run formula engine against all 100K CADSynth STEP files x 5 materials x 4 quantities = **2M labeled training pairs** |
| 4.8 | **Xometry cost label generation (Strategy 2)** | Select 5,000-10,000 representative STEP files → batch-submit to Xometry API → collect market prices |
| 4.9 | **Multi-signal training dataset** | Combine: formula-generated labels + Xometry labels + feature labels. Each sample has embedding, formula_cost, xometry_price, feature_labels |
| 4.10 | **Vector index for similarity search** | Embed all open dataset parts → pgvectorscale index |
| 4.11 | **SimilarityAPI endpoint** | `POST /v1/parts/similar` → k-NN search on embeddings → ranked results |

**The bootstrapping flywheel:**

```
Open CAD Datasets (2M+ STEP files, no cost labels)
     |
     +---> Formula Engine (Phase 2) generates cost labels
     |     (physically grounded: material + machining + setup + overhead)
     |     = 2M training pairs at +/-30% accuracy
     |
     +---> Xometry API generates price labels
     |     (market calibrated: real quotes for 5-10K representative parts)
     |     = 5-10K training pairs at market accuracy
     |
     +---> Combined multi-signal dataset
           +-- Point-MAE encoder (pre-trained, self-supervised)
           +-- BRepFormer encoder (pre-trained, self-supervised)
           +-- Cost prediction head (trained on formula + Xometry labels)
           +-- Process classifier (trained on CADSynth feature labels)
                |
                v
           LAUNCH with meaningful AI accuracy from Day 1
```

**Exit criteria:** Pre-trained encoder produces meaningful embeddings (similar parts cluster). Cost prediction model trained on synthetic + Xometry labels achieves <25% MAPE on held-out test set.

#### Phase 5: CostAPI v2 — AI-Powered Cost Estimation (Weeks 22-30)

**Goal:** Replace/augment formula engine with ML-based cost prediction. Per-tenant fine-tuning.

| # | Task | Details |
|---|------|---------|
| 5.1 | **AI cost prediction model** | Pre-trained encoder (frozen) + cost MLP head. Input: 512-dim embedding + metadata. Output: cost estimate + confidence interval |
| 5.2 | **Ensemble: formula + AI** | Return both estimates. Confidence-weighted blend. Flag when they diverge >20% |
| 5.3 | **Per-tenant LoRA fine-tuning** | Customer uploads parts with actual costs → fine-tune LoRA adapter (2-5% parameter overhead) |
| 5.4 | **Active learning pipeline** | AI predicts → customer corrects → correction stored → nightly batch retrain of tenant LoRA adapter |
| 5.5 | **Model serving via Triton** | Base model loaded once + LoRA adapters loaded on-demand per request. Dynamic batching. |
| 5.6 | **Confidence calibration** | Low (<0.6) = formula fallback; medium (0.6-0.8) = show range; high (>0.8) = primary estimate |
| 5.7 | **A/B testing framework** | Route % of traffic to new model version; compare accuracy; auto-promote or rollback |

**Exit criteria:** AI model matches or beats formula engine accuracy. Per-tenant fine-tuning shows measurable improvement after 200+ corrections.

#### Phase 6: Advanced Intelligence Features (Weeks 28-40)

**Goal:** DFM feedback, cost driver visualization, supplier matching, part family clustering.

| # | Task | Details |
|---|------|---------|
| 6.1 | **DFM rules engine** | Min wall thickness, bore depth-to-diameter ratio, undercut detection, draft angle for molding. Return warnings + suggestions |
| 6.2 | **Cost driver attribution** | SHAP/Grad-CAM → identify which geometric features drive cost. Structured `cost_drivers` array |
| 6.3 | **What-if analysis endpoint** | `POST /v1/cost/what-if` — material change cost impact, tolerance relaxation savings |
| 6.4 | **Part family clustering** | HDBSCAN on embeddings → natural part families. Group technology recommendations |
| 6.5 | **Supplier capability matching** | Part embedding vs supplier capability vectors → ranked qualified suppliers |
| 6.6 | **Quotation quality scoring** | Compare incoming quote vs AI-predicted cost → flag outliers |
| 6.7 | **Material recommendation** | Part geometry + requirements → optimal material suggestion |

**Exit criteria:** DFM endpoint returns actionable warnings. Cost driver visualization correctly identifies top-3 cost-driving features.

#### Phase 7: Platform & Scale (Weeks 36+, ongoing)

**Goal:** Enterprise readiness, PLM/ERP integrations, SDK packages.

| # | Task | Details |
|---|------|---------|
| 7.1 | **SDKs** | Python, TypeScript, C#/.NET, Java — auto-generated from OpenAPI spec + hand-crafted wrappers |
| 7.2 | **PLM/ERP connectors** | Siemens Teamcenter, PTC Windchill, SAP PLM, Autodesk Fusion/Vault |
| 7.3 | **Webhook system** | Async notifications for job completion, cost changes, DFM alerts |
| 7.4 | **Developer portal** | Interactive API docs, sandbox environment (free tier: 50 cost calcs + 200 enrichments/month) |
| 7.5 | **Admin dashboard** | Full HTMX + Alpine.js dashboard: tenant management, usage analytics, model performance, configuration UI |
| 7.6 | **gRPC interface** | High-throughput option for PLM vendors doing bulk enrichment (10K+ parts/batch) |
| 7.7 | **Multi-region deployment** | EU + US + Asia via Docker-based deployment for data sovereignty compliance |
| 7.8 | **SOC 2 / ISO 27001** | Enterprise security certification for defense/aerospace customers |

---

### 14.7 Key Architecture Decisions

#### 13.7.1 Multi-Signal Cost Training Labels

```
Training sample = {
  geometry_embedding: [512 dims from Point-MAE/BRepFormer],
  geometry_features: {volume, surface_area, bore_count, thread_count, ...},
  material: {density, cost_per_kg, machinability},
  formula_cost: 42.50,        // from deterministic formula engine
  xometry_price: 38.50,       // from Xometry API (market price)
  label_source: "synthetic",  // vs "customer_correction" in production
}
```

The cost model learns from both signals. Formula costs teach physics. Xometry prices teach market reality. Customer corrections eventually dominate both.

#### 13.7.2 Per-Tenant Model Isolation via LoRA

```
Base BRepFormer model (trained on 2M+ open CAD models)  -- shared, loaded once
     |
     +-- Tenant A LoRA adapter (fine-tuned on 500 aerospace parts)     -- 10MB
     +-- Tenant B LoRA adapter (fine-tuned on 2000 automotive parts)   -- 10MB
     +-- Tenant C: no adapter yet (uses base model + formula fallback) -- 0MB
```

LoRA adapters loaded on-demand per request. Triton handles adapter routing.

#### 13.7.3 Drawing Intelligence Two-Tier Architecture

- **Tier 1 (fast, free):** PyMuPDF text extraction + regex patterns. Handles 60-70% of modern CAD-generated vector PDFs.
- **Tier 2 (accurate, costs LLM tokens):** VLM vision (GPT-4o/Claude) for scanned drawings or low-confidence text extraction. Structured JSON schema output.

Tier 1 runs first. If confidence < 0.8, Tier 2 activates automatically.

---

### 14.8 Cost Formula Engine Reference Implementation

The formula engine (Phase 2) ports the logic from Section 7.6. Core calculation:

```
material_cost     = raw_weight_kg * material.cost_per_kg
setup_cost        = (machine.setup_time_min / 60) * machine.setup_rate
rough_time        = cutting_volume_cm3 / (base_mrr * material.machinability)
finish_time       = machined_surface_cm2 / finish_rate
hole_time         = bore_count * time_per_bore + thread_count * time_per_thread
machining_cost    = (rough_time + finish_time + hole_time) / 60 * machine.hourly_rate
machining_cost   *= tolerance_multiplier    // from drawing data if available
surface_cost      = f(tightest_Ra)          // additional finishing operations
secondary_cost    = heat_treatment + coating + plating
overhead_cost     = subtotal * overhead_rate
unit_cost(qty)    = (per_unit * qty + setup_cost) / qty
```

Tolerance multipliers (from drawing analysis):
- <= 0.01mm: 1.8x (grinding/lapping)
- <= 0.05mm: 1.3x (precision machining)
- <= 0.10mm: 1.1x (standard CNC)

All rates configurable per tenant via `/v1/config/*` endpoints and admin UI.

---

### 14.9 Verification & Testing Strategy

| Level | What | How |
|-------|------|-----|
| **Unit tests** | Geometry extractor, formula engine, material matcher | pytest with sample STEP fixtures (5-10 STEP files of varying complexity) |
| **Integration tests** | Full API flow: upload STEP → job → geometry → cost | FastAPI TestClient + test database |
| **Accuracy benchmarks** | Formula engine output vs known parts | Benchmark set of 20+ parts with known manufacturing costs; track MAPE per model version |
| **Load tests** | Concurrent STEP processing throughput | Locust: target 50 concurrent uploads, <30s p95 latency |
| **Model evaluation** | Pre-trained encoder quality | Embedding clustering quality on held-out set (silhouette score) |
| **Drawing extraction** | VLM accuracy on engineering drawings | 50+ drawings with known specs; measure extraction precision/recall per field |
| **End-to-end smoke** | Upload STEP + drawing → enrichment + cost + similar parts | CI pipeline against staging after every deploy |

---

### 14.10 Revenue Model

> **Note:** The Free/Starter/Growth/Enterprise tier model below is superseded by the usage-based per-call pricing architecture in **Section 15.6**. The revenue targets remain directionally valid — the pricing *mechanism* changes to per-call (no plans, no tiers). See Section 15.6 for the definitive pricing model.

#### Pricing Architecture

| Tier | Monthly | Included | Overage |
|------|---------|----------|---------|
| **Free / Sandbox** | $0 | 50 cost estimates + 200 enrichments | Hard cap |
| **Starter** | $299 | 1,000 cost + 5,000 enrich | $0.25/cost, $0.05/enrich |
| **Growth** | $999 | 5,000 cost + 25,000 enrich + drawing analysis | $0.20/cost, $0.04/enrich |
| **Enterprise** | Custom | Unlimited + LoRA fine-tuning + SLA + dedicated support | Volume discount |

#### Revenue Targets

| Year | Tenants | MRR | ARR |
|------|---------|-----|-----|
| Y1 | 50 paying | $25K | $300K |
| Y2 | 200 paying | $150K | $1.8M |
| Y3 | 500 paying + PLM embeds | $500K | $6M |

PLM/ERP embed licensing (Teamcenter, Windchill, SAP) provides per-seat or per-transaction royalties — the path to $100M+ ARR.

---

### 14.11 Getting Started

**Prerequisites for development:**
- Python 3.12+
- Node.js 20+ (Tailwind CSS build only)
- Docker + Docker Compose
- PostgreSQL 16 (via Docker)
- Redis (via Docker)
- MinIO (via Docker, S3-compatible local storage)
- PythonOCC-core (via conda in Docker worker image)

**First development session should:**
1. Create the standalone `cadprice` repository
2. Set up pyproject.toml with FastAPI, SQLAlchemy, Celery, Pydantic dependencies
3. Create docker-compose.yml with all services
4. Implement FastAPI app factory with health check endpoint
5. Set up Alembic + initial migration with core tables
6. Implement API key auth middleware
7. Build the async job pattern (POST → 202 → poll GET)
8. Wire up STEP file upload → MinIO storage → Celery task

This gets the skeleton running end-to-end. Geometry extraction and cost formulas build on top of this foundation.

---

## 15. Platform Architecture: Two Pillars, One Intelligence Layer

Sections 11-14 describe *what* CADPrice does — geometry extraction, cost formulas, AI cost prediction, similar part search, drawing intelligence, process routing. But they don't answer the architectural question that matters most for engineering, pricing, and trust:

**Which capabilities are deterministic (same input → same output, every time) and which are probabilistic (AI/ML, improves over time, confidence-bounded)?**

This distinction drives everything:
- **Infrastructure**: deterministic capabilities run on plain CPU; AI capabilities need GPU inference
- **Pricing**: deterministic calls have ~$0.01 marginal cost; AI calls have ~$0.03-0.50 depending on model
- **Trust**: manufacturers need to know whether a number came from a formula or a neural network
- **Testing**: deterministic capabilities have exact expected outputs; AI capabilities have accuracy bands
- **Availability**: deterministic capabilities work from day one; AI capabilities improve with data

Section 15 defines the formal architecture: two pillars with a clear interface contract, a parallel enrichment pipeline, three end-to-end workflows, an ensemble pattern for blending estimates, and a usage-based pricing model.

---

### 15.1 The Two Pillars: Architectural Definition

Every capability in CADPrice belongs to exactly one of two pillars. There is no ambiguity — each capability ID (D1-D7 or A1-A9) maps to precisely one pillar.

#### Pillar 1 — Deterministic Data Enhancement Engine (DDE)

Pure computation. No neural networks. No training data. No confidence intervals. Given the same STEP file and the same configuration, DDE produces byte-identical output every time. This is the foundation that works from day one.

| ID | Capability | Input | Output | Basis | Latency |
|----|-----------|-------|--------|-------|---------|
| **D1** | Geometry Extraction | STEP file | 47+ parameters (volume, surface area, bounding box, bore count/diameter/depth, thread count, wall thickness, turning profile, sheet metal thickness/bends) | PythonOCC B-Rep traversal — walks the CAD topology tree and computes geometric properties from faces, edges, and solids | 2-15s |
| **D2** | Drawing Intelligence Tier 1 | PDF (vector-based engineering drawing) | Material specification, general tolerances, surface roughness (Ra) values, secondary process callouts (heat treatment, coating, plating) | PyMuPDF text/vector extraction + regex pattern matching against ISO/DIN/ASME standards | <1s |
| **D3** | Master Data Classification | D1 geometry parameters | Manufacturing method (milling/turning/molding/sheet metal/assembly), eCl@ss 14.0 code, UNSPSC code | Rule-based decision tree: e.g., if turning_profile exists AND max_diameter/length > 0.3 → turning; if bend_count > 0 AND thickness < 6mm → sheet metal | <100ms |
| **D4** | Cost Formula Engine | D1 geometry + D2 material + machine configuration + quantity | Full cost breakdown: material cost, setup cost, machining cost (roughing + finishing + holes), surface finishing cost, secondary process cost, overhead, per-unit cost at quantity | Configurable rate tables ($/hr per machine, $/kg per material) × geometry-derived cycle times. See Section 14.8 for formula pseudocode | <500ms |
| **D5** | DFM Rule Checks | D1 geometry parameters | Manufacturability warnings: wall thickness below minimum, bore depth/diameter ratio exceeded, undercut geometry detected, tolerance tighter than process capability | Threshold rules from manufacturing handbooks (e.g., CNC milling min wall = 0.8mm, bore depth/diameter max = 10:1) | <100ms |
| **D6** | Material Fuzzy Matching | Raw material designation string (from drawing or user input) | Canonical material code (e.g., "1.4301" → "X5CrNi18-10" → "AISI 304") + material properties (density, tensile strength, machinability index) | Levenshtein distance + n-gram similarity against alias lookup table (10K+ material designations across DIN/AISI/JIS/GB standards) | <100ms |
| **D7** | Quantity Break Calculation | D4 unit costs + setup cost + batch parameters | Per-unit cost at qty 1, 10, 100, 1000, custom quantities | Setup cost amortization: `unit_cost(qty) = (per_unit_variable × qty + setup_cost) / qty` — pure arithmetic | <10ms |

**DDE characteristics:**
- **Total latency** (serial): 2-16s, dominated by D1 geometry extraction
- **Infrastructure**: CPU only. No GPU. No model serving. Runs on any $5/mo VPS
- **Reproducibility**: Bit-for-bit identical output given identical input + configuration
- **Configuration surface**: Machine hourly rates, material prices, overhead percentages, DFM thresholds — all tenant-configurable via admin UI and `/v1/config/*` API endpoints
- **Day-one readiness**: Works immediately. No training data required. No cold-start problem

#### Pillar 2 — AI Feature Set (AFS)

Neural networks. Training data. Confidence intervals. Improves with every correction. This is the intelligence layer that learns from data and eventually surpasses formula-based estimation for tenants with sufficient history.

| ID | Capability | Input | Output | Model | Training Data | Latency |
|----|-----------|-------|--------|-------|---------------|---------|
| **A1** | Geometric Encoder | STEP file (converted to point cloud or B-Rep graph) | 512-dimensional embedding vector — a learned "fingerprint" of the part's geometry | Point-MAE (point cloud) or BRepFormer (B-Rep graph) — self-supervised pre-training on shape reconstruction | 2M+ open CAD models from ABC Dataset, Fusion 360 Gallery, Thingi10K (self-supervised — no labels needed) | 1-3s |
| **A2** | AI Cost Prediction | A1 embedding + D1 explicit features + material + quantity | Predicted cost + 95% confidence interval + cost breakdown estimate | MLP regression head + per-tenant LoRA fine-tuning layers | **Pre-training**: 9M+ labeled pairs from aPriori/Classmate oracle runs (Section 13.3). **Fine-tuning**: Customer production costs, ERP actuals, manual corrections | 200-500ms |
| **A3** | Drawing Intelligence Tier 2 | PDF (scanned drawings, complex GD&T, multi-sheet) | Structured extraction: full GD&T callouts, title block fields (part number, revision, material, weight), BOM tables, notes | Vision-Language Model (GPT-4o / Claude) with structured output prompting | General VLM pre-training (no task-specific fine-tuning needed — prompt engineering + few-shot examples) | 3-10s |
| **A4** | Similar Part Search | A1 embedding vector | Top-K most geometrically similar parts from tenant's catalog + cross-tenant anonymized matches | k-NN search on pgvectorscale (HNSW index) | No explicit training — uses A1 embeddings indexed at ingestion time | <200ms |
| **A5** | Process Route Suggestion | A1 embedding + D1 features + D3 classification | Ordered operation sequence (e.g., saw → lathe rough → lathe finish → mill pockets → deburr → heat treat) + machine selection per operation | Graph Neural Network on machining feature graph | MFCAD++ dataset: 160K CAD models with labeled machining features (slot, hole, pocket, boss, etc.) + oracle process routes from aPriori | 500ms-1s |
| **A6** | AI DFM Feedback | A1 embedding + D1 geometry + D4 formula cost | Learned risk patterns beyond rule-based D5: unusual feature combinations, historical failure modes, cost optimization suggestions ("this pocket adds 40% to machining time — consider a simpler profile") | Pattern recognition from oracle DFM analysis | 9M aPriori-labeled parts include DFM warnings and manufacturing notes — distill these into a learned DFM model | 500ms |
| **A7** | Cost Driver Attribution | A2 model internals + D1 geometry + cost prediction | Per-feature cost contribution percentages: "bore #3 contributes 22% of machining cost; tight tolerance on surface B adds 15%" | SHAP (SHapley Additive exPlanations) / Grad-CAM applied to A2 model | Inherent to A2 — no additional training, computed from model gradients | 1-2s |
| **A8** | Part Family Clustering | All tenant embeddings from A1 | Natural part groupings: families of similar parts, outlier detection, catalog organization suggestions | HDBSCAN (Hierarchical Density-Based Spatial Clustering) — unsupervised, no labels needed | Embeddings from A1, computed at ingestion. Clustering runs as batch job (nightly or on-demand) | Batch (minutes) |
| **A9** | Material Recommendation | A1 embedding + cost/weight/strength constraints | Ranked material suggestions with cost/performance trade-off analysis: "switching from 1.4404 to 1.4301 saves 12% material cost with equivalent corrosion resistance for this application" | Classification head on top of A1 embeddings | Oracle material selections from aPriori labels + customer historical material choices + material property database | 200-500ms |

**AFS characteristics:**
- **Total latency** (serial from STEP): A1 (1-3s) + A2-A9 (0.5-2s each) — but A2-A9 run largely in parallel after A1
- **Infrastructure**: GPU for A1 encoding and A2 inference. CPU sufficient for A4 (vector search) and A8 (batch clustering). VLM calls (A3) are external API calls
- **Confidence-bounded**: Every AI output includes a confidence score. Low confidence → fall back to deterministic
- **Improves over time**: Per-tenant LoRA fine-tuning on A2; embedding index grows with A4; clustering improves with A8
- **Cold-start mitigation**: Pre-trained on 9M oracle labels (Section 13.3). New tenants get base model accuracy (~85% within ±20%) from day one. LoRA fine-tuning improves to ~92-95% within ±10% after 500+ tenant-specific corrections

---

### 15.2 Interface Contract Between the Two Pillars

The DDE and AFS are not independent silos — they share data through well-defined feeds. The interface contract specifies exactly what crosses the boundary and in which direction.

#### Data Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          INPUT: STEP + PDF                              │
└───────────┬─────────────────────────────────────┬───────────────────────┘
            │                                     │
            ▼                                     ▼
┌───────────────────────────┐       ┌───────────────────────────┐
│   PILLAR 1: DDE           │       │   PILLAR 2: AFS           │
│                           │       │                           │
│  D1 Geometry Extraction ──┼──[F1]─┼──► A1 Geometric Encoder   │
│          │                │       │          │                │
│  D2 Drawing Intel T1 ────┼──[F2]─┼──► A2 AI Cost Prediction  │
│          │                │       │          │                │
│  D6 Material Match        │       │  A3 Drawing Intel T2      │
│  D3 Classification        │       │  A4 Similar Part Search   │
│  D5 DFM Rules             │       │  A5 Process Route         │
│  D4 Cost Formula ─────────┼──[F3]─┼──► A2 (training signal)  │
│  D7 Quantity Breaks       │       │  A6 AI DFM Feedback       │
│          ▲                │       │  A7 Cost Attribution      │
│          │                │       │  A8 Part Family Cluster   │
│          └────────────────┼──[F4]─┼──  A9 Material Recommend  │
│                           │       │     A5 Process Route      │
└───────────────────────────┘       └───────────────────────────┘
            │                                     │
            ▼                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                    ENSEMBLE / CONFIDENCE LAYER                          │
│         Merge DDE + AFS → select primary estimate → deliver            │
└─────────────────────────────────────────────────────────────────────────┘
```

#### Feed Definitions

**Feed 1 (F1): Geometry Parameters → AI Feature Input**
- **Source**: D1 Geometry Extraction
- **Destination**: A1 Geometric Encoder (STEP file itself), A2 AI Cost Prediction (explicit features)
- **Payload**: The 47+ geometry parameters from D1 become explicit input features to A2 alongside the A1 embedding. A1 takes the raw STEP file (not D1 output) to learn its own representation
- **Contract**: D1 must complete before A2 can run. A1 can start in parallel with D1 (both take raw STEP)

**Feed 2 (F2): Drawing Data → Metadata Features**
- **Source**: D2 Drawing Intelligence Tier 1
- **Destination**: D4 Cost Formula (tolerance multipliers, material spec), A2 AI Cost Prediction (all extracted metadata as features)
- **Payload**: Material designation, general tolerance class, surface roughness values, secondary process list
- **Contract**: D2 output enriches both pillars. If no PDF provided, D4 and A2 use defaults

**Feed 3 (F3): Formula Costs → AI Training Signal**
- **Source**: D4 Cost Formula Engine
- **Destination**: A2 AI Cost Prediction (as bootstrap training label)
- **Payload**: D4's cost breakdown serves as a training signal for A2 during the bootstrap phase (before tenant has production actuals). Once ERP actual costs are available, F3's role diminishes — actual costs become the primary training signal
- **Contract**: This is a training-time feed, not an inference-time feed. At inference time, D4 and A2 produce independent estimates that the ensemble layer compares

**Feed 4 (F4): AI Suggestions → Formula Input (Feedback Path)**
- **Source**: A9 Material Recommendation, A5 Process Route Suggestion
- **Destination**: D4 Cost Formula Engine (alternative material/process inputs)
- **Payload**: A9 may suggest a different material; A5 may suggest a different process route. If accepted (by user or automation rule), these become new inputs to D4 for a re-costed estimate
- **Contract**: This is an optional feedback path. D4 always runs first with the given inputs. A9/A5 suggestions trigger a D4 re-run only if the user or an automation rule accepts the suggestion

#### Interface Data Types

```python
# Feed 1: D1 → A2
@dataclass
class GeometryFeatures:
    volume_mm3: float
    surface_area_mm2: float
    bounding_box: tuple[float, float, float]  # L, W, H in mm
    bore_count: int
    thread_count: int
    max_bore_depth_ratio: float
    wall_thickness_min_mm: float
    turning_profile: bool
    bend_count: int
    # ... 47+ fields total

# Feed 2: D2 → D4, A2
@dataclass
class DrawingMetadata:
    material_designation: str | None
    tolerance_class: str | None        # e.g., "ISO 2768-mK"
    surface_roughness_ra: list[float]  # Ra values in μm
    secondary_processes: list[str]     # e.g., ["heat_treatment", "zinc_plating"]
    title_block: dict | None           # part number, revision, etc.

# Feed 3: D4 → A2 (training only)
@dataclass
class FormulaCostLabel:
    total_cost: float
    material_cost: float
    setup_cost: float
    machining_cost: float
    finishing_cost: float
    overhead_cost: float
    quantity: int
    confidence: float  # always 1.0 for formula (deterministic)

# Feed 4: A9/A5 → D4 (feedback)
@dataclass
class AISuggestion:
    suggestion_type: Literal["material", "process_route"]
    current_value: str
    suggested_value: str
    rationale: str
    estimated_impact: float  # % cost change
```

---

### 15.3 The Enrichment Pipeline: How a Single Part Flows

When a STEP file (and optional PDF drawing) enters CADPrice, it flows through a three-stage pipeline. The key insight is that **Stages 1 and 2 run in parallel** — both take the STEP file as input and start simultaneously. This means total latency is dominated by the slower of the two, not the sum.

#### Pipeline Diagram

```
INPUT: STEP file + optional PDF drawing
       │
       ▼
┌──────────────────────────────────────────────────────────────────┐
│  STAGE 0: Format Normalization                          (0-5s)  │
│                                                                  │
│  Native CAD format?  ──YES──►  CAD Exchanger  ──►  STEP 214     │
│         │                                                        │
│         NO (already STEP)  ──►  Pass through                     │
│                                                                  │
│  Supported native formats: CATIA V5 (.CATPart), NX (.prt),      │
│  SolidWorks (.SLDPRT), Creo (.prt), Inventor (.ipt)             │
│  via CAD Exchanger SDK ($2,500/yr server license)                │
└──────────────────────┬───────────────────────────────────────────┘
                       │
          ┌────────────┴────────────┐
          │                         │
          ▼                         ▼
┌─────────────────────┐   ┌─────────────────────┐
│ STAGE 1: DDE        │   │ STAGE 2: AFS        │
│ (ALWAYS RUNS)       │   │ (IF AI TIER)        │
│                     │   │                     │
│ ┌─────┐  ┌─────┐   │   │ ┌─────┐  ┌─────┐   │
│ │ D1  │  │ D2  │   │   │ │ A1  │  │ A3  │   │
│ │Geom │  │Draw │   │   │ │Enc  │  │Draw │   │
│ │2-15s│  │ <1s │   │   │ │1-3s │  │3-10s│   │
│ └──┬──┘  └──┬──┘   │   │ └──┬──┘  └──┬──┘   │
│    │        │       │   │    │        │       │
│    ▼        ▼       │   │    ▼        ▼       │
│ ┌─────────────────┐ │   │ ┌─────────────────┐ │
│ │ D6 Material     │ │   │ │ A2 AI Cost      │ │
│ │ D3 Classify     │ │   │ │ 200-500ms       │ │
│ │ D5 DFM Rules    │ │   │ └────┬────────────┘ │
│ │ <300ms total    │ │   │      │               │
│ └────┬────────────┘ │   │      ▼               │
│      │              │   │ ┌─────────────────┐  │
│      ▼              │   │ │ A4 Similar      │  │
│ ┌─────────────────┐ │   │ │ A5 Process      │  │
│ │ D4 Cost Formula │ │   │ │ A6 AI DFM       │  │
│ │ <500ms          │ │   │ │ A7 Attribution  │  │
│ └────┬────────────┘ │   │ │ A9 Material     │  │
│      │              │   │ │ 0.5-2s total    │  │
│      ▼              │   │ └────┬────────────┘  │
│ ┌─────────────────┐ │   │      │               │
│ │ D7 Qty Breaks   │ │   │      │               │
│ │ <10ms           │ │   │      │               │
│ └────┬────────────┘ │   │      │               │
│      │              │   │      │               │
└──────┼──────────────┘   └──────┼───────────────┘
       │                         │
       ▼                         ▼
┌──────────────────────────────────────────────────────────────────┐
│  STAGE 3: Ensemble & Delivery                          (<100ms) │
│                                                                  │
│  1. Merge DDEResult + AFSResult into EnrichedPart               │
│  2. Calculate divergence: |ai_cost - formula_cost| / formula    │
│  3. Apply confidence thresholds (see Section 15.5)              │
│  4. Select primary estimate + attach metadata                    │
│  5. Return via API / push to PLM / render in UI                  │
└──────────────────────────────────────────────────────────────────┘
```

#### Latency Analysis

| Scenario | Stage 0 | Stage 1 (DDE) | Stage 2 (AFS) | Stage 3 | Total |
|----------|---------|---------------|----------------|---------|-------|
| **Deterministic only** (small STEP, no PDF) | 0s | 2-3s | N/A | <100ms | **2-3s** |
| **Deterministic only** (large STEP + PDF) | 0s | 12-15s | N/A | <100ms | **12-15s** |
| **Full AI** (small STEP, no PDF) | 0s | 2-3s | 2-4s | <100ms | **2-4s** |
| **Full AI** (large STEP + PDF) | 0s | 12-15s | 5-12s | <100ms | **12-15s** |
| **Native CAD + Full AI** (large, PDF) | 3-5s | 12-15s | 5-12s | <100ms | **15-20s** |

Key observations:
- **Stages 1 and 2 run in parallel**, so total ≈ max(Stage 1, Stage 2), not sum
- DDE (Stage 1) is the bottleneck for large files — D1 geometry extraction dominates at 2-15s
- AFS (Stage 2) adds zero latency when DDE is slow, because A1 encoding (1-3s) finishes before D1
- For small files, AFS can actually be the bottleneck if A3 drawing Tier 2 is invoked (3-10s VLM call)
- **Typical end-to-end: 5-21s** depending on file complexity and whether AI tier is requested

#### Parallelism Detail

Within each stage, tasks also run in parallel where dependencies allow:

```
Stage 1 parallel groups:
  Group 1 (parallel): D1, D2           # Both take raw input, no dependencies
  Group 2 (serial after G1): D6 → D3   # D6 needs D2 output, D3 needs D1+D6
  Group 3 (serial after G2): D5, D4    # Both need D1+D3, can run parallel
  Group 4 (serial after G3): D7        # Needs D4 output

Stage 2 parallel groups:
  Group 1 (parallel): A1, A3           # Both take raw input, no dependencies
  Group 2 (serial after A1): A2        # Needs A1 embedding + D1 features
  Group 3 (parallel after A2): A4, A5, A6, A7, A9  # All need A1/A2, independent
```

---

### 15.4 Three User Workflows End-to-End

CADPrice serves three distinct consumption patterns. Each workflow uses the same enrichment pipeline (Section 15.3) but differs in trigger, delivery, and feedback mechanism.

#### Workflow A — Middleware (PLM → CADPrice → ERP)

The primary enterprise workflow. No human intervention for standard parts. Engineers release parts in their PLM system; enriched data appears in ERP automatically.

```
┌──────────────┐    Event:          ┌──────────────┐    Enriched      ┌──────────────┐
│  Teamcenter  │    part_released   │              │    attributes    │     SAP      │
│  Windchill   │ ──────────────────►│   CADPrice   │ ───────────────► │    Oracle    │
│  3DEXPERIENCE│    STEP + metadata │   Pipeline   │    + cost est.   │    IFS       │
└──────┬───────┘                    └──────┬───────┘                  └──────┬───────┘
       │                                   │                                 │
       │          Low-confidence           │         Production              │
       │◄──────── queue for review ────────┤         completion              │
       │          (PLM workflow task)       │◄────────────────────────────────┘
       │                                   │         actual cost → LoRA retrain
       │          Engineer corrects        │
       └──────────────────────────────────►│
                  → active learning        │
                    training sample        │
```

**Step-by-step flow:**

1. **Trigger**: Part reaches "Released" state in PLM (Teamcenter, Windchill, 3DEXPERIENCE). PLM connector webhook fires
2. **Enrichment**: CADPrice receives STEP file + PLM metadata. Runs full pipeline (deterministic + AI if tenant has AI tier)
3. **Confidence check**: If AI confidence > 0.8 and divergence < 15% → auto-push to ERP. Otherwise → queue for engineer review in PLM
4. **ERP push**: Enriched attributes (classification, material code, cost estimate, DFM flags) written to ERP material master via ERP connector
5. **Feedback loop**: When production completes, ERP sends actual cost back to CADPrice → becomes LoRA fine-tuning sample
6. **Engineer review**: For low-confidence parts, engineer sees formula + AI estimates side by side in PLM task. Their correction becomes a training sample

**Connector pricing**: $500-2,000/mo per connected system (flat pipe fee) + per-call enrichment pricing. A Teamcenter connector processing 5,000 parts/month = connector fee + 5,000 × enrichment call price.

#### Workflow B — API (Developer Calls REST)

For software teams integrating CADPrice into their own applications. Separate endpoints for deterministic vs. AI — the caller explicitly chooses, like choosing between OpenAI model endpoints.

**Endpoint definitions:**

```
POST /v1/enrich/deterministic
  Request:  { step_file: base64, drawing_pdf?: base64, quantity?: int, config?: {...} }
  Response: DDEResult (geometry, classification, formula cost, DFM rules, qty breaks)
  Price:    $1-3/call
  Latency:  2-15s

POST /v1/enrich/ai
  Request:  { step_file: base64, drawing_pdf?: base64, quantity?: int, config?: {...} }
  Response: EnrichedPart (DDEResult + AI cost + confidence + similar parts + process route + cost drivers)
  Price:    $3-8/call
  Latency:  3-21s

POST /v1/enrich/drawing
  Request:  { drawing_pdf: base64, extraction_level?: "tier1" | "tier2" | "auto" }
  Response: DrawingMetadata (material, tolerances, GD&T, title block)
  Price:    $1-3/call
  Latency:  <1s (Tier 1) or 3-10s (Tier 2)

POST /v1/search/similar
  Request:  { step_file: base64, top_k?: int, tenant_only?: bool }
  Response: SimilarPartResult (top-K similar parts with similarity scores + metadata)
  Price:    $0.10-0.50/call
  Latency:  1-3s (includes A1 encoding)

POST /v1/training/correct
  Request:  { part_id: str, field: str, corrected_value: any, source?: str }
  Response: { accepted: true, training_queue_position: int }
  Price:    Free (corrections are training data — we want them)
  Latency:  <100ms
```

**API design principles:**
- **Explicit endpoint choice**: `/deterministic` vs `/ai` — no magic "auto" mode. Developer knows what they're paying for
- **Stateless**: Each call is independent. No sessions, no state, no "upload then query" pattern. STEP file goes in, result comes out
- **Async option**: For large files, `POST` returns `202 Accepted` with job ID; `GET /v1/jobs/{id}` polls for result
- **Idempotent**: Same STEP + same config = same result (deterministic). AI results cached for 24h per config hash
- **Rate limits**: 100 concurrent requests per API key (soft limit, raise on request)

**Authentication:**
```
Authorization: Bearer cpk_live_abc123...    # Production key
Authorization: Bearer cpk_test_abc123...    # Sandbox key (free credits, no billing)
```

#### Workflow C — Interactive (Web UI Playground)

For engineers evaluating CADPrice, exploring their parts, and providing corrections. Progressive rendering shows results as they arrive.

```
┌─────────────────────────────────────────────────────────────────────┐
│  CADPrice Playground                                      [Export] │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │  Drop STEP file + optional PDF here           [Browse...]   │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ┌─────────────────────────┐  ┌─────────────────────────────┐     │
│  │  GEOMETRY (3s) ✓        │  │  DRAWING DATA (1s) ✓        │     │
│  │  Volume: 42,350 mm³     │  │  Material: 1.4301 (AISI304) │     │
│  │  Surface: 18,200 mm²    │  │  Tolerance: ISO 2768-mK     │     │
│  │  Bores: 6 (max Ø12mm)  │  │  Ra: 1.6 / 3.2 / 6.3 μm    │     │
│  │  Threads: 4 × M8        │  │  Heat treatment: Yes         │     │
│  │  Classification: Milling │  │  Plating: Zinc (Fe/Zn 8)   │     │
│  └─────────────────────────┘  └─────────────────────────────┘     │
│                                                                     │
│  ┌─────────────────────────┐  ┌─────────────────────────────┐     │
│  │  DFM CHECKS (3.5s) ✓   │  │  FORMULA COST (4s) ✓        │     │
│  │  ⚠ Wall 0.6mm < 0.8mm  │  │  Material:    €12.40        │     │
│  │  ⚠ Bore #3: 14:1 ratio │  │  Setup:       €45.00        │     │
│  │  ✓ No undercuts         │  │  Machining:   €38.60        │     │
│  │  ✓ Threads standard     │  │  Finishing:   €8.20         │     │
│  │                         │  │  Overhead:    €15.63        │     │
│  │                         │  │  ─────────────────────      │     │
│  │                         │  │  TOTAL:       €119.83/pc    │     │
│  └─────────────────────────┘  │  Qty 100:     €74.38/pc     │     │
│                                  └─────────────────────────────┘     │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  AI PREDICTION (6s) ✓                     Confidence: 87%   │  │
│  │                                                              │  │
│  │  AI Estimate:  €108.50/pc  ±€11.20 (95% CI)                │  │
│  │  Formula:      €119.83/pc                                    │  │
│  │  Divergence:   9.4% — NORMAL                                 │  │
│  │                                                              │  │
│  │  Cost Drivers:                                               │  │
│  │  ████████████░░ Machining (52%) — 6 bores + tight tolerance │  │
│  │  ████░░░░░░░░░░ Material (18%) — stainless steel premium    │  │
│  │  ███░░░░░░░░░░░ Finishing (14%) — heat treat + zinc plate   │  │
│  │  ██░░░░░░░░░░░░ Setup (10%)                                 │  │
│  │  █░░░░░░░░░░░░░ Overhead (6%)                               │  │
│  │                                                              │  │
│  │  [Correct this estimate]  [View similar parts (12 found)]   │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  SIMILAR PARTS (6.5s) ✓                                     │  │
│  │  1. Housing-A340 (94% similar) — last costed €115.20        │  │
│  │  2. Cover-B112 (89% similar) — last costed €98.40           │  │
│  │  3. Bracket-C205 (82% similar) — last costed €102.70        │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                     │
│  [Export PDF Report]  [Save to Catalog]  [Send to ERP]             │
└─────────────────────────────────────────────────────────────────────┘
```

**Progressive rendering flow:**
1. **0-3s**: Geometry extraction results appear (D1). 3D viewer renders part
2. **0-1s**: Drawing data appears (D2) — often faster than geometry
3. **3-4s**: DFM rules (D5) and classification (D3) appear
4. **4-5s**: Formula cost (D4) and quantity breaks (D7) appear
5. **5-7s**: AI cost prediction (A2) with confidence and cost drivers (A7) appear
6. **6-8s**: Similar parts (A4) and process route (A5) appear
7. **Anytime**: User clicks "Correct this estimate" → correction form → submitted as training sample via `/v1/training/correct`

---

### 15.5 The Ensemble/Confidence Pattern

When both DDE and AFS produce cost estimates, the ensemble layer decides which to present as the primary estimate and how to communicate uncertainty to the user.

#### Decision Matrix

| AI Confidence | Divergence from Formula | Primary Estimate | UI Behavior | API `estimate_source` |
|---------------|------------------------|-----------------|-------------|----------------------|
| **High** (>0.8) | **Low** (<15%) | AI estimate | AI primary, formula shown as reference. Green confidence badge | `"ai"` |
| **High** (>0.8) | **High** (>15%) | AI estimate + divergence warning | AI primary with yellow alert: "AI and formula diverge by X% — review recommended". Flag for investigation | `"ai_divergent"` |
| **Medium** (0.6-0.8) | **Low** (<15%) | Weighted blend | `blend = conf × ai + (1-conf) × formula`. Show both values. Yellow confidence badge | `"blended"` |
| **Medium** (0.6-0.8) | **High** (>15%) | Formula + AI range | Formula primary, AI shown as secondary context with wide CI. "AI estimate less certain for this part type" | `"formula_ai_context"` |
| **Low** (<0.6) | Any | Formula only | Formula primary. AI estimate hidden or shown as footnote: "AI model has insufficient data for this part type" | `"formula_only"` |
| **No AI model** | N/A | Formula only | Caller used `/deterministic` endpoint, or tenant is pre-LoRA. No AI section shown | `"deterministic"` |

#### Divergence Thresholds

| Divergence Band | Color | Interpretation | Action |
|----------------|-------|----------------|--------|
| **<15%** | Green | Normal — formula and AI agree within expected tolerance | No action needed |
| **15-25%** | Yellow | Attention — meaningful disagreement, could indicate unusual part or config issue | Queue for review in middleware; show warning in UI/API |
| **>25%** | Red | Alarm — significant disagreement, likely indicates data quality issue, missing info, or out-of-distribution part | Block auto-push to ERP; require human review; investigate root cause |

#### Blend Formula

When `estimate_source` is `"blended"` (medium confidence, low divergence):

```python
def blend_estimates(ai_cost: float, formula_cost: float, ai_confidence: float) -> float:
    """
    Weighted blend favoring the more confident source.
    At confidence 0.6: 60% AI + 40% formula
    At confidence 0.8: 80% AI + 20% formula
    """
    return ai_confidence * ai_cost + (1 - ai_confidence) * formula_cost
```

The blend is a simple linear interpolation. More sophisticated approaches (e.g., Bayesian model averaging) are possible but add complexity without proportional value — the goal is a reasonable default, not a perfect posterior.

#### Confidence Calibration

AI confidence must be **calibrated**, not just a raw softmax score. Calibration means: when the model says "80% confident", the true cost should fall within the predicted CI 80% of the time.

Calibration strategy:
1. **Pre-launch**: Calibrate on held-out oracle labels (10% of 9M aPriori/Classmate labels)
2. **Per-tenant**: Recalibrate after every LoRA retrain using tenant's own correction history
3. **Monitoring**: Track calibration drift weekly. Alert if reliability diagram shows >5% miscalibration

---

### 15.6 Usage-Based Pricing Model

> **Note:** This section supersedes the plan-based tier models in Section 13.5 (four-tier connector/event/platform/data architecture) and Section 14.10 (Free/Starter/Growth/Enterprise plans). The revenue projections in those sections remain valid — only the pricing *mechanism* changes from plan tiers to per-call usage. See bridge notes in Sections 13.5 and 14.10.

**No plans. No tiers. No commitments.** Sign up, get an API key, pay per call. Volume discounts kick in automatically. This is the OpenAI/Stripe model applied to manufacturing intelligence.

#### Per-Call Pricing

| Call Type | What You Get | Price | Marginal Cost | Gross Margin |
|-----------|-------------|-------|---------------|-------------|
| **Deterministic Enrichment** | D1-D7: geometry extraction + master data classification + formula cost breakdown + DFM rule checks + quantity breaks | $1-3 | ~$0.01 (CPU only) | ~99% |
| **AI Enrichment** | Everything in Deterministic PLUS A1-A9: AI cost prediction with confidence interval + similar part search + process route suggestion + cost driver attribution + AI DFM feedback + material recommendation | $3-8 | ~$0.03 (GPU inference) | ~96% |
| **Full Enrichment + Drawing** | Everything above + D2/A3 drawing intelligence (Tier 1 runs automatically; Tier 2 VLM invoked if Tier 1 extraction confidence is low or drawing is scanned/complex) | $5-12 | ~$0.05-0.50 (VLM if Tier 2) | ~92-99% |
| **Similar Part Search only** | A4: k-NN query against tenant's indexed part catalog. Requires prior enrichment of catalog parts | $0.10-0.50 | ~$0.001 | ~99% |
| **Drawing Analysis only** | D2 + A3: extract material spec, tolerances, GD&T, title block from PDF engineering drawing | $1-3 | ~$0.01-0.30 | ~90-99% |

Price ranges reflect file complexity — a 10KB STEP file costs less than a 5MB assembly. Billing is based on actual compute consumed, rounded to the nearest pricing tier.

#### Volume Discounts (Automatic, No Negotiation)

Discounts apply automatically based on rolling 30-day call volume. No sales calls. No contract negotiations. No annual commitments. Just use more, pay less per call.

| Monthly Volume | Discount | Effective AI Enrichment Price (from $5.00 base) |
|---------------|----------|--------------------------------------------------|
| 0-500 calls | List price | $5.00 |
| 501-2,000 | 10% | $4.50 |
| 2,001-10,000 | 20% | $4.00 |
| 10,001-50,000 | 35% | $3.25 |
| 50,001+ | 50% (floor) | $2.50 |

Volume tiers are evaluated monthly. If usage drops, the discount adjusts down the following month. No clawback on past usage.

#### Free Credits on Signup

Every new account receives:
- **100 deterministic enrichment calls** — enough to validate geometry extraction and formula costing on real parts
- **25 AI enrichment calls** — enough to see AI cost prediction, similar part search, and cost drivers in action
- **No credit card required** — reduce friction to zero for evaluation

Credits expire after 90 days. After credits, pay-as-you-go begins. No surprise charges — billing dashboard shows real-time usage and projected monthly cost.

#### Add-Ons (Usage-Based, Not Plan-Gated)

| Add-on | Price | Notes |
|--------|-------|-------|
| **Per-tenant LoRA fine-tuning** | $0.50 per training sample ingested + $25 per retrain run | Automatically triggered when correction queue reaches threshold (default: 50 new samples). Customer's production data improves their AI accuracy without affecting other tenants |
| **PLM/ERP connector** | $500-2,000/mo per connected system | Flat monthly fee for the connector infrastructure (webhook listener, credential management, field mapping UI). Enrichment calls through the connector priced per-call as above |
| **Active learning corrections** | Free (included) | Every correction is a free training sample that improves the model. We want corrections — they make the product better. No charge, ever |
| **Batch processing** (>1,000 parts) | 40% discount on per-call rates | For vault migrations, legacy catalog enrichment, initial catalog onboarding. Submitted as a batch job, results delivered via webhook or download |

#### Why Usage-Based Beats Plan-Based

| Plan-Based Problem | Usage-Based Solution |
|-------------------|---------------------|
| "Which plan do I need?" → decision paralysis | Just call the API. Pay for what you use |
| SMB priced out of advanced features | Want AI? Call `/ai`. Want deterministic? Call `/deterministic`. No artificial gating |
| Enterprise "unlimited" plans destroy unit economics | Every call has a price. Volume discounts reward scale without giving away margin |
| Annual commitments scare off new customers | Month-to-month. No commitment. Start today, stop tomorrow |
| Feature gating creates resentment | All features available to all customers. Price = usage, not access |

**Natural scaling examples:**
- **SMB** at 50 parts/month: 50 × $5.00 = **$250/mo** — affordable entry point
- **Mid-market** at 2,000 parts/month: 2,000 × $4.00 = **$8,000/mo** — organic growth
- **Enterprise** at 50,000 parts/month: 50,000 × $2.50 = **$125,000/mo** — same API, no plan migration

**PLM/ERP connectors are just automated callers:** A Teamcenter connector that processes 5,000 parts/month = $1,000 connector fee + 5,000 × $4.00 = $21,000/mo total. The middleware pricing IS the API pricing.

**Stripe comparison:** Stripe charges 2.9% + $0.30 per transaction. They don't have plans — you just use it and pay per transaction. We charge $3-8 per enrichment. Both scale infinitely with no plan changes. Both make it trivially easy to start and naturally expensive to leave.

#### Revenue Projections at Scale

**Conservative (Year 3):**
- 1,000 paying customers × 500 AI enrichments/mo × $4.00 avg = **$2.0M/mo = $24M ARR**
- Plus 500 connectors × $1,000/mo = **$6M ARR**
- Plus LoRA fine-tuning: 200 tenants × $500/mo avg = **$1.2M ARR**
- **Total: ~$31M ARR**

**Growth (Year 5):**
- 5,000 paying customers × 2,000 enrichments/mo × $3.50 avg = **$35M/mo = $420M ARR**
- Plus 2,000 connectors × $1,000/mo = **$24M ARR**
- Plus LoRA fine-tuning: 1,000 tenants × $800/mo avg = **$9.6M ARR**
- **Total: ~$454M ARR**

**Why these numbers work:** The revenue math from Sections 13.5 and 14.10 remains valid — the TAM ($1.5-5B) and customer counts are unchanged. Only the pricing mechanism changes. Usage-based actually *increases* revenue potential because there's no ceiling — a heavy user pays proportionally more, while plan-based "Enterprise Unlimited" caps revenue per customer.

---

### 15.7 The Data Flywheel

Every tenant progresses through four stages as their data accumulates. Each stage changes the balance between deterministic and AI capabilities.

#### Flywheel Stages

```
┌─────────────────────────────────────────────────────────────────────┐
│                    TENANT DATA FLYWHEEL                             │
│                                                                     │
│  COLD (0-100 parts)           WARMING (100-500 parts)              │
│  ┌─────────────────┐          ┌─────────────────┐                  │
│  │ Base model only  │          │ LoRA showing     │                  │
│  │ Formula primary  │   ──►    │ improvement      │                  │
│  │ AI = reference   │          │ Ensemble blend   │                  │
│  │ Conf: 0.4-0.6   │          │ Conf: 0.6-0.75   │                  │
│  └─────────────────┘          └─────────────────┘                  │
│         │                              │                            │
│         ▼                              ▼                            │
│  WARM (500-2000 parts)         HOT (2000+ parts)                   │
│  ┌─────────────────┐          ┌─────────────────┐                  │
│  │ LoRA outperforms │          │ High confidence   │                  │
│  │ formula for       │   ──►    │ across most types │                  │
│  │ common types     │          │ Formula = sanity  │                  │
│  │ Formula = check  │          │ check only        │                  │
│  │ Conf: 0.75-0.85 │          │ Conf: 0.85-0.95  │                  │
│  └─────────────────┘          └─────────────────┘                  │
│                                                                     │
│  Each correction:                                                   │
│  • Improves LoRA accuracy for THIS tenant                          │
│  • Improves similar part search for THIS tenant                    │
│  • Anonymized features improve base model for ALL tenants          │
│  • Higher accuracy → fewer corrections needed → lower cost         │
└─────────────────────────────────────────────────────────────────────┘
```

#### Stage Details

| Stage | Parts | AI Confidence | Primary Estimate | Formula Role | Typical Customer |
|-------|-------|---------------|-----------------|--------------|-----------------|
| **Cold** | 0-100 | 0.4-0.6 | Formula (blend leans formula) | Primary — AI is supplementary | New signup, evaluation phase |
| **Warming** | 100-500 | 0.6-0.75 | Blended (roughly 65:35 AI:formula) | Co-primary — ensemble blend | First 3-6 months of active use |
| **Warm** | 500-2,000 | 0.75-0.85 | AI for common types, formula for rare | Sanity check — flags divergence | Established customer, 6-18 months |
| **Hot** | 2,000+ | 0.85-0.95 | AI (high confidence) | Safety net — only activates on anomalies | Mature customer, 18+ months |

#### Cross-Tenant Learning

The flywheel isn't tenant-isolated. Anonymized geometric features and cost patterns flow into the base model:

1. **Tenant correction** → LoRA fine-tuning (tenant-specific)
2. **Anonymized features** (geometry + manufacturing method + cost bucket, no part numbers or customer names) → quarterly base model retrain
3. **Improved base model** → all new tenants start from a better baseline → faster Cold → Warming transition
4. **Network effect**: 1,000 tenants × 500 corrections/mo = 500K training samples/mo feeding the base model. This is the defensible moat — impossible for a newcomer to replicate without the installed base

---

### 15.8 Architectural Interface Specifications

The formal data contracts between the two pillars and the ensemble layer. These dataclasses are the source of truth — all API responses serialize from these types.

#### Core Result Types

```python
from dataclasses import dataclass, field
from typing import Literal
from datetime import datetime


@dataclass
class GeometryParams:
    """D1 output: Extracted geometry parameters from STEP file."""
    volume_mm3: float
    volume_raw_mm3: float
    cutting_volume_mm3: float
    surface_area_mm2: float
    bounding_box_length_mm: float
    bounding_box_width_mm: float
    bounding_box_height_mm: float
    bounding_box_volume_mm3: float
    bore_count_radial: int
    bore_count_angular: int
    thread_count: int
    thread_diameter_mm: float | None
    bore_collection: list[dict]           # [{type, count, diameter, depth}, ...]
    wall_thickness_min_mm: float | None
    wall_thickness_max_mm: float | None
    turning_profile: bool
    turning_diameter_min_mm: float | None
    turning_diameter_max_mm: float | None
    sheet_metal_thickness_mm: float | None
    bend_count: int
    machined_area_percentage: float
    component_count: int                   # 1 for single part, >1 for assembly
    extraction_time_ms: int


@dataclass
class DrawingData:
    """D2/A3 output: Extracted drawing intelligence."""
    tier: Literal["tier1", "tier2"]        # Which extraction method was used
    material_designation: str | None
    material_canonical: str | None         # After D6 fuzzy matching
    tolerance_class: str | None            # e.g., "ISO 2768-mK"
    surface_roughness_ra: list[float]      # Ra values in μm
    secondary_processes: list[str]         # ["heat_treatment", "zinc_plating", ...]
    gdt_callouts: list[dict] | None       # Tier 2 only: full GD&T
    title_block: dict | None              # Tier 2 only: {part_no, revision, ...}
    extraction_confidence: float           # 0.0-1.0
    extraction_time_ms: int


@dataclass
class Classification:
    """D3 output: Manufacturing classification."""
    manufacturing_method: str              # "milling", "turning", "molding", "sheet_metal", "assembly"
    manufacturing_confidence: float
    eclass_code: str | None               # e.g., "23-17-01-01"
    eclass_description: str | None
    unspsc_code: str | None               # e.g., "31161500"
    unspsc_description: str | None


@dataclass
class DFMWarning:
    """Single DFM rule check result."""
    rule_id: str                           # e.g., "wall_thickness_min"
    severity: Literal["warning", "critical"]
    message: str                           # Human-readable description
    feature: str | None                    # Which geometric feature triggered it
    actual_value: float
    threshold_value: float
    unit: str                              # "mm", "ratio", etc.


@dataclass
class CostBreakdown:
    """D4 output: Formula-based cost calculation."""
    material_cost: float
    setup_cost: float
    machining_cost: float
    machining_detail: dict                 # {roughing, finishing, holes, threads}
    finishing_cost: float
    secondary_process_cost: float
    overhead_cost: float
    total_unit_cost: float
    currency: str                          # "EUR", "USD", etc.
    quantity: int
    tolerance_multiplier: float
    formula_version: str                   # Track which formula set was used


@dataclass
class QuantityBreaks:
    """D7 output: Cost at multiple quantities."""
    breaks: list[dict]                     # [{qty: 1, unit_cost: 119.83}, {qty: 10, ...}, ...]
    setup_cost: float
    variable_cost_per_unit: float


@dataclass
class DDEResult:
    """Complete Pillar 1 (Deterministic) output."""
    geometry: GeometryParams               # D1
    drawing: DrawingData | None            # D2 (None if no PDF provided)
    classification: Classification         # D3
    cost: CostBreakdown                    # D4
    dfm_warnings: list[DFMWarning]         # D5
    material_match: dict | None            # D6: {input, canonical, properties}
    quantity_breaks: QuantityBreaks        # D7
    pipeline_time_ms: int
    timestamp: datetime


@dataclass
class AIConfidence:
    """Confidence metadata for an AI prediction."""
    score: float                           # 0.0-1.0, calibrated
    lower_bound: float                     # 95% CI lower
    upper_bound: float                     # 95% CI upper
    calibration_date: datetime
    model_version: str
    lora_version: str | None               # None if base model only


@dataclass
class AICostPrediction:
    """A2 output: AI-predicted cost."""
    predicted_cost: float
    confidence: AIConfidence
    cost_breakdown_estimate: dict | None   # AI's estimate of breakdown (less reliable than D4)
    currency: str


@dataclass
class SimilarPart:
    """Single result from A4 similar part search."""
    part_id: str
    similarity_score: float                # 0.0-1.0
    part_name: str | None
    manufacturing_method: str | None
    last_cost: float | None                # Historical cost if available
    tenant_id: str | None                  # None for cross-tenant (anonymized)


@dataclass
class ProcessStep:
    """Single step in A5 process route."""
    operation: str                         # "saw", "lathe_rough", "mill_pockets", ...
    machine_type: str                      # "CNC_lathe", "3axis_mill", ...
    estimated_time_min: float | None
    sequence_order: int


@dataclass
class CostDriver:
    """Single cost driver from A7 attribution."""
    feature: str                           # "bore_3", "surface_tolerance_B", ...
    cost_contribution_pct: float           # 0.0-1.0
    absolute_cost: float
    explanation: str                        # Human-readable


@dataclass
class MaterialSuggestion:
    """Single suggestion from A9."""
    material_code: str
    material_name: str
    estimated_cost_change_pct: float       # Negative = cheaper
    trade_off: str                         # Human-readable explanation
    confidence: float


@dataclass
class AFSResult:
    """Complete Pillar 2 (AI) output."""
    embedding: list[float]                 # A1: 512-dim vector (for storage/search)
    cost_prediction: AICostPrediction      # A2
    drawing_tier2: DrawingData | None      # A3 (None if Tier 1 was sufficient)
    similar_parts: list[SimilarPart]       # A4
    process_route: list[ProcessStep]       # A5
    dfm_feedback: list[str]               # A6: AI-generated DFM suggestions
    cost_drivers: list[CostDriver]         # A7
    material_suggestions: list[MaterialSuggestion]  # A9
    pipeline_time_ms: int
    timestamp: datetime


@dataclass
class EnsembleDecision:
    """Stage 3 output: How the ensemble resolved DDE vs AFS."""
    estimate_source: Literal[
        "ai",                  # High confidence, low divergence
        "ai_divergent",        # High confidence, high divergence (warning)
        "blended",             # Medium confidence, low divergence
        "formula_ai_context",  # Medium confidence, high divergence
        "formula_only",        # Low confidence or no AI
        "deterministic",       # Caller used deterministic endpoint
    ]
    primary_cost: float
    divergence_pct: float | None           # |ai - formula| / formula
    divergence_band: Literal["normal", "attention", "alarm"] | None
    blend_weight_ai: float | None          # Only for "blended" source


@dataclass
class EnrichedPart:
    """
    The top-level response object combining both pillars.

    This is the complete output of the CADPrice enrichment pipeline.
    API responses for /v1/enrich/ai serialize from this type.
    API responses for /v1/enrich/deterministic serialize DDEResult only.
    """
    part_id: str                           # System-assigned unique ID
    dde: DDEResult                         # Pillar 1: always present
    afs: AFSResult | None                  # Pillar 2: None for deterministic-only calls
    ensemble: EnsembleDecision             # Stage 3: resolution of the two pillars
    total_pipeline_time_ms: int
    api_version: str                       # "2026-02-01"
    timestamp: datetime
```

#### Serialization Contract

API responses serialize these dataclasses to JSON with the following conventions:
- All field names use `snake_case` (matching Python dataclass field names)
- `datetime` serialized as ISO 8601 (`"2026-02-20T14:30:00Z"`)
- `None` fields omitted from response (not serialized as `null`)
- Embedding vectors (`list[float]`) included only if `?include_embedding=true` (large payload)
- `DFMWarning` list ordered by severity (critical first, then warning)
- `SimilarPart` list ordered by `similarity_score` descending
- `CostDriver` list ordered by `cost_contribution_pct` descending
- `ProcessStep` list ordered by `sequence_order` ascending

#### Versioning

- API version in URL path: `/v1/enrich/...`
- Response includes `api_version` field (date-based: `"2026-02-01"`)
- Breaking changes increment URL version (`/v2/...`)
- Non-breaking additions (new optional fields) don't increment version
- Clients should ignore unknown fields (forward compatibility)

---

## 16. AI Tech Stack & Training Strategy (Consolidated Reference)

> **Purpose:** A CTO, ML engineer, or investor should be able to read this single section and understand the complete AI/ML stack — what models are used, how they get trained, what data feeds them, and how per-tenant accuracy improves over time. This section consolidates information detailed across Sections 11, 13, 14, 15, and Appendices E/G into one authoritative reference with cross-references back to the source sections.

---

### 16.1 AI Tech Stack — Complete Reference

Every model, framework, and library in the CADPrice AI stack:

| Component | Technology | Role | Runs On | Phase |
|-----------|-----------|------|---------|-------|
| **Geometric Encoder (primary)** | Point-MAE (self-supervised masked autoencoder) | Produce 512-dim shape embeddings from point clouds (2048–4096 pts sampled from STEP via trimesh/Open3D) | GPU | Phase 4 |
| **Geometric Encoder (B-Rep)** | BRepFormer (2025 SOTA Transformer) | 512-dim embeddings from B-Rep face/edge/vertex graphs (PythonOCC extraction) | GPU | Phase 4 |
| **Cost Prediction Head** | PyTorch MLP (2–3 layers) + per-tenant LoRA adapters | Cost estimate + 95% CI from embedding + 47 geometry features + material + drawing metadata | GPU | Phase 5 |
| **Process Route Model** | GNN (graph attention, MaProNet architecture) | Operation sequence + machine selection from machining feature graph | GPU | Phase 5 |
| **Material Classifier** | Classification head on A1 embeddings | Ranked material suggestions with cost/performance trade-offs | GPU | Phase 5 |
| **DFM Pattern Recognizer** | Learned from oracle DFM labels (9M aPriori outputs) | Risk patterns beyond rule-based D5 checks | GPU | Phase 5 |
| **Cost Explainer** | SHAP / Grad-CAM on A2 model | Per-feature cost contribution % | CPU | Phase 5 |
| **Part Family Clustering** | HDBSCAN (unsupervised) | Natural part groupings, outlier detection | CPU | Phase 5 |
| **Similar Part Search** | k-NN on pgvectorscale (HNSW index) | Top-K geometrically similar parts | CPU (vector DB) | Phase 4 |
| **Drawing Intelligence T1** | PyMuPDF + regex/rule-based parsing | Material, tolerances, title block from vector PDFs | CPU | Phase 3 |
| **Drawing Intelligence T2** | VLM (GPT-4o / Claude) | GD&T, BOM, notes from scanned/complex PDFs | External API | Phase 3 |
| **Drawing Segmentation** | eDOCr2 + Qwen2-VL / YOLOv11 + Donut | Region detection + annotation extraction (97.3% F1) | GPU | Phase 3 |
| **Feature Recognition** | BRepFormer fine-tuned on CADSynth (24 types) + MFCAD++ | Per-face machining feature labels (holes, slots, pockets, etc.) | GPU | Phase 4 |
| **ML Serving** | Triton Inference Server | Multi-framework serving (PyTorch + ONNX), dynamic batching, A/B testing, on-demand LoRA loading | GPU cluster | Phase 5 |
| **Vector Store** | pgvectorscale (PostgreSQL extension, HNSW) | Embedding storage + k-NN queries for A4 | CPU | Phase 4 |
| **Training Framework** | PyTorch (distributed) | All model training | GPU | Phase 4–5 |
| **Pipeline Orchestration** | Airflow / Prefect | Oracle labeling pipeline, nightly LoRA retrains, batch embedding | CPU | Phase 4 |
| **STEP Processing** | PythonOCC-core (OpenCascade) | B-Rep traversal, geometry extraction (D1), format validation | CPU | Phase 2 |
| **Point Cloud Generation** | trimesh + Open3D | STEP → 2048/4096-point clouds for Point-MAE input | CPU | Phase 4 |
| **Monitoring** | OpenTelemetry + Prometheus + Grafana | Model accuracy tracking, drift detection, latency | CPU | Phase 5 |

---

### 16.2 Model Architecture

Three-layer architecture with tenant isolation:

```
┌─────────────────────────────────────────────────────────────────┐
│                     Shared Foundation Layer                      │
│                                                                 │
│  Point-MAE encoder ─────┐                                       │
│  BRepFormer encoder ────┤──→ 512-dim embedding (frozen weights) │
│  Feature classifier ────┘                                       │
│                                                                 │
│  Trained once on 2M+ open CAD models. Shared across all tenants.│
│  Updated quarterly with new open data. ~500MB model weights.    │
├─────────────────────────────────────────────────────────────────┤
│                     Oracle-Trained Base Models                   │
│                                                                 │
│  Cost MLP (base) ──── trained on 9M aPriori labels             │
│  Route GNN (base) ─── trained on MFCAD++ 60K + CADSynth 100K  │
│  DFM patterns (base) ─ learned from 9M oracle DFM warnings     │
│  Material classifier ─ trained on oracle labels + alias table   │
│                                                                 │
│  Provides +/-5–15% accuracy from day one. ~200MB total.         │
├─────────────────────────────────────────────────────────────────┤
│                     Per-Tenant LoRA Adapters                     │
│                                                                 │
│  Tenant A adapter ──── fine-tuned on 500 aerospace parts (10MB) │
│  Tenant B adapter ──── fine-tuned on 2000 automotive parts(10MB)│
│  Tenant C ──────────── no adapter yet (uses base model)         │
│                                                                 │
│  Loaded on-demand via Triton. 2–5% parameter overhead per tenant│
│  Retrained nightly when correction queue reaches 50 samples.    │
└─────────────────────────────────────────────────────────────────┘
```

**Key design decisions:**

- **Why LoRA not full fine-tuning?** 10MB per tenant vs. 500MB. Enables 10,000+ tenants on shared GPU infrastructure. Fast retraining (minutes, not hours).
- **Why two encoders?** Point-MAE captures global shape (fast, robust). BRepFormer captures manufacturing-relevant topology (faces, edges, feature adjacency). Ensemble or concat both for best accuracy.
- **Why freeze the encoder?** Pre-trained on 2M+ models with self-supervised objectives — already produces excellent embeddings. Freezing prevents catastrophic forgetting when fine-tuning cost heads on small tenant datasets.

---

### 16.3 Training Data Strategy — Four Sources

Four distinct data sources, each serving a different purpose in the training pipeline:

#### Source 1: Open CAD Datasets (Geometry Only — No Cost Labels)

| Dataset | Size | What It Provides | Use |
|---------|------|-----------------|-----|
| ABC Dataset (Onshape/NYU) | 1M STEP | Parametric curves/surfaces, ground truth normals | Pre-train Point-MAE encoder |
| CADSynth (Beihang) | 100K STEP, 6.2GB | Per-face machining feature labels (24 types) | Pre-train BRepFormer + feature classifier |
| 1M Synthetic CAD (Beihang) | 1M STEP, 113.7GB | Parametric feature sequences | Pre-train BRepFormer |
| MFCAD++ (Queen's Belfast) | 59.7K STEP | Per-face machining feature labels | Fine-tune feature classifier |
| MFInstSeg | 60K+ | Instance-level feature labels | Feature recognition validation |

Critical gap: **none contain cost labels.** They teach the encoder to understand geometry — not what geometry costs. See [Appendix E](#appendix-e-open-cad-dataset-reference) for full dataset specifications.

#### Source 2: Oracle Engines (9M Cost-Labeled Pairs)

150K curated STEP files × 60 manufacturing configurations = 9,000,000 labeled pairs.

Configurations: 5 materials × 4 quantities × 3 regional cost profiles.

Each label is a rich JSON: `geometry_features` + `cost_breakdown` (material, setup, machining, finishing, overhead) + `process_data` (cycle time, route, machine) + `dfm_warnings` + `sustainability` (CO2e, utilization).

Quality: cross-engine consensus (aPriori vs. simus). 80% high-confidence (agree within 10%), 15% moderate (10–25%), 5% excluded (>25% divergence). See [Section 13.2](#132-the-training-data-generation-strategy) for label schema detail and [Appendix G](#appendix-g-apriori--classmate-cloud-technical-reference) for API reference.

#### Source 3: Deterministic Formula Engine (Synthetic Bootstrap)

The D4 formula engine generates unlimited training pairs from day one:

`(geometry_features + material + machine_config) → formula_cost_breakdown`

These teach the AI to approximate physics-based cost models. Later superseded by oracle and production data — but critical for cold-start. See [Section 15.1 (D4)](#151-capability-matrix) for formula engine specification.

#### Source 4: Production Data (Customer Corrections + ERP Actuals)

- **User corrections:** AI predicts €42.50 → user says "actually €38" → training pair
- **ERP actuals:** production completion events → actual costs, cycle times, supplier prices
- **Xometry market prices:** 5–10K representative parts submitted for instant quotes → market benchmark

This is the only source that captures **tenant-specific** cost structures (their machines, labor rates, overhead allocation, supplier relationships). See [Section 15.7](#157-data-flywheel) for the progression model.

---

### 16.4 The Oracle Labeling Pipeline

Full pipeline from raw STEP files to quality-tiered training data:

```
┌─────────────────────────────────────────────────────────────────────┐
│                     Oracle Labeling Pipeline                         │
│                     (One-time, ~3 weeks with 20 workers)            │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  1. Source: Open STEP datasets (ABC + CADSynth + MFCAD++ + Fusion) │
│     → Filter to ~150K manufacturable, watertight STEP files         │
│                                                                     │
│  2. Validate: OpenCascade geometry check                            │
│     → Watertight? Sane dimensions? No degenerate faces?             │
│                                                                     │
│  3. Extract: PythonOCC → bounding box, volume, surface area,       │
│     feature recognition, bore/thread counts, wall thickness         │
│                                                                     │
│  4. Label (primary): aPriori aP Generate REST API                   │
│     → 60 configs per file (5 mat × 4 qty × 3 region)              │
│     → 150K × 60 = 9,000,000 API calls                             │
│     → BCA batch mode: ~100 parts/batch, 10–20 parallel workers     │
│     → Duration: ~3 weeks with 20 workers                           │
│     → Cost: $200–500K enterprise license (~$0.02–0.06/label)       │
│                                                                     │
│  5. Validate (cross-engine): simus costing24 API                    │
│     → 10K representative parts × 6 configs = 60K labels            │
│     → Free via Partner Module for integrators                       │
│     → Consensus scoring: agree within 10% = high confidence         │
│                                                                     │
│  6. Quality tier assignment:                                        │
│     → High (80%): both engines agree <10%  → full training weight   │
│     → Moderate (15%): agree 10–25%         → reduced weight         │
│     → Low (5%): disagree >25%              → excluded               │
│                                                                     │
│  7. Output: Parquet dataset + vector embeddings in S3/MinIO         │
│     → ~18GB structured labels + ~150MB embeddings = ~50GB total     │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

**The AlphaGo analogy:** learn from expert deterministic engines first, then surpass them by incorporating real-world production data that deterministic models cannot capture (customer-specific overhead, regional labor dynamics, supplier relationships). See [Section 13.1](#131-the-manufacturing-intelligence-middleware-paradigm) for the strategic framing of this approach.

---

### 16.5 Training Pipeline — Four Stages

```
┌───────────────────────────────────────────────────────────────────────┐
│ Stage 1: Self-Supervised Pre-training (Phase 4, no labels needed)     │
│                                                                       │
│ Point-MAE: masked autoencoder on 2M+ point clouds                    │
│   → learns to reconstruct masked patches → understands 3D shape      │
│   → output: 512-dim embedding per part                               │
│                                                                       │
│ BRepFormer: transformer on B-Rep graphs from CADSynth + 1M Synth    │
│   → learns face/edge topology → understands manufacturing features   │
│   → output: 512-dim embedding per part                               │
│                                                                       │
│ Feature classifier: fine-tune on CADSynth (24 types) + MFCAD++      │
│   → per-face labels: through_hole, blind_hole, slot, pocket, etc.   │
├───────────────────────────────────────────────────────────────────────┤
│ Stage 2: Oracle-Supervised Training (Phase 4–5, 9M labels)           │
│                                                                       │
│ Freeze encoder → attach cost MLP head                                │
│   Input: 512-dim embedding + 47 geometry features + material props   │
│   Labels: 9M aPriori cost breakdowns (material/setup/machining/etc.) │
│   → learns: geometry shape → manufacturing cost relationship         │
│   → achieves: +/-5–15% accuracy from day one                        │
│                                                                       │
│ Simultaneously train:                                                │
│   → Process route GNN on MFCAD++ + CADSynth feature labels          │
│   → DFM pattern model on 9M aPriori DFM warnings                    │
│   → Material classifier on oracle material ↔ geometry associations   │
├───────────────────────────────────────────────────────────────────────┤
│ Stage 3: Multi-Signal Fusion (Phase 5)                               │
│                                                                       │
│ Combine three cost signals into training:                            │
│   → Formula costs: teach manufacturing physics                       │
│   → Oracle labels: teach industrial-grade should-costing             │
│   → Xometry prices: teach market reality (5–10K benchmark parts)    │
│                                                                       │
│ Each signal gets a source weight in the loss function:               │
│   → Oracle (high confidence): weight 1.0                             │
│   → Oracle (moderate): weight 0.5                                    │
│   → Formula: weight 0.3 (physics regularizer)                       │
│   → Xometry: weight 0.7 (market reality)                            │
├───────────────────────────────────────────────────────────────────────┤
│ Stage 4: Per-Tenant LoRA Fine-Tuning + Active Learning (Production)  │
│                                                                       │
│ Tenant uploads parts with actual costs → LoRA adapter fine-tuned:    │
│   → 200–500 labeled parts = useful predictions                       │
│   → 500+ parts = outperforms formula for common types                │
│   → 2000+ parts = high confidence across most types                  │
│                                                                       │
│ Active learning loop:                                                │
│   AI predicts → user corrects → correction queued → nightly retrain  │
│   "The model learns YOUR cost structure, not generic rates"          │
│                                                                       │
│ ERP feedback loop:                                                   │
│   Production completion → actual cost → LoRA retrain trigger         │
│   Purchase orders → supplier pricing → market benchmark update       │
└───────────────────────────────────────────────────────────────────────┘
```

See [Section 11.4](#114-the-foundation-model-pattern) for the pre-train → fine-tune rationale and [Section 14 (Phases 4–5)](#14-cadprice--implementation-plan) for step-by-step implementation tasks.

---

### 16.6 Context Data Enhancement — How Non-Geometric Data Feeds Training

The AI model does NOT learn from geometry alone. Five context data channels enhance every training sample:

#### Channel 1: Drawing Intelligence → Material + Tolerances + Surface Finish

| Extracted | Source | Effect on Training |
|-----------|--------|-------------------|
| Material designation ("AL 6061-T6") | D2 (PyMuPDF) or A3 (VLM) | Fuzzy-matched via D6 → density, machinability, cost/kg become explicit input features |
| Tolerances (±0.05mm, H7/g6) | D2/A3 from GD&T frames | Tolerance multiplier feature: ≤0.01mm = 1.8×, ≤0.05mm = 1.3×, ≤0.10mm = 1.1× |
| Surface finish (Ra values) | D2/A3 | Selects finishing operations; cost adder feature |
| GD&T (flatness, position, runout) | A3 (VLM for complex callouts) | Inspection cost adder (5–15%) as training feature |
| Heat treatment / coatings | D2/A3 | Secondary process cost (10–40% of total) as training feature |
| BOM table | D2/A3 | Auto-populate BomItems, assembly cost context |

#### Channel 2: Material Properties → Physics-Informed Features

D6 material fuzzy matching resolves extracted text to canonical material code → material properties (density, tensile strength, machinability index, cost/kg) become explicit input features to A2. The model learns that titanium parts cost more not just because "titanium" appears in the label but because density=4.43, machinability=0.3, cost/kg=$35.

#### Channel 3: Formula Engine → Physics Regularization

D4 formula outputs (material cost, setup cost, machining cost) serve as additional input features AND as a regularization signal during training. The AI learns "my prediction should be in the neighborhood of the formula" — preventing wild hallucinations on out-of-distribution parts.

#### Channel 4: ERP Production Actuals → Ground Truth

The bidirectional PLM → CADPrice → ERP pipeline captures:

- `Cost Roll-Up Complete` → actual cost for LoRA retraining
- `Production Order Completion` → actual cycle times for process model validation
- `Purchase Order for Outsourced Part` → supplier pricing for market benchmarking

See [Appendix H](#appendix-h-plmerp-integration-reference) for integration event specifications.

#### Channel 5: Similar Part History → Contextual Anchoring

A4 similar part search provides context: "5 most similar parts in your catalog had costs ranging €35–48." This range becomes a training signal and a runtime sanity check — if the AI predicts €150 for a part similar to €40 parts, confidence drops automatically. See [Section 15.5](#155-ensembleconfidence-decision-matrix) for the confidence decision matrix.

---

### 16.7 The Complete Training Sample

Every training sample fed to the cost model combines geometric, contextual, and label data:

```python
@dataclass
class TrainingSample:
    # From A1: Geometric encoder (shared, frozen)
    point_cloud_embedding: list[float]   # 512 dims from Point-MAE
    brep_embedding: list[float]          # 512 dims from BRepFormer

    # From D1: Deterministic geometry extraction (47+ features)
    geometry: GeometryFeatures           # volume, surface_area, bores, threads,
                                         # wall_thickness, turning_profile, bend_count...

    # From D2/A3: Drawing intelligence
    drawing: DrawingMetadata | None      # material_designation, tolerance_class,
                                         # surface_roughness_ra, secondary_processes

    # From D6: Material properties (after fuzzy matching)
    material: MaterialProperties         # density, cost_per_kg, machinability_index,
                                         # tensile_strength

    # From D4: Formula engine output (physics regularizer)
    formula_cost: float                  # deterministic formula estimate
    formula_breakdown: CostBreakdown     # material/setup/machining/finishing/overhead

    # Labels (one or more of these):
    oracle_cost: float | None            # from aPriori/simus (9M labels)
    oracle_breakdown: CostBreakdown | None
    oracle_dfm_warnings: list[DFMWarning] | None
    oracle_process_route: list[str] | None
    xometry_price: float | None          # from Xometry API (market benchmark)
    customer_actual: float | None        # from user correction or ERP actual

    # Metadata
    label_source: str                    # "oracle" | "formula" | "xometry" | "customer"
    label_confidence: float              # from cross-engine consensus or source quality
    configuration: CostingConfig         # material, quantity, region, shop_rate
```

This structure maps directly to the [Section 15.2](#152-interface-contracts) data feed contracts between the Deterministic and AI pillars.

---

### 16.8 The Data Flywheel — Per-Tenant Accuracy Progression

| Stage | Parts Processed | Primary Estimate | AI Role | Accuracy |
|-------|----------------|-----------------|---------|----------|
| **Cold** | 0–100 | Formula (D4) | Base model provides context only | Formula: +/-20–30% |
| **Warming** | 100–500 | Weighted blend | `blend = conf × ai + (1-conf) × formula` | Blend: +/-15–20% |
| **Warm** | 500–2000 | AI (A2) with formula sanity check | LoRA outperforms formula for common types | AI: +/-8–12% |
| **Hot** | 2000+ | AI (A2) primary | High confidence, active learning corrections rare | AI: +/-5–8% |

**What triggers transitions:** not just part count, but the model's confidence calibration score on held-out oracle labels (10% of 9M). When the LoRA adapter's mean absolute error on the validation set drops below the formula engine's MAE, the ensemble shifts from formula-primary to AI-primary.

See [Section 15.7](#157-data-flywheel) for the business progression model and [Section 15.5](#155-ensembleconfidence-decision-matrix) for the ensemble decision matrix that governs these transitions at runtime.

---

### 16.9 Cross-Reference Index

This section consolidates material from across the document. The table below maps each topic to its detailed treatment:

| Topic | Detailed Treatment | Section |
|-------|-------------------|---------|
| Training data problem & three label sources | First principles discussion | [11.3](#113-the-training-data-problem) |
| Foundation model pattern (pre-train → fine-tune) | Architecture rationale | [11.4](#114-the-foundation-model-pattern) |
| Beyond-cost AI features (similarity, routing, DFM) | Feature-by-feature analysis | [11.5](#115-beyond-cost-ai-features) |
| Academic references & model benchmarks | Papers, datasets, accuracy numbers | [11.9](#119-academic-references) |
| Oracle concept (AlphaGo analogy) | Strategic framing | [13.1](#131-the-manufacturing-intelligence-middleware-paradigm) |
| 9M training pairs generation | Pipeline detail + label schema | [13.2](#132-the-training-data-generation-strategy) |
| aPriori partnership model | Business relationship | [13.3](#133-apriori-partnership-model) |
| Open CAD dataset inventory | Dataset-by-dataset specs | [Appendix E](#appendix-e-open-cad-dataset-reference) |
| aPriori & simus API reference | REST endpoints, auth, output formats | [Appendix G](#appendix-g-apriori--classmate-cloud-technical-reference) |
| Pre-training pipeline tasks | Step-by-step implementation | [14 Phase 4](#phase-4-ai-pre-training-pipeline-months-16-21) |
| AI cost model training tasks | Step-by-step implementation | [14 Phase 5](#phase-5-ai-cost-model-training-months-19-24) |
| D1–D7 / A1–A9 capability tables | Definitive capability reference | [15.1](#151-capability-matrix) |
| Three data feeds between pillars | Interface contract | [15.2](#152-interface-contracts) |
| Ensemble/confidence decision matrix | Runtime behavior | [15.5](#155-ensembleconfidence-decision-matrix) |
| Data flywheel stages | Business progression model | [15.7](#157-data-flywheel) |
| PLM/ERP integration events | Event specifications | [Appendix H](#appendix-h-plmerp-integration-reference) |
