from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy import select, desc, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.dependencies import get_current_user
from backend.database import get_db
from backend.database.models import User, Conversation, Message
from backend.limiter import limiter

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


class ConvResponse(BaseModel):
    id: int
    title: str
    is_archived: bool
    message_count: int
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm(cls, conv: Conversation):
        return cls(
            id=conv.id,
            title=conv.title,
            is_archived=conv.is_archived,
            message_count=conv.message_count,
            created_at=conv.created_at.isoformat() if conv.created_at else "",
            updated_at=conv.updated_at.isoformat() if conv.updated_at else "",
        )


class MsgResponse(BaseModel):
    id: int
    role: str
    content: str
    tokens_used: int | None
    search_results: list | None
    created_at: str


@router.get("", response_model=list[ConvResponse])
@limiter.limit("30/minute")
async def list_conversations(
    request: Request,
    archived: bool = Query(False),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    offset = (page - 1) * size
    stmt = (
        select(Conversation)
        .where(Conversation.user_id == user.id, Conversation.is_archived == archived)
        .order_by(desc(Conversation.updated_at))
        .offset(offset)
        .limit(size)
    )
    result = await db.execute(stmt)
    convs = result.scalars().all()
    return [ConvResponse.from_orm(c) for c in convs]


@router.post("", response_model=ConvResponse)
@limiter.limit("10/minute")
async def create_conversation(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    conv = Conversation(user_id=user.id)
    db.add(conv)
    await db.flush()
    await db.refresh(conv)
    return ConvResponse.from_orm(conv)


@router.get("/{conv_id}/messages", response_model=list[MsgResponse])
@limiter.limit("30/minute")
async def get_messages(
    request: Request,
    conv_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    conv = await db.scalar(
        select(Conversation).where(
            Conversation.id == conv_id, Conversation.user_id == user.id
        )
    )
    if not conv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="对话不存在")

    stmt = (
        select(Message)
        .where(Message.conversation_id == conv_id)
        .order_by(Message.created_at)
    )
    result = await db.execute(stmt)
    msgs = result.scalars().all()
    return [
        MsgResponse(
            id=m.id,
            role=m.role,
            content=m.content,
            tokens_used=m.tokens_used,
            search_results=m.search_results,
            created_at=m.created_at.isoformat() if m.created_at else "",
        )
        for m in msgs
    ]


@router.delete("/{conv_id}")
@limiter.limit("10/minute")
async def delete_conversation(
    request: Request,
    conv_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    conv = await db.scalar(
        select(Conversation).where(
            Conversation.id == conv_id, Conversation.user_id == user.id
        )
    )
    if not conv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="对话不存在")
    await db.delete(conv)
    await db.commit()
    return {"ok": True}
