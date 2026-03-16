import os
import io
import logging
from datetime import datetime

import pandas as pd
from aiogram import Router, F, types
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
    BufferedInputFile,
)
from sqlalchemy import select, update

from database import async_session, Employee, KPI, Advance, Penalty, SalaryHistory

logger = logging.getLogger(__name__)

ADMIN_ID = int(os.getenv("ADMIN_ID", "1064992756"))

admin_router = Router()

# Faqat admin uchun
admin_router.message.filter(F.from_user.id == ADMIN_ID)
admin_router.callback_query.filter(F.from_user.id == ADMIN_ID)


# =========================
# FSM
# =========================
class ApproveFSM(StatesGroup):
    emp_id = State()
    salary_type = State()
    base_salary = State()


class ActionFSM(StatesGroup):
    action_type = State()
    employee_id = State()
    amount = State()
    description = State()


# =========================
# YORDAMCHI FUNKSIYALAR
# =========================
def get_current_month() -> str:
    return datetime.now().strftime("%Y-%m")


def fmt_money(value: float) -> str:
    return f"{value:,.0f} so'm"


async def get_admin_menu(session):
    pending_count = len(
        (
            await session.execute(
                select(Employee.id).where(Employee.status == "pending")
            )
        ).scalars().all()
    )
    req_text = f"📩 So'rovlar ({pending_count})" if pending_count > 0 else "📩 So'rovlar"

    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=req_text)],
            [KeyboardButton(text="📈 Mukofot pullari (Premiya)"), KeyboardButton(text="💸 Avans berish")],
            [KeyboardButton(text="⚠️ Jarima yozish"), KeyboardButton(text="📋 Ishchilar ma'lumoti")],
            [KeyboardButton(text="📥 Umumiy hisobot"), KeyboardButton(text="💵 Oylikni to'lash")],
            [KeyboardButton(text="📊 Oylik yopish")],
            [KeyboardButton(text="🔙 Bekor qilish")]
        ],
        resize_keyboard=True,
        is_persistent=True
    )


async def calculate_employee_balance(session, emp_id: int):
    emp = await session.get(Employee, emp_id)
    if not emp:
        return None

    kpis = sum((
        await session.scalars(
            select(KPI.amount).where(
                KPI.employee_id == emp_id,
                KPI.is_closed == False
            )
        )
    ).all())

    advances = sum((
        await session.scalars(
            select(Advance.amount).where(
                Advance.employee_id == emp_id,
                Advance.is_closed == False
            )
        )
    ).all())

    penalties = sum((
        await session.scalars(
            select(Penalty.amount).where(
                Penalty.employee_id == emp_id,
                Penalty.is_closed == False
            )
        )
    ).all())

    current_balance = emp.base_salary + kpis - advances - penalties

    return {
        "employee": emp,
        "kpis": kpis,
        "advances": advances,
        "penalties": penalties,
        "current_balance": current_balance
    }


async def get_or_create_salary_sheet_for_month(session, month: str):
    employees = (
        await session.execute(
            select(Employee).where(Employee.status == "approved")
        )
    ).scalars().all()

    created_count = 0

    for emp in employees:
        exists = await session.scalar(
            select(SalaryHistory).where(
                SalaryHistory.employee_id == emp.id,
                SalaryHistory.month == month
            )
        )
        if exists:
            continue

        calc = await calculate_employee_balance(session, emp.id)
        if not calc:
            continue

        session.add(
            SalaryHistory(
                employee_id=emp.id,
                total_kpi=calc["kpis"],
                total_advance=calc["advances"],
                total_penalty=calc["penalties"],
                final_salary=calc["current_balance"],
                month=month,
                is_paid=False,
                is_closed=False
            )
        )
        created_count += 1

    if created_count > 0:
        await session.commit()

    return created_count


