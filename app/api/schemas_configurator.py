"""Pydantic request/response schemas for the product configurator domain."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field


# ── Product Family ───────────────────────────────────────


class ProductFamilyCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    slug: str = Field(..., min_length=2, max_length=100, pattern=r"^[a-z0-9][a-z0-9_-]*[a-z0-9]$")
    description: str | None = None
    metadata: dict[str, Any] | None = None


class ProductFamilyUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    metadata: dict[str, Any] | None = None


class ProductFamilyResponse(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    description: str | None
    metadata: dict | None = Field(None, alias="metadata_")
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True, "populate_by_name": True}


# ── Product ──────────────────────────────────────────────


class ProductCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    slug: str = Field(..., min_length=2, max_length=100, pattern=r"^[a-z0-9][a-z0-9_-]*[a-z0-9]$")
    family_id: uuid.UUID | None = None
    description: str | None = None
    sku_prefix: str | None = Field(default=None, max_length=50)
    status: str = "draft"
    metadata: dict[str, Any] | None = None


class ProductUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    family_id: uuid.UUID | None = None
    description: str | None = None
    sku_prefix: str | None = Field(default=None, max_length=50)
    status: str | None = None
    metadata: dict[str, Any] | None = None


class ProductResponse(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    family_id: uuid.UUID | None
    description: str | None
    sku_prefix: str | None
    status: str
    metadata: dict | None = Field(None, alias="metadata_")
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True, "populate_by_name": True}


class ProductVersionCreate(BaseModel):
    label: str | None = Field(default=None, max_length=100)


class ProductVersionResponse(BaseModel):
    id: uuid.UUID
    product_id: uuid.UUID
    version_number: int
    label: str | None
    is_active: bool
    published_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Characteristic Group ─────────────────────────────────


class CharacteristicGroupCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    slug: str = Field(..., min_length=2, max_length=100, pattern=r"^[a-z0-9][a-z0-9_-]*[a-z0-9]$")
    description: str | None = None
    display_order: int = 0


class CharacteristicGroupUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    display_order: int | None = None


class CharacteristicGroupResponse(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    description: str | None
    display_order: int
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Characteristic ───────────────────────────────────────


class CharacteristicCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    slug: str = Field(..., min_length=2, max_length=100, pattern=r"^[a-z0-9][a-z0-9_-]*[a-z0-9]$")
    group_id: uuid.UUID | None = None
    description: str | None = None
    char_type: str = Field(..., pattern=r"^(enum|numeric|boolean|text)$")
    numeric_min: float | None = None
    numeric_max: float | None = None
    numeric_step: float | None = None
    unit: str | None = Field(default=None, max_length=50)
    is_required: bool = False
    is_multi_select: bool = False
    default_value: str | None = Field(default=None, max_length=500)
    display_order: int = 0


class CharacteristicUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    group_id: uuid.UUID | None = None
    description: str | None = None
    numeric_min: float | None = None
    numeric_max: float | None = None
    numeric_step: float | None = None
    unit: str | None = Field(default=None, max_length=50)
    is_required: bool | None = None
    is_multi_select: bool | None = None
    default_value: str | None = Field(default=None, max_length=500)
    display_order: int | None = None


class CharacteristicValueCreate(BaseModel):
    value: str = Field(..., min_length=1, max_length=500)
    label: str = Field(..., min_length=1, max_length=500)
    description: str | None = None
    display_order: int = 0
    is_default: bool = False
    price_adjustment: Decimal | None = None
    image_url: str | None = Field(default=None, max_length=2048)


class CharacteristicValueUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = None
    display_order: int | None = None
    is_default: bool | None = None
    price_adjustment: Decimal | None = None
    image_url: str | None = Field(default=None, max_length=2048)


class CharacteristicValueResponse(BaseModel):
    id: uuid.UUID
    characteristic_id: uuid.UUID
    value: str
    label: str
    description: str | None
    display_order: int
    is_default: bool
    price_adjustment: Decimal | None
    image_url: str | None

    model_config = {"from_attributes": True}


class CharacteristicResponse(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    group_id: uuid.UUID | None
    description: str | None
    char_type: str
    numeric_min: float | None
    numeric_max: float | None
    numeric_step: float | None
    unit: str | None
    is_required: bool
    is_multi_select: bool
    default_value: str | None
    display_order: int
    values: list[CharacteristicValueResponse] = []
    created_at: datetime

    model_config = {"from_attributes": True}


class CharacteristicAssignmentCreate(BaseModel):
    product_id: uuid.UUID
    characteristic_id: uuid.UUID
    display_order: int = 0
    is_required: bool | None = None
    default_value: str | None = None


class CharacteristicAssignmentResponse(BaseModel):
    id: uuid.UUID
    product_id: uuid.UUID
    characteristic_id: uuid.UUID
    display_order: int
    is_required: bool | None
    default_value: str | None

    model_config = {"from_attributes": True}


# ── Constraint ───────────────────────────────────────────


class ConstraintGroupCreate(BaseModel):
    product_id: uuid.UUID
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    is_active: bool = True


class ConstraintGroupUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    is_active: bool | None = None


class ConstraintGroupResponse(BaseModel):
    id: uuid.UUID
    product_id: uuid.UUID
    name: str
    description: str | None
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class ConstraintRuleCreate(BaseModel):
    product_id: uuid.UUID
    group_id: uuid.UUID | None = None
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    constraint_type: str = Field(..., pattern=r"^(requires|excludes|selection_condition|default_value|formula|table)$")
    expression: dict[str, Any]
    priority: int = 0
    is_active: bool = True
    effective_from: datetime | None = None
    effective_to: datetime | None = None


class ConstraintRuleUpdate(BaseModel):
    group_id: uuid.UUID | None = None
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    expression: dict[str, Any] | None = None
    priority: int | None = None
    is_active: bool | None = None
    effective_from: datetime | None = None
    effective_to: datetime | None = None


class ConstraintRuleResponse(BaseModel):
    id: uuid.UUID
    product_id: uuid.UUID
    group_id: uuid.UUID | None
    name: str
    description: str | None
    constraint_type: str
    expression: dict
    priority: int
    is_active: bool
    effective_from: datetime | None
    effective_to: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ConstraintValidateRequest(BaseModel):
    expression: dict[str, Any]
    constraint_type: str


class ConstraintValidateResponse(BaseModel):
    is_valid: bool
    errors: list[str] = []


# ── Variant Table ────────────────────────────────────────


class VariantTableCreate(BaseModel):
    product_id: uuid.UUID
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    columns: list[dict[str, Any]]
    rows: list[dict[str, Any]]
    input_columns: list[str]
    output_columns: list[str]


class VariantTableUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    columns: list[dict[str, Any]] | None = None
    rows: list[dict[str, Any]] | None = None
    input_columns: list[str] | None = None
    output_columns: list[str] | None = None


class VariantTableResponse(BaseModel):
    id: uuid.UUID
    product_id: uuid.UUID
    name: str
    description: str | None
    columns: list[dict]
    rows: list[dict]
    input_columns: list[str]
    output_columns: list[str]
    created_at: datetime

    model_config = {"from_attributes": True}


# ── BOM ──────────────────────────────────────────────────


class BOMHeaderCreate(BaseModel):
    product_id: uuid.UUID
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    bom_type: str = "manufacturing"
    is_primary: bool = False
    effective_from: datetime | None = None
    effective_to: datetime | None = None


class BOMHeaderUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    bom_type: str | None = None
    is_primary: bool | None = None
    effective_from: datetime | None = None
    effective_to: datetime | None = None


class BOMHeaderResponse(BaseModel):
    id: uuid.UUID
    product_id: uuid.UUID
    name: str
    description: str | None
    bom_type: str
    is_primary: bool
    effective_from: datetime | None
    effective_to: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class BOMItemCreate(BaseModel):
    parent_item_id: uuid.UUID | None = None
    item_type: str = "component"
    part_number: str = Field(..., min_length=1, max_length=100)
    part_name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    quantity: Decimal = Decimal("1.0000")
    quantity_expression: dict[str, Any] | None = None
    unit_of_measure: str = "EA"
    sub_product_id: uuid.UUID | None = None
    selection_condition: dict[str, Any] | None = None
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    sort_order: int = 0
    is_optional: bool = False
    unit_cost: Decimal | None = None
    lead_time_days: int | None = None


class BOMItemUpdate(BaseModel):
    parent_item_id: uuid.UUID | None = None
    item_type: str | None = None
    part_number: str | None = Field(default=None, min_length=1, max_length=100)
    part_name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    quantity: Decimal | None = None
    quantity_expression: dict[str, Any] | None = None
    unit_of_measure: str | None = None
    sub_product_id: uuid.UUID | None = None
    selection_condition: dict[str, Any] | None = None
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    sort_order: int | None = None
    is_optional: bool | None = None
    unit_cost: Decimal | None = None
    lead_time_days: int | None = None


class BOMItemResponse(BaseModel):
    id: uuid.UUID
    bom_header_id: uuid.UUID
    parent_item_id: uuid.UUID | None
    item_type: str
    part_number: str
    part_name: str
    description: str | None
    quantity: Decimal
    quantity_expression: dict | None
    unit_of_measure: str
    sub_product_id: uuid.UUID | None
    selection_condition: dict | None
    sort_order: int
    is_optional: bool
    unit_cost: Decimal | None
    lead_time_days: int | None
    children: list["BOMItemResponse"] = []

    model_config = {"from_attributes": True}


class BOMItemReorderRequest(BaseModel):
    item_ids: list[uuid.UUID]


class WhereUsedResponse(BaseModel):
    bom_header_id: uuid.UUID
    bom_name: str
    product_id: uuid.UUID
    product_name: str
    item_id: uuid.UUID
    part_number: str
    quantity: Decimal

    model_config = {"from_attributes": True}


# ── BOM Header with Items ────────────────────────────────


class BOMHeaderDetailResponse(BOMHeaderResponse):
    items: list[BOMItemResponse] = []


# ── Configuration Session ────────────────────────────────


class ConfigurationSessionCreate(BaseModel):
    product_id: uuid.UUID
    product_version_id: uuid.UUID | None = None
    name: str | None = None
    template_id: uuid.UUID | None = None
    external_reference: str | None = None


class ConfigurationSelectionRequest(BaseModel):
    characteristic_id: uuid.UUID
    value: str = Field(..., min_length=1, max_length=500)


class ConfigurationSelectionResponse(BaseModel):
    id: uuid.UUID
    characteristic_id: uuid.UUID
    value: str
    is_auto_set: bool
    set_by_rule_id: uuid.UUID | None

    model_config = {"from_attributes": True}


class ValidationErrorDetail(BaseModel):
    characteristic_slug: str | None = None
    rule_id: str | None = None
    rule_name: str | None = None
    error_type: str
    message: str


class ConfigurationSessionResponse(BaseModel):
    id: uuid.UUID
    product_id: uuid.UUID
    product_version_id: uuid.UUID | None
    user_id: uuid.UUID | None
    name: str | None
    status: str
    is_valid: bool
    is_complete: bool
    validation_errors: list[dict] | None
    available_domains: dict | None
    template_id: uuid.UUID | None
    external_reference: str | None
    selections: list[ConfigurationSelectionResponse] = []
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SelectionResultResponse(BaseModel):
    session: ConfigurationSessionResponse
    auto_set_values: dict[str, str] = {}
    excluded_values: dict[str, list[str]] = {}


# ── Configuration Template ───────────────────────────────


class ConfigurationTemplateCreate(BaseModel):
    product_id: uuid.UUID
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    is_partial: bool = True
    is_public: bool = False
    selections: list[dict[str, str]] = []


class ConfigurationTemplateResponse(BaseModel):
    id: uuid.UUID
    product_id: uuid.UUID
    name: str
    description: str | None
    is_partial: bool
    is_public: bool
    selections: list[dict]
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Configured BOM ───────────────────────────────────────


class ConfiguredBOMResponse(BaseModel):
    id: uuid.UUID
    session_id: uuid.UUID
    bom_header_id: uuid.UUID
    resolved_items: list[dict]
    total_components: int
    total_cost: Decimal | None
    selection_snapshot: dict
    resolved_at: datetime
    resolution_duration_ms: int | None

    model_config = {"from_attributes": True}


# ── Pricing ──────────────────────────────────────────────


class PricingRuleCreate(BaseModel):
    product_id: uuid.UUID
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    rule_type: str = Field(..., pattern=r"^(base_price|option_surcharge|volume_discount|conditional|formula|tiered|margin)$")
    expression: dict[str, Any]
    priority: int = 0
    is_active: bool = True
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    currency: str = "EUR"


class PricingRuleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    expression: dict[str, Any] | None = None
    priority: int | None = None
    is_active: bool | None = None
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    currency: str | None = None


class PricingRuleResponse(BaseModel):
    id: uuid.UUID
    product_id: uuid.UUID
    name: str
    description: str | None
    rule_type: str
    expression: dict
    priority: int
    is_active: bool
    effective_from: datetime | None
    effective_to: datetime | None
    currency: str
    created_at: datetime

    model_config = {"from_attributes": True}


class PricingSimulateRequest(BaseModel):
    product_id: uuid.UUID
    selections: dict[str, str]


class ConfigurationPricingResponse(BaseModel):
    id: uuid.UUID
    session_id: uuid.UUID
    currency: str
    base_price: Decimal
    total_adjustments: Decimal
    final_price: Decimal
    total_cost: Decimal
    margin_amount: Decimal
    margin_percentage: Decimal
    price_breakdown: list[dict]
    is_profitable: bool
    resolved_at: datetime

    model_config = {"from_attributes": True}
