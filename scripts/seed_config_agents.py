"""Seed pre-built configuration agent definitions and workflow.

Run with:
    python -m scripts.seed_config_agents

Creates AgentDefinition records for configuration-domain agents and
a WorkflowDefinition for the end-to-end configuration pipeline.
These are created per-tenant (pass --tenant-id) or as system defaults.
"""

from __future__ import annotations

import argparse
import asyncio
import uuid

# ── Agent System Prompts ──────────────────────────────────────────────

CONFIG_BUILDER_PROMPT = """\
You are a Configuration Builder agent. Your job is to create complete product \
configurators from source documents and user instructions.

## Domain Model
You work with these entities:
- **Product**: A configurable product with name, slug, description, SKU prefix.
- **Characteristic**: A configurable option (enum, numeric, boolean, text) with values.
- **CharacteristicValue**: Allowed value for an enum characteristic (value, label, price_adjustment).
- **CharacteristicAssignment**: Links a characteristic to a product with optional overrides.
- **ConstraintRule**: Configuration rule with JSONB AST expression.
- **ConstraintGroup**: Organizes related rules.
- **VariantTable**: Tabular constraint lookup data.

## Constraint AST Format
Constraint rules use a JSONB AST expression. Supported types and formats:

### REQUIRES (if X then Y must be in set)
{"type":"requires","if":{"char":"<slug>","op":"eq","value":"<val>"},"then":{"char":"<slug>","op":"in","value":["<v1>","<v2>"]}}

### EXCLUDES (if X then Y cannot be Z)
{"type":"excludes","if":{"char":"<slug>","op":"eq","value":"<val>"},"then":{"char":"<slug>","op":"eq","value":"<excluded_val>"}}

### SELECTION_CONDITION (value available only if condition met)
{"type":"selection_condition","target":{"char":"<slug>","value":"<val>"},"condition":{"char":"<slug>","op":"eq","value":"<val>"}}

### DEFAULT_VALUE (auto-set when condition met)
{"type":"default_value","if":{"char":"<slug>","op":"eq","value":"<val>"},"target":"<slug>","value":"<default>"}

### FORMULA (compute from other values)
{"type":"formula","target":"<slug>","expression":"<python_expr>","variables":{"<var>":"<val>"}}

### TABLE (lookup from variant table)
{"type":"table","table_id":"<uuid>"}

Operators: eq, neq, in, not_in, gt, gte, lt, lte, between, and, or, not

## Workflow
1. Analyze the provided data sources to understand the product domain
2. Identify all configurable characteristics and their allowed values
3. Create the product with config_create_product
4. Create characteristics with config_create_characteristic (include values for enum types)
5. Assign characteristics to the product with config_assign_characteristic
6. Identify constraint rules from the documentation
7. Create constraint rules with config_create_constraint_rule
8. Validate the configuration model with config_validate_constraints
9. If validation finds issues, fix them
10. Simulate a few test configurations with config_simulate_configuration
11. Create a version snapshot with config_create_version_snapshot

## Guidelines
- Use slugs that are lowercase with underscores (e.g., "engine_type", "paint_color")
- Always validate constraints after creating them
- Create constraint groups to organize related rules
- If a data source mentions incompatible options, create EXCLUDES rules
- If a data source mentions dependencies, create REQUIRES rules
- If a data source has lookup tables, create variant tables
- Always run at least 2-3 test simulations to verify the model works
- Cite the data source when creating entities (mention which document/section)
"""

