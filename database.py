import os
from datetime import datetime
from sqlalchemy import BigInteger, ForeignKey, String, Boolean, Float, DateTime
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

# ==========================================
# 1️⃣ BAZAGA ULANISH SOZLAMALARI
# ==========================================
# .env fayldan bazani o'qiydi, agar yo'q bo'lsa SQLite yaratadi
DB_URL = os.getenv("DB_URL", "sqlite+aiosqlite:///company_kpi.db")

# Asinxron engine yaratish
engine = create_async_engine(DB_URL, echo=False)

# Sessiya (bazaga so'rovlarni yuborish uchun yordamchi)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

# Barcha modellar uchun ota-klass
class Base(DeclarativeBase):
    pass

# ==========================================
# 2️⃣ JADVALLAR (MODELLAR)
# ==========================================

class Employee(Base):
    """ Xodimlar jadvali """
    __tablename__ = 'employees'
    
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True) # Telegram ID
    full_name: Mapped[str] = mapped_column(String(100))
    phone: Mapped[str] = mapped_column(String(20))
    role: Mapped[str] = mapped_column(String(50), default="worker")
    
    # 🌟 YANGI QO'SHILGAN USTUNLAR:
    status: Mapped[str] = mapped_column(String(20), default="pending") # pending yoki approved
    salary_type: Mapped[str] = mapped_column(String(20), nullable=True) # Fix yoki KPI
    base_salary: Mapped[float] = mapped_column(Float, default=0.0)
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Boshqa jadvallar bilan bog'lanish (Cascade = xodim o'chirilsa uning tarixi ham tozalab yuboriladi)
    kpis: Mapped[list["KPI"]] = relationship(back_populates="employee", cascade="all, delete-orphan")
    advances: Mapped[list["Advance"]] = relationship(back_populates="employee", cascade="all, delete-orphan")
    penalties: Mapped[list["Penalty"]] = relationship(back_populates="employee", cascade="all, delete-orphan")
    salary_history: Mapped[list["SalaryHistory"]] = relationship(back_populates="employee", cascade="all, delete-orphan")


class KPI(Base):
    """ KPI (Qo'shimcha ish haqi) jadvali """
    __tablename__ = 'kpi'
    
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey('employees.id', ondelete="CASCADE"))
    amount: Mapped[float] = mapped_column(Float)
    description: Mapped[str] = mapped_column(String(255))
    
    is_closed: Mapped[bool] = mapped_column(Boolean, default=False) # Oylik yopilganda True bo'ladi
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    employee: Mapped["Employee"] = relationship(back_populates="kpis")


class Advance(Base):
    """ Avanslar jadvali """
    __tablename__ = 'advances'
    
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey('employees.id', ondelete="CASCADE"))
    amount: Mapped[float] = mapped_column(Float)
    description: Mapped[str] = mapped_column(String(255))
    
    is_closed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    employee: Mapped["Employee"] = relationship(back_populates="advances")


class Penalty(Base):
    """ Jarimalar jadvali """
    __tablename__ = 'penalties'
    
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey('employees.id', ondelete="CASCADE"))
    amount: Mapped[float] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(String(255)) # Jarima sababi
    
    is_closed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    employee: Mapped["Employee"] = relationship(back_populates="penalties")


class SalaryHistory(Base):
    """ Oyliklar tarixi (Yopilgan oylar uchun arxiv) """
    __tablename__ = 'salary_history'
    
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey('employees.id', ondelete="CASCADE"))
    total_kpi: Mapped[float] = mapped_column(Float)
    total_advance: Mapped[float] = mapped_column(Float)
    total_penalty: Mapped[float] = mapped_column(Float)
    final_salary: Mapped[float] = mapped_column(Float)
    
    month: Mapped[str] = mapped_column(String(10)) # Format: "2026-02"
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    employee: Mapped["Employee"] = relationship(back_populates="salary_history")

# ==========================================
# 3️⃣ JADVALLARNI AVTOMATIK YARATISH
# ==========================================
async def init_db():
    """ Bot yonganda jadvallarni tekshiradi va yo'q bo'lsa yaratadi """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)