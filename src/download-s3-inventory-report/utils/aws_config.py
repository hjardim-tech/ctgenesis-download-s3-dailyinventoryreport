import os
import subprocess
from typing import Any, Callable, Optional, TypeVar


def _build_session_kwargs(profile_name: str) -> dict[str, Any]:
    """Return boto3 session kwargs that explicitly use the local AWS config files."""
    aws_home = os.path.expanduser("~/.aws")
    config_path = os.path.join(aws_home, "config")
    credentials_path = os.path.join(aws_home, "credentials")

    kwargs: dict[str, Any] = {"profile_name": profile_name}
    if os.path.exists(config_path):
        kwargs["config"] = {"config_file": config_path}
    if os.path.exists(credentials_path):
        kwargs["credentials"] = None
    return kwargs

try:
    import boto3
    from botocore.exceptions import ClientError
except ImportError:  # pragma: no cover - optional dependency in test env
    boto3 = None  # type: ignore[assignment]
    ClientError = Exception  # type: ignore[assignment]

try:
    from botocore.exceptions import NoCredentialsError
except ImportError:  # pragma: no cover - older botocore versions
    class NoCredentialsError(Exception):
        """Fallback for environments without explicit credential errors."""


T = TypeVar("T")


def get_session(
    profile_name: str,
    session_factory: Optional[Callable[..., Any]] = None,
    log: Optional[Callable[[str], None]] = None,
) -> Any:
    """Return a boto3 session for the given AWS profile.

    The helper first tries the standard AWS credential chain, including shared
    credentials files such as ~/.aws/credentials. If that fails and an SSO
    profile is configured, it will attempt to refresh the token with the AWS CLI.
    """
    if session_factory is None:
        if boto3 is None:
            raise RuntimeError("boto3 is required to create an AWS session")
        session_factory = boto3.Session

    if log is None:
        log = print

    session = session_factory(**_build_session_kwargs(profile_name))
    try:
        log(f"[{profile_name}] Checking session credentials...")
        session.client("sts").get_caller_identity()
        log(f"[{profile_name}] Valid credentials found.")
        return session
    except (ClientError, NoCredentialsError) as exc:
        log(f"[{profile_name}] No valid session ({exc}). Trying AWS CLI SSO login...")
        result = subprocess.run(
            [
                "aws",
                "sso",
                "login",
                "--profile",
                profile_name,
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            log(
                f"[{profile_name}] SSO login failed. stdout: {result.stdout!r} stderr: {result.stderr!r}"
            )
            raise RuntimeError(
                f"SSO login failed for profile {profile_name}. stdout: {result.stdout!r} stderr: {result.stderr!r}"
            )
        log(
            f"[{profile_name}] SSO login succeeded. stdout: {result.stdout!r} stderr: {result.stderr!r}"
        )
        return session_factory(**_build_session_kwargs(profile_name))
