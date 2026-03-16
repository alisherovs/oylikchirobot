import os
from aiogram import Router, F, types
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select, desc

from database import async_session, Employee, KPI, Advance, Penalty, SalaryHistory

user_router = Router()
ADMIN_ID = int(os.getenv("ADMIN_ID", "8153822793"))

# ADMIN user routerga tushmasin
user_router.message.filter(F.from_user.id != ADMIN_ID)
user_router.callback_query.filter(F.from_user.id != ADMIN_ID)


class RegisterFSM(StatesGroup):
    full_name = State()
    phone = State()


def format_money(amount: float) -> str:
    return f"{amount:,.0f} so'm"


def get_user_main_kb():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📊 Joriy oy hisoboti", callback_data="current_month_stats")],
            [InlineKeyboardButton(text="🗂 Oyliklar tarixi", callback_data="salary_history")]
        ]
    )


@user_router.message(CommandStart())
async def user_start(message: types.Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id

    async with async_session() as session:
        employee = await session.scalar(
            select(Employee).where(Employee.id == user_id)
        )

        # 1) Bazada yo'q bo'lsa - registratsiya
        if not employee:
            await message.answer(
                "👋 <b>Assalomu alaykum! Ishchilar ro'yxatiga xush kelibsiz.</b>\n\n"
                "Iltimos, ro'yxatdan o'tish uchun to'liq ism-sharifingizni kiriting:",
                parse_mode="HTML"
            )
            await state.set_state(RegisterFSM.full_name)
            return

        # 2) Pending bo'lsa
        if employee.status == "pending":
            await message.answer(
                "⏳ <b>So'rovingiz qabul qilingan.</b>\n\n"
                "Rahbariyat tasdiqlashini kuting. Tasdiqlangach sizga xabar yuboriladi.",
                parse_mode="HTML"
            )
            return

        # 3) Fired bo'lsa
        if employee.status == "fired":
            await message.answer(
                "🚫 <b>Siz faol ishchilar ro'yxatida emassiz.</b>\n"
                "Savollar bo'lsa admin bilan bog'laning.",
                parse_mode="HTML"
            )
            return

        # 4) Approved bo'lsa
        await message.answer(
            f"Assalomu alaykum, <b>{employee.full_name}</b>! 👋\n\n"
            "Ishchi paneliga xush kelibsiz.",
            reply_markup=get_user_main_kb(),
            parse_mode="HTML"
        )


@user_router.message(RegisterFSM.full_name)
async def process_reg_name(message: types.Message, state: FSMContext):
    full_name = (message.text or "").strip()

    if len(full_name) < 5:
        return await message.answer("❌ Iltimos, to'liq ism-sharifni to'g'ri kiriting.")

    await state.update_data(full_name=full_name)
    await message.answer("📞 Endi telefon raqamingizni kiriting.\nMasalan: <code>+998901234567</code>", parse_mode="HTML")
    await state.set_state(RegisterFSM.phone)


@user_router.message(RegisterFSM.phone)
async def process_reg_phone(message: types.Message, state: FSMContext):
    phone = (message.text or "").strip()
    data = await state.get_data()
    user_id = message.from_user.id

    # oddiy tekshiruv
    if not phone.startswith("+998") or len(phone) < 13:
        return await message.answer("❌ Telefon raqamini to'g'ri kiriting.\nMasalan: <code>+998901234567</code>", parse_mode="HTML")

    async with async_session() as session:
        existing = await session.scalar(select(Employee).where(Employee.id == user_id))

        if existing:
            await state.clear()
            return await message.answer("ℹ️ Siz allaqachon ro'yxatdan o'tgansiz. /start ni bosing.")

        new_emp = Employee(
            id=user_id,
            full_name=data["full_name"],
            phone=phone,
            status="pending"
        )
        session.add(new_emp)
        await session.commit()

    await message.answer(
        "✅ <b>So'rovingiz adminga yuborildi!</b>\n\n"
        "Tasdiqlangach botdan to'liq foydalana olasiz.",
        parse_mode="HTML"
    )

    try:
        await message.bot.send_message(
            chat_id=ADMIN_ID,
            text=(
                f"🔔 <b>Yangi ishchi ro'yxatdan o'tdi!</b>\n\n"
                f"👤 Ismi: {data['full_name']}\n"
                f"📞 Tel: {phone}\n\n"
                f"Tasdiqlash uchun /admin panelga kiring."
            ),
            parse_mode="HTML"
        )
    except Exception:
        pass

    await state.clear()


@user_router.callback_query(F.data == "current_month_stats")
async def show_current_stats(call: types.CallbackQuery):
    user_id = call.from_user.id

    async with async_session() as session:
        emp = await session.scalar(select(Employee).where(Employee.id == user_id))
        if not emp:
            return await call.answer("Siz bazada topilmadingiz.", show_alert=True)

        if emp.status != "approved":
            return await call.answer("Sizga bu bo'limdan foydalanish ruxsat etilmagan.", show_alert=True)

        kpis = sum((
            await session.scalars(
                select(KPI.amount).where(
                    KPI.employee_id == user_id,
                    KPI.is_closed == False
                )
            )
        ).all())

        advances = sum((
            await session.scalars(
                select(Advance.amount).where(
                    Advance.employee_id == user_id,
                    Advance.is_closed == False
                )
            )
        ).all())

        penalties = sum((
            await session.scalars(
                select(Penalty.amount).where(
                    Penalty.employee_id == user_id,
                    Penalty.is_closed == False
                )
            )
        ).all())

        current_balance = emp.base_salary + kpis - advances - penalties
        salary_type_text = "Asosiy (FIX)" if emp.salary_type == "Fix" else "Faqat KPI"

        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Orqaga", callback_data="back_to_main")]
            ]
        )

        text = (
            f"📊 <b>JORIY OY HISOBOTINGIZ:</b>\n\n"
            f"📌 Oylik turi: <b>{salary_type_text}</b>\n"
            f"💵 Boshlang'ich/Fix oylik: <b>{format_money(emp.base_salary)}</b>\n"
            f"📈 Ishlangan KPI: <b>+{format_money(kpis)}</b>\n"
            f"💸 Olingan avanslar: <b>-{format_money(advances)}</b>\n"
            f"⚠️ Jarimalar: <b>-{format_money(penalties)}</b>\n"
            f"〰️〰️〰️〰️〰️〰️〰️〰️〰️〰️\n"
            f"💰 <b>Joriy qoldiq (Raschyot): {format_money(current_balance)}</b>\n\n"
            f"<i>Bu summa oy yopilgunga qadar o'zgarishi mumkin.</i>"
        )

        await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        await call.answer()


