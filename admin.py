import os
import io
from datetime import datetime
import pandas as pd

from aiogram import Router, F, types
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from sqlalchemy import select, update
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton, 
    ReplyKeyboardMarkup, KeyboardButton, BufferedInputFile
)

# Ma'lumotlar bazasidan modellar
from database import async_session, Employee, KPI, Advance, Penalty, SalaryHistory

ADMIN_ID = int(os.getenv("ADMIN_ID", "7044905076"))

admin_router = Router()

# ==========================================
# 🔒 XAVFSIZLIK FILTRI
# ==========================================
admin_router.message.filter(F.from_user.id == ADMIN_ID)
admin_router.callback_query.filter(F.from_user.id == ADMIN_ID)

# ==========================================
# 🧠 FSM HOLATLARI
# ==========================================
class ApproveFSM(StatesGroup):
    emp_id = State()
    salary_type = State()
    base_salary = State()

class ActionFSM(StatesGroup):
    action_type = State()
    employee_id = State()
    amount = State()
    description = State()

# ==========================================
# 🎛 ASOSIY MENYU (PASTKI TUGMALAR)
# ==========================================
async def get_admin_menu(session):
    pending_count = len((await session.execute(select(Employee.id).where(Employee.status == "pending"))).scalars().all())
    req_text = f"📩 So'rovlar ({pending_count})" if pending_count > 0 else "📩 So'rovlar"
    
    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=req_text)],
            [KeyboardButton(text="📈 Mukofot pullari (Premiya)"), KeyboardButton(text="💸 Avans berish")],
            [KeyboardButton(text="⚠️ Jarima yozish"), KeyboardButton(text="📋 Ishchilar ma'lumoti")],
            [KeyboardButton(text="📥 Umumiy hisobot"), KeyboardButton(text="📊 Oylik yopish")],
            [KeyboardButton(text="🔙 Bekor qilish")]
        ],
        resize_keyboard=True,
        is_persistent=True
    )
    return kb

@admin_router.message(Command("cancel"))
@admin_router.message(F.text == "🔙 Bekor qilish")
async def cancel_handler(message: types.Message, state: FSMContext):
    await state.clear()
    async with async_session() as session:
        kb = await get_admin_menu(session)
    await message.answer("🚫 Barcha amallar bekor qilindi. Asosiy menyudasiz.", reply_markup=kb)

@admin_router.message(CommandStart())
@admin_router.message(Command("admin"))
async def admin_start(message: types.Message, state: FSMContext):
    await state.clear()
    async with async_session() as session:
        kb = await get_admin_menu(session)
    await message.answer("👑 <b>Admin paneliga xush kelibsiz!</b>\n\nQuyidagi menyudan foydalaning:", reply_markup=kb, parse_mode="HTML")

# ==========================================
# 1️⃣ SO'ROVLARNI TASDIQLASH
# ==========================================
@admin_router.message(F.text.startswith("📩 So'rovlar"))
async def view_requests(message: types.Message, state: FSMContext):
    await state.clear()
    async with async_session() as session:
        pendings = (await session.execute(select(Employee).where(Employee.status == "pending"))).scalars().all()
        
    if not pendings:
        return await message.answer("Yangi so'rovlar yo'q!")
        
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"✅ {emp.full_name}", callback_data=f"approve_{emp.id}")] for emp in pendings
    ])
    await message.answer("Tasdiqlash uchun ishchini tanlang:", reply_markup=kb)

@admin_router.callback_query(F.data.startswith("approve_"))
async def approve_step1(call: types.CallbackQuery, state: FSMContext):
    await state.update_data(emp_id=int(call.data.split("_")[1]))
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Belgilangan aniq oylik (Oklad)", callback_data="type_Fix")],
        [InlineKeyboardButton(text="Faqat qilingan ishga qarab (Foiz)", callback_data="type_KPI")]
    ])
    await call.message.edit_text("Ushbu xodim qanday oylik tizimida ishlaydi?", reply_markup=kb)
    await state.set_state(ApproveFSM.salary_type)

@admin_router.callback_query(ApproveFSM.salary_type)
async def approve_step2(call: types.CallbackQuery, state: FSMContext):
    s_type = call.data.split("_")[1]
    await state.update_data(salary_type=s_type)
    text = "💰 Belgilangan oylik summasini kiriting:" if s_type == "Fix" else "💰 Boshlang'ich bazaviy oylikni kiriting (Agar faqat foizga ishlasa 0 deb yozing):"
    await call.message.edit_text(text)
    await state.set_state(ApproveFSM.base_salary)

