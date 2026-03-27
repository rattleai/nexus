"""CPQ application models.

Re-exports all model classes and provides an ``ALL_MODELS`` list
for plugin registration with the infrastructure model discovery.
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
    CloudConnection,
    CloudProvider,
    ConfigItemProvenance,
    DataSource,
    DataSourceChunk,
    DataSourceStatus,
    DataSourceType,
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
    # Data Sources
    DataSource,
    DataSourceChunk,
    CloudConnection,
    ConfigItemProvenance,
]

__all__ = [
    "ALL_MODELS",
    # Product
    "ProductFamily",
    "Product",
    "ProductVersion",
    "ProductStatus",
    "CharacteristicGroup",
    "Characteristic",
    "CharacteristicType",
    "CharacteristicValue",
    "CharacteristicAssignment",
    "ConstraintGroup",
    "ConstraintRule",
    "ConstraintType",
    "VariantTable",
    "ProductMedia",
    # BOM
    "BOMHeader",
    "BOMItem",
    "BOMItemType",
    # Configurator
    "ConfigurationSession",
    "ConfigurationStatus",
    "ConfigurationSelection",
    "ConfigurationTemplate",
    "ConfiguredBOM",
    "PricingRule",
    "PricingRuleType",
    "ConfigurationPricing",
    # Data Sources
    "DataSource",
    "DataSourceType",
    "DataSourceStatus",
    "DataSourceChunk",
    "CloudConnection",
    "CloudProvider",
    "ConfigItemProvenance",
]
