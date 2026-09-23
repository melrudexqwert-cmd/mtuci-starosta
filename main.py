# -*- coding: utf-8 -*-
import asyncio
import logging
from datetime import datetime, timedelta
import aiosqlite

from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message, CallbackQuery, 
    InlineKeyboardMarkup, InlineKeyboardButton,
    BufferedInputFile
)
from aiogram.filters import CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# ================= НАСТРОЙКИ СИСТЕМЫ =================
BOT_TOKEN = "8602029674:AAGa7OsWmTSXIZjkvG0Uo0FPD2w6Jr1TZ5I"
ADMIN_ID = 1154469594  # Хамедов Даниил
ZAM_ID = 8411029132    # Радостнов Пётр
DB_PATH = "group_study.db"

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# Список предметов
SUBJECTS = {
    "Математика": "📐", "Физика": "⚡", "Информатика": "💻",
    "Русский язык": "✍️", "Литература": "📚", "Иностранный язык": "🇬🇧",
    "История": "🏛", "Обществознание": "⚖️", "ОБЗР": "🛡",
    "Химия": "🧪", "Биология": "🧬", "География": "🌍",
    "Родной язык": "🗣", "Проектная деятельность": "💡"
}

# ================= СОСТОЯНИЯ =================
class RegStates(StatesGroup):
    waiting_for_fio = State()

class AddHwStates(StatesGroup):
    waiting_for_subject = State()
    waiting_for_task = State()
    waiting_for_deadline = State()

class GradeStates(StatesGroup):
    waiting_for_student = State()
    waiting_for_content = State()

class AdminStates(StatesGroup):
    waiting_for_roster = State()
    waiting_for_broadcast = State()
    waiting_for_ban = State()
    waiting_for_unban = State()
    waiting_for_teachers = State()
    waiting_for_book_sub = State()
    waiting_for_book_title = State()
    waiting_for_book_file = State()

# ================= БАЗА ДАННЫХ =================
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, full_name TEXT, is_admin INTEGER, is_blocked INTEGER, joined_at TEXT)")
        await db.execute("CREATE TABLE IF NOT EXISTS group_roster (id INTEGER PRIMARY KEY AUTOINCREMENT, full_name TEXT UNIQUE, is_registered INTEGER DEFAULT 0, user_id INTEGER)")
        await db.execute("CREATE TABLE IF NOT EXISTS homework (id INTEGER PRIMARY KEY AUTOINCREMENT, subject TEXT, task TEXT, file_id TEXT, file_type TEXT, deadline TEXT)")
        await db.execute("CREATE TABLE IF NOT EXISTS books (id INTEGER PRIMARY KEY AUTOINCREMENT, subject TEXT, title TEXT, file_id TEXT)")
        await db.execute("CREATE TABLE IF NOT EXISTS teachers (id INTEGER PRIMARY KEY, info TEXT)")
        await db.commit()

# ================= КЛАВИАТУРЫ =================
def main_menu_kb(is_admin: bool = False):
    kb = [
        [InlineKeyboardButton(text="📚 Домашние задания", callback_data="hw_view")],
        [
            InlineKeyboardButton(text="📖 Учебники", callback_data="books_view"),
            InlineKeyboardButton(text="👩‍🏫 Преподаватели & Ав...", callback_data="teachers_view")
        ],
        [
            InlineKeyboardButton(text="👤 Личный кабинет (Оц...", callback_data="profile_view"),
            InlineKeyboardButton(text="📅 Расписание ↗️", url="https://t.me/vvfsched_bot")
        ]
    ]
    if is_admin:
        kb.append([InlineKeyboardButton(text="⚙️ Панель управления", callback_data="admin_menu")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def admin_menu_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить ДЗ", callback_data="adm_add_hw"), InlineKeyboardButton(text="❌ Удалить ДЗ", callback_data="adm_del_hw")],
        [InlineKeyboardButton(text="⭐ Поставить оценку", callback_data="adm_grade"), InlineKeyboardButton(text="🗑️ Удалить оценку", callback_data="adm_del_grade")],
        [InlineKeyboardButton(text="📝 Перекличка", callback_data="adm_check"), InlineKeyboardButton(text="✏️ Инфа по автоматам", callback_data="adm_edit_teachers")],
        [InlineKeyboardButton(text="📁 Добавить учебник", callback_data="adm_add_book"), InlineKeyboardButton(text="👥 Список группы", callback_data="adm_roster_list")],
        [InlineKeyboardButton(text="📋 Загрузить список", callback_data="adm_imp"), InlineKeyboardButton(text="📥 Экспорт (.txt)", callback_data="adm_exp")],
        [InlineKeyboardButton(text="🚫 Блокировка", callback_data="adm_ban"), InlineKeyboardButton(text="✅ Разблокировка", callback_data="adm_unban")],
        [InlineKeyboardButton(text="📢 Объявление группе", callback_data="adm_bc")],
        [InlineKeyboardButton(text="⬅️ Главное меню", callback_data="to_main")]
    ])

