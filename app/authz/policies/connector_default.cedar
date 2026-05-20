// Default connector tool policy.
//
// Permits invocation when:
//   - principal is a User or Agent
//   - the connector's trust_level is verified or trusted
// Forbids invocation when:
//   - the connector's trust_level is untrusted (tool description is a
//     generic stub, so agents shouldn't be calling it without explicit
//     user approval in any case)
//
// Override this with per-tenant / per-agent policies as needed.

permit (
    principal,
    action == Action::"invoke",
    resource
)
when {
    context.trust_level == "verified"
    || context.trust_level == "trusted"
};

forbid (
    principal,
    action == Action::"invoke",
    resource
)
when {
    context.trust_level == "untrusted"
};
