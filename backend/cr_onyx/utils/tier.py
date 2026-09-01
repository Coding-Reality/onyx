from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError


def require_business_tier_for_multi_sso() -> None:
    """Keep the CR Community deployment to one enabled provider per tenant."""
    raise OnyxError(
        OnyxErrorCode.FEATURE_NOT_AVAILABLE,
        "Community Edition supports one enabled SSO provider per tenant.",
    )
