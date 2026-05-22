"""Infrastructure model package.

Re-exports all infrastructure models. Application-specific models live
in their plugin packages under ``app.apps.<name>.models`` — see
``app.apps.example.models`` for the reference layout.

Alembic discovers plugin models via ``env.py`` through the plugin registry.
"""

from app.agents.models import (
    AgentDefinition,
    AgentDefinitionMemoryEntry,
    AgentInstance,
    AgentMemoryEntry,
    AgentPolicy,
    AgentSession,
    AgentStatus,
    CapabilityPreset,
    InstanceStatus,
    SessionStatus,
    TenantTool,
    ToolSource,
    WorkflowDefinition,
    WorkflowRun,
    WorkflowRunStatus,
    WorkflowStatus,
)
from app.connectors.models import (
    AuthType,
    BrokerType,
    ConnectionStatus,
    ConnectorAppCredential,
    ConnectorAuditLog,
    ConnectorDefinition,
    ConnectorOAuthState,
    ConnectorSource,
    ConnectorTask,
    ConnectorTaskStatus,
    ConnectorType,
    CredentialType,
    TenantConnection,
    TenantCredential,
    TrustLevel,
)
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
from app.db.models.datasource import (
    DataSource,
    DataSourceChunk,
    DataSourceStatus,
    DataSourceType,
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
    DataRetentionPolicy,
    DataSubjectRequest,
    DSARStatus,
    DSARType,
    Job,
    JobStatus,
)
from app.db.models.rag_config import (
    TenantRAGConfig,
)
from app.db.models.rag_graph import (
    RAGEntity,
    RAGRelationship,
)
from app.evaluation.models import (
    RAGEvaluationDataset,
    RAGEvaluationQuery,
    RAGEvaluationResult,
    RAGEvaluationRun,
    RAGQueryLog,
)

__all__ = [
    # AI
    "AIProvider",
    "AIUsageLog",
    # Agent runtime (app.agents.models — registered here so alembic
    # autogenerate can see them on Base.metadata)
    "AgentDefinition",
    "AgentDefinitionMemoryEntry",
    "AgentInstance",
    "AgentMemoryEntry",
    "AgentPolicy",
    "AgentSession",
    "AgentStatus",
    "ApiKey",
    "AuditLog",
    "AuthType",
    "BrokerType",
    "CapabilityPreset",
    "ChangeLog",
    "ConnectionStatus",
    "ConnectorAppCredential",
    "ConnectorAuditLog",
    # Connectors
    "ConnectorDefinition",
    "ConnectorOAuthState",
    "ConnectorSource",
    "ConnectorTask",
    "ConnectorTaskStatus",
    "ConnectorType",
    # GDPR
    "Consent",
    "ConsentType",
    "CredentialType",
    "CreditPack",
    "DSARStatus",
    "DSARType",
    "DataRetentionPolicy",
    # Data Sources (infrastructure — application-agnostic)
    "DataSource",
    "DataSourceChunk",
    "DataSourceStatus",
    "DataSourceType",
    "DataSubjectRequest",
    "DollarWallet",
    "EmailVerificationToken",
    # Features
    "FeatureFlag",
    "InstanceStatus",
    # Collaboration
    "Invitation",
    "InvitationStatus",
    # Operations
    "Job",
    "JobStatus",
    "Notification",
    # Auth
    "OAuthAccount",
    # OAuth
    "OAuthClient",
    # Billing
    "Plan",
    "PlanTier",
    "PromptTemplate",
    # Mobile
    "PushSubscription",
    # RAG Graph
    "RAGEntity",
    # RAG Evaluation
    "RAGEvaluationDataset",
    "RAGEvaluationQuery",
    "RAGEvaluationResult",
    "RAGEvaluationRun",
    "RAGQueryLog",
    "RAGRelationship",
    "RefreshToken",
    # Enterprise
    "SSOConfiguration",
    "SSOProvider",
    "Subscription",
    "SubscriptionStatus",
    "SessionStatus",
    "SyncMixin",
    # Core
    "Tenant",
    "TenantAIProviderKey",
    "TenantConnection",
    "TenantCredential",
    "TenantFeatureOverride",
    "TenantMembership",
    # RAG Configuration
    "TenantRAGConfig",
    "TenantTool",
    "ToolSource",
    "TrustLevel",
    "UsageRecord",
    "User",
    "UserRole",
    "WalletTransaction",
    "WalletTransactionType",
    "WebAuthnCredential",
    "WebhookDelivery",
    "WebhookEndpoint",
    "WorkflowDefinition",
    "WorkflowRun",
    "WorkflowRunStatus",
    "WorkflowStatus",
]
