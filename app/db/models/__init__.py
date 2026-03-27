"""Domain-driven model package — re-exports all models for backward compatibility.

All existing imports like ``from app.db.models import Tenant`` continue to work.
Alembic discovers models through this package via ``env.py``.
"""

from app.db.models.ai import (
    AIProvider,
    AIUsageLog,
    DollarWallet,
    PromptTemplate,
    TenantAIProviderKey,
    WalletTransaction,
    WalletTransactionType,
)
from app.db.models.auth import (
    EmailVerificationToken,
    OAuthAccount,
    RefreshToken,
)
from app.db.models.billing import (
    CreditPack,
    Plan,
    PlanTier,
    Subscription,
    SubscriptionStatus,
    UsageRecord,
)
from app.db.models.collaboration import (
    Invitation,
    InvitationStatus,
    Notification,
    WebhookDelivery,
    WebhookEndpoint,
)
from app.db.models.core import (
    ApiKey,
    Tenant,
    TenantMembership,
    User,
    UserRole,
)
from app.db.models.enterprise import (
    SSOConfiguration,
    SSOProvider,
)
from app.db.models.features import (
    FeatureFlag,
    TenantFeatureOverride,
)
from app.db.models.mobile import (
    ChangeLog,
    PushSubscription,
    SyncMixin,
    WebAuthnCredential,
)
from app.db.models.oauth_client import (
    OAuthClient,
)
# CPQ app models — backward-compat re-exports from new location
from app.apps.cpq.models.product import (  # noqa: F401
    CharacteristicAssignment,
    CharacteristicGroup,
    CharacteristicType,
    CharacteristicValue,
    Characteristic,
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
from app.apps.cpq.models.bom import (  # noqa: F401
    BOMHeader,
    BOMItem,
    BOMItemType,
)
from app.apps.cpq.models.datasource import (  # noqa: F401
    CloudConnection,
    CloudProvider,
    ConfigItemProvenance,
    DataSource,
    DataSourceChunk,
    DataSourceStatus,
    DataSourceType,
)
from app.apps.cpq.models.configurator import (  # noqa: F401
    ConfigurationPricing,
    ConfigurationSelection,
    ConfigurationSession,
    ConfigurationStatus,
    ConfigurationTemplate,
    ConfiguredBOM,
    PricingRule,
    PricingRuleType,
)
from app.db.models.operations import (
    AuditLog,
    Consent,
    ConsentType,
    DSARStatus,
    DSARType,
    DataRetentionPolicy,
    DataSubjectRequest,
    Job,
    JobStatus,
)

# ── Plugin model discovery ─────────────────────────────────
# Import all plugin models so they register on Base.metadata.
# This ensures Alembic sees them and backward-compat re-exports work.
from app.plugins.registry import registry as _plugin_registry

for _plugin in _plugin_registry:
    _plugin.get_models()  # Side effect: imports and registers models on Base.metadata

__all__ = [
    # Core
    "Tenant",
    "ApiKey",
    "User",
    "TenantMembership",
    "UserRole",
    # Auth
    "OAuthAccount",
    "RefreshToken",
    "EmailVerificationToken",
    # Operations
    "Job",
    "JobStatus",
    "AuditLog",
    # GDPR
    "Consent",
    "ConsentType",
    "DataSubjectRequest",
    "DSARType",
    "DSARStatus",
    "DataRetentionPolicy",
    # Features
    "FeatureFlag",
    "TenantFeatureOverride",
    # Collaboration
    "Invitation",
    "InvitationStatus",
    "Notification",
    "WebhookEndpoint",
    "WebhookDelivery",
    # Billing
    "Plan",
    "PlanTier",
    "Subscription",
    "SubscriptionStatus",
    "UsageRecord",
    "CreditPack",
    # Enterprise
    "SSOConfiguration",
    "SSOProvider",
    # AI
    "AIProvider",
    "TenantAIProviderKey",
    "DollarWallet",
    "WalletTransaction",
    "WalletTransactionType",
    "AIUsageLog",
    "PromptTemplate",
    # OAuth
    "OAuthClient",
    # Mobile
    "PushSubscription",
    "WebAuthnCredential",
    "ChangeLog",
    "SyncMixin",
    # Product Configurator
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
    # Data Sources
    "DataSource",
    "DataSourceType",
    "DataSourceStatus",
    "DataSourceChunk",
    "CloudConnection",
    "CloudProvider",
    "ConfigItemProvenance",
    # Configurator
    "ConfigurationSession",
    "ConfigurationStatus",
    "ConfigurationSelection",
    "ConfigurationTemplate",
    "ConfiguredBOM",
    "PricingRule",
    "PricingRuleType",
    "ConfigurationPricing",
]
