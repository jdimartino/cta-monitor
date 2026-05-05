"""
CTA Intelligence System — Authentication
Autor: JDM | #JDMRules
"""

from __future__ import annotations

import pickle
import random
import time
import logging
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

import config

logger = logging.getLogger("auth")


def _build_adapter():
    """HTTPAdapter con pool y retry de urllib3 dentro del propio adapter.

    Why: LibreSSL 2.8.3 (macOS system Python) tiene bugs conocidos con session
    resumption de TLS — conexiones keep-alive pueden quedar en estado roto y
    reusarse causando SSLEOFError(_ssl.c:1129). El adapter limita el pool y
    permite retries de HTTP antes de que la excepción suba a la app.

    NOTE: SSLError NO se incluye en raise_on_status porque queremos que los
    reintentos SSL los gestione el loop de authenticated_get (con reset de pool
    y jitter), no urllib3 (que agostaría sus reintentos antes de llegar al
    manejo de nivel superior).
    """
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
    return HTTPAdapter(
        pool_connections=2,
        pool_maxsize=4,
        max_retries=Retry(
            total=3,
            connect=3,
            read=2,
            backoff_factor=2.0,
            status_forcelist=[502, 503, 504],
            allowed_methods=["GET"],
            raise_on_status=False,
        ),
    )


def create_session() -> requests.Session:
    """Create a new requests.Session with proper headers and pooled adapter."""
    session = requests.Session()
    session.headers.update({
        "User-Agent": config.USER_AGENT,
        # Forzamos cierre de conexión para evitar reuso de TLS sessions rotas
        # bajo LibreSSL 2.8.3. Coste: handshake por request, pero cero SSLEOFError
        # de conexiones zombie en pool.
        "Connection": "close",
    })
    adapter = _build_adapter()
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def _get_csrf_token(session: requests.Session) -> str | None:
    """GET the login page and extract csrfmiddlewaretoken."""
    try:
        resp = session.get(config.LOGIN_URL, timeout=10)
        resp.raise_for_status()
    except Exception as e:
        logger.error(f"Error loading login page: {e}")
        return None

    soup = BeautifulSoup(resp.text, "html.parser")
    csrf_input = soup.find("input", {"name": "csrfmiddlewaretoken"})
    if not csrf_input:
        logger.error("CSRF token not found in login form")
        return None

    return csrf_input["value"]


def login(session: requests.Session = None) -> requests.Session | None:
    """Authenticate against ctatenis.com. Returns authenticated session or None."""
    if not config.CTA_CEDULA or not config.CTA_PASSWORD:
        logger.error("Missing CTA credentials in .env")
        return None

    if session is None:
        session = create_session()

    csrf_token = _get_csrf_token(session)
    if not csrf_token:
        return None

    payload = {
        "csrfmiddlewaretoken": csrf_token,
        "username": config.CTA_CEDULA,
        "password": config.CTA_PASSWORD,
    }
    headers = {"Referer": config.LOGIN_URL}

    try:
        resp = session.post(
            config.LOGIN_URL, data=payload, headers=headers, timeout=10
        )
        resp.raise_for_status()
    except Exception as e:
        logger.error(f"Login POST failed: {e}")
        return None

    if "/accounts/login/" in resp.url:
        logger.error("Login failed — bad credentials or unexpected redirect")
        return None

    logger.info(f"Login successful → {resp.url}")
    save_session(session)
    return session


def save_session(session: requests.Session):
    """Persist session cookies to disk."""
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    try:
        with open(config.SESSION_FILE, "wb") as f:
            pickle.dump(session.cookies, f)
        logger.debug(f"Session saved to {config.SESSION_FILE}")
    except Exception as e:
        logger.warning(f"Could not save session: {e}")


def _session_age_seconds() -> float | None:
    """Edad del archivo de sesión en segundos, o None si no existe."""
    import os
    p = Path(config.SESSION_FILE)
    if not p.exists():
        return None
    return (datetime.now() - datetime.fromtimestamp(os.path.getmtime(p))).total_seconds()


def load_session() -> requests.Session | None:
    """Load a previously saved session. Returns None if missing or expired."""
    session_path = Path(config.SESSION_FILE)
    if not session_path.exists():
        return None

    age = _session_age_seconds()
    if age is None or age > config.SESSION_MAX_AGE_HOURS * 3600:
        logger.info("Saved session expired, will re-login")
        return None

    try:
        session = create_session()
        with open(session_path, "rb") as f:
            session.cookies = pickle.load(f)
        logger.debug("Loaded saved session from disk")
        return session
    except Exception as e:
        logger.warning(f"Could not load session: {e}")
        return None