# ================= ОБРАБОТКА /START =================
@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT full_name, is_blocked FROM users WHERE user_id = ?", (message.from_user.id,)) as cur:
            user = await cur.fetchone()
    
    if user:
        if user[1]: return await message.answer("⛔ Доступ ограничен.")
        is_adm = message.from_user.id in [ADMIN_ID, ZAM_ID]
        await message.answer(f"👋 С возвращением, **{user[0]}**!\n\nГлавное меню:", reply_markup=main_menu_kb(is_adm), parse_mode="Markdown")
    else:
        await message.answer("👋 Привет! Это бот группы 11.02.18.\n\n📝 **Напиши Фамилию Имя Отчество строго по списку**:\n*(Пример: Иванов Иван Иванович)*", parse_mode="Markdown")
        await state.set_state(RegStates.waiting_for_fio)

@dp.message(StateFilter(RegStates.waiting_for_fio))
async def proc_reg(message: Message, state: FSMContext):
    fio = " ".join(message.text.strip().split())
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT full_name, is_registered FROM group_roster WHERE LOWER(full_name) = LOWER(?)", (fio,)) as cur:
            row = await cur.fetchone()
        if not row: return await message.answer("❌ Тебя нет в списке группы! Проверь ФИО.")
        if row[1]: return await message.answer("⚠️ Этот человек уже зарегистрирован.")
        
        is_adm = 1 if message.from_user.id in [ADMIN_ID, ZAM_ID] else 0
        await db.execute("INSERT INTO users VALUES (?,?,?,?,?)", (message.from_user.id, row[0], is_adm, 0, datetime.now().strftime("%d.%m.%Y")))
        await db.execute("UPDATE group_roster SET is_registered=1, user_id=? WHERE full_name=?", (message.from_user.id, row[0]))
        await db.commit()
    
    await state.clear()
    await message.answer(f"✅ Регистрация: **{row[0]}**", reply_markup=main_menu_kb(is_adm == 1), parse_mode="Markdown")

# ================= ЛИЧНЫЙ КАБИНЕТ И ОЦЕНКИ =================
@dp.callback_query(F.data == "profile_view")
async def cb_prof(call: CallbackQuery):
    await call.answer()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT full_name, joined_at FROM users WHERE user_id=?", (call.from_user.id,)) as cur:
            u = await cur.fetchone()
    await call.message.edit_text(f"👤 **Личный кабинет**\n\n• {u[0]}\n• В боте с: {u[1]}\n\n📊 Здесь отображаются твои личные оценки и фото из журнала, когда их пришлет староста.", 
                                 reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="to_main")]]), parse_mode="Markdown")

