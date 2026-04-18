"""CPQ application models.

Re-exports all model classes and provides an ``ALL_MODELS`` list
for plugin registration with the infrastructure model discovery.

Infrastructure models (DataSource, CloudConnection, etc.) live in
``app.db.models`` — only CPQ-specific models are here.
"""

from app.apps.cpq.models.bom import (
    BOMHeader,
    BOMItem,
    BOMItemType,
)
from app.apps.cpq.models.configurator import (
    ConfigurationPricing,
    ConfigurationSelection,
    ConfigurationSession,
    ConfigurationStatus,
    ConfigurationTemplate,
    ConfiguredBOM,
    PricingRule,
    PricingRuleType,
)
from app.apps.cpq.models.datasource import (
    ConfigItemProvenance,
)
from app.apps.cpq.models.product import (
    Characteristic,
    CharacteristicAssignment,
    CharacteristicGroup,
    CharacteristicType,
    CharacteristicValue,
    ConstraintGroup,
    ConstraintRule,
    ConstraintType,
    Product,
    ProductFamily,
    ProductMedia,
    ProductStatus,
    ProductVersion,
    VariantTable,
)

ALL_MODELS: list[type] = [
    # Product
    ProductFamily,
    Product,
    ProductVersion,
    CharacteristicGroup,
    Characteristic,
    CharacteristicValue,
    CharacteristicAssignment,
    ConstraintGroup,
    ConstraintRule,
    VariantTable,
    ProductMedia,
    # BOM
    BOMHeader,
    BOMItem,
    # Configurator
    ConfigurationSession,
    ConfigurationSelection,
    ConfigurationTemplate,
    ConfiguredBOM,
    PricingRule,
    ConfigurationPricing,
    # Data Sources (CPQ-specific only)
    ConfigItemProvenance,
]

__all__ = [
    "ALL_MODELS",
    # BOM
    "BOMHeader",
    "BOMItem",
    "BOMItemType",
    "Characteristic",
    "CharacteristicAssignment",
    "CharacteristicGroup",
    "CharacteristicType",
    "CharacteristicValue",
    # Data Sources (CPQ-specific)
    "ConfigItemProvenance",
    "ConfigurationPricing",
    "ConfigurationSelection",
    # Configurator
    "ConfigurationSession",
    "ConfigurationStatus",
    "ConfigurationTemplate",
    "ConfiguredBOM",
    "ConstraintGroup",
    "ConstraintRule",
    "ConstraintType",
    "PricingRule",
    "PricingRuleType",
    "Product",
    # Product
    "ProductFamily",
    "ProductMedia",
    "ProductStatus",
    "ProductVersion",
    "VariantTable",
]