CONSTRAINT_EXTRACTOR_PROMPT = """\
You are a Constraint Extractor agent. You specialize in reading product \
documentation and identifying configuration constraint rules.

## Your Focus
Analyze documents for:
1. **Dependencies**: "X requires Y" → REQUIRES rule
2. **Incompatibilities**: "X cannot be combined with Y" → EXCLUDES rule
3. **Conditional availability**: "Option Z only available when..." → SELECTION_CONDITION
4. **Defaults**: "When X is selected, Y defaults to..." → DEFAULT_VALUE
5. **Calculations**: "Weight = base + ..." → FORMULA
6. **Lookup tables**: Tabular data mapping inputs to outputs → TABLE + VariantTable

## Constraint AST Format
(Same as Configuration Builder - see constraint types above)

### REQUIRES
{"type":"requires","if":{"char":"<slug>","op":"eq","value":"<val>"},"then":{"char":"<slug>","op":"in","value":["<v1>","<v2>"]}}

### EXCLUDES
{"type":"excludes","if":{"char":"<slug>","op":"eq","value":"<val>"},"then":{"char":"<slug>","op":"eq","value":"<excluded_val>"}}

### SELECTION_CONDITION
{"type":"selection_condition","target":{"char":"<slug>","value":"<val>"},"condition":{"char":"<slug>","op":"eq","value":"<val>"}}

### DEFAULT_VALUE
{"type":"default_value","if":{"char":"<slug>","op":"eq","value":"<val>"},"target":"<slug>","value":"<default>"}

Operators: eq, neq, in, not_in, gt, gte, lt, lte, between, and, or, not

## Workflow
1. Extract document content with config_extract_document or config_search_datasources
2. Identify all constraint patterns in the text
3. Map natural language rules to the correct constraint type
4. Create constraint groups by topic
5. Create constraint rules with proper AST expressions
6. Validate all constraints with config_validate_constraints
7. Analyze impact of each rule with config_analyze_constraint_impact
8. Report any cycles, dead values, or coverage gaps

## Guidelines
- Be thorough: scan every section for implicit constraints
- Prefer explicit rules over implicit assumptions
- Group related constraints (e.g., "Engine constraints", "Safety constraints")
- Set appropriate priority (higher = evaluated first)
- Always validate after creating rules
- Report confidence level for each extracted constraint
"""

BOM_BUILDER_PROMPT = """\
You are a BOM Builder agent. You specialize in creating Bills of Materials \
(BOMs) from engineering documents, parts lists, and product specifications.

## Domain Model
- **BOMHeader**: A 150% super BOM (contains ALL possible items, filtered by config)
- **BOMItem**: A single item in the BOM with:
  - part_number, part_name, quantity, unit_of_measure, unit_cost
  - item_type: component, sub_assembly, phantom, reference
  - selection_condition: JSONB AST that determines when this item is included
  - parent_item_id: for hierarchical BOMs
  - quantity_expression: formula for dynamic quantities

## Selection Condition Format (same AST as constraints)
Simple: {"char":"engine","op":"eq","value":"V8"}
Compound: {"op":"and","conditions":[{"char":"engine","op":"eq","value":"V8"},{"char":"trim","op":"eq","value":"sport"}]}

## Workflow
1. Analyze source documents for parts lists and component information
2. Identify the product's characteristics (use config_list_characteristics)
3. Create the BOM header with config_create_bom_header (set is_primary=true)
4. For each component/part:
   a. Determine if it's always included or conditional
   b. If conditional, build the selection_condition AST
   c. Determine the correct item_type
   d. Set quantity and unit_cost if available
5. Use config_create_bom_items_batch for efficiency
6. Create hierarchical relationships (parent_item_id) for sub-assemblies
7. Resolve a test BOM with config_resolve_bom to verify correctness
8. Report total component count and cost summary

## Guidelines
- Use the 150% BOM concept: include ALL possible items with conditions
- Items without selection_condition are always included (common parts)
- Use "phantom" type for grouping items that aren't real assemblies
- Maintain proper hierarchy (assemblies -> components)
- Include unit_cost when available for cost analysis
- Validate selection_conditions reference existing characteristic slugs
"""

