"""Agent tool definitions for the CPQ application.

These definitions are contributed to the agent tool registry via the
plugin's ``get_agent_tool_definitions()`` method. They describe the
input schema for each configuration domain tool so agents know what
arguments to pass.
"""

from __future__ import annotations

from typing import Any

CPQ_TOOL_DEFINITIONS: dict[str, dict[str, Any]] = {
    "config_create_product": {
        "description": "Create a new configurable product with name, slug, and optional description.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Product display name"},
                "slug": {"type": "string", "description": "URL-safe identifier (lowercase, underscores)"},
                "description": {"type": "string"},
                "sku_prefix": {"type": "string"},
                "family_id": {"type": "string", "description": "Optional product family UUID"},
            },
            "required": ["name", "slug"],
        },
    },
    "config_list_products": {
        "description": "List products for the tenant. Optionally filter by status.",
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["draft", "active", "deprecated", "archived"]},
                "limit": {"type": "integer", "default": 50},
            },
        },
    },
    "config_get_product": {
        "description": "Get a product with its characteristics, constraints, and BOMs.",
        "input_schema": {
            "type": "object",
            "properties": {"product_id": {"type": "string", "description": "Product UUID"}},
            "required": ["product_id"],
        },
    },
    "config_create_characteristic": {
        "description": (
            "Create a configurable characteristic (option). Types: enum, numeric, boolean, text. "
            "For enum type, pass values as array of objects. For numeric, set min/max/step/unit."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "slug": {"type": "string", "description": "Lowercase with underscores"},
                "char_type": {"type": "string", "enum": ["enum", "numeric", "boolean", "text"]},
                "group_id": {"type": "string", "description": "Optional CharacteristicGroup UUID"},
                "values": {"type": "array", "description": "For enum type: [{value, label, ...}]", "items": {"type": "object"}},
                "numeric_min": {"type": "number"},
                "numeric_max": {"type": "number"},
                "numeric_step": {"type": "number"},
                "unit": {"type": "string"},
                "is_required": {"type": "boolean", "default": False},
                "is_multi_select": {"type": "boolean", "default": False},
                "default_value": {"type": "string"},
                "description": {"type": "string"},
            },
            "required": ["name", "slug", "char_type"],
        },
    },
    "config_create_characteristic_values": {
        "description": "Batch-create values for an existing enum characteristic.",
        "input_schema": {
            "type": "object",
            "properties": {
                "characteristic_id": {"type": "string"},
                "values": {"type": "array", "items": {"type": "object", "properties": {"value": {"type": "string"}, "label": {"type": "string"}}, "required": ["value", "label"]}},
            },
            "required": ["characteristic_id", "values"],
        },
    },
    "config_assign_characteristic": {
        "description": "Assign a characteristic to a product with optional overrides.",
        "input_schema": {
            "type": "object",
            "properties": {
                "product_id": {"type": "string"},
                "characteristic_id": {"type": "string"},
                "display_order": {"type": "integer", "default": 0},
                "is_required": {"type": "boolean"},
                "default_value": {"type": "string"},
            },
            "required": ["product_id", "characteristic_id"],
        },
    },
    "config_list_characteristics": {
        "description": "List characteristics, optionally filtered by product assignment.",
        "input_schema": {
            "type": "object",
            "properties": {"product_id": {"type": "string", "description": "Filter by product UUID"}},
        },
    },
    "config_create_constraint_group": {
        "description": "Create a constraint group to organize related rules.",
        "input_schema": {
            "type": "object",
            "properties": {"product_id": {"type": "string"}, "name": {"type": "string"}, "description": {"type": "string"}},
            "required": ["product_id", "name"],
        },
    },
    "config_create_constraint_rule": {
        "description": "Create a constraint rule with JSONB AST expression.",
        "input_schema": {
            "type": "object",
            "properties": {
                "product_id": {"type": "string"},
                "name": {"type": "string"},
                "constraint_type": {"type": "string", "enum": ["requires", "excludes", "selection_condition", "default_value", "formula", "table"]},
                "expression": {"type": "object", "description": "JSONB AST expression"},
                "group_id": {"type": "string"},
                "description": {"type": "string"},
                "priority": {"type": "integer", "default": 10},
            },
            "required": ["product_id", "name", "constraint_type", "expression"],
        },
    },
    "config_validate_constraints": {
        "description": "Validate constraints for a product: detect cycles, dead values, coverage gaps.",
        "input_schema": {"type": "object", "properties": {"product_id": {"type": "string"}}, "required": ["product_id"]},
    },
    "config_simulate_configuration": {
        "description": "Simulate constraint propagation with a set of selections.",
        "input_schema": {
            "type": "object",
            "properties": {"product_id": {"type": "string"}, "selections": {"type": "object"}},
            "required": ["product_id", "selections"],
        },
    },
    "config_analyze_constraint_impact": {
        "description": "Analyze the impact of a constraint rule expression on the configuration model.",
        "input_schema": {
            "type": "object",
            "properties": {"product_id": {"type": "string"}, "rule_expression": {"type": "object"}},
            "required": ["product_id", "rule_expression"],
        },
    },
    "config_create_bom_header": {
        "description": "Create a 150% super BOM header for a product.",
        "input_schema": {
            "type": "object",
            "properties": {"product_id": {"type": "string"}, "name": {"type": "string"}, "description": {"type": "string"}, "bom_type": {"type": "string", "default": "manufacturing"}, "is_primary": {"type": "boolean", "default": True}},
            "required": ["product_id", "name"],
        },
    },
    "config_create_bom_item": {
        "description": "Add a BOM item with optional selection_condition AST.",
        "input_schema": {
            "type": "object",
            "properties": {
                "bom_header_id": {"type": "string"}, "part_number": {"type": "string"}, "part_name": {"type": "string"},
                "quantity": {"type": "number", "default": 1.0}, "selection_condition": {"type": "object"},
                "item_type": {"type": "string", "enum": ["component", "sub_assembly", "phantom", "reference"], "default": "component"},
                "parent_item_id": {"type": "string"}, "description": {"type": "string"},
                "unit_of_measure": {"type": "string", "default": "EA"}, "unit_cost": {"type": "number"},
            },
            "required": ["bom_header_id", "part_number", "part_name"],
        },
    },
    "config_create_bom_items_batch": {
        "description": "Batch-create multiple BOM items at once.",
        "input_schema": {
            "type": "object",
            "properties": {"bom_header_id": {"type": "string"}, "items": {"type": "array", "items": {"type": "object"}}},
            "required": ["bom_header_id", "items"],
        },
    },
    "config_resolve_bom": {
        "description": "Resolve a configured BOM from a configuration session (150% -> 100%).",
        "input_schema": {"type": "object", "properties": {"session_id": {"type": "string"}}, "required": ["session_id"]},
    },
    "config_create_variant_table": {
        "description": "Create a variant table for tabular constraint lookups.",
        "input_schema": {
            "type": "object",
            "properties": {
                "product_id": {"type": "string"}, "name": {"type": "string"},
                "columns": {"type": "array", "items": {"type": "object"}},
                "rows": {"type": "array", "items": {"type": "object"}},
                "input_columns": {"type": "array", "items": {"type": "string"}},
                "output_columns": {"type": "array", "items": {"type": "string"}},
                "description": {"type": "string"},
            },
            "required": ["product_id", "name", "columns", "rows", "input_columns", "output_columns"],
        },
    },
    "config_import_variant_table": {
        "description": "Create a variant table from extracted table data (headers + rows).",
        "input_schema": {
            "type": "object",
            "properties": {
                "product_id": {"type": "string"}, "name": {"type": "string"},
                "table_data": {"type": "object"}, "input_columns": {"type": "array", "items": {"type": "string"}},
                "output_columns": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["product_id", "name", "table_data", "input_columns", "output_columns"],
        },
    },
    "config_create_pricing_rule": {
        "description": "Create a pricing rule. Types: base_price, option_surcharge, volume_discount, conditional, formula, tiered, margin.",
        "input_schema": {
            "type": "object",
            "properties": {
                "product_id": {"type": "string"}, "name": {"type": "string"},
                "rule_type": {"type": "string", "enum": ["base_price", "option_surcharge", "volume_discount", "conditional", "formula", "tiered", "margin"]},
                "expression": {"type": "object"}, "priority": {"type": "integer", "default": 10},
                "currency": {"type": "string", "default": "EUR"}, "description": {"type": "string"},
            },
            "required": ["product_id", "name", "rule_type", "expression"],
        },
    },
    "config_simulate_pricing": {
        "description": "Simulate pricing for a set of selections.",
        "input_schema": {
            "type": "object",
            "properties": {"product_id": {"type": "string"}, "selections": {"type": "object"}},
            "required": ["product_id", "selections"],
        },
    },
    "config_create_version_snapshot": {
        "description": "Create a version snapshot of a product's configuration model.",
        "input_schema": {
            "type": "object",
            "properties": {"product_id": {"type": "string"}, "label": {"type": "string"}},
            "required": ["product_id"],
        },
    },
    "config_extract_document": {
        "description": "Extract structured content from a data source file.",
        "input_schema": {"type": "object", "properties": {"data_source_id": {"type": "string"}}, "required": ["data_source_id"]},
    },
    "config_search_datasources": {
        "description": "Search across tenant data sources using semantic similarity.",
        "input_schema": {"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer", "default": 10}}, "required": ["query"]},
    },
    "config_update_product": {
        "description": "Update an existing product.",
        "input_schema": {
            "type": "object",
            "properties": {"product_id": {"type": "string"}, "name": {"type": "string"}, "description": {"type": "string"}, "status": {"type": "string"}, "sku_prefix": {"type": "string"}},
            "required": ["product_id"],
        },
    },
    "config_delete_product": {
        "description": "Soft-delete a product.",
        "input_schema": {"type": "object", "properties": {"product_id": {"type": "string"}}, "required": ["product_id"]},
    },
    "config_update_constraint_rule": {
        "description": "Update an existing constraint rule.",
        "input_schema": {"type": "object", "properties": {"rule_id": {"type": "string"}, "name": {"type": "string"}, "expression": {"type": "object"}, "priority": {"type": "integer"}, "is_active": {"type": "boolean"}}, "required": ["rule_id"]},
    },
    "config_delete_constraint_rule": {
        "description": "Soft-delete a constraint rule.",
        "input_schema": {"type": "object", "properties": {"rule_id": {"type": "string"}}, "required": ["rule_id"]},
    },
    "config_update_pricing_rule": {
        "description": "Update an existing pricing rule.",
        "input_schema": {"type": "object", "properties": {"rule_id": {"type": "string"}, "name": {"type": "string"}, "expression": {"type": "object"}, "priority": {"type": "integer"}, "is_active": {"type": "boolean"}}, "required": ["rule_id"]},
    },
    "config_delete_pricing_rule": {
        "description": "Soft-delete a pricing rule.",
        "input_schema": {"type": "object", "properties": {"rule_id": {"type": "string"}}, "required": ["rule_id"]},
    },
    "config_list_variant_tables": {
        "description": "List variant tables for a product.",
        "input_schema": {"type": "object", "properties": {"product_id": {"type": "string"}}, "required": ["product_id"]},
    },
    "config_create_product_family": {
        "description": "Create a product family for grouping related products.",
        "input_schema": {"type": "object", "properties": {"name": {"type": "string"}, "slug": {"type": "string"}, "description": {"type": "string"}}, "required": ["name", "slug"]},
    },
    "config_list_product_families": {
        "description": "List product families for the tenant.",
        "input_schema": {"type": "object", "properties": {"limit": {"type": "integer", "default": 50}}},
    },
    "config_create_characteristic_group": {
        "description": "Create a characteristic group for organizing characteristics.",
        "input_schema": {"type": "object", "properties": {"name": {"type": "string"}, "description": {"type": "string"}, "display_order": {"type": "integer", "default": 0}}, "required": ["name"]},
    },
    "config_list_characteristic_groups": {
        "description": "List characteristic groups.",
        "input_schema": {"type": "object", "properties": {"limit": {"type": "integer", "default": 50}}},
    },
    "config_create_session": {
        "description": "Create a configuration session for a product.",
        "input_schema": {"type": "object", "properties": {"product_id": {"type": "string"}, "product_version_id": {"type": "string"}}, "required": ["product_id"]},
    },
    "config_get_session": {
        "description": "Get a configuration session with its current selections.",
        "input_schema": {"type": "object", "properties": {"session_id": {"type": "string"}}, "required": ["session_id"]},
    },
    "config_make_selection": {
        "description": "Make a selection in a configuration session.",
        "input_schema": {"type": "object", "properties": {"session_id": {"type": "string"}, "characteristic_slug": {"type": "string"}, "value": {"type": "string"}}, "required": ["session_id", "characteristic_slug", "value"]},
    },
    "config_list_sessions": {
        "description": "List configuration sessions, optionally filtered by product.",
        "input_schema": {"type": "object", "properties": {"product_id": {"type": "string"}, "limit": {"type": "integer", "default": 20}}},
    },
}
