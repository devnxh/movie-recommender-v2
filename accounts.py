"""Persistent accounts and favorites. Guest watchlists remain in Flask's own cookie."""
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import re
import secrets
import sqlite3
import tempfile
import threading
import time
from urllib.parse import urlsplit

from flask import Blueprint, current_app, g, jsonify, request, session
from itsdangerous import BadData, URLSafeTimedSerializer
from werkzeug.security import check_password_hash, generate_password_hash


api = Blueprint("accounts", __name__, url_prefix="/api")
COOKIE = "cinewatch_account"
SESSION_TTL = 30 * 86400
HANDLE = re.compile(r"[A-Za-z0-9_-]{3,32}\Z")
DUMMY_HASH = "scrypt:32768:8:1$invalid-user$" + "0" * 128


class StoreUnavailable(Exception):
    """The account store is unconfigured or temporarily unreachable."""


def _local_key(directory):
    """Atomically publish one key shared by development workers and restarts."""
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    destination = directory / "session.key"
    if not destination.exists():
        with tempfile.NamedTemporaryFile(dir=directory, delete=False) as tmp:
            tmp.write(secrets.token_bytes(32))
            tmp.flush()
            os.fsync(tmp.fileno())
        try:
            os.link(tmp.name, destination)
        except FileExistsError:
            pass
        finally:
            os.unlink(tmp.name)
    return destination.read_bytes()


def init_accounts(app, card_lookup):
    """Set up the store without making catalog startup depend on a database connection."""
    hosted = bool(os.getenv("RENDER") or os.getenv("VERCEL"))
    local_dir = Path(app.root_path) / "var"
    database = os.getenv("DATABASE_URL", "")
    db_path = os.getenv("CINEWATCH_DB_PATH") or (None if hosted else str(local_dir / "cinewatch.sqlite3"))
    secret = os.getenv("FLASK_SECRET_KEY")
    if not secret:
        if db_path:
            try:
                secret = _local_key(Path(db_path).resolve().parent / ".cinewatch")
            except OSError:
                app.logger.warning("Account storage is inaccessible. Using the temporary directory for guest sessions.")
        if not secret:
            owner = os.getuid() if hasattr(os, "getuid") else "local"
            secret = _local_key(Path(tempfile.gettempdir()) / f"cinewatch-{owner}")
    app.secret_key = secret
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=bool(os.getenv("RENDER_EXTERNAL_URL") or os.getenv("VERCEL")),
    )
    app.extensions["cinewatch_store"] = {
        "url": database, "path": db_path, "cards": card_lookup,
        "lock": threading.Lock(), "initialized": False,
    }
    app.register_blueprint(api)
    app.before_request(_migrate_guest_watchlist)
    app.register_error_handler(StoreUnavailable, _unavailable)


def _migrate_guest_watchlist():
    """Read only the guest's own watchlist from the pre-account cookie format."""
    if request.endpoint != "watchlist" or "watchlist" in session:
        return
    cookie = request.cookies.get(current_app.config["SESSION_COOKIE_NAME"], "")
    if not cookie or len(cookie) > 4096:
        return
    interface = current_app.session_interface
    # The old key is public. Never use this serializer to authenticate a user or
    # sign new data; import only client-owned movie records into a fresh session.
    legacy = URLSafeTimedSerializer(
        "cinewatch_secret_key", salt=interface.salt, serializer=interface.serializer,
        signer_kwargs={"key_derivation": interface.key_derivation, "digest_method": interface.digest_method},
    )
    try:
        old = legacy.loads(cookie, max_age=int(current_app.permanent_session_lifetime.total_seconds()))
    except BadData:
        return
    items = old.get("watchlist") if isinstance(old, dict) else None
    if isinstance(items, list):
        session["watchlist"] = [item for item in items
                                if isinstance(item, dict) and isinstance(item.get("title"), str)]


def _unavailable(_error):
    return jsonify(available=False, user=None, favorite_ids=[], error="Accounts are currently unavailable."), 503


def _configured():
    store = current_app.extensions["cinewatch_store"]
    return bool(store["url"] or store["path"])


