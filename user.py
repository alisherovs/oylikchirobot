import os
from aiogram import Router, F, types
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select, desc

# Ma'lumotlar bazasi modellarini import qilamiz
from database import async_session, Employee, KPI, Advance, Penalty, SalaryHistory

user_router = Router()
ADMIN_ID = int(os.getenv("ADMIN_ID", "123456789"))

# ==========================================
# 🧠 FSM HOLATLARI (Ro'yxatdan o'tish uchun)
# ==========================================
class RegisterFSM(StatesGroup):
    full_name = State()
    phone = State()

# ==========================================
# 1️⃣ BOTGA KIRISH VA ASOSIY MENYU
# ==========================================
@user_router.message(CommandStart())
async def user_start(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    
    async with async_session() as session:
        result = await session.execute(select(Employee).where(Employee.id == user_id))
        employee = result.scalar_one_or_none()
        
        # 1-Holat: Umuman bazada yo'q (Yangi ishchi)
        if not employee:
            await message.answer(
                "👋 <b>Assalomu alaykum! Ishchilar ro'yxatiga xush kelibsiz.</b>\n\n"
                "Iltimos, ro'yxatdan o'tish uchun to'liq ism-sharifingizni (F.I.SH) kiriting:",
                parse_mode="HTML"
            )
            return await state.set_state(RegisterFSM.full_name)
            
        # 2-Holat: Ro'yxatdan o'tgan, lekin admin hali tasdiqlamagan
        if employee.status == "pending":
            return await message.answer(
                "⏳ <b>So'rovingiz qabul qilingan!</b>\n\n"
                "Rahbariyat tasdiqlashini kuting. Tasdiqlangach, sizga xabar yuboramiz.",
                parse_mode="HTML"
            )

        # 3-Holat: Tasdiqlangan va bemalol ishlata oladi
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📊 Joriy oy hisoboti", callback_data="current_month_stats")],
            [InlineKeyboardButton(text="🗂 Oyliklar tarixi", callback_data="salary_history")]
        ])
        
        await message.answer(
            f"Assalomu alaykum, <b>{employee.full_name}</b>! 👋\n\n"
            f"Ishchi paneliga xush kelibsiz. Nima quramiz?", 
            reply_markup=kb, 
            parse_mode="HTML"
        )

# ==========================================
# 2️⃣ RO'YXATDAN O'TISH JARAYONI
# ==========================================
@user_router.message(RegisterFSM.full_name)
async def process_reg_name(message: types.Message, state: FSMContext):
    await state.update_data(full_name=message.text)
    await message.answer("📞 Endi o'zingizning telefon raqamingizni kiriting (Masalan: +998901234567):")
    await state.set_state(RegisterFSM.phone)

@user_router.message(RegisterFSM.phone)
async def process_reg_phone(message: types.Message, state: FSMContext):
    data = await state.get_data()
    user_id = message.from_user.id
    
    async with async_session() as session:
        new_emp = Employee(
            id=user_id, 
            full_name=data['full_name'], 
            phone=message.text, 
            status="pending" # Kutish holatida bazaga tushadi
        )
        session.add(new_emp)
        await session.commit()
        
    await message.answer("✅ <b>So'rov adminga yuborildi!</b>\n\nTasdiqlangach, botdan to'liq foydalana olasiz.", parse_mode="HTML")
    
    # Adminga ogohlantirish yuborish
    try:
        await message.bot.send_message(
            chat_id=ADMIN_ID, 
            text=f"🔔 <b>Yangi ishchi ro'yxatdan o'tdi!</b>\n\n"
                 f"👤 Ismi: {data['full_name']}\n"
                 f"📞 Tel: {message.text}\n\n"
                 f"Tasdiqlash uchun /admin panelga kiring.",
            parse_mode="HTML"
        )
    except Exception:
        pass # Agar admin botni bloklagan bo'lsa xato bermaydi
    
    await state.clear()