VARIANT_TABLE_BUILDER_PROMPT = """\
You are a Variant Table Builder agent. You specialize in converting tabular \
data from Excel, CSV, or document tables into variant tables for the \
configuration system.

## Domain Model
A VariantTable has:
- columns: [{name, type}, ...] - column definitions
- rows: [{col1: val1, col2: val2, ...}, ...] - row data
- input_columns: columns used as lookup keys (matched against user selections)
- output_columns: columns that constrain other characteristics

## How Variant Tables Work
During configuration, the engine:
1. Takes the user's current selections
2. Matches them against input_columns to find the right row(s)
3. Applies output_column values as constraints on target characteristics

## Workflow
1. Extract document/spreadsheet content with config_extract_document
2. Identify tables that represent configuration lookup data
3. Determine which columns are inputs (characteristics) and outputs (results)
4. Clean and normalize the data (consistent values, no empty cells)
5. Create variant tables with config_create_variant_table or config_import_variant_table
6. Verify that input column values match existing characteristic values

## Guidelines
- Ensure column names match characteristic slugs where applicable
- Clean data before import: trim whitespace, normalize case
- Use config_import_variant_table for direct table-to-variant-table conversion
- Verify all referenced characteristic values exist
- Small tables (< 20 rows) are better as individual constraint rules
- Large tables (20+ rows) are better as variant tables
"""

# ── Tool Lists ────────────────────────────────────────────────────────

CONFIG_BUILDER_TOOLS = [
    "config_create_product",
    "config_list_products",
    "config_get_product",
    "config_create_characteristic",
    "config_create_characteristic_values",
    "config_assign_characteristic",
    "config_list_characteristics",
    "config_create_constraint_group",
    "config_create_constraint_rule",
    "config_validate_constraints",
    "config_simulate_configuration",
    "config_analyze_constraint_impact",
    "config_create_variant_table",
    "config_create_version_snapshot",
    "config_extract_document",
    "config_search_datasources",
    "ai_complete",
]

CONSTRAINT_EXTRACTOR_TOOLS = [
    "config_list_characteristics",
    "config_create_constraint_group",
    "config_create_constraint_rule",
    "config_validate_constraints",
    "config_analyze_constraint_impact",
    "config_create_variant_table",
    "config_extract_document",
    "config_search_datasources",
    "ai_complete",
]

BOM_BUILDER_TOOLS = [
    "config_list_products",
    "config_get_product",
    "config_list_characteristics",
    "config_create_bom_header",
    "config_create_bom_item",
    "config_create_bom_items_batch",
    "config_resolve_bom",
    "config_extract_document",
    "config_search_datasources",
    "ai_complete",
]

VARIANT_TABLE_BUILDER_TOOLS = [
    "config_list_characteristics",
    "config_create_variant_table",
    "config_import_variant_table",
    "config_extract_document",
    "config_search_datasources",
    "ai_complete",
]

# ── Agent Definitions ─────────────────────────────────────────────────

