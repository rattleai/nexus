"""Domain events for the product configurator lifecycle."""

from dataclasses import dataclass

from app.core.events import DomainEvent


@dataclass
class ConfigurationStarted(DomainEvent):
    session_id: str = ""
    product_id: str = ""
    tenant_id: str = ""
    user_id: str = ""


@dataclass
class ConfigurationSelectionMade(DomainEvent):
    session_id: str = ""
    characteristic_slug: str = ""
    value: str = ""
    tenant_id: str = ""


@dataclass
class ConfigurationSelectionRemoved(DomainEvent):
    session_id: str = ""
    characteristic_slug: str = ""
    tenant_id: str = ""


@dataclass
class ConfigurationCompleted(DomainEvent):
    session_id: str = ""
    product_id: str = ""
    tenant_id: str = ""


@dataclass
class ConfigurationLocked(DomainEvent):
    session_id: str = ""
    product_id: str = ""
    tenant_id: str = ""


@dataclass
class BOMResolved(DomainEvent):
    session_id: str = ""
    configured_bom_id: str = ""
    total_components: int = 0
    total_cost: str = ""
    tenant_id: str = ""


@dataclass
class PricingResolved(DomainEvent):
    session_id: str = ""
    final_price: str = ""
    margin_percentage: str = ""
    is_profitable: bool = False
    tenant_id: str = ""


@dataclass
class ProductVersionPublished(DomainEvent):
    product_id: str = ""
    version_id: str = ""
    version_number: int = 0
    tenant_id: str = ""