@user_router.callback_query(F.data == "salary_history")
async def show_salary_history(call: types.CallbackQuery):
    user_id = call.from_user.id

    async with async_session() as session:
        emp = await session.scalar(select(Employee).where(Employee.id == user_id))
        if not emp:
            return await call.answer("Siz bazada topilmadingiz.", show_alert=True)

        histories = (
            await session.scalars(
                select(SalaryHistory)
                .where(
                    SalaryHistory.employee_id == user_id,
                    SalaryHistory.is_closed == True
                )
                .order_by(desc(SalaryHistory.created_at))
                .limit(5)
            )
        ).all()

        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Orqaga", callback_data="back_to_main")]
            ]
        )

        if not histories:
            await call.message.edit_text(
                "🗂 <b>Sizda hali yopilgan oyliklar tarixi yo'q.</b>\n"
                "Oylik yopilgandan keyin bu yerda ko'rinadi.",
                reply_markup=kb,
                parse_mode="HTML"
            )
            return await call.answer()

        text = "🗂 <b>OXIRGI OYLIKLAR TARIXI:</b>\n\n"
        for record in histories:
            paid_text = "✅ To'langan" if getattr(record, "is_paid", False) else "⏳ To'lanmagan"

            text += (
                f"📅 <b>Oy: {record.month}</b>\n"
                f"📈 KPI: +{format_money(record.total_kpi)}\n"
                f"💸 Avans: -{format_money(record.total_advance)}\n"
                f"⚠️ Jarima: -{format_money(record.total_penalty)}\n"
                f"💰 <b>Yakuniy oylik: {format_money(record.final_salary)}</b>\n"
                f"📌 Holat: {paid_text}\n"
                f"〰️〰️〰️〰️〰️〰️〰️〰️〰️\n"
            )

        await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        await call.answer()


@user_router.callback_query(F.data == "back_to_main")
async def back_to_main_menu(call: types.CallbackQuery):
    user_id = call.from_user.id

    async with async_session() as session:
        emp = await session.scalar(select(Employee).where(Employee.id == user_id))
        if not emp:
            return await call.answer("Siz bazada topilmadingiz.", show_alert=True)

        await call.message.edit_text(
            f"Assalomu alaykum, <b>{emp.full_name}</b>! 👋\n\n"
            "Asosiy menyuga qaytdingiz.",
            reply_markup=get_user_main_kb(),
            parse_mode="HTML"
        )
        await call.answer()
