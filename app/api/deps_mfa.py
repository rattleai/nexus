"""MFA enforcement dependency for sensitive endpoints.

Usage:
    @router.post("/sensitive", dependencies=[Depends(RequireMFA())])
    async def sensitive_endpoint(...): ...
"""

from __future__ import annotations

import jwt
from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.core.security import _get_effective_algorithm, _get_jwt_verification_key


class RequireMFA:
    """FastAPI dependency that checks for MFA in the token's amr claim.

    Validates that the JWT access token contains "mfa" in its Authentication
    Methods Reference (amr) claim, indicating the user completed multi-factor
    authentication.

    JWT-authenticated users without MFA get a 403. API key auth is exempt.
    """

    async def __call__(
        self,
        request: Request,
        db: AsyncSession = Depends(get_db),
    ) -> None:
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            # API key auth or no auth — MFA not applicable
            return

        token = auth_header[7:]
        try:
            algorithm = _get_effective_algorithm()
            payload = jwt.decode(
                token,
                _get_jwt_verification_key(),
                algorithms=[algorithm],
                issuer="saas-platform",
                audience="saas-platform",
            )
        except jwt.InvalidTokenError:
            raise HTTPException(status_code=401, detail="Invalid token") from None

        # Check token revocation
        from app.core.security import is_token_revoked

        jti = payload.get("jti")
        if jti and await is_token_revoked(jti):
            raise HTTPException(status_code=401, detail="Token has been revoked")

        amr = payload.get("amr", [])
        if "mfa" not in amr:
            raise HTTPException(
                status_code=403,
                detail="Multi-factor authentication required for this endpoint",
            )
