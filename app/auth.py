"""
Wyze authentication with support for:
  - Email/password (standard)
  - TOTP 2FA via a base32 secret key
  - Wyze API key (newer method, no TUTK support yet)

Credentials are never logged, even at DEBUG level.
"""

import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)


class AuthError(RuntimeError):
    pass


class MFARequired(AuthError):
    pass


def _get_totp_code(totp_key: str) -> str:
    try:
        import pyotp
    except ImportError:
        raise AuthError(
            "pyotp is required for TOTP 2FA — install it with: pip install pyotp"
        )
    totp = pyotp.TOTP(totp_key.strip().replace(" ", ""))
    return totp.now()


def login(
    email: str,
    password: str,
    totp_key: str = "",
    max_retries: int = 3,
) -> tuple:
    """
    Authenticate with Wyze and return (credential, account) tuple.

    Uses wyzecam under the hood, which wraps the Wyze REST API and
    handles the TUTK session setup.

    Raises AuthError on permanent failure, MFARequired if 2FA is needed
    but no totp_key was provided.
    """
    try:
        import wyzecam
    except ImportError:
        raise AuthError(
            "wyzecam is not installed — add it to requirements.txt"
        )

    last_exc: Optional[Exception] = None
    for attempt in range(1, max_retries + 1):
        try:
            logger.debug("Attempting Wyze login (attempt %d/%d)", attempt, max_retries)
            credential = _do_login(wyzecam, email, password, totp_key)
            account = wyzecam.get_user_info(credential)
            logger.info("Authenticated with Wyze as %s", _mask_email(email))
            return credential, account
        except MFARequired:
            raise  # Don't retry — caller must provide a TOTP key
        except AuthError:
            raise  # Don't retry permanent auth failures
        except Exception as exc:
            last_exc = exc
            logger.warning(
                "Login attempt %d failed: %s", attempt, type(exc).__name__
            )
            if attempt < max_retries:
                time.sleep(2 ** attempt)  # Exponential back-off

    raise AuthError(
        f"Failed to authenticate after {max_retries} attempts: {last_exc}"
    ) from last_exc


def _do_login(wyzecam, email: str, password: str, totp_key: str):
    """Inner login; raises specific exceptions for each failure mode."""
    try:
        credential = wyzecam.login(email, password)
    except Exception as exc:
        msg = str(exc).lower()

        if "mfa" in msg or "2fa" in msg or "verification" in msg or "otp" in msg:
            if not totp_key:
                raise MFARequired(
                    "This Wyze account requires 2FA. "
                    "Set WYZE_TOTP_KEY to your base32 TOTP secret."
                ) from exc
            # Retry with a fresh TOTP code
            code = _get_totp_code(totp_key)
            try:
                # wyzecam.login accepts mfa_type and mfa_code kwargs
                credential = wyzecam.login(
                    email, password,
                    mfa_type="TotpVerificationCode",
                    mfa_code=code,
                )
            except Exception as inner:
                raise AuthError(
                    f"2FA login failed — check WYZE_TOTP_KEY: {type(inner).__name__}"
                ) from inner
        elif "invalid" in msg or "incorrect" in msg or "unauthorized" in msg:
            raise AuthError(
                "Invalid Wyze credentials — check WYZE_EMAIL and WYZE_PASSWORD"
            ) from exc
        else:
            raise  # Unknown error — let the retry loop handle it

    # Some wyzecam versions return a credential that still needs MFA
    if hasattr(credential, "mfa_options") and credential.mfa_options:
        if not totp_key:
            raise MFARequired(
                "This Wyze account requires 2FA. "
                "Set WYZE_TOTP_KEY to your base32 TOTP secret."
            )
        code = _get_totp_code(totp_key)
        try:
            credential = wyzecam.login(
                email, password,
                mfa_type="TotpVerificationCode",
                mfa_code=code,
            )
        except Exception as exc:
            raise AuthError(f"2FA login failed: {type(exc).__name__}") from exc

    return credential


def refresh_credential(credential, email: str, password: str, totp_key: str = ""):
    """
    Refresh a stale Wyze credential.
    Returns a fresh (credential, account) pair.
    """
    logger.info("Refreshing Wyze credentials for %s", _mask_email(email))
    return login(email, password, totp_key)


def _mask_email(email: str) -> str:
    """Mask an email address for safe logging: user@example.com → u***@e***.com"""
    if "@" not in email:
        return "***"
    local, domain = email.split("@", 1)
    masked_local = local[0] + "***" if local else "***"
    parts = domain.split(".")
    masked_domain = parts[0][0] + "***" if parts[0] else "***"
    tld = "." + parts[-1] if len(parts) > 1 else ""
    return f"{masked_local}@{masked_domain}{tld}"