@admin_router.message(ApproveFSM.base_salary)
async def approve_step3(message: types.Message, state: FSMContext):
    if not message.text.isdigit(): return await message.answer("❌ Faqat raqamlarda kiriting:")
    data = await state.get_data()
    async with async_session() as session:
        await session.execute(update(Employee).where(Employee.id == data['emp_id']).values(
            status="approved", salary_type=data['salary_type'], base_salary=float(message.text)
        ))
        await session.commit()
        kb = await get_admin_menu(session)
    await message.answer("✅ <b>Xodim tasdiqlandi!</b>", reply_markup=kb, parse_mode="HTML")
    try:
        await message.bot.send_message(chat_id=data['emp_id'], text="🎉 <b>Tabriklaymiz!</b> So'rovingiz tasdiqlandi. /start ni bosing.", parse_mode="HTML")
    except: pass
    await state.clear()

# ==========================================
# 2️⃣ AMALLAR: PREMIYA, AVANS, JARIMA
# ==========================================
@admin_router.message(F.text.in_(["📈 Mukofot pullari (Premiya)", "💸 Avans berish", "⚠️ Jarima yozish"]))
async def select_action_emp(message: types.Message, state: FSMContext):
    await state.clear()
    action_type = "kpi" if "Mukofot" in message.text else "advance" if "Avans" in message.text else "penalty"
    await state.update_data(action_type=action_type)
    
    async with async_session() as session:
        employees = (await session.execute(select(Employee).where(Employee.status == "approved"))).scalars().all()
    if not employees: return await message.answer("❌ Tasdiqlangan ishchilar yo'q.")
        
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=emp.full_name, callback_data=f"emp_{emp.id}")] for emp in employees])
    await message.answer(f"👤 {message.text} uchun ishchini tanlang:", reply_markup=kb)
    await state.set_state(ActionFSM.employee_id)

@admin_router.callback_query(ActionFSM.employee_id, F.data.startswith("emp_"))
async def process_action_amount(call: types.CallbackQuery, state: FSMContext):
    await state.update_data(employee_id=int(call.data.split("_")[1]))
    await call.message.edit_text("💰 Summani kiriting (Faqat raqam):")
    await state.set_state(ActionFSM.amount)

@admin_router.message(ActionFSM.amount)
async def process_action_desc(message: types.Message, state: FSMContext):
    if not message.text.isdigit(): return await message.answer("❌ Summani raqamda kiriting!")
    data = await state.get_data()
    await state.update_data(amount=float(message.text))
    
    q = "📈 Premiya nima uchun yozilmoqda?" if data['action_type'] == "kpi" else "💸 Avans nima maqsadda berilyapti?" if data['action_type'] == "advance" else "⚠️ Jarima sababi nima?"
    await message.answer(q)
    await state.set_state(ActionFSM.description)

@admin_router.message(ActionFSM.description)
async def save_action(message: types.Message, state: FSMContext):
    data = await state.get_data()
    emp_id, amount, action_type = data['employee_id'], data['amount'], data['action_type']
    
    async with async_session() as session:
        emp = await session.get(Employee, emp_id)
        if action_type == "kpi":
            session.add(KPI(employee_id=emp_id, amount=amount, description=message.text))
            text_type = "qo'shildi 📈"
        elif action_type == "advance":
            session.add(Advance(employee_id=emp_id, amount=amount, description=message.text))
            text_type = "avans olindi 💸"
        else:
            session.add(Penalty(employee_id=emp_id, amount=amount, reason=message.text))
            text_type = "jarima yozildi ⚠️"
        
        # MANA SHU QATOR TUSHIB QOLGAN EDI (BAZAGA SAQLASH)
        await session.commit() 
        
        kpis = sum((await session.scalars(select(KPI.amount).where(KPI.employee_id == emp_id, KPI.is_closed == False))).all())
        advances = sum((await session.scalars(select(Advance.amount).where(Advance.employee_id == emp_id, Advance.is_closed == False))).all())
        penalties = sum((await session.scalars(select(Penalty.amount).where(Penalty.employee_id == emp_id, Penalty.is_closed == False))).all())
        current_balance = emp.base_salary + kpis - advances - penalties
        kb = await get_admin_menu(session)
        
    await message.answer("✅ <b>Muvaffaqiyatli saqlandi!</b>", reply_markup=kb, parse_mode="HTML")
    try:
        user_msg = f"🔔 <b>Hisobingizda o'zgarish!</b>\n\n<b>{amount:,.0f} so'm</b> {text_type}\n📝 Izoh: <i>{message.text}</i>\n💰 <b>Qoldiq: {current_balance:,.0f} so'm</b>"
        await message.bot.send_message(chat_id=emp_id, text=user_msg, parse_mode="HTML")
    except: pass
    await state.clear()


