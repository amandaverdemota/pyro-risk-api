from datetime import date as date_, datetime

from sqlalchemy import Date, DateTime, Float, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from pyro_risk_api.core.db import Base


class FWIScore(Base):
    __tablename__ = "fwi_score"
    __table_args__ = (UniqueConstraint("camera_id", "date", name="uq_fwi_score_cam_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    camera_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    date: Mapped[date_] = mapped_column(Date, index=True, nullable=False)
    fwi: Mapped[float | None] = mapped_column(Float, nullable=True)
    fwi_class: Mapped[str | None] = mapped_column(String(16), nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)