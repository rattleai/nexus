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
]
