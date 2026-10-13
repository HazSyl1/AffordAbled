from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base


class AgentCorrectionModel(Base):
    __tablename__ = 'agent_corrections'

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    thread_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    original_proposal: Mapped[dict] = mapped_column(JSON, nullable=False)
    corrected_proposal: Mapped[dict] = mapped_column(JSON, nullable=False)
    user_message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