# ==========================================
# 3️⃣ JORIY OY HISOBOTI (REAL VAQTDA)
# ==========================================
@user_router.callback_query(F.data == "current_month_stats")
async def show_current_stats(call: types.CallbackQuery):
    user_id = call.from_user.id
    
    async with async_session() as session:
        emp = (await session.execute(select(Employee).where(Employee.id == user_id))).scalar_one_or_none()
        if not emp:
            return await call.answer("Xatolik: Siz bazadan topilmadingiz.", show_alert=True)

        kpis = sum((await session.scalars(select(KPI.amount).where(KPI.employee_id == user_id, KPI.is_closed == False))).all())
        advances = sum((await session.scalars(select(Advance.amount).where(Advance.employee_id == user_id, Advance.is_closed == False))).all())
        penalties = sum((await session.scalars(select(Penalty.amount).where(Penalty.employee_id == user_id, Penalty.is_closed == False))).all())

        current_balance = emp.base_salary + kpis - advances - penalties
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Orqaga", callback_data="back_to_main")]
        ])
        
        # Oylik turiga qarab matnni chiroyli qilish
        salary_type_text = f"Asosiy (FIX)" if emp.salary_type == "Fix" else "Faqat KPI"
        
        text = (
            f"📊 <b>JORIY OY UCHUN HISOBOTINGIZ:</b>\n\n"
            f"📌 Oylik turi: <b>{salary_type_text}</b>\n"
            f"💵 Boshlang'ich/Fix oylik: <b>{emp.base_salary:,.0f} so'm</b>\n"
            f"📈 Ishlangan KPI: <b>+{kpis:,.0f} so'm</b>\n"
            f"💸 Olingan avanslar: <b>-{advances:,.0f} so'm</b>\n"
            f"⚠️ Jarimalar: <b>-{penalties:,.0f} so'm</b>\n"
            f"〰️〰️〰️〰️〰️〰️〰️〰️〰️〰️〰️〰️\n"
            f"💰 <b>Joriy qoldiq (Raschyot): {current_balance:,.0f} so'm</b>\n\n"
            f"<i>💡 Eslatma: Ushbu qoldiq oylik yopilgunga qadar o'zgarishi mumkin.</i>"
        )
        
        await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        await call.answer()

# ==========================================
# 4️⃣ OYLIKLAR TARIXI (OLDINGI OYLAR)
# ==========================================
@user_router.callback_query(F.data == "salary_history")
async def show_salary_history(call: types.CallbackQuery):
    user_id = call.from_user.id
    
    async with async_session() as session:
        history_query = select(SalaryHistory).where(SalaryHistory.employee_id == user_id).order_by(desc(SalaryHistory.created_at)).limit(5)
        histories = (await session.scalars(history_query)).all()
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Orqaga", callback_data="back_to_main")]
        ])
        
        if not histories:
            await call.message.edit_text("🗂 <b>Sizda hali oylik maoshlar tarixi yo'q.</b>\nOylik yopilgandan so'ng bu yerda paydo bo'ladi.", reply_markup=kb, parse_mode="HTML")
            return await call.answer()

        text = "🗂 <b>OXIRGI OYLIKLAR TARIXI:</b>\n\n"
        for record in histories:
            text += (
                f"📅 <b>Oy: {record.month}</b>\n"
                f"📈 KPI: +{record.total_kpi:,.0f} so'm\n"
                f"💸 Avans: -{record.total_advance:,.0f} so'm\n"
                f"⚠️ Jarima: -{record.total_penalty:,.0f} so'm\n"
                f"✅ <b>Qo'lga tekkan: {record.final_salary:,.0f} so'm</b>\n"
                f"〰️〰️〰️〰️〰️〰️〰️〰️〰️\n"
            )
            
        await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        await call.answer()

# ==========================================
# 5️⃣ ORQAGA QAYTISH
# ==========================================
@user_router.callback_query(F.data == "back_to_main")
async def back_to_main_menu(call: types.CallbackQuery):
    user_id = call.from_user.id
    
    async with async_session() as session:
        emp = (await session.execute(select(Employee).where(Employee.id == user_id))).scalar_one_or_none()
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📊 Joriy oy hisoboti", callback_data="current_month_stats")],
            [InlineKeyboardButton(text="🗂 Oyliklar tarixi", callback_data="salary_history")]
        ])
        
        await call.message.edit_text(
            f"Assalomu alaykum, <b>{emp.full_name}</b>! 👋\n\n"
            f"Asosiy menyuga qaytdingiz. Nima quramiz?", 
            reply_markup=kb, 
            parse_mode="HTML"
        )
        await call.answer()