@dp.callback_query(F.data == "adm_grade")
async def cb_adm_grade(call: CallbackQuery, state: FSMContext):
    await call.answer()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT full_name, user_id FROM users WHERE user_id != ?", (call.from_user.id,)) as cur:
            users = await cur.fetchall()
    if not users: return await call.message.answer("Никто еще не зашел в бота.")
    kb = [[InlineKeyboardButton(text=u[0], callback_data=f"send_to:{u[1]}")] for u in users]
    kb.append([InlineKeyboardButton(text="❌ Отмена", callback_data="admin_menu")])
    await call.message.edit_text("Кому отправить оценку/фото?", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await state.set_state(GradeStates.waiting_for_student)

@dp.callback_query(StateFilter(GradeStates.waiting_for_student), F.data.startswith("send_to:"))
async def cb_grade_target(call: CallbackQuery, state: FSMContext):
    await state.update_data(target=call.data.split(":")[1])
    await call.message.edit_text("Отправь текст оценки или ФОТОГРАФИЮ журнала:")
    await state.set_state(GradeStates.waiting_for_content)

@dp.message(StateFilter(GradeStates.waiting_for_content))
async def proc_send_grade(message: Message, state: FSMContext):
    data = await state.get_data()
    tid = int(data['target'])
    try:
        if message.photo: await bot.send_photo(tid, message.photo[-1].file_id, caption="📊 **Староста прислал твою оценку/фото журнала**", parse_mode="Markdown")
        else: await bot.send_message(tid, f"📊 **Личное сообщение от старосты:**\n\n{message.text}", parse_mode="Markdown")
        await message.answer("✅ Отправлено лично студенту!")
    except: await message.answer("❌ Не удалось отправить (заблок).")
    await state.clear()

# ================= ПЕРЕКЛИЧКА =================
@dp.callback_query(F.data == "adm_check")
async def cb_attendance(call: CallbackQuery, state: FSMContext):
    await call.answer()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT full_name FROM group_roster ORDER BY full_name") as cur:
            names = [x[0] for x in await cur.fetchall()]
    attend = {n: True for n in names}
    await state.update_data(att=attend)
    await render_attendance(call.message, attend)

async def render_attendance(msg, attend):
    kb = []
    for name, status in attend.items():
        icon = "✅" if status else "❌"
        short_name = f"{name.split()[0]} {name.split()[1][0]}."
        kb.append([InlineKeyboardButton(text=f"{short_name}: {icon}", callback_data=f"toggle_att:{name}")])
    kb.append([InlineKeyboardButton(text="📢 Сохранить и отчет", callback_data="save_att")])
    kb.append([InlineKeyboardButton(text="❌ Отмена", callback_data="admin_menu")])
    await msg.edit_text("📝 **ПЕРЕКЛИЧКА ГРУППЫ**\nНажмите для смены статуса:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="Markdown")

@dp.callback_query(F.data.startswith("toggle_att:"))
async def cb_toggle_att(call: CallbackQuery, state: FSMContext):
    await call.answer()
    name = call.data.split(":")[1]
    data = await state.get_data()
    data['att'][name] = not data['att'][name]
    await state.update_data(att=data['att'])
    await render_attendance(call.message, data['att'])

@dp.callback_query(F.data == "save_att")
async def cb_save_att(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    att = data['att']
    total = len(att)
    present = sum(1 for v in att.values() if v)
    percent = int((present/total)*100) if total > 0 else 0
    
    text = f"📊 **ОТЧЕТ ПО ПОСЕЩАЕМОСТИ** ({datetime.now().strftime('%d.%m.%Y')})\nГруппа 11.02.18\n"
    text += "⎯" * 15 + f"\n👥 Всего: {total} | ✅ Присутствуют: {present}\n🎉 {percent}% присутствие группы!\n\n"
    if percent < 100:
        text += "❌ **ОТСУТСТВУЮТ:**\n"
        for n, s in att.items():
            if not s: text += f"• {n}\n"
    
    await call.message.edit_text(text, reply_markup=admin_menu_kb(), parse_mode="Markdown")
    await state.clear()

# ================= ПРЕПОДАВАТЕЛИ И АВТОМАТЫ =================
@dp.callback_query(F.data == "teachers_view")
async def cb_teachers(call: CallbackQuery):
    await call.answer()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT info FROM teachers WHERE id=1") as cur:
            row = await cur.fetchone()
    text = row[0] if row else "ℹ️ Информация о преподавателях и условиях получения автомата пока не добавлена."
    await call.message.edit_text(f"👩‍🏫 **Преподаватели & Автоматы**\n\n{text}", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="to_main")]]), parse_mode="Markdown")