def _schema(query, postgres):
    if postgres:
        # Two fresh workers can otherwise race on PostgreSQL's internal sequences.
        query("SELECT pg_advisory_xact_lock(593460872)")
    key_type = "BIGSERIAL PRIMARY KEY" if postgres else "INTEGER PRIMARY KEY"
    query(f"""CREATE TABLE IF NOT EXISTS cw_users (
        id {key_type}, username TEXT NOT NULL, username_key TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL
    )""")
    query("""CREATE TABLE IF NOT EXISTS cw_sessions (
        token_hash TEXT PRIMARY KEY, user_id BIGINT NOT NULL REFERENCES cw_users(id) ON DELETE CASCADE,
        expires BIGINT NOT NULL
    )""")
    query("CREATE INDEX IF NOT EXISTS cw_sessions_expiry ON cw_sessions(expires)")
    query("""CREATE TABLE IF NOT EXISTS cw_favorites (
        user_id BIGINT NOT NULL REFERENCES cw_users(id) ON DELETE CASCADE,
        movie_id BIGINT NOT NULL, created BIGINT NOT NULL, PRIMARY KEY (user_id, movie_id)
    )""")
    query("CREATE INDEX IF NOT EXISTS cw_favorites_movie ON cw_favorites(movie_id, user_id)")
    query("""CREATE TABLE IF NOT EXISTS cw_reviews (
        movie_id BIGINT NOT NULL, user_id BIGINT NOT NULL REFERENCES cw_users(id) ON DELETE CASCADE,
        rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 10), body TEXT NOT NULL,
        updated_at BIGINT NOT NULL, PRIMARY KEY (movie_id, user_id)
    )""")
    query("CREATE INDEX IF NOT EXISTS cw_reviews_recent ON cw_reviews(movie_id, updated_at DESC)")
    query("""CREATE TABLE IF NOT EXISTS cw_attempts (
        bucket TEXT PRIMARY KEY, period BIGINT NOT NULL, attempts INTEGER NOT NULL
    )""")
    query("CREATE INDEX IF NOT EXISTS cw_attempts_period ON cw_attempts(period)")


@contextmanager
def transaction():
    """Yield query(sql, params) with ? parameters; commit the whole operation or roll it back."""
    store = current_app.extensions["cinewatch_store"]
    postgres = bool(store["url"])
    if postgres:
        import psycopg
        try:
            conn = psycopg.connect(store["url"], connect_timeout=4)
        except psycopg.Error as error:
            raise StoreUnavailable from error
        unavailable_errors = (psycopg.OperationalError, psycopg.InterfaceError)
    else:
        if not store["path"]:
            raise StoreUnavailable
        try:
            path = Path(store["path"])
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            conn = sqlite3.connect(path, timeout=5)
            conn.execute("PRAGMA foreign_keys=ON")
        except (OSError, sqlite3.OperationalError) as error:
            raise StoreUnavailable from error
        unavailable_errors = (sqlite3.OperationalError,)

    def query(sql, params=()):
        return conn.execute(sql.replace("?", "%s") if postgres else sql, params)

    try:
        if not store["initialized"]:
            with store["lock"]:
                if not store["initialized"]:
                    _schema(query, postgres)
                    conn.commit()
                    store["initialized"] = True
        yield query
        conn.commit()
    except unavailable_errors as error:
        conn.rollback()
        raise StoreUnavailable from error
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def require_json_write():
    """Reject cross-site browser writes and form submissions; API clients use JSON."""
    origin = request.headers.get("Origin")
    if origin:
        source, target = urlsplit(origin), urlsplit(request.host_url)
        if source.scheme not in ("http", "https") or source.netloc.lower() != target.netloc.lower():
            return jsonify(error="This request must come from CineWatch."), 403
        if source.scheme != target.scheme and not (source.scheme == "https" and target.scheme == "http"):
            return jsonify(error="This request must come from CineWatch."), 403
    if request.headers.get("Sec-Fetch-Site") in ("cross-site", "same-site"):
        return jsonify(error="This request must come from CineWatch."), 403
    if not request.is_json:
        return jsonify(error="Use a JSON request body."), 415
    return None


@api.before_request
def _guard():
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        request.max_content_length = 4096
        return require_json_write()


@api.after_request
def _no_cache(response):
    response.headers["Cache-Control"] = "private, no-store"
    return response


def _digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def _cookie_hash():
    token = request.cookies.get(COOKIE, "")
    return _digest(token) if len(token) == 43 and token.isascii() else None


def _user(query):
    token_hash = _cookie_hash()
    if not token_hash:
        return None
    row = query("""SELECT u.id, u.username FROM cw_sessions s JOIN cw_users u ON s.user_id=u.id
        WHERE s.token_hash=? AND s.expires>?""", (token_hash, int(time.time()))).fetchone()
    return {"id": row[0], "username": row[1]} if row else None


def current_user_id():
    if not _configured() or not _cookie_hash():
        return None
    if "cinewatch_user" not in g:
        with transaction() as query:
            g.cinewatch_user = _user(query)
    return g.cinewatch_user["id"] if g.cinewatch_user else None


def _favorite_ids(query, uid):
    return [row[0] for row in query("""SELECT movie_id FROM cw_favorites
        WHERE user_id=? ORDER BY created DESC, movie_id DESC""", (uid,))]


def favorite_sets(user_id):
    """Return the target and neighbors sharing at least one favorite, without exposing identities in the API."""
    result = {user_id: set()}
    with transaction() as query:
        rows = query("""SELECT f.user_id, f.movie_id FROM cw_favorites f WHERE f.user_id IN (
            SELECT neighbor.user_id FROM cw_favorites seed JOIN cw_favorites neighbor
              ON neighbor.movie_id=seed.movie_id WHERE seed.user_id=?
        )""", (user_id,))
        for member, movie in rows:
            result.setdefault(member, set()).add(movie)
    return result


@api.get("/account")
def status():
    if not _configured():
        return jsonify(available=False, user=None, favorite_ids=[])
    with transaction() as query:
        user = _user(query)
        return jsonify(available=True, user=user, favorite_ids=_favorite_ids(query, user["id"]) if user else [])


