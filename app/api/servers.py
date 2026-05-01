import secrets

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from app.database import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.models.server import Server
from app.schemas.server import ServerCreate, ServerRead, ServerWithKey
from app.core.security import hash_password

router = APIRouter()


@router.post("/register", response_model=ServerWithKey, status_code=status.HTTP_201_CREATED)
async def register_server(
    data: ServerCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    secret = secrets.token_urlsafe(32)

    new_server = Server(
        name=data.name,
        api_key_hash=hash_password(secret),
        owner_id=current_user.id,
    )

    db.add(new_server)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Сервер с таким именем уже существует",
        )
    await db.refresh(new_server)

    api_key = f"{new_server.id}.{secret}"

    return ServerWithKey(
        id=new_server.id,
        name=new_server.name,
        is_active=new_server.is_active,
        created_at=new_server.created_at,
        last_seen_at=new_server.last_seen_at,
        api_key=api_key,
    )


@router.get("/me", response_model=list[ServerRead])
async def list_my_servers(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(Server).where(Server.owner_id == current_user.id)
    result = await db.execute(query)
    servers = result.scalars().all()
    return servers