def _validate_session(session: requests.Session) -> bool:
    """Check if session is still authenticated by hitting a known page."""
    try:
        url = f"{config.BASE_URL}/cts/tabla_posiciones/{config.LIGA_ID}/{config.CATEGORIA_ID}/"
        resp = session.get(url, timeout=10, allow_redirects=False)
        if resp.status_code in (301, 302):
            location = resp.headers.get("Location", "")
            if "/accounts/login/" in location:
                return False
        return resp.status_code == 200
    except Exception:
        return False


def get_session() -> requests.Session | None:
    """Main entry point. Try saved session, validate, re-login if needed.

    Optimizaciones:
    - Si la sesión es muy fresca (<5 min), saltea validación (request extra innecesario).
    - Si la sesión es vieja (>2h, mitad del TTL), refresca proactivamente para
      reducir riesgo de re-login mid-crawl.
    """
    session = load_session()
    if session:
        age = _session_age_seconds() or 0
        # Refresh proactivo a la mitad del TTL — evita expiry mid-crawl
        if age > (config.SESSION_MAX_AGE_HOURS * 3600) / 2:
            logger.info(f"Session age {age/60:.0f}min > half-TTL — refreshing proactively")
        elif age < 300:
            logger.info("Using cached session (fresh, skipping validation)")
            return session
        elif _validate_session(session):
            logger.info("Using cached session")
            return session

    logger.info("Logging in fresh...")
    return login()


def _reset_connection_pool(session: requests.Session):
    """Remonta adapters frescos para recuperarse de SSL drops sin perder la sesión.

    Bajo LibreSSL 2.8.3, una conexión TLS rota puede contaminar el pool. Reseteamos
    los adapters (NO session.close() — eso borra cookies y headers) para forzar
    handshakes nuevos en el próximo request.
    """
    try:
        # Cerrar solo los adapters existentes, NO la sesión completa
        for adapter in session.adapters.values():
            try:
                adapter.close()
            except Exception:
                pass
    except Exception:
        pass
    new_adapter = _build_adapter()
    session.mount("https://", new_adapter)
    session.mount("http://", new_adapter)


def authenticated_get(
    session: requests.Session, url: str, max_retries: int = 5
) -> requests.Response | None:
    """GET with auto-retry on session expiry, HTTP errors, and SSL/connection drops."""
    for attempt in range(max_retries + 1):
        try:
            resp = session.get(url, timeout=30, allow_redirects=True)
            resp.raise_for_status()

            # Check if we got redirected to login
            if "/accounts/login/" in resp.url:
                if attempt < max_retries:
                    logger.warning(f"Session expired, re-authenticating (attempt {attempt + 1})")
                    new_session = login(session)
                    if not new_session:
                        return None
                    time.sleep(config.REQUEST_DELAY)
                    continue
                else:
                    logger.error("Could not re-authenticate after retries")
                    return None

            time.sleep(config.REQUEST_DELAY)
            return resp

        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response else 0
            if status in (429, 503) and attempt < max_retries:
                wait = min(config.REQUEST_DELAY * (2 ** attempt), 60)
                logger.warning(f"HTTP {status}, backing off {wait}s")
                time.sleep(wait)
                continue
            logger.error(f"HTTP error fetching {url}: {e}")
            return None
        except (requests.exceptions.SSLError, requests.exceptions.ConnectionError) as e:
            if attempt < max_retries:
                # Backoff exponencial con jitter para evitar thundering herd
                # en crawls paralelos (todos los threads fallan al mismo tiempo).
                base_wait = min(config.REQUEST_DELAY * (2 ** attempt), 45)
                jitter = random.uniform(0, base_wait * 0.4)
                wait = base_wait + jitter
                logger.warning(
                    f"SSL/Connection error (attempt {attempt + 1}/{max_retries}), "
                    f"retrying in {wait:.1f}s — resetting pool: {e}"
                )
                time.sleep(wait)
                _reset_connection_pool(session)
                continue
            logger.error(f"Error fetching {url}: {e}")
            return None
        except Exception as e:
            logger.error(f"Error fetching {url}: {e}")
            return None

    return None
