import logging

from fastapi import APIRouter, Depends

from app.api.dependencies import get_current_user
from app.models.user import User
from app.schemas.auth import AuthUserResponse

logger = logging.getLogger("shopeasy.auth.identity")

router = APIRouter(tags=["Identity"])


@router.get(
    "/me",
    response_model=AuthUserResponse,
    summary="Fetch profile of the currently authenticated customer or administrator",
)
def get_authenticated_user_profile(
    current_user: User = Depends(get_current_user),
) -> AuthUserResponse:
    """Return the profile of the currently authenticated user.

    Enforces:
      - Requires a valid Bearer access token (type='access').
      - Rejects missing, expired, invalid, and MFA-pending tokens with HTTP 401.
      - Supports both Customer and Administrator roles.
      - Returns: id, full_name, phone, role, referral_code, is_active.
      - Never exposes password_hash or sensitive fields.
    """
    return AuthUserResponse.model_validate(current_user)

