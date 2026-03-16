import os
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    ForeignKey,
    String,
    Boolean,
    Float,
    DateTime,
    Integer,
    UniqueConstraint,
    text,
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

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    full_name: Mapped[str] = mapped_column(String(100))
    phone: Mapped[str] = mapped_column(String(20))
    role: Mapped[str] = mapped_column(String(50), default="worker")

    status: Mapped[str] = mapped_column(String(20), default="pending")
    salary_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    base_salary: Mapped[float] = mapped_column(Float, default=0.0)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


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

    month: Mapped[str] = mapped_column(String(10))
    is_paid: Mapped[bool] = mapped_column(Boolean, default=False)
    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    is_closed: Mapped[bool] = mapped_column(Boolean, default=False)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    employee: Mapped["Employee"] = relationship(back_populates="salary_history")


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def migrate_db():
    async with engine.begin() as conn:
        # =========================
        # employees jadvali
        # =========================
        result = await conn.execute(text("PRAGMA table_info(employees)"))
        employee_columns = [row[1] for row in result.fetchall()]

        if "status" not in employee_columns:
            await conn.execute(
                text("ALTER TABLE employees ADD COLUMN status VARCHAR(20) DEFAULT 'pending'")
            )

        if "salary_type" not in employee_columns:
            await conn.execute(
                text("ALTER TABLE employees ADD COLUMN salary_type VARCHAR(20)")
            )

        if "base_salary" not in employee_columns:
            await conn.execute(
                text("ALTER TABLE employees ADD COLUMN base_salary FLOAT DEFAULT 0")
            )

        if "role" not in employee_columns:
            await conn.execute(
                text("ALTER TABLE employees ADD COLUMN role VARCHAR(50) DEFAULT 'worker'")
            )

        if "created_at" not in employee_columns:
            await conn.execute(
                text("ALTER TABLE employees ADD COLUMN created_at DATETIME")
            )

        await conn.execute(text("UPDATE employees SET status='pending' WHERE status IS NULL"))
        await conn.execute(text("UPDATE employees SET base_salary=0 WHERE base_salary IS NULL"))
        await conn.execute(text("UPDATE employees SET role='worker' WHERE role IS NULL"))

        # =========================
        # kpi jadvali
        # =========================
        result = await conn.execute(text("PRAGMA table_info(kpi)"))
        kpi_columns = [row[1] for row in result.fetchall()]

        if "is_closed" not in kpi_columns:
            await conn.execute(
                text("ALTER TABLE kpi ADD COLUMN is_closed BOOLEAN DEFAULT 0")
            )

        if "created_at" not in kpi_columns:
            await conn.execute(
                text("ALTER TABLE kpi ADD COLUMN created_at DATETIME")
            )

        await conn.execute(text("UPDATE kpi SET is_closed=0 WHERE is_closed IS NULL"))

        # =========================
        # advances jadvali
        # =========================
        result = await conn.execute(text("PRAGMA table_info(advances)"))
        advance_columns = [row[1] for row in result.fetchall()]

        if "is_closed" not in advance_columns:
            await conn.execute(
                text("ALTER TABLE advances ADD COLUMN is_closed BOOLEAN DEFAULT 0")
            )

        if "created_at" not in advance_columns:
            await conn.execute(
                text("ALTER TABLE advances ADD COLUMN created_at DATETIME")
            )

        await conn.execute(text("UPDATE advances SET is_closed=0 WHERE is_closed IS NULL"))

        # =========================
        # penalties jadvali
        # =========================
        result = await conn.execute(text("PRAGMA table_info(penalties)"))
        penalty_columns = [row[1] for row in result.fetchall()]

        if "is_closed" not in penalty_columns:
            await conn.execute(
                text("ALTER TABLE penalties ADD COLUMN is_closed BOOLEAN DEFAULT 0")
            )

        if "created_at" not in penalty_columns:
            await conn.execute(
                text("ALTER TABLE penalties ADD COLUMN created_at DATETIME")
            )

        await conn.execute(text("UPDATE penalties SET is_closed=0 WHERE is_closed IS NULL"))

        # =========================
        # salary_history jadvali
        # =========================
        result = await conn.execute(text("PRAGMA table_info(salary_history)"))
        salary_columns = [row[1] for row in result.fetchall()]

        if "is_paid" not in salary_columns:
            await conn.execute(
                text("ALTER TABLE salary_history ADD COLUMN is_paid BOOLEAN DEFAULT 0")
            )

        if "paid_at" not in salary_columns:
            await conn.execute(
                text("ALTER TABLE salary_history ADD COLUMN paid_at DATETIME")
            )

        if "is_closed" not in salary_columns:
            await conn.execute(
                text("ALTER TABLE salary_history ADD COLUMN is_closed BOOLEAN DEFAULT 0")
            )

        if "closed_at" not in salary_columns:
            await conn.execute(
                text("ALTER TABLE salary_history ADD COLUMN closed_at DATETIME")
            )

        if "created_at" not in salary_columns:
            await conn.execute(
                text("ALTER TABLE salary_history ADD COLUMN created_at DATETIME")
            )

        await conn.execute(text("UPDATE salary_history SET is_paid=0 WHERE is_paid IS NULL"))
        await conn.execute(text("UPDATE salary_history SET is_closed=0 WHERE is_closed IS NULL"))