# ==========================================
# 3️⃣ ISHCHILAR MA'LUMOTI VA SHAXSIY PROFIL
# ==========================================
@admin_router.message(F.text == "📋 Ishchilar ma'lumoti")
async def show_employee_list(message: types.Message, state: FSMContext):
    await state.clear()
    async with async_session() as session:
        employees = (await session.execute(select(Employee).where(Employee.status == "approved"))).scalars().all()
        
    if not employees:
        return await message.answer("❌ Hozircha ishchilar yo'q.")
        
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=f"👤 {emp.full_name}", callback_data=f"empinfo_{emp.id}")] for emp in employees]
    )
    await message.answer("📋 Profilini ko'rish uchun ishchini tanlang:", reply_markup=kb)

@admin_router.callback_query(F.data.startswith("empinfo_"))
async def show_employee_profile(call: types.CallbackQuery):
    emp_id = int(call.data.split("_")[1])
    
    async with async_session() as session:
        emp = await session.get(Employee, emp_id)
        if not emp: return await call.answer("Ishchi topilmadi!", show_alert=True)
        
        kpis = sum((await session.scalars(select(KPI.amount).where(KPI.employee_id == emp_id, KPI.is_closed == False))).all())
        advances = sum((await session.scalars(select(Advance.amount).where(Advance.employee_id == emp_id, Advance.is_closed == False))).all())
        penalties = sum((await session.scalars(select(Penalty.amount).where(Penalty.employee_id == emp_id, Penalty.is_closed == False))).all())
        current_balance = emp.base_salary + kpis - advances - penalties

    s_type_text = "Belgilangan oylik (Oklad)" if emp.salary_type == "Fix" else "Qilingan ishga qarab (Foiz)"

    text = (
        f"👤 <b>{emp.full_name} ma'lumotlari:</b>\n"
        f"📞 Tel: {emp.phone}\n"
        f"💼 Oylik turi: {s_type_text}\n"
        f"💵 Asosiy maosh: {emp.base_salary:,.0f} so'm\n\n"
        f"📈 Berilgan premiyalar: +{kpis:,.0f} so'm\n"
        f"💸 Olingan avanslar: -{advances:,.0f} so'm\n"
        f"⚠️ Jarimalar: -{penalties:,.0f} so'm\n"
        f"〰️〰️〰️〰️〰️〰️〰️〰️〰️\n"
        f"💰 <b>Qo'lga tegadigan joriy qoldiq: {current_balance:,.0f} so'm</b>"
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📥 Shaxsiy hisobotni yuklash", callback_data=f"empexcel_{emp_id}")],
        [InlineKeyboardButton(text="❌ Ishchilar safidan chetlatish", callback_data=f"fire_{emp_id}")]
    ])
    await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")


# ==========================================
# 4️⃣ ISHCHINI BO'SHATISH (CHETLATISH)
# ==========================================
@admin_router.callback_query(F.data.startswith("fire_"))
async def fire_prompt(call: types.CallbackQuery):
    emp_id = int(call.data.split("_")[1])
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Ha, chetlatish", callback_data=f"fireconf_{emp_id}")],
        [InlineKeyboardButton(text="❌ Yo'q, bekor qilish", callback_data=f"empinfo_{emp_id}")]
    ])
    await call.message.edit_text("⚠️ <b>Haqiqatan ham bu ishchini bazadan o'chirib yubormoqchimisiz?</b>\n<i>Bu amalni orqaga qaytarib bo'lmaydi!</i>", reply_markup=kb, parse_mode="HTML")

@admin_router.callback_query(F.data.startswith("fireconf_"))
async def fire_confirm(call: types.CallbackQuery):
    emp_id = int(call.data.split("_")[1])
    async with async_session() as session:
        emp = await session.get(Employee, emp_id)
        if emp:
            await session.delete(emp)
            await session.commit()
    await call.message.edit_text("✅ Xodim ishchilar safidan va bazadan to'liq o'chirildi.")
    await call.answer()

# ==========================================
# 5️⃣ UMUMIY VA SHAXSIY EXCEL YUKLASH 
# ==========================================
@admin_router.message(F.text == "📥 Umumiy hisobot")
async def export_excel_all(message: types.Message):
    await message.answer("⏳ Hisobot tayyorlanmoqda, kuting...")
    await export_excel_logic(message, None)