async def get_unpaid_salary_rows(session, month: str):
    rows = await session.execute(
        select(SalaryHistory, Employee)
        .join(Employee, Employee.id == SalaryHistory.employee_id)
        .where(
            SalaryHistory.month == month,
            SalaryHistory.is_paid == False,
            Employee.status == "approved"
        )
        .order_by(Employee.full_name)
    )
    return rows.all()


# =========================
# START / CANCEL
# =========================
@admin_router.message(Command("cancel"))
@admin_router.message(F.text == "🔙 Bekor qilish")
async def cancel_handler(message: types.Message, state: FSMContext):
    await state.clear()
    async with async_session() as session:
        kb = await get_admin_menu(session)
    await message.answer(
        "🚫 Barcha amallar bekor qilindi. Asosiy menyudasiz.",
        reply_markup=kb
    )


@admin_router.message(CommandStart())
@admin_router.message(Command("admin"))
async def admin_start(message: types.Message, state: FSMContext):
    await state.clear()
    async with async_session() as session:
        kb = await get_admin_menu(session)
    await message.answer(
        "👑 <b>Admin paneliga xush kelibsiz!</b>\n\nQuyidagi menyudan foydalaning:",
        reply_markup=kb,
        parse_mode="HTML"
    )


# =========================
# 1) SO'ROVLARNI TASDIQLASH
# =========================
@admin_router.message(F.text.startswith("📩 So'rovlar"))
async def view_requests(message: types.Message, state: FSMContext):
    await state.clear()
    async with async_session() as session:
        pendings = (
            await session.execute(
                select(Employee).where(Employee.status == "pending")
            )
        ).scalars().all()

    if not pendings:
        return await message.answer("Yangi so'rovlar yo'q.")

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"✅ {emp.full_name}", callback_data=f"approve_{emp.id}")]
            for emp in pendings
        ]
    )
    await message.answer("Tasdiqlash uchun ishchini tanlang:", reply_markup=kb)


@admin_router.callback_query(F.data.startswith("approve_"))
async def approve_step1(call: types.CallbackQuery, state: FSMContext):
    emp_id = int(call.data.split("_")[1])
    await state.update_data(emp_id=emp_id)

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Belgilangan aniq oylik (Oklad)", callback_data="type_Fix")],
            [InlineKeyboardButton(text="Faqat qilingan ishga qarab (Foiz)", callback_data="type_KPI")]
        ]
    )
    await call.message.edit_text(
        "Ushbu xodim qanday oylik tizimida ishlaydi?",
        reply_markup=kb
    )
    await state.set_state(ApproveFSM.salary_type)
    await call.answer()


@admin_router.callback_query(ApproveFSM.salary_type, F.data.startswith("type_"))
async def approve_step2(call: types.CallbackQuery, state: FSMContext):
    salary_type = call.data.split("_")[1]
    await state.update_data(salary_type=salary_type)

    text = (
        "💰 Belgilangan oylik summasini kiriting:"
        if salary_type == "Fix"
        else "💰 Boshlang'ich bazaviy oylikni kiriting (faqat foiz bo'lsa 0 yozing):"
    )

    await call.message.edit_text(text)
    await state.set_state(ApproveFSM.base_salary)
    await call.answer()