@dp.callback_query(F.data == "adm_edit_teachers")
async def cb_edit_teachers(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await call.message.edit_text("✏️ Отправь новый текст с информацией о преподавателях и автоматах:")
    await state.set_state(AdminStates.waiting_for_teachers)

@dp.message(StateFilter(AdminStates.waiting_for_teachers))
async def proc_edit_teachers(message: Message, state: FSMContext):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR REPLACE INTO teachers (id, info) VALUES (1, ?)", (message.text,))
        await db.commit()
    await state.clear()
    await message.answer("✅ Информация обновлена!", reply_markup=admin_menu_kb())

# ================= ДОБАВЛЕНИЕ ДЗ =================
@dp.callback_query(F.data == "adm_add_hw")
async def cb_add_hw(call: CallbackQuery, state: FSMContext):
    await call.answer()
    kb = []
    row = []
    for s in SUBJECTS:
        row.append(InlineKeyboardButton(text=f"{SUBJECTS[s]} {s}", callback_data=f"hws:{s}"))
        if len(row)==2: kb.append(row); row=[]
    kb.append([InlineKeyboardButton(text="❌ Отмена", callback_data="admin_menu")])
    await call.message.edit_text("Выберите предмет:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await state.set_state(AddHwStates.waiting_for_subject)

@dp.callback_query(StateFilter(AddHwStates.waiting_for_subject))
async def cb_hw_sub(call: CallbackQuery, state: FSMContext):
    await state.update_data(sub=call.data.split(":")[1])
    await call.message.edit_text("📝 Отправь задание (текст, фото или файл):")
    await state.set_state(AddHwStates.waiting_for_task)

@dp.message(StateFilter(AddHwStates.waiting_for_task))
async def proc_hw_task(message: Message, state: FSMContext):
    fid, ftype = None, None
    if message.photo: fid, ftype = message.photo[-1].file_id, "photo"
    elif message.document: fid, ftype = message.document.file_id, "document"
    
    await state.update_data(txt=message.caption or message.text or "См. файл", fid=fid, ftype=ftype)
    kb = [[InlineKeyboardButton(text="Завтра", callback_data="dl:Завтра"), InlineKeyboardButton(text="Послезавтра", callback_data="dl:Послезавтра")],
          [InlineKeyboardButton(text="На след. неделю", callback_data="dl:На след. неделю")]]
    await message.answer("⏳ Срок сдачи:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await state.set_state(AddHwStates.waiting_for_deadline)

@dp.callback_query(StateFilter(AddHwStates.waiting_for_deadline))
async def proc_hw_final(call: CallbackQuery, state: FSMContext):
    d = await state.get_data()
    deadline = call.data.split(":")[1]
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO homework (subject, task, file_id, file_type, deadline) VALUES (?,?,?,?,?)", 
                         (d['sub'], d['txt'], d['fid'], d['ftype'], deadline))
        await db.commit()
    
    await state.clear()
    await call.message.edit_text("✅ ДЗ добавлено и разослано группе!")
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id FROM users WHERE is_blocked=0") as cur:
            ids = [x[0] for x in await cur.fetchall()]
    
    msg = f"🚨 **НОВОЕ ДЗ!**\n{SUBJECTS.get(d['sub'], '')} {d['sub']}\n📝 {d['txt']}\n⏳ Срок: {deadline}"
    for i in ids:
        try:
            if d['fid']:
                if d['ftype']=="photo": await bot.send_photo(i, d['fid'], caption=msg, parse_mode="Markdown")
                else: await bot.send_document(i, d['fid'], caption=msg, parse_mode="Markdown")
            else: await bot.send_message(i, msg, parse_mode="Markdown")
        except: pass

# ================= УДАЛЕНИЕ ДЗ =================
@dp.callback_query(F.data == "adm_del_hw")
async def cb_del_hw(call: CallbackQuery):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id, subject, task FROM homework ORDER BY id DESC LIMIT 10") as cur:
            rows = await cur.fetchall()
    if not rows: return await call.message.edit_text("🌴 Нет заданий для удаления.", reply_markup=admin_menu_kb())
    kb = [[InlineKeyboardButton(text=f"❌ [{r[1]}] {r[2][:25]}...", callback_data=f"delhw:{r[0]}")] for r in rows]
    kb.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_menu")])
    await call.message.edit_text("Выберите задание для удаления:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data.startswith("delhw:"))
async def cb_delhw_fin(call: CallbackQuery):
    hid = int(call.data.split(":")[1])
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM homework WHERE id=?", (hid,))
        await db.commit()
    await call.answer("Задание удалено!")
    await cb_del_hw(call)

# ================= ПРОСМОТР ДЗ =================
@dp.callback_query(F.data == "hw_view")
async def cb_hw_view(call: CallbackQuery):
    await call.answer()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT subject, task, file_id, file_type, deadline FROM homework ORDER BY id DESC LIMIT 5") as cur:
            rows = await cur.fetchall()
    if not rows: return await call.message.edit_text("🌴 Заданий нет!", reply_markup=main_menu_kb())
    
    await call.message.delete()
    for r in rows:
        m = f"{SUBJECTS.get(r[0],'')} **{r[0]}**\n📝 {r[1]}\n⏳ Сдать до: {r[4]}"
        if r[2]:
            if r[3]=="photo": await call.message.answer_photo(r[2], caption=m, parse_mode="Markdown")
            else: await call.message.answer_document(r[2], caption=m, parse_mode="Markdown")
        else: await call.message.answer(m, parse_mode="Markdown")
    await call.message.answer("Это последние 5 заданий.", reply_markup=main_menu_kb())

# ================= УЧЕБНИКИ =================
@dp.callback_query(F.data == "books_view")
async def cb_books(call: CallbackQuery):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id, subject, title FROM books") as cur:
            books = await cur.fetchall()
    if not books: return await call.message.edit_text("📖 Учебников пока нет.", reply_markup=main_menu_kb())
    kb = [[InlineKeyboardButton(text=f"{SUBJECTS.get(b[1],'')} {b[1]}: {b[2]}", callback_data=f"getb:{b[0]}")] for b in books]
    kb.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="to_main")])
    await call.message.edit_text("Выберите учебник:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data.startswith("getb:"))
async def cb_getb(call: CallbackQuery):
    bid = int(call.data.split(":")[1])
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT title, file_id, subject FROM books WHERE id=?", (bid,)) as cur:
            b = await cur.fetchone()
    if b: await call.message.answer_document(b[1], caption=f"📖 **{b[2]}**: {b[0]}", parse_mode="Markdown")

@dp.callback_query(F.data == "adm_add_book")
async def cb_add_book(call: CallbackQuery, state: FSMContext):
    kb = [[InlineKeyboardButton(text=f"{SUBJECTS[s]} {s}", callback_data=f"bks:{s}")] for s in SUBJECTS]
    kb.append([InlineKeyboardButton(text="❌ Отмена", callback_data="admin_menu")])
    await call.message.edit_text("Выберите предмет для учебника:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await state.set_state(AdminStates.waiting_for_book_sub)

@dp.callback_query(StateFilter(AdminStates.waiting_for_book_sub), F.data.startswith("bks:"))
async def cb_book_sub_sel(call: CallbackQuery, state: FSMContext):
    await state.update_data(sub=call.data.split(":")[1])
    await call.message.edit_text("📖 Введите название учебника/части:")
    await state.set_state(AdminStates.waiting_for_book_title)

@dp.message(StateFilter(AdminStates.waiting_for_book_title))
async def cb_book_title_sel(message: Message, state: FSMContext):
    await state.update_data(title=message.text.strip())
    await message.answer("📄 Отправьте PDF файл учебника:")
    await state.set_state(AdminStates.waiting_for_book_file)

@dp.message(StateFilter(AdminStates.waiting_for_book_file), F.document)
async def cb_book_file_sel(message: Message, state: FSMContext):
    data = await state.get_data()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO books (subject, title, file_id) VALUES (?,?,?)", (data['sub'], data['title'], message.document.file_id))
        await db.commit()
    await state.clear()
    await message.answer("✅ Учебник успешно добавлен!", reply_markup=admin_menu_kb())

# ================= БЛОКИРОВКИ И РАССЫЛКИ =================
@dp.callback_query(F.data == "adm_bc")
async def cb_bc(call: CallbackQuery, state: FSMContext):
    await call.message.answer("📢 Введите текст объявления для всей группы:")
    await state.set_state(AdminStates.waiting_for_broadcast)

@dp.message(StateFilter(AdminStates.waiting_for_broadcast))
async def proc_bc(message: Message, state: FSMContext):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id FROM users WHERE is_blocked=0") as cur:
            ids = [x[0] for x in await cur.fetchall()]
    for i in ids:
        try: await bot.send_message(i, f"📢 **ИНФОРМАЦИЯ:**\n\n{message.text}", parse_mode="Markdown")
        except: pass
    await state.clear()
    await message.answer("✅ Объявление отправлено!", reply_markup=admin_menu_kb())

@dp.callback_query(F.data == "adm_ban")
async def cb_ban(call: CallbackQuery, state: FSMContext):
    await call.message.answer("Введите Telegram ID для блокировки:")
    await state.set_state(AdminStates.waiting_for_ban)

@dp.message(StateFilter(AdminStates.waiting_for_ban))
async def proc_ban(message: Message, state: FSMContext):
    try:
        uid = int(message.text.strip())
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE users SET is_blocked=1 WHERE user_id=?", (uid,))
            await db.commit()
        await message.answer(f"⛔ Пользователь {uid} заблокирован.", reply_markup=admin_menu_kb())
    except: await message.answer("Ошибка. ID должен быть числом.")
    await state.clear()

@dp.callback_query(F.data == "adm_unban")
async def cb_unban(call: CallbackQuery, state: FSMContext):
    await call.message.answer("Введите Telegram ID для разблокировки:")
    await state.set_state(AdminStates.waiting_for_unban)

@dp.message(StateFilter(AdminStates.waiting_for_unban))
async def proc_unban(message: Message, state: FSMContext):
    try:
        uid = int(message.text.strip())
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE users SET is_blocked=0 WHERE user_id=?", (uid,))
            await db.commit()
        await message.answer(f"✅ Пользователь {uid} разблокирован.", reply_markup=admin_menu_kb())
    except: await message.answer("Ошибка. ID должен быть числом.")
    await state.clear()

# ================= ВСПОМОГАТЕЛЬНЫЕ =================
@dp.callback_query(F.data == "admin_menu")
async def cb_adm(call: CallbackQuery):
    if call.from_user.id not in [ADMIN_ID, ZAM_ID]: return await call.answer("Нет прав.")
    await call.message.edit_text("⚙️ **Панель управления**", reply_markup=admin_menu_kb(), parse_mode="Markdown")

@dp.callback_query(F.data == "to_main")
async def cb_main(call: CallbackQuery, state: FSMContext):
    await state.clear()
    is_adm = call.from_user.id in [ADMIN_ID, ZAM_ID]
    await call.message.edit_text("Главное меню:", reply_markup=main_menu_kb(is_adm))

@dp.callback_query(F.data == "adm_roster_list")
async def cb_roster_list(call: CallbackQuery):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT full_name, is_registered FROM group_roster ORDER BY full_name") as cur:
            rows = await cur.fetchall()
    text = "👥 **Список группы:**\n\n"
    kb = []
    for r in rows:
        status = "✅" if r[1] else "❌"
        text += f"{status} {r[0]}\n"
        if r[1]: kb.append([InlineKeyboardButton(text=f"🔄 Сброс: {r[0].split()[0]}", callback_data=f"reset_u:{r[0]}")])
    kb.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_menu")])
    await call.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="Markdown")

@dp.callback_query(F.data.startswith("reset_u:"))
async def cb_reset_u(call: CallbackQuery):
    name = call.data.replace("reset_u:", "")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM users WHERE full_name=?", (name,))
        await db.execute("UPDATE group_roster SET is_registered=0, user_id=NULL WHERE full_name=?", (name,))
        await db.commit()
    await call.answer(f"Студент {name} удален из базы.")
    await cb_roster_list(call)

@dp.callback_query(F.data == "adm_imp")
async def cb_imp(call: CallbackQuery, state: FSMContext):
    await call.message.answer("Пришли .txt файл со списком ФИО (каждый с новой строки):")
    await state.set_state(AdminStates.waiting_for_roster)

@dp.message(StateFilter(AdminStates.waiting_for_roster), F.document)
async def proc_imp(message: Message, state: FSMContext):
    file = await bot.get_file(message.document.file_id)
    content = await bot.download_file(file.file_path)
    names = content.read().decode("utf-8").splitlines()
    async with aiosqlite.connect(DB_PATH) as db:
        for n in names:
            if n.strip(): await db.execute("INSERT OR IGNORE INTO group_roster (full_name) VALUES (?)", (n.strip(),))
        await db.commit()
    await message.answer("✅ Список загружен!")
    await state.clear()

@dp.callback_query(F.data == "adm_exp")
async def cb_exp(call: CallbackQuery):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT full_name, user_id FROM users") as cur:
            rows = await cur.fetchall()
    txt = "Авторизованные студенты:\n" + "\n".join([f"{r[0]} (ID: {r[1]})" for r in rows])
    doc = BufferedInputFile(txt.encode("utf-8"), filename="students.txt")
    await call.message.answer_document(doc, caption="📁 Список пользователей бота")

async def main():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA journal_mode=WAL;")
        await db.commit()
    await init_db()
    await bot.delete_webhook(drop_pending_updates=True)
    print("🚀 Бот запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