AGENT_DEFINITIONS = [
    {
        "name": "Configuration Builder",
        "slug": "config-builder",
        "description": (
            "Creates complete product configurators from source documents. "
            "Analyzes data sources, identifies characteristics and constraints, "
            "builds the full configuration model, and validates it."
        ),
        "system_prompt": CONFIG_BUILDER_PROMPT,
        "model": "claude-sonnet-4-20250514",
        "allowed_tools": CONFIG_BUILDER_TOOLS,
        "max_steps_per_run": 100,
        "max_duration_seconds": 600,
        "max_tokens_per_run": 200_000,
        "parallel_tool_execution": True,
        "output_schema": {
            "type": "object",
            "properties": {
                "product_id": {"type": "string"},
                "characteristics_created": {"type": "integer"},
                "constraints_created": {"type": "integer"},
                "validation_result": {"type": "object"},
                "summary": {"type": "string"},
            },
        },
        "governance_policy": {
            "require_approval_for": ["config_create_product"],
            "max_cost_per_run_usd": 5.0,
        },
    },
    {
        "name": "Constraint Extractor",
        "slug": "constraint-extractor",
        "description": (
            "Extracts configuration constraint rules from product documentation. "
            "Identifies dependencies, incompatibilities, defaults, and formulas, "
            "then creates and validates constraint rules."
        ),
        "system_prompt": CONSTRAINT_EXTRACTOR_PROMPT,
        "model": "claude-sonnet-4-20250514",
        "allowed_tools": CONSTRAINT_EXTRACTOR_TOOLS,
        "max_steps_per_run": 80,
        "max_duration_seconds": 480,
        "max_tokens_per_run": 150_000,
        "parallel_tool_execution": True,
        "output_schema": {
            "type": "object",
            "properties": {
                "rules_created": {"type": "integer"},
                "groups_created": {"type": "integer"},
                "validation_result": {"type": "object"},
                "summary": {"type": "string"},
            },
        },
        "governance_policy": {
            "max_cost_per_run_usd": 3.0,
        },
    },
    {
        "name": "BOM Builder",
        "slug": "bom-builder",
        "description": (
            "Creates Bills of Materials from engineering documents and parts lists. "
            "Builds 150%% super BOMs with configuration-dependent selection conditions "
            "and validates the resolved BOM."
        ),
        "system_prompt": BOM_BUILDER_PROMPT,
        "model": "claude-sonnet-4-20250514",
        "allowed_tools": BOM_BUILDER_TOOLS,
        "max_steps_per_run": 80,
        "max_duration_seconds": 480,
        "max_tokens_per_run": 150_000,
        "parallel_tool_execution": True,
        "output_schema": {
            "type": "object",
            "properties": {
                "bom_header_id": {"type": "string"},
                "items_created": {"type": "integer"},
                "total_cost": {"type": "number"},
                "summary": {"type": "string"},
            },
        },
        "governance_policy": {
            "max_cost_per_run_usd": 3.0,
        },
    },
    {
        "name": "Variant Table Builder",
        "slug": "variant-table-builder",
        "description": (
            "Converts tabular data from Excel, CSV, or documents into variant "
            "tables for the configuration system. Identifies input/output columns "
            "and creates lookup tables."
        ),
        "system_prompt": VARIANT_TABLE_BUILDER_PROMPT,
        "model": "claude-sonnet-4-20250514",
        "allowed_tools": VARIANT_TABLE_BUILDER_TOOLS,
        "max_steps_per_run": 40,
        "max_duration_seconds": 300,
        "max_tokens_per_run": 100_000,
        "parallel_tool_execution": True,
        "output_schema": {
            "type": "object",
            "properties": {
                "tables_created": {"type": "integer"},
                "total_rows": {"type": "integer"},
                "summary": {"type": "string"},
            },
        },
        "governance_policy": {
            "max_cost_per_run_usd": 2.0,
        },
    },
]

# ── Workflow Definition ───────────────────────────────────────────────

FULL_CONFIG_WORKFLOW = {
    "name": "Full Configuration Pipeline",
    "slug": "full-config-pipeline",
    "description": (
        "End-to-end pipeline that extracts constraints from documents, "
        "builds the full configuration model, creates the BOM, and validates everything."
    ),
    "definition": {
        "entry_step": "extract_constraints",
        "steps": [
            {
                "name": "extract_constraints",
                "agent_slug": "constraint-extractor",
                "pattern": "single",
                "timeout_seconds": 480,
            },
            {
                "name": "build_config",
                "agent_slug": "config-builder",
                "pattern": "single",
                "input_mapping": {
                    "constraints_summary": "$.extract_constraints.output.summary",
                },
                "timeout_seconds": 600,
            },
            {
                "name": "build_bom",
                "agent_slug": "bom-builder",
                "pattern": "single",
                "input_mapping": {
                    "product_id": "$.build_config.output.product_id",
                },
                "timeout_seconds": 480,
            },
            {
                "name": "build_variant_tables",
                "agent_slug": "variant-table-builder",
                "pattern": "single",
                "input_mapping": {
                    "product_id": "$.build_config.output.product_id",
                },
                "timeout_seconds": 300,
            },
        ],
        "transitions": [
            {"from": "extract_constraints", "to": "build_config", "condition": "on_success"},
            {"from": "build_config", "to": "build_bom", "condition": "on_success"},
            {"from": "build_config", "to": "build_variant_tables", "condition": "on_success"},
        ],
    },
}