def _reserve_attempts(username_key, register):
    """Reserve an attempt atomically across workers before doing password hashing."""
    window = int(time.time()) // 600
    route = "register" if register else "login"
    buckets = [("ip:" + route + ":" + _digest(request.remote_addr or "unknown"), 12 if register else 120)]
    if not register:
        buckets.append(("name:" + _digest(username_key), 12))
    with transaction() as query:
        query("DELETE FROM cw_attempts WHERE period < ?", (window,))
        for bucket, limit in buckets:
            row = query("""INSERT INTO cw_attempts(bucket,period,attempts) VALUES(?,?,1)
                ON CONFLICT(bucket) DO UPDATE SET attempts=cw_attempts.attempts+1
                WHERE cw_attempts.period=excluded.period AND cw_attempts.attempts<? RETURNING attempts""",
                (bucket, window, limit)).fetchone()
            if not row:
                return False
    return True


def _session_response(query, user, code):
    token = secrets.token_urlsafe(32)
    query("DELETE FROM cw_sessions WHERE token_hash=? OR expires<=?", (_cookie_hash(), int(time.time())))
    query("INSERT INTO cw_sessions(token_hash,user_id,expires) VALUES(?,?,?)",
          (_digest(token), user["id"], int(time.time()) + SESSION_TTL))
    response = jsonify(available=True, user=user, favorite_ids=_favorite_ids(query, user["id"]))
    response.set_cookie(COOKIE, token, max_age=SESSION_TTL, httponly=True, samesite="Lax",
                        secure=current_app.config["SESSION_COOKIE_SECURE"] or request.is_secure or request.headers.get("Origin", "").startswith("https://"))
    return response, code


@api.post("/account/register")
@api.post("/account/login")
def authenticate():
    if not _configured():
        raise StoreUnavailable
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="Enter a username and password."), 400
    name, password = data.get("username"), data.get("password")
    if not isinstance(name, str) or not HANDLE.fullmatch(name.strip()):
        return jsonify(error="Use 3–32 letters, numbers, underscores or hyphens for your username."), 400
    register = request.path.endswith("/register")
    if not isinstance(password, str) or len(password) > 128 or not password or (register and len(password) < 10):
        return jsonify(error="Use a password between 10 and 128 characters."), 400
    name = name.strip()
    key = name.lower()
    if not _reserve_attempts(key, register):
        response = jsonify(error="Too many attempts. Please try again in a few minutes.")
        response.headers["Retry-After"] = str(600 - int(time.time()) % 600)
        return response, 429
    if register:
        hashed = generate_password_hash(password)
        with transaction() as query:
            row = query("""INSERT INTO cw_users(username,username_key,password_hash) VALUES(?,?,?)
                ON CONFLICT(username_key) DO NOTHING RETURNING id""", (name, key, hashed)).fetchone()
            if not row:
                return jsonify(error="That username is already taken."), 409
            return _session_response(query, {"id": row[0], "username": name}, 201)
    with transaction() as query:
        row = query("SELECT id,username,password_hash FROM cw_users WHERE username_key=?", (key,)).fetchone()
    if not check_password_hash(row[2] if row else DUMMY_HASH, password) or row is None:
        return jsonify(error="Incorrect username or password."), 401
    with transaction() as query:
        query("DELETE FROM cw_attempts WHERE bucket=?", ("name:" + _digest(key),))
        return _session_response(query, {"id": row[0], "username": row[1]}, 200)


@api.post("/account/logout")
def logout():
    if _configured() and _cookie_hash():
        with transaction() as query:
            query("DELETE FROM cw_sessions WHERE token_hash=?", (_cookie_hash(),))
    response = jsonify(available=_configured(), user=None, favorite_ids=[])
    response.delete_cookie(COOKIE, httponly=True, samesite="Lax")
    return response


@api.get("/favorites")
@api.route("/favorites/<int:movie_id>", methods=["PUT", "DELETE"])
def favorites(movie_id=None):
    if not _configured():
        raise StoreUnavailable
    lookup = current_app.extensions["cinewatch_store"]["cards"]
    with transaction() as query:
        user = _user(query)
        if not user:
            return jsonify(error="Sign in to manage favorites."), 401
        uid = user["id"]
        if request.method == "PUT":
            if movie_id > 2**63-1 or not lookup([movie_id]):
                return jsonify(error="Movie not found."), 404
            query("""INSERT INTO cw_favorites(user_id,movie_id,created) VALUES(?,?,?)
                ON CONFLICT(user_id,movie_id) DO NOTHING""", (uid, movie_id, time.time_ns()))
        elif request.method == "DELETE":
            if movie_id <= 2**63-1:
                query("DELETE FROM cw_favorites WHERE user_id=? AND movie_id=?", (uid, movie_id))
        ids = _favorite_ids(query, uid)
    if request.method in ("GET", "HEAD"):
        return jsonify(favorite_ids=ids, movies=lookup(ids))
    return jsonify(favorite_ids=ids)
