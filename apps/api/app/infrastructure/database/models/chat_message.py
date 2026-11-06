from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base


class ChatMessageModel(Base):
    __tablename__ = 'chat_messages'
    __table_args__ = (
        UniqueConstraint('user_id', 'turn_id', 'role', name='uq_chat_messages_user_turn_role'),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    thread_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    turn_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True, index=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