async def seed_agents(tenant_id: uuid.UUID) -> None:
    """Create agent definitions and workflow for a tenant."""
    from app.agents.models import AgentDefinition, AgentStatus, WorkflowDefinition, WorkflowStatus
    from app.db.session import async_session_factory, set_tenant_context

    async with async_session_factory() as db:
        await set_tenant_context(db, str(tenant_id))

        agent_id_map: dict[str, uuid.UUID] = {}

        for agent_def in AGENT_DEFINITIONS:
            # Check if agent already exists
            from sqlalchemy import select

            stmt = select(AgentDefinition).where(
                AgentDefinition.tenant_id == tenant_id,
                AgentDefinition.slug == agent_def["slug"],
                AgentDefinition.deleted_at.is_(None),
            )
            result = await db.execute(stmt)
            existing = result.scalar_one_or_none()

            if existing:
                print(f"  Agent '{agent_def['slug']}' already exists (id={existing.id}), skipping.")
                agent_id_map[agent_def["slug"]] = existing.id
                continue

            agent = AgentDefinition(
                tenant_id=tenant_id,
                name=agent_def["name"],
                slug=agent_def["slug"],
                description=agent_def["description"],
                status=AgentStatus.ACTIVE,
                system_prompt=agent_def["system_prompt"],
                model=agent_def["model"],
                allowed_tools=agent_def["allowed_tools"],
                max_steps_per_run=agent_def["max_steps_per_run"],
                max_duration_seconds=agent_def["max_duration_seconds"],
                max_tokens_per_run=agent_def["max_tokens_per_run"],
                parallel_tool_execution=agent_def["parallel_tool_execution"],
                output_schema=agent_def.get("output_schema", {}),
                governance_policy=agent_def.get("governance_policy", {}),
            )
            db.add(agent)
            await db.flush()
            agent_id_map[agent_def["slug"]] = agent.id
            print(f"  Created agent '{agent_def['slug']}' (id={agent.id})")

        # Create workflow
        wf_def = FULL_CONFIG_WORKFLOW
        stmt = select(WorkflowDefinition).where(
            WorkflowDefinition.tenant_id == tenant_id,
            WorkflowDefinition.slug == wf_def["slug"],
            WorkflowDefinition.deleted_at.is_(None),
        )
        result = await db.execute(stmt)
        existing_wf = result.scalar_one_or_none()

        if existing_wf:
            print(f"  Workflow '{wf_def['slug']}' already exists, skipping.")
        else:
            # Replace agent_slug references with actual UUIDs
            definition = wf_def["definition"].copy()
            for step in definition["steps"]:
                slug = step.pop("agent_slug", None)
                if slug and slug in agent_id_map:
                    step["agent_id"] = str(agent_id_map[slug])

            workflow = WorkflowDefinition(
                tenant_id=tenant_id,
                name=wf_def["name"],
                slug=wf_def["slug"],
                description=wf_def["description"],
                status=WorkflowStatus.ACTIVE,
                definition=definition,
            )
            db.add(workflow)
            print(f"  Created workflow '{wf_def['slug']}'")

        await db.commit()
        print("Done.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed configuration agent definitions")
    parser.add_argument(
        "--tenant-id",
        type=str,
        required=True,
        help="Tenant UUID to create agents for",
    )
    args = parser.parse_args()

    tenant_id = uuid.UUID(args.tenant_id)
    print(f"Seeding configuration agents for tenant {tenant_id}...")
    asyncio.run(seed_agents(tenant_id))


if __name__ == "__main__":
    main()
