import asyncio
import json
import os

import firebase_admin
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from firebase_admin import auth, credentials

_bearer = HTTPBearer(auto_error=False)


def _init_firebase() -> None:
    if firebase_admin._apps:
        return
    raw = os.getenv("FIREBASE_CREDENTIALS")
    if not raw:
        raise RuntimeError("FIREBASE_CREDENTIALS environment variable is not set")
    cred = credentials.Certificate(json.loads(raw))
    firebase_admin.initialize_app(cred)


async def verify_firebase_token(token: str) -> dict:
    _init_firebase()
    try:
        # verify_id_token is synchronous and makes network I/O — run in thread
        return await asyncio.to_thread(auth.verify_id_token, token)
    except auth.ExpiredIdTokenError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Token has expired")
    except auth.RevokedIdTokenError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Token has been revoked")
    except auth.InvalidIdTokenError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    except Exception:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Could not validate token")


async def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict:
    if not creds:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header missing",
            headers={"WWW-Authenticate": "Bearer"},
        )
    decoded = await verify_firebase_token(creds.credentials)
    return {"uid": decoded["uid"], "email": decoded.get("email")}
