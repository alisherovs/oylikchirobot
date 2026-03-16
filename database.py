import os
from datetime import datetime
from sqlalchemy import (
    BigInteger, ForeignKey, String, Boolean, Float, DateTime,
    Integer, UniqueConstraint
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

DB_URL = os.getenv("DB_URL", "sqlite+aiosqlite:///company_kpi.db")

engine = create_async_engine(DB_URL, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class Employee(Base):
    __tablename__ = "employees"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)  # Telegram ID
    full_name: Mapped[str] = mapped_column(String(100))
    phone: Mapped[str] = mapped_column(String(20))
    role: Mapped[str] = mapped_column(String(50), default="worker")

    # pending / approved / fired
    status: Mapped[str] = mapped_column(String(20), default="pending")
    # Fix / KPI
    salary_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    base_salary: Mapped[float] = mapped_column(Float, default=0.0)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    kpis: Mapped[list["KPI"]] = relationship(back_populates="employee", cascade="all, delete-orphan")
    advances: Mapped[list["Advance"]] = relationship(back_populates="employee", cascade="all, delete-orphan")
    penalties: Mapped[list["Penalty"]] = relationship(back_populates="employee", cascade="all, delete-orphan")
    salary_history: Mapped[list["SalaryHistory"]] = relationship(back_populates="employee", cascade="all, delete-orphan")


class KPI(Base):
    __tablename__ = "kpi"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"))
    amount: Mapped[float] = mapped_column(Float, default=0)
    description: Mapped[str] = mapped_column(String(255))

    is_closed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    employee: Mapped["Employee"] = relationship(back_populates="kpis")


class Advance(Base):
    __tablename__ = "advances"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"))
    amount: Mapped[float] = mapped_column(Float, default=0)
    description: Mapped[str] = mapped_column(String(255))

    is_closed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    employee: Mapped["Employee"] = relationship(back_populates="advances")


class Penalty(Base):
    __tablename__ = "penalties"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"))
    amount: Mapped[float] = mapped_column(Float, default=0)
    reason: Mapped[str] = mapped_column(String(255))

    is_closed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    employee: Mapped["Employee"] = relationship(back_populates="penalties")


class SalaryHistory(Base):
    __tablename__ = "salary_history"
    __table_args__ = (
        UniqueConstraint("employee_id", "month", name="uq_salaryhistory_employee_month"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"))

    total_kpi: Mapped[float] = mapped_column(Float, default=0)
    total_advance: Mapped[float] = mapped_column(Float, default=0)
    total_penalty: Mapped[float] = mapped_column(Float, default=0)
    final_salary: Mapped[float] = mapped_column(Float, default=0)

    month: Mapped[str] = mapped_column(String(10))  # 2026-03
    is_paid: Mapped[bool] = mapped_column(Boolean, default=False)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    is_closed: Mapped[bool] = mapped_column(Boolean, default=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    employee: Mapped["Employee"] = relationship(back_populates="salary_history")


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