@admin_router.message(ApproveFSM.base_salary)
async def approve_step3(message: types.Message, state: FSMContext):
    text = (message.text or "").replace(" ", "")
    if not text.isdigit():
        return await message.answer("❌ Faqat raqam kiriting.")

    data = await state.get_data()

    async with async_session() as session:
        await session.execute(
            update(Employee)
            .where(Employee.id == data["emp_id"])
            .values(
                status="approved",
                salary_type=data["salary_type"],
                base_salary=float(text)
            )
        )
        await session.commit()
        kb = await get_admin_menu(session)

    await message.answer(
        "✅ <b>Xodim tasdiqlandi!</b>",
        reply_markup=kb,
        parse_mode="HTML"
    )

    try:
        await message.bot.send_message(
            chat_id=data["emp_id"],
            text="🎉 <b>Tabriklaymiz!</b> So'rovingiz tasdiqlandi. /start ni bosing.",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.warning("Userga approve xabar yuborilmadi: %s", e)

    await state.clear()


# =========================
# 2) PREMIA / AVANS / JARIMA
# =========================
@admin_router.message(F.text.in_(["📈 Mukofot pullari (Premiya)", "💸 Avans berish", "⚠️ Jarima yozish"]))
async def select_action_emp(message: types.Message, state: FSMContext):
    await state.clear()

    if "Mukofot" in message.text:
        action_type = "kpi"
    elif "Avans" in message.text:
        action_type = "advance"
    else:
        action_type = "penalty"

    await state.update_data(action_type=action_type)

    async with async_session() as session:
        employees = (
            await session.execute(
                select(Employee).where(Employee.status == "approved")
            )
        ).scalars().all()

    if not employees:
        return await message.answer("❌ Tasdiqlangan ishchilar yo'q.")

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=emp.full_name, callback_data=f"emp_{emp.id}")]
            for emp in employees
        ]
    )
    await message.answer(
        f"👤 {message.text} uchun ishchini tanlang:",
        reply_markup=kb
    )
    await state.set_state(ActionFSM.employee_id)


@admin_router.callback_query(ActionFSM.employee_id, F.data.startswith("emp_"))
async def process_action_amount(call: types.CallbackQuery, state: FSMContext):
    employee_id = int(call.data.split("_")[1])
    await state.update_data(employee_id=employee_id)
    await call.message.edit_text("💰 Summani kiriting (faqat raqam):")
    await state.set_state(ActionFSM.amount)
    await call.answer()


@admin_router.message(ActionFSM.amount)
async def process_action_desc(message: types.Message, state: FSMContext):
    text = (message.text or "").replace(" ", "")
    if not text.isdigit():
        return await message.answer("❌ Summani raqamda kiriting.")

    data = await state.get_data()
    await state.update_data(amount=float(text))

    if data["action_type"] == "kpi":
        q = "📈 Premiya nima uchun yozilmoqda?"
    elif data["action_type"] == "advance":
        q = "💸 Avans nima maqsadda berilyapti?"
    else:
        q = "⚠️ Jarima sababi nima?"

    await message.answer(q)
    await state.set_state(ActionFSM.description)


@admin_router.message(ActionFSM.description)
async def save_action(message: types.Message, state: FSMContext):
    data = await state.get_data()
    emp_id = data["employee_id"]
    amount = data["amount"]
    action_type = data["action_type"]

    async with async_session() as session:
        emp = await session.get(Employee, emp_id)
        if not emp or emp.status != "approved":
            await state.clear()
            return await message.answer("❌ Ishchi topilmadi yoki faol emas.")

        if action_type == "kpi":
            session.add(KPI(employee_id=emp_id, amount=amount, description=message.text))
            text_type = "qo'shildi 📈"
        elif action_type == "advance":
            session.add(Advance(employee_id=emp_id, amount=amount, description=message.text))
            text_type = "avans olindi 💸"
        else:
            session.add(Penalty(employee_id=emp_id, amount=amount, reason=message.text))
            text_type = "jarima yozildi ⚠️"

        await session.commit()

        calc = await calculate_employee_balance(session, emp_id)
        kb = await get_admin_menu(session)

    await message.answer(
        "✅ <b>Muvaffaqiyatli saqlandi!</b>",
        reply_markup=kb,
        parse_mode="HTML"
    )

    try:
        user_msg = (
            f"🔔 <b>Hisobingizda o'zgarish!</b>\n\n"
            f"<b>{fmt_money(amount)}</b> {text_type}\n"
            f"📝 Izoh: <i>{message.text}</i>\n"
            f"💰 <b>Qoldiq: {fmt_money(calc['current_balance'])}</b>"
        )
        await message.bot.send_message(chat_id=emp_id, text=user_msg, parse_mode="HTML")
    except Exception as e:
        logger.warning("Userga action xabar yuborilmadi: %s", e)

    await state.clear()


