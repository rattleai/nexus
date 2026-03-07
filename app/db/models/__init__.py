"""Domain-driven model package — re-exports all models for backward compatibility.

All existing imports like ``from app.db.models import Tenant`` continue to work.
Alembic discovers models through this package via ``env.py``.
"""

from app.db.models.ai import (
    AIProvider,
    AIUsageLog,
    PromptTemplate,
    TenantAIProviderKey,
    TokenWallet,
    WalletTransaction,
    WalletTransactionType,
)
from app.db.models.auth import (
    EmailVerificationToken,
    OAuthAccount,
    RefreshToken,
)
from app.db.models.billing import (
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
from app.db.models.operations import (
    AuditLog,
    Job,
    JobStatus,
)

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
    # Enterprise
    "SSOConfiguration",
    "SSOProvider",
    # AI
    "AIProvider",
    "TenantAIProviderKey",
    "TokenWallet",
    "WalletTransaction",
    "WalletTransactionType",
    "AIUsageLog",
    "PromptTemplate",
    # Mobile
    "PushSubscription",
    "WebAuthnCredential",
    "ChangeLog",
    "SyncMixin",
]