@admin_router.callback_query(F.data.startswith("empexcel_"))
async def export_excel_single(call: types.CallbackQuery):
    emp_id = int(call.data.split("_")[1])
    await call.message.answer("⏳ Shaxsiy hisobot tayyorlanmoqda...")
    await export_excel_logic(call.message, emp_id)
    await call.answer()

async def export_excel_logic(message: types.Message, single_emp_id: int = None):
    report_data = []
    async with async_session() as session:
        query = select(Employee).where(Employee.status == "approved")
        if single_emp_id:
            query = query.where(Employee.id == single_emp_id)
        employees = (await session.execute(query)).scalars().all()
        
        if not employees: return await message.answer("❌ Hisobot tayyorlash uchun ma'lumot yo'q.")
            
        for emp in employees:
            kpis = sum((await session.scalars(select(KPI.amount).where(KPI.employee_id == emp.id, KPI.is_closed == False))).all())
            advances = sum((await session.scalars(select(Advance.amount).where(Advance.employee_id == emp.id, Advance.is_closed == False))).all())
            penalties = sum((await session.scalars(select(Penalty.amount).where(Penalty.employee_id == emp.id, Penalty.is_closed == False))).all())
            
            s_type_text = "Oklad" if emp.salary_type == "Fix" else "Foiz"

            report_data.append({
                "F.I.SH": emp.full_name, "Telefon raqami": emp.phone, "Oylik Turi": s_type_text,
                "Boshlang'ich (so'm)": emp.base_salary, "Premiya pullari (so'm)": kpis,
                "Olingan Avans (so'm)": advances, "Jarimalar (so'm)": penalties,
                "Qo'lga tegadigan qoldiq (Raschyot)": emp.base_salary + kpis - advances - penalties
            })
            
    df = pd.DataFrame(report_data)
    output = io.BytesIO()

    with pd.ExcelWriter(output, engine='openpyxl') as writer: 
        df.to_excel(writer, index=False, sheet_name='Hisobot')
        worksheet = writer.sheets['Hisobot']
        for column_cells in worksheet.columns:
            length = max(len(str(cell.value)) for cell in column_cells)
            worksheet.column_dimensions[column_cells[0].column_letter].width = length + 2

    output.seek(0)
    file_name = f"Shaxsiy_{single_emp_id}.xlsx" if single_emp_id else f"Umumiy_Hisobot.xlsx"
    await message.answer_document(document=BufferedInputFile(output.read(), filename=file_name))

# ==========================================
# 6️⃣ OYLIK YOPISH VA TARIXGA YOZISH
# ==========================================
@admin_router.message(F.text == "📊 Oylik yopish")
async def close_month_handler(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("⏳ Oylik yopilmoqda. Iltimos kuting...")
    
    closed_count = 0
    current_month = datetime.now().strftime("%Y-%m")
    
    async with async_session() as session:
        employees = (await session.execute(select(Employee).where(Employee.status == "approved"))).scalars().all()
        
        for emp in employees:
            kpis = sum((await session.scalars(select(KPI.amount).where(KPI.employee_id == emp.id, KPI.is_closed == False))).all())
            advances = sum((await session.scalars(select(Advance.amount).where(Advance.employee_id == emp.id, Advance.is_closed == False))).all())
            penalties = sum((await session.scalars(select(Penalty.amount).where(Penalty.employee_id == emp.id, Penalty.is_closed == False))).all())
            
            final_salary = emp.base_salary + kpis - advances - penalties
            
            session.add(SalaryHistory(employee_id=emp.id, total_kpi=kpis, total_advance=advances, total_penalty=penalties, final_salary=final_salary, month=current_month))
            await session.execute(update(KPI).where(KPI.employee_id == emp.id, KPI.is_closed == False).values(is_closed=True))
            await session.execute(update(Advance).where(Advance.employee_id == emp.id, Advance.is_closed == False).values(is_closed=True))
            await session.execute(update(Penalty).where(Penalty.employee_id == emp.id, Penalty.is_closed == False).values(is_closed=True))
            
            closed_count += 1
            
        await session.commit()
        kb = await get_admin_menu(session)
        
    await message.answer(f"✅ <b>{current_month} oyi yopildi!</b>\n{closed_count} ta ishchining qoldiqlari nollandi.", reply_markup=kb, parse_mode="HTML")