# =========================
# 3) ISHCHILAR MA'LUMOTI
# =========================
@admin_router.message(F.text == "📋 Ishchilar ma'lumoti")
async def show_employee_list(message: types.Message, state: FSMContext):
    await state.clear()

    async with async_session() as session:
        employees = (
            await session.execute(
                select(Employee).where(Employee.status == "approved")
            )
        ).scalars().all()

    if not employees:
        return await message.answer("❌ Hozircha ishchilar yo'q.")

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"👤 {emp.full_name}", callback_data=f"empinfo_{emp.id}")]
            for emp in employees
        ]
    )
    await message.answer("📋 Profilini ko'rish uchun ishchini tanlang:", reply_markup=kb)


@admin_router.callback_query(F.data.startswith("empinfo_"))
async def show_employee_profile(call: types.CallbackQuery):
    emp_id = int(call.data.split("_")[1])

    async with async_session() as session:
        calc = await calculate_employee_balance(session, emp_id)
        if not calc:
            return await call.answer("Ishchi topilmadi.", show_alert=True)

        emp = calc["employee"]

    s_type_text = "Belgilangan oylik (Oklad)" if emp.salary_type == "Fix" else "Qilingan ishga qarab (Foiz)"

    text = (
        f"👤 <b>{emp.full_name} ma'lumotlari:</b>\n"
        f"📞 Tel: {emp.phone}\n"
        f"💼 Oylik turi: {s_type_text}\n"
        f"💵 Asosiy maosh: {fmt_money(emp.base_salary)}\n\n"
        f"📈 Berilgan premiyalar: +{fmt_money(calc['kpis'])}\n"
        f"💸 Olingan avanslar: -{fmt_money(calc['advances'])}\n"
        f"⚠️ Jarimalar: -{fmt_money(calc['penalties'])}\n"
        f"〰️〰️〰️〰️〰️〰️〰️〰️〰️\n"
        f"💰 <b>Qo'lga tegadigan joriy qoldiq: {fmt_money(calc['current_balance'])}</b>"
    )

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📥 Shaxsiy hisobotni yuklash", callback_data=f"empexcel_{emp_id}")],
            [InlineKeyboardButton(text="🚫 Ishchini chetlatish", callback_data=f"fire_{emp_id}")]
        ]
    )

    await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await call.answer()


# =========================
# 4) ISHCHINI CHETLATISH
# =========================
@admin_router.callback_query(F.data.startswith("fire_"))
async def fire_prompt(call: types.CallbackQuery):
    emp_id = int(call.data.split("_")[1])
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Ha, chetlatish", callback_data=f"fireconf_{emp_id}")],
            [InlineKeyboardButton(text="❌ Yo'q, bekor qilish", callback_data=f"empinfo_{emp_id}")]
        ]
    )
    await call.message.edit_text(
        "⚠️ <b>Haqiqatan ham bu ishchini chetlatmoqchimisiz?</b>\n"
        "<i>Tarixi saqlanadi, lekin faol ro'yxatdan chiqadi.</i>",
        reply_markup=kb,
        parse_mode="HTML"
    )
    await call.answer()


@admin_router.callback_query(F.data.startswith("fireconf_"))
async def fire_confirm(call: types.CallbackQuery):
    emp_id = int(call.data.split("_")[1])

    async with async_session() as session:
        emp = await session.get(Employee, emp_id)
        if not emp:
            return await call.answer("Ishchi topilmadi.", show_alert=True)

        emp.status = "fired"
        await session.commit()

    await call.message.edit_text("✅ Xodim chetlatildi va faol ro'yxatdan chiqarildi.")
    await call.answer("Bajarildi")


# =========================
# 5) EXCEL HISOBOT
# =========================
@admin_router.message(F.text == "📥 Umumiy hisobot")
async def export_excel_all(message: types.Message):
    await message.answer("⏳ Hisobot tayyorlanmoqda...")
    await export_excel_logic(message, None)


