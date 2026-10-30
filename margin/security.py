"""Login and request checks. Every route but /api/health needs the reader login."""
import logging
import secrets

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from .config import Settings

log = logging.getLogger(__name__)
basic = HTTPBasic(realm="Margin")


class Auth:
    def __init__(self, settings: Settings):
        self.user = settings.margin_user
        self.password = settings.margin_password or ""
        if not self.password:
            self.password = secrets.token_urlsafe(16)
            log.warning("MARGIN_PASSWORD is not set. Generated a password for '%s' for this run: %s",
                        self.user, self.password)

    def check(self, credentials: HTTPBasicCredentials) -> str:
        ok_user = secrets.compare_digest(credentials.username.encode(), self.user.encode())
        ok_pass = secrets.compare_digest(credentials.password.encode(), self.password.encode())
        if not (ok_user and ok_pass):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong username or password",
                                headers={"WWW-Authenticate": 'Basic realm="Margin"'})
        return credentials.username


def require_user(request: Request, credentials: HTTPBasicCredentials = Depends(basic)) -> str:
    user = request.app.state.auth.check(credentials)
    # Browsers resend Basic credentials to any site that posts here. A custom header can't be added
    # cross-site without a CORS preflight, which we never allow, so it blocks CSRF.
    if request.method not in ("GET", "HEAD", "OPTIONS") and request.headers.get("x-requested-with") != "margin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Missing X-Requested-With header")
    return user


SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
                               "font-src https://fonts.gstatic.com; img-src 'self' data:; frame-ancestors 'none'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}