@admin_router.callback_query(F.data.startswith("empexcel_"))
async def export_excel_single(call: types.CallbackQuery):
    emp_id = int(call.data.split("_")[1])
    await call.message.answer("⏳ Shaxsiy hisobot tayyorlanmoqda...")
    await export_excel_logic(call.message, emp_id)
    await call.answer()


async def export_excel_logic(message: types.Message, single_emp_id: int | None = None):
    report_data = []

    async with async_session() as session:
        query = select(Employee).where(Employee.status == "approved")
        if single_emp_id:
            query = query.where(Employee.id == single_emp_id)

        employees = (await session.execute(query)).scalars().all()

        if not employees:
            return await message.answer("❌ Hisobot tayyorlash uchun ma'lumot yo'q.")

        for emp in employees:
            calc = await calculate_employee_balance(session, emp.id)
            if not calc:
                continue

            s_type_text = "Oklad" if emp.salary_type == "Fix" else "Foiz"

            report_data.append({
                "F.I.SH": emp.full_name,
                "Telefon raqami": emp.phone,
                "Oylik turi": s_type_text,
                "Asosiy maosh (so'm)": emp.base_salary,
                "Premiya (so'm)": calc["kpis"],
                "Avans (so'm)": calc["advances"],
                "Jarima (so'm)": calc["penalties"],
                "Joriy qoldiq (so'm)": calc["current_balance"],
            })

    df = pd.DataFrame(report_data)
    output = io.BytesIO()

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Hisobot")
        ws = writer.sheets["Hisobot"]

        for column_cells in ws.columns:
            max_length = max(len(str(cell.value)) if cell.value is not None else 0 for cell in column_cells)
            ws.column_dimensions[column_cells[0].column_letter].width = max_length + 2

    output.seek(0)

    file_name = f"Shaxsiy_{single_emp_id}.xlsx" if single_emp_id else "Umumiy_Hisobot.xlsx"
    await message.answer_document(
        document=BufferedInputFile(output.read(), filename=file_name)
    )


# =========================
# 6) OYLIKNI TO'LASH
# =========================
@admin_router.message(F.text == "💵 Oylikni to'lash")
async def show_unpaid_salaries(message: types.Message, state: FSMContext):
    await state.clear()
    current_month = get_current_month()

    async with async_session() as session:
        await get_or_create_salary_sheet_for_month(session, current_month)
        unpaid_rows = await get_unpaid_salary_rows(session, current_month)

        if not unpaid_rows:
            kb = await get_admin_menu(session)
            return await message.answer(
                f"✅ {current_month} uchun to'lanmagan oyliklar yo'q.",
                reply_markup=kb
            )

        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=f"💵 {emp.full_name} — {fmt_money(salary_row.final_salary)}",
                        callback_data=f"pay_salary_{salary_row.id}"
                    )
                ]
                for salary_row, emp in unpaid_rows
            ]
        )

    await message.answer(
        f"📋 {current_month} uchun to'lanmagan oyliklar ro'yxati:\n\n"
        f"To'langan ishchini tanlang:",
        reply_markup=kb
    )


@admin_router.callback_query(F.data.startswith("pay_salary_"))
async def mark_salary_as_paid(call: types.CallbackQuery):
    salary_id = int(call.data.split("_")[2])

    async with async_session() as session:
        salary_row = await session.get(SalaryHistory, salary_id)
        if not salary_row:
            return await call.answer("❌ Oylik yozuvi topilmadi.", show_alert=True)

        if salary_row.is_paid:
            return await call.answer("ℹ️ Bu oylik oldin to'langan.", show_alert=True)

        emp = await session.get(Employee, salary_row.employee_id)
        if not emp:
            return await call.answer("❌ Ishchi topilmadi.", show_alert=True)

        salary_row.is_paid = True
        salary_row.paid_at = datetime.now()
        await session.commit()

        await call.message.edit_text(
            f"✅ <b>{emp.full_name}</b> uchun oylik to'landi deb belgilandi.\n"
            f"💵 Summa: <b>{fmt_money(salary_row.final_salary)}</b>\n"
            f"📅 Oy: <b>{salary_row.month}</b>",
            parse_mode="HTML"
        )

        try:
            await call.bot.send_message(
                chat_id=emp.id,
                text=(
                    f"💵 <b>Oyligingiz to'landi</b>\n\n"
                    f"📅 Oy: <b>{salary_row.month}</b>\n"
                    f"💰 Summa: <b>{fmt_money(salary_row.final_salary)}</b>"
                ),
                parse_mode="HTML"
            )
        except Exception as e:
            logger.warning("Userga oylik to'landi xabari yuborilmadi: %s", e)

    await call.answer("To'landi deb belgilandi ✅")


# =========================
# 7) OYLIK YOPISH
# =========================
@admin_router.message(F.text == "📊 Oylik yopish")
async def close_month_handler(message: types.Message, state: FSMContext):
    await state.clear()
    current_month = get_current_month()

    async with async_session() as session:
        employees = (
            await session.execute(
                select(Employee).where(Employee.status == "approved")
            )
        ).scalars().all()

        if not employees:
            kb = await get_admin_menu(session)
            return await message.answer("❌ Tasdiqlangan ishchilar yo'q.", reply_markup=kb)

        created_count = await get_or_create_salary_sheet_for_month(session, current_month)

        # Agar hozirgina vedomost yaratilgan bo'lsa, admin avval to'lovlarni bajarishi kerak
        if created_count > 0:
            kb = await get_admin_menu(session)
            return await message.answer(
                f"📋 <b>{current_month}</b> uchun oylik vedomosti yaratildi.\n\n"
                f"Endi avval <b>\"💵 Oylikni to'lash\"</b> bo'limiga kirib, "
                f"ishchilarning oyligini birma-bir to'langan deb belgilang.\n\n"
                f"<b>Hamma ishchi oyligini olmaguncha oy yopilmaydi.</b>",
                reply_markup=kb,
                parse_mode="HTML"
            )

        unpaid_rows = await get_unpaid_salary_rows(session, current_month)

        if unpaid_rows:
            names = "\n".join(
                f"• {emp.full_name} — {fmt_money(salary_row.final_salary)}"
                for salary_row, emp in unpaid_rows[:20]
            )
            more = f"\n... va yana {len(unpaid_rows) - 20} ta ishchi" if len(unpaid_rows) > 20 else ""

            kb = await get_admin_menu(session)
            return await message.answer(
                f"❌ <b>Oyni yopib bo'lmaydi!</b>\n\n"
                f"Quyidagi ishchilarga hali oylik to'lanmagan:\n\n"
                f"{names}{more}\n\n"
                f"Avval <b>\"💵 Oylikni to'lash\"</b> bo'limidan barchasini to'langan deb belgilang.",
                reply_markup=kb,
                parse_mode="HTML"
            )

        # Hamma oylik to'langan bo'lsa, yopamiz
        for emp in employees:
            await session.execute(
                update(KPI)
                .where(KPI.employee_id == emp.id, KPI.is_closed == False)
                .values(is_closed=True)
            )

            await session.execute(
                update(Advance)
                .where(Advance.employee_id == emp.id, Advance.is_closed == False)
                .values(is_closed=True)
            )

            await session.execute(
                update(Penalty)
                .where(Penalty.employee_id == emp.id, Penalty.is_closed == False)
                .values(is_closed=True)
            )

        await session.execute(
            update(SalaryHistory)
            .where(
                SalaryHistory.month == current_month,
                SalaryHistory.is_paid == True,
                SalaryHistory.is_closed == False
            )
            .values(
                is_closed=True,
                closed_at=datetime.now()
            )
        )

        await session.commit()
        kb = await get_admin_menu(session)

    await message.answer(
        f"✅ <b>{current_month} oyi muvaffaqiyatli yopildi.</b>\n\n"
        f"Barcha ishchilarning oyligi to'langan va oy yakunlandi.",
        reply_markup=kb,
        parse_mode="HTML"
    )
