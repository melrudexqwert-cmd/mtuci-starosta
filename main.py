# -*- coding: utf-8 -*-
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Callable, Dict, Any, Awaitable
import aiosqlite

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from aiogram import Bot, Dispatcher, F, BaseMiddleware
from aiogram.types import (
    Message, CallbackQuery, TelegramObject,
    InlineKeyboardMarkup, InlineKeyboardButton,
    BufferedInputFile
)
from aiogram.filters import CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

import os
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()

# Токен берется из скрытой переменной
BOT_TOKEN = os.getenv("BOT_TOKEN")

# А ваши ID прямо в коде (это абсолютно безопасно для GitHub!)
ADMIN_ID = 1154469594  # Даня
ZAM_ID = 8411029132    # Пётр
DB_PATH = "group_study.db"
TIMEZONE = "Europe/Moscow"

if not BOT_TOKEN:
    raise ValueError("❌ ОШИБКА: Не задан BOT_TOKEN в переменных окружения (.env)!")

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

RU_DAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
RU_MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", 
             "июля", "августа", "сентября", "октября", "ноября", "декабря"]

SUBJECTS = {
    "Математика": "📐", "Физика": "⚡", "Информатика": "💻",
    "Русский язык": "✍️", "Литература": "📚", "Иностранный язык": "🇬🇧",
    "История": "🏛", "Обществознание": "⚖️", "ОБЗР": "🛡",
    "Химия": "🧪", "Биология": "🧬", "География": "🌍",
    "Родной язык": "🗣", "Проектная деятельность": "💡"
}

current_attendance = {}

# ================= MIDDLEWARE (ПРОВЕРКА БАНА) =================
class BanCheckMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        user = data.get("event_from_user")
        if not user:
            return await handler(event, data)

        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT is_blocked FROM users WHERE user_id = ?", (user.id,)) as cur:
                row = await cur.fetchone()

        if row and row[0] == 1:
            if isinstance(event, Message):
                await event.answer("⛔ Доступ к боту ограничен администратором.")
            elif isinstance(event, CallbackQuery):
                await event.answer("⛔ Доступ заблокирован.", show_alert=True)
            return

        return await handler(event, data)

dp.message.middleware(BanCheckMiddleware())
dp.callback_query.middleware(BanCheckMiddleware())

# ================= FSM СОСТОЯНИЯ =================
class RegStates(StatesGroup):
    waiting_for_fio = State()

class AddHwStates(StatesGroup):
    waiting_for_subject_choice = State()
    waiting_for_task = State()
    waiting_for_deadline_choice = State()

class BookStates(StatesGroup):
    waiting_for_subject_choice = State()
    waiting_for_name = State()
    waiting_for_file = State()

class TeacherInfoStates(StatesGroup):
    waiting_for_subject = State()
    waiting_for_fio = State()
    waiting_for_avtomat = State()

class PersonalMsgStates(StatesGroup):
    waiting_for_student = State()
    waiting_for_content = State()

class AdminStates(StatesGroup):
    waiting_for_ban_id = State()
    waiting_for_broadcast = State()
    waiting_for_roster_input = State()

STUDENTS_LIST = [
    "Хамедов Даниил",
    "Радостнов Пётр Кириллович",
]

class AddSingleStudentState(StatesGroup):
    waiting_for_name = State()

# ================= БАЗА ДАННЫХ =================
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                is_admin INTEGER DEFAULT 0,
                is_blocked INTEGER DEFAULT 0,
                joined_at TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS group_roster (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                full_name TEXT UNIQUE,
                is_registered INTEGER DEFAULT 0,
                user_id INTEGER DEFAULT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS homework (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subject TEXT,
                task TEXT,
                file_id TEXT,
                file_type TEXT,
                deadline TEXT,
                created_at TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS books (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subject TEXT,
                title TEXT,
                file_id TEXT,
                file_name TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS teachers_info (
                subject TEXT PRIMARY KEY,
                teacher_fio TEXT,
                contacts TEXT,
                avtomat_conditions TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS attendance_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT,
                full_name TEXT,
                status TEXT
            )
        """)

        for student in STUDENTS_LIST:
            clean_name = " ".join(student.strip().split())
            if clean_name:
                await db.execute("INSERT OR IGNORE INTO group_roster (full_name) VALUES (?)", (clean_name,))

        await db.commit()

# ================= КЛАВИАТУРЫ =================
def main_menu_kb(is_admin: bool = False):
    kb = [
        [InlineKeyboardButton(text="📚 Домашние задания", callback_data="hw_view")],
        [
            InlineKeyboardButton(text="📖 Учебники", callback_data="books_view"),
            InlineKeyboardButton(text="👨‍🏫 Преподаватели & Автоматы", callback_data="teachers_view")
        ],
        [
            InlineKeyboardButton(text="👤 Личный кабинет", callback_data="user_profile"),
            InlineKeyboardButton(text="📅 Расписание", url="https://t.me/vvfsched_bot")
        ]
    ]
    if is_admin:
        kb.append([InlineKeyboardButton(text="⚙️ Панель управления", callback_data="admin_menu")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def admin_menu_kb():
    kb = [
        [
            InlineKeyboardButton(text="➕ Добавить ДЗ", callback_data="adm_add_hw"),
            InlineKeyboardButton(text="❌ Удалить ДЗ", callback_data="adm_delete_hw_menu")
        ],
        [
            InlineKeyboardButton(text="✉️ Написать лично", callback_data="adm_personal_msg"),
            InlineKeyboardButton(text="📝 Перекличка (Журнал)", callback_data="adm_attendance_start")
        ],
        [
            InlineKeyboardButton(text="✏️ Инфа по автоматам", callback_data="adm_edit_teacher_start"),
            InlineKeyboardButton(text="➕ Добавить студента", callback_data="adm_add_student_single")
        ],
        [
            InlineKeyboardButton(text="📋 Загрузить списком", callback_data="adm_import_roster"),
            InlineKeyboardButton(text="📁 Добавить учебник", callback_data="adm_add_book")
        ],
        [
            InlineKeyboardButton(text="👥 Список группы", callback_data="adm_roster_status"),
            InlineKeyboardButton(text="📥 Экспорт (.txt)", callback_data="adm_export_txt")
        ],
        [
            InlineKeyboardButton(text="📢 Объявление группе", callback_data="adm_broadcast"),
            InlineKeyboardButton(text="🚫 Блокировка / Разбан", callback_data="adm_ban")
        ],
        [InlineKeyboardButton(text="⬅️ Главное меню", callback_data="to_main_menu")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

def back_to_main_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Главное меню", callback_data="to_main_menu")]
    ])

def subjects_selection_kb(prefix: str):
    kb = []
    row = []
    for sub, icon in SUBJECTS.items():
        row.append(InlineKeyboardButton(text=f"{icon} {sub}", callback_data=f"{prefix}:{sub}"))
        if len(row) == 2:
            kb.append(row)
            row = []
    if row:
        kb.append(row)
    kb.append([InlineKeyboardButton(text="❌ Отмена", callback_data="to_main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def deadline_selection_kb():
    today = datetime.now()
    kb = []
    d_tomorrow = today + timedelta(days=1)
    d_after_tom = today + timedelta(days=2)
    
    label_tom = f"Завтра ({RU_DAYS[d_tomorrow.weekday()]}, {d_tomorrow.day} {RU_MONTHS[d_tomorrow.month-1]})"
    label_after = f"Послезавтра ({RU_DAYS[d_after_tom.weekday()]}, {d_after_tom.day} {RU_MONTHS[d_after_tom.month-1]})"
    
    kb.append([InlineKeyboardButton(text=label_tom, callback_data="dl_val:Завтра")])
    kb.append([InlineKeyboardButton(text=label_after, callback_data="dl_val:Послезавтра")])
    
    row = []
    for i in range(3, 8):
        d = today + timedelta(days=i)
        btn_text = f"{RU_DAYS[d.weekday()]} ({d.day}.{d.month:02d})"
        val_text = f"{RU_DAYS[d.weekday()]}, {d.day} {RU_MONTHS[d.month-1]}"
        row.append(InlineKeyboardButton(text=btn_text, callback_data=f"dl_val:{val_text}"))
        if len(row) == 2:
            kb.append(row)
            row = []
    if row:
        kb.append(row)
        
    kb.append([InlineKeyboardButton(text="К следующей паре", callback_data="dl_val:К следующей паре")])
    kb.append([InlineKeyboardButton(text="❌ Отмена", callback_data="to_main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

# ================= ПЛАНИРОВЩИК ДЗ (19:00) =================
async def send_daily_hw_reminder():
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT subject, task, deadline FROM homework ORDER BY id DESC LIMIT 6") as cur:
            rows = await cur.fetchall()
        async with db.execute("SELECT user_id FROM users WHERE is_blocked = 0") as cur:
            users = await cur.fetchall()

    if not rows or not users:
        return

    text = "🔔 **ВЕЧЕРНЕЕ НАПОМИНАНИЕ О ДОМАШНИХ ЗАДАНИЯХ:**\n\n"
    for r in rows:
        icon = SUBJECTS.get(r[0], "📖")
        text += f"{icon} **{r[0]}**\n📝 {r[1]}\n⏳ Срок: `{r[2]}`\n───────────────\n"

    for u in users:
        try:
            await bot.send_message(u[0], text, parse_mode="Markdown")
            await asyncio.sleep(0.05)
        except Exception:
            pass

# ================= СТАРТ И АВТОРИЗАЦИЯ =================
@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    username = f"@{message.from_user.username}" if message.from_user.username else "без_ника"
    now_str = datetime.now().strftime("%d.%m.%Y %H:%M")

    if user_id == ADMIN_ID or user_id == ZAM_ID:
        admin_fio = "Хамедов Даниил (Староста)" if user_id == ADMIN_ID else "Радостнов Пётр (Зам)"
        
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                INSERT INTO users (user_id, username, full_name, is_admin, is_blocked, joined_at)
                VALUES (?, ?, ?, 1, 0, ?)
                ON CONFLICT(user_id) DO UPDATE SET is_admin = 1, full_name = ?
            """, (user_id, username, admin_fio, now_str, admin_fio))
            
            await db.execute("""
                INSERT INTO group_roster (full_name, is_registered, user_id)
                VALUES (?, 1, ?)
                ON CONFLICT(full_name) DO UPDATE SET is_registered = 1, user_id = ?
            """, (admin_fio, user_id, user_id))
            await db.commit()

        await message.answer(
            f"👑 **Добро пожаловать, {admin_fio}!**\n\nПанель управления готова к работе.",
            reply_markup=main_menu_kb(is_admin=True),
            parse_mode="Markdown"
        )
        return

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT full_name, is_admin FROM users WHERE user_id = ?", (user_id,)) as cur:
            user = await cur.fetchone()

    if user:
        is_admin = (user[1] == 1)
        await message.answer(
            f"👋 С возвращением, **{user[0]}**!\n\nВыберите нужный раздел:",
            reply_markup=main_menu_kb(is_admin),
            parse_mode="Markdown"
        )
    else:
        reg_text = "👋 Привет! Это бот учебной группы.\n\n📝 **Для входа напиши свои Фамилию Имя Отчество точь-в-точь как в списке**:\n*(Пример: Иванов Иван Иванович)*"
        await message.answer(reg_text, parse_mode="Markdown")
        await state.set_state(RegStates.waiting_for_fio)

@dp.message(StateFilter(RegStates.waiting_for_fio))
async def process_fio(message: Message, state: FSMContext):
    fio_input = " ".join(message.text.strip().split())
    user_id = message.from_user.id
    username = f"@{message.from_user.username}" if message.from_user.username else "без_ника"
    now_str = datetime.now().strftime("%d.%m.%Y %H:%M")

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT full_name FROM users WHERE user_id = ?", (user_id,)) as cur:
            already_reg = await cur.fetchone()
        if already_reg:
            await message.answer(f"⚠️ Вы уже зарегистрированы как **{already_reg[0]}**!", parse_mode="Markdown")
            await state.clear()
            return

        async with db.execute("SELECT full_name, user_id FROM group_roster WHERE LOWER(full_name) = LOWER(?)", (fio_input,)) as cur:
            roster_row = await cur.fetchone()

        if not roster_row:
            await message.answer("❌ **Такого ФИО нет в списке группы!**\nПроверьте написание или напишите старосте.", parse_mode="Markdown")
            return

        exact_fio = roster_row[0]
        assigned_user_id = roster_row[1]

        if assigned_user_id is not None and assigned_user_id != user_id:
            await message.answer("⚠️ Этот студент уже зарегистрирован с другого Telegram-аккаунта!", parse_mode="Markdown")
            return

        is_admin = (user_id == ADMIN_ID) or (user_id == ZAM_ID)

        await db.execute("""
            INSERT INTO users (user_id, username, full_name, is_admin, is_blocked, joined_at)
            VALUES (?, ?, ?, ?, 0, ?)
            ON CONFLICT(user_id) DO UPDATE SET full_name = ?, is_admin = ?
        """, (user_id, username, exact_fio, 1 if is_admin else 0, now_str, exact_fio, 1 if is_admin else 0))
        
        await db.execute("UPDATE group_roster SET is_registered = 1, user_id = ? WHERE LOWER(full_name) = LOWER(?)", (user_id, exact_fio))
        await db.commit()

    await state.clear()
    await message.answer(f"✅ Регистрация завершена!\n👤 Студент: **{exact_fio}**", reply_markup=main_menu_kb(is_admin), parse_mode="Markdown")

# ================= ЛИЧНЫЙ КАБИНЕТ =================
@dp.callback_query(F.data == "user_profile")
async def cb_profile(call: CallbackQuery):
    await call.answer()
    user_id = call.from_user.id
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT full_name, joined_at FROM users WHERE user_id = ?", (user_id,)) as cur:
            u = await cur.fetchone()
        
        if not u:
            await call.message.edit_text("Ошибка авторизации. Нажмите /start")
            return

        full_name = u[0]

        async with db.execute("""
            SELECT 
                SUM(CASE WHEN status = 'present' THEN 1 ELSE 0 END),
                SUM(CASE WHEN status = 'ill' THEN 1 ELSE 0 END),
                SUM(CASE WHEN status = 'valid' THEN 1 ELSE 0 END),
                SUM(CASE WHEN status = 'absent' THEN 1 ELSE 0 END)
            FROM attendance_history WHERE full_name = ?
        """, (full_name,)) as cur:
            att = await cur.fetchone()

        present_c = att[0] or 0
        ill_c = att[1] or 0
        valid_c = att[2] or 0
        absent_c = att[3] or 0

    text = (
        f"👤 **ЛИЧНЫЙ КАБИНЕТ СТУДЕНТА**\n"
        f"─────────────────────\n"
        f"🎓 **ФИО:** {full_name}\n"
        f"📅 **В системе с:** {u[1]}\n\n"
        f"📊 **ВАША ПОСЕЩАЕМОСТЬ:**\n"
        f"• ✅ Присутствовал: **{present_c}** пар(ы)\n"
        f"• 🤒 По болезни: **{ill_c}**\n"
        f"• 📄 Уважительная: **{valid_c}**\n"
        f"• ❌ **Прогулов (н/а): {absent_c}**\n"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Главное меню", callback_data="to_main_menu")]
    ])
    await call.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")

# ================= АДМИНКА: ЛИЧНЫЕ СООБЩЕНИЯ СТУДЕНТУ =================
@dp.callback_query(F.data == "adm_personal_msg")
async def cb_adm_personal_msg(call: CallbackQuery, state: FSMContext):
    await call.answer()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT full_name, user_id FROM users WHERE user_id IS NOT NULL AND is_blocked = 0") as cur:
            users = await cur.fetchall()

    if not users:
        await call.message.edit_text("⚠️ В боте еще нет зарегистрированных студентов.", reply_markup=admin_menu_kb())
        return

    kb = []
    for u in users:
        kb.append([InlineKeyboardButton(text=f"✉️ {u[0]}", callback_data=f"pm_u:{u[1]}")])
    kb.append([InlineKeyboardButton(text="❌ Отмена", callback_data="admin_menu")])

    await call.message.edit_text("✉️ **Выберите студента, которому хотите написать лично:**", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="Markdown")
    await state.set_state(PersonalMsgStates.waiting_for_student)

@dp.callback_query(StateFilter(PersonalMsgStates.waiting_for_student), F.data.startswith("pm_u:"))
async def cb_pm_user_chosen(call: CallbackQuery, state: FSMContext):
    await call.answer()
    target_id = int(call.data.split(":")[1])
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT full_name FROM users WHERE user_id = ?", (target_id,)) as cur:
            u = await cur.fetchone()

    if not u:
        await call.message.edit_text("Студент не найден.", reply_markup=admin_menu_kb())
        await state.clear()
        return

    await state.update_data(target_user_id=target_id, target_name=u[0])
    await call.message.edit_text(f"✉️ Студент: **{u[0]}**\n\n📝 Отправьте сообщение, фото или файл (староста/зам):", reply_markup=back_to_main_kb(), parse_mode="Markdown")
    await state.set_state(PersonalMsgStates.waiting_for_content)

@dp.message(StateFilter(PersonalMsgStates.waiting_for_content), F.text | F.photo | F.document)
async def process_personal_msg(message: Message, state: FSMContext):
    data = await state.get_data()
    target_id = data["target_user_id"]
    target_name = data["target_name"]

    caption = message.caption or message.text or ""
    header = "👑 **Личное сообщение от старости/зама:**\n\n"
    full_caption = header + caption if caption else header

    try:
        if message.photo:
            await bot.send_photo(target_id, photo=message.photo[-1].file_id, caption=full_caption, parse_mode="Markdown")
        elif message.document:
            await bot.send_document(target_id, document=message.document.file_id, caption=full_caption, parse_mode="Markdown")
        else:
            await bot.send_message(target_id, full_caption, parse_mode="Markdown")

        await message.answer(f"✅ Сообщение успешно отправлено студенту **{target_name}**!", reply_markup=admin_menu_kb(), parse_mode="Markdown")
    except Exception as e:
        await message.answer(f"❌ Не удалось отправить сообщение.\nОшибка: {e}", reply_markup=admin_menu_kb())

    await state.clear()

# ================= АДМИНКА: ДОБАВЛЕНИЕ СТУДЕНТОВ =================
@dp.callback_query(F.data == "adm_add_student_single")
async def cb_add_student_single(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await call.message.answer(
        "👤 **Добавление студента:**\n\nВведите Фамилию Имя (и Отчество) студента:\n*(Пример: Смирнов Алексей Игоревич)*"
    )
    await state.set_state(AddSingleStudentState.waiting_for_name)

@dp.message(StateFilter(AddSingleStudentState.waiting_for_name))
async def process_single_student_name(message: Message, state: FSMContext):
    clean_name = " ".join(message.text.strip().split())
    if len(clean_name.split()) < 2:
        await message.answer("⚠️ Пожалуйста, введите минимум Фамилию и Имя:")
        return

    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute("INSERT INTO group_roster (full_name) VALUES (?)", (clean_name,))
            await db.commit()
            await message.answer(f"✅ Студент **{clean_name}** добавлен в группу!", reply_markup=admin_menu_kb(), parse_mode="Markdown")
        except Exception:
            await message.answer("⚠️ Такой студент уже есть в списке группы!", reply_markup=admin_menu_kb())
    await state.clear()

# ================= РАЗДЕЛ: ДЗ =================
@dp.callback_query(F.data == "hw_view")
async def cb_hw_view(call: CallbackQuery):
    await call.answer()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT subject, task, file_id, file_type, deadline, created_at FROM homework ORDER BY id DESC LIMIT 5") as cur:
            rows = await cur.fetchall()

    if not rows:
        text = "🌴 **На данный момент актуальных заданий нет.** Всё чисто!"
        await call.message.edit_text(text, reply_markup=back_to_main_kb(), parse_mode="Markdown")
        return

    await call.message.edit_text("📚 **АКТУАЛЬНЫЕ ДОМАШНИЕ ЗАДАНИЯ:**", reply_markup=back_to_main_kb(), parse_mode="Markdown")
    for r in rows:
        icon = SUBJECTS.get(r[0], "📖")
        task_text = f"{icon} **{r[0]}**\n📝 **Задание:** {r[1]}\n⏳ **Срок сдачи:** `{r[4]}`\n───────────────"
        if r[2]:
            if r[3] == "photo":
                await call.message.answer_photo(photo=r[2], caption=task_text, parse_mode="Markdown")
            elif r[3] == "document":
                await call.message.answer_document(document=r[2], caption=task_text, parse_mode="Markdown")
        else:
            await call.message.answer(task_text, parse_mode="Markdown")

@dp.callback_query(F.data == "adm_delete_hw_menu")
async def cb_adm_delete_hw_menu(call: CallbackQuery):
    await call.answer()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id, subject, task, deadline FROM homework ORDER BY id DESC LIMIT 8") as cur:
            rows = await cur.fetchall()

    if not rows:
        await call.message.edit_text("🌴 Нет заданий для удаления.", reply_markup=admin_menu_kb())
        return

    kb = []
    for r in rows:
        short_task = (r[2][:18] + '..') if len(r[2]) > 18 else r[2]
        btn_text = f"❌ {r[1]}: {short_task} ({r[3]})"
        kb.append([InlineKeyboardButton(text=btn_text, callback_data=f"del_hw:{r[0]}")])
    kb.append([InlineKeyboardButton(text="⬅️ В админку", callback_data="admin_menu")])

    await call.message.edit_text("🗑 **Выберите задание для удаления:**", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="Markdown")

@dp.callback_query(F.data.startswith("del_hw:"))
async def cb_del_hw_confirm(call: CallbackQuery):
    hw_id = int(call.data.split(":")[1])
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM homework WHERE id = ?", (hw_id,))
        await db.commit()
    await call.answer("✅ Задание удалено!", show_alert=True)
    await cb_adm_delete_hw_menu(call)

# ================= ПРЕПОДАВАТЕЛИ И АВТОМАТЫ =================
@dp.callback_query(F.data == "teachers_view")
async def cb_teachers_view(call: CallbackQuery):
    await call.answer()
    await call.message.edit_text(
        "👨‍🏫 **Выберите предмет для просмотра инфы о преподавателе и условиях автомата:**",
        reply_markup=subjects_selection_kb("view_teacher"),
        parse_mode="Markdown"
    )

@dp.callback_query(F.data.startswith("view_teacher:"))
async def cb_view_teacher_info(call: CallbackQuery):
    await call.answer()
    subject = call.data.split(":")[1]
    icon = SUBJECTS.get(subject, "📖")

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT teacher_fio, contacts, avtomat_conditions FROM teachers_info WHERE subject = ?", (subject,)) as cur:
            info = await cur.fetchone()

    if not info:
        text = f"{icon} **Предмет:** {subject}\n\nℹ️ Информация ещё не внесена старостой."
    else:
        text = (
            f"{icon} **Предмет:** {subject}\n\n"
            f"👤 **Преподаватель:** {info[0] or 'Не указан'}\n"
            f"📱 **Контакты / Кабинет:** {info[1] or 'Не указаны'}\n\n"
            f"🎯 **Условия автомата / сдачи:**\n{info[2] or 'Уточняются'}"
        )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ К предметам", callback_data="teachers_view")],
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="to_main_menu")]
    ])
    await call.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")

@dp.callback_query(F.data == "adm_edit_teacher_start")
async def cb_edit_teacher_start(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await call.message.edit_text("✏️ **Выберите предмет для настройки:**", reply_markup=subjects_selection_kb("adm_sub_t"))
    await state.set_state(TeacherInfoStates.waiting_for_subject)

@dp.callback_query(StateFilter(TeacherInfoStates.waiting_for_subject), F.data.startswith("adm_sub_t:"))
async def cb_edit_teacher_chosen(call: CallbackQuery, state: FSMContext):
    await call.answer()
    subject = call.data.split(":")[1]
    await state.update_data(subject=subject)
    await call.message.edit_text("👤 Введите **ФИО преподавателя и кабинет/контакты**:", parse_mode="Markdown")
    await state.set_state(TeacherInfoStates.waiting_for_fio)

@dp.message(StateFilter(TeacherInfoStates.waiting_for_fio))
async def process_teacher_fio(message: Message, state: FSMContext):
    await state.update_data(teacher_fio=message.text.strip())
    await message.answer("🎯 Напишите **условия получения автомата / сдачи зачета**:")
    await state.set_state(TeacherInfoStates.waiting_for_avtomat)

@dp.message(StateFilter(TeacherInfoStates.waiting_for_avtomat))
async def process_teacher_avtomat(message: Message, state: FSMContext):
    data = await state.get_data()
    subject = data["subject"]
    fio = data["teacher_fio"]
    avtomat = message.text.strip()

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO teachers_info (subject, teacher_fio, contacts, avtomat_conditions)
            VALUES (?, ?, '', ?)
            ON CONFLICT(subject) DO UPDATE SET teacher_fio = ?, avtomat_conditions = ?
        """, (subject, fio, avtomat, fio, avtomat))
        await db.commit()

    await state.clear()
    await message.answer(f"✅ Информация по **{subject}** сохранена!", reply_markup=admin_menu_kb(), parse_mode="Markdown")

# ================= ПЕРЕКЛИЧКА =================
STATUS_EMOJIS = {"present": "✅ Был", "ill": "🤒 Болеет", "absent": "❌ Прогул", "valid": "📄 Уваж."}

def attendance_kb():
    kb = []
    for r_id, info in current_attendance.items():
        fio = info["name"]
        status = info["status"]
        short_name = " ".join([fio.split()[0], fio.split()[1][0] + "." if len(fio.split()) > 1 else ""])
        btn_text = f"{short_name}: {STATUS_EMOJIS.get(status, '✅')}"
        kb.append([InlineKeyboardButton(text=btn_text, callback_data=f"att_t:{r_id}")])
    
    kb.append([InlineKeyboardButton(text="📢 Сохранить и сформировать отчет", callback_data="att_finish")])
    kb.append([InlineKeyboardButton(text="❌ Отмена", callback_data="admin_menu")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

@dp.callback_query(F.data == "adm_attendance_start")
async def cb_attendance_start(call: CallbackQuery):
    await call.answer()
    global current_attendance
    current_attendance = {}
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id, full_name FROM group_roster ORDER BY full_name") as cur:
            students = await cur.fetchall()

    if not students:
        await call.message.edit_text("⚠️ Ростер группы пуст.", reply_markup=admin_menu_kb())
        return

    for s in students:
        current_attendance[s[0]] = {"name": s[1], "status": "present"}

    await call.message.edit_text("📝 **ПЕРЕКЛИЧКА ГРУППЫ**\n\nНажимайте для смены статуса:", reply_markup=attendance_kb(), parse_mode="Markdown")

@dp.callback_query(F.data.startswith("att_t:"))
async def cb_attendance_toggle(call: CallbackQuery):
    r_id = int(call.data.replace("att_t:", ""))
    statuses = ["present", "ill", "absent", "valid"]
    
    if r_id in current_attendance:
        curr = current_attendance[r_id]["status"]
        next_idx = (statuses.index(curr) + 1) % len(statuses)
        current_attendance[r_id]["status"] = statuses[next_idx]

    await call.answer()
    await call.message.edit_reply_markup(reply_markup=attendance_kb())

@dp.callback_query(F.data == "att_finish")
async def cb_attendance_finish(call: CallbackQuery):
    await call.answer()
    today_str = datetime.now().strftime("%d.%m.%Y")

    async with aiosqlite.connect(DB_PATH) as db:
        for r_id, info in current_attendance.items():
            await db.execute("INSERT INTO attendance_history (date, full_name, status) VALUES (?, ?, ?)", (today_str, info["name"], info["status"]))
        await db.commit()

    total = len(current_attendance)
    present_cnt = sum(1 for s in current_attendance.values() if s["status"] == "present")
    ill_list = [s["name"] for s in current_attendance.values() if s["status"] == "ill"]
    absent_list = [s["name"] for s in current_attendance.values() if s["status"] == "absent"]
    valid_list = [s["name"] for s in current_attendance.values() if s["status"] == "valid"]

    report = f"📊 **ОТЧЕТ ПО ПОСЕЩАЕМОСТИ ({today_str})**\nГруппа 11.02.18\n─────────────────────\n"
    report += f"👥 Всего: **{total}** | ✅ Присутствуют: **{present_cnt}**\n\n"

    if ill_list:
        report += "🤒 **Болеют:**\n" + "\n".join([f"• {name}" for name in ill_list]) + "\n\n"
    if valid_list:
        report += "📄 **Уважительная причина:**\n" + "\n".join([f"• {name}" for name in valid_list]) + "\n\n"
    if absent_list:
        report += "❌ **Неаттестация / Прогул:**\n" + "\n".join([f"• {name}" for name in absent_list]) + "\n\n"

    if not ill_list and not absent_list and not valid_list:
        report += "🎉 **100% присутствие группы!**"

    await call.message.edit_text(report, reply_markup=admin_menu_kb(), parse_mode="Markdown")

# ================= УЧЕБНИКИ =================
@dp.callback_query(F.data == "books_view")
async def cb_books_view(call: CallbackQuery):
    await call.answer()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id, subject, title FROM books ORDER BY id DESC") as cur:
            books = await cur.fetchall()

    if not books:
        await call.message.edit_text("📖 Раздел учебников пуст.", reply_markup=back_to_main_kb())
        return

    kb = []
    for b in books:
        icon = SUBJECTS.get(b[1], "📖")
        kb.append([InlineKeyboardButton(text=f"{icon} {b[1]}: {b[2]}", callback_data=f"get_book:{b[0]}")])
    kb.append([InlineKeyboardButton(text="⬅️ Главное меню", callback_data="to_main_menu")])

    await call.message.edit_text("📖 **Учебники и материалы:**", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="Markdown")

@dp.callback_query(F.data.startswith("get_book:"))
async def cb_get_book(call: CallbackQuery):
    book_id = int(call.data.split(":")[1])
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT title, file_id, subject FROM books WHERE id = ?", (book_id,)) as cur:
            b = await cur.fetchone()

    if b:
        await call.answer("Отправляю...")
        icon = SUBJECTS.get(b[2], "📖")
        await call.message.answer_document(document=b[1], caption=f"{icon} **{b[2]}**: {b[0]}")
    else:
        await call.answer("Файл не найден.", show_alert=True)

# ================= НАВИГАЦИЯ И АДМИНКА =================
@dp.callback_query(F.data == "to_main_menu")
async def cb_to_main(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await state.clear()
    user_id = call.from_user.id
    is_admin = (user_id == ADMIN_ID) or (user_id == ZAM_ID)
    if not is_admin:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT is_admin FROM users WHERE user_id = ?", (user_id,)) as cur:
                u = await cur.fetchone()
                if u and u[0] == 1:
                    is_admin = True

    await call.message.edit_text("Главное меню:", reply_markup=main_menu_kb(is_admin))

@dp.callback_query(F.data == "admin_menu")
async def cb_admin_menu(call: CallbackQuery):
    user_id = call.from_user.id
    is_admin = (user_id == ADMIN_ID) or (user_id == ZAM_ID)
    if not is_admin:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT is_admin FROM users WHERE user_id = ?", (user_id,)) as cur:
                u = await cur.fetchone()
                if u and u[0] == 1:
                    is_admin = True

    if not is_admin:
        await call.answer("Доступ ограничен.", show_alert=True)
        return

    await call.answer()
    await call.message.edit_text("⚙️ **Панель управления:**", reply_markup=admin_menu_kb(), parse_mode="Markdown")

# Добавление ДЗ
@dp.callback_query(F.data == "adm_add_hw")
async def cb_add_hw(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await call.message.edit_text("📖 **Выберите предмет:**", reply_markup=subjects_selection_kb("sub_hw"))
    await state.set_state(AddHwStates.waiting_for_subject_choice)

@dp.callback_query(StateFilter(AddHwStates.waiting_for_subject_choice), F.data.startswith("sub_hw:"))
async def cb_hw_subject_selected(call: CallbackQuery, state: FSMContext):
    await call.answer()
    subject_name = call.data.split(":")[1]
    await state.update_data(subject=subject_name)
    icon = SUBJECTS.get(subject_name, "📖")
    await call.message.edit_text(f"{icon} Предмет: **{subject_name}**\n\n📝 Отправьте **текст задания, фотографию или документ (файл)**:", parse_mode="Markdown")
    await state.set_state(AddHwStates.waiting_for_task)

@dp.message(StateFilter(AddHwStates.waiting_for_task), F.text | F.photo | F.document)
async def hw_task_input(message: Message, state: FSMContext):
    task_text = message.caption or message.text or "Домашнее задание (без текста)"
    file_id = None
    file_type = None

    if message.photo:
        file_id = message.photo[-1].file_id
        file_type = "photo"
    elif message.document:
        file_id = message.document.file_id
        file_type = "document"

    await state.update_data(task=task_text, file_id=file_id, file_type=file_type)
    await message.answer("⏳ **Выберите срок сдачи:**", reply_markup=deadline_selection_kb())
    await state.set_state(AddHwStates.waiting_for_deadline_choice)

@dp.callback_query(StateFilter(AddHwStates.waiting_for_deadline_choice), F.data.startswith("dl_val:"))
async def hw_deadline_chosen(call: CallbackQuery, state: FSMContext):
    await call.answer()
    deadline = call.data.replace("dl_val:", "")
    data = await state.get_data()
    subject = data["subject"]
    task = data["task"]
    file_id = data.get("file_id")
    file_type = data.get("file_type")
    created = datetime.now().strftime("%d.%m.%Y")
    icon = SUBJECTS.get(subject, "📖")

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO homework (subject, task, file_id, file_type, deadline, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (subject, task, file_id, file_type, deadline, created)
        )
        await db.commit()
        async with db.execute("SELECT user_id FROM users WHERE is_blocked = 0") as cur:
            students = await cur.fetchall()

    await state.clear()
    await call.message.edit_text("✅ Задание сохранено! Рассылаю уведомления...")

    alert_msg = f"🚨 **НОВОЕ ДОМАШНЕЕ ЗАДАНИЕ!**\n\n{icon} **Предмет:** {subject}\n📝 **Задание:** {task}\n⏳ **Сдать до:** `{deadline}`\n"
    for s in students:
        try:
            if file_id:
                if file_type == "photo":
                    await bot.send_photo(s[0], photo=file_id, caption=alert_msg, parse_mode="Markdown")
                elif file_type == "document":
                    await bot.send_document(s[0], document=file_id, caption=alert_msg, parse_mode="Markdown")
            else:
                await bot.send_message(s[0], alert_msg, parse_mode="Markdown")
            await asyncio.sleep(0.05)
        except Exception:
            pass

    await call.message.answer("🚀 Уведомление доставлено группе!", reply_markup=admin_menu_kb())

# Добавление книги
@dp.callback_query(F.data == "adm_add_book")
async def cb_add_book_start(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await call.message.edit_text("📖 **Выберите предмет для книги:**", reply_markup=subjects_selection_kb("sub_book"))
    await state.set_state(BookStates.waiting_for_subject_choice)

@dp.callback_query(StateFilter(BookStates.waiting_for_subject_choice), F.data.startswith("sub_book:"))
async def cb_book_subject_selected(call: CallbackQuery, state: FSMContext):
    await call.answer()
    subject_name = call.data.split(":")[1]
    await state.update_data(subject=subject_name)
    await call.message.edit_text("📖 Введите название книги (например: *Часть 1 (Боголюбов)*):", parse_mode="Markdown")
    await state.set_state(BookStates.waiting_for_name)

@dp.message(StateFilter(BookStates.waiting_for_name))
async def process_book_name(message: Message, state: FSMContext):
    await state.update_data(book_title=message.text.strip())
    await message.answer("📄 Отправьте **PDF файл** учебника:")
    await state.set_state(BookStates.waiting_for_file)

@dp.message(StateFilter(BookStates.waiting_for_file), F.document)
async def process_book_file(message: Message, state: FSMContext):
    data = await state.get_data()
    subject = data["subject"]
    title = data["book_title"]
    file_id = message.document.file_id
    file_name = message.document.file_name

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO books (subject, title, file_id, file_name) VALUES (?, ?, ?, ?)", (subject, title, file_id, file_name))
        await db.commit()

    await state.clear()
    await message.answer(f"✅ Учебник **{subject}: {title}** сохранен!", reply_markup=admin_menu_kb(), parse_mode="Markdown")

# Статистика ростера
@dp.callback_query(F.data == "adm_roster_status")
async def cb_roster_status(call: CallbackQuery):
    await call.answer()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT full_name, is_registered FROM group_roster ORDER BY full_name") as cur:
            roster = await cur.fetchall()
        async with db.execute("SELECT full_name, username, is_blocked FROM users ORDER BY full_name") as cur:
            registered = await cur.fetchall()

    text = f"📊 **СПИСОК ГРУППЫ:**\nВсего в базе: **{len(roster)}** | Зашли: **{len(registered)}**\n\n"
    text += "✅ **АВТОРИЗОВАЛИСЬ:**\n"
    for idx, r in enumerate(registered, 1):
        status = " [⛔ БАН]" if r[2] == 1 else ""
        text += f"{idx}. {r[0]} ({r[1]}){status}\n"

    not_reg = [x[0] for x in roster if x[1] == 0]
    if not_reg:
        text += "\n❌ **НЕ ЗАХОДИЛИ:**\n"
        for idx, name in enumerate(not_reg, 1):
            text += f"{idx}. {name}\n"

    if len(text) > 4000:
        text = text[:4000] + "\n...список сокращен."
    await call.message.edit_text(text, reply_markup=admin_menu_kb(), parse_mode="Markdown")

# Импорт ростера списком
@dp.callback_query(F.data == "adm_import_roster")
async def cb_import_roster(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await call.message.answer("📋 Отправьте **.txt файл** со списком ФИО или скопируйте список сюда в чат:")
    await state.set_state(AdminStates.waiting_for_roster_input)

@dp.message(StateFilter(AdminStates.waiting_for_roster_input))
async def process_roster_input(message: Message, state: FSMContext):
    lines = []
    if message.document:
        file = await bot.get_file(message.document.file_id)
        f_content = await bot.download_file(file.file_path)
        lines = f_content.read().decode("utf-8").splitlines()
    elif message.text:
        lines = message.text.splitlines()

    names = [" ".join(l.strip().split()) for l in lines if len(l.strip().split()) >= 2]
    added = 0
    async with aiosqlite.connect(DB_PATH) as db:
        for name in names:
            try:
                await db.execute("INSERT OR IGNORE INTO group_roster (full_name) VALUES (?)", (name,))
                added += 1
            except Exception:
                pass
        await db.commit()

    await state.clear()
    await message.answer(f"✅ Добавлено студентов в список: **{added}**", reply_markup=admin_menu_kb())

# Экспорт ростера
@dp.callback_query(F.data == "adm_export_txt")
async def cb_export_txt(call: CallbackQuery):
    await call.answer()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT full_name, username, user_id, joined_at, is_blocked FROM users ORDER BY full_name") as cur:
            users = await cur.fetchall()
        async with db.execute("SELECT full_name FROM group_roster WHERE is_registered = 0 ORDER BY full_name") as cur:
            not_users = await cur.fetchall()

    content = f"СПИСОК ГРУППЫ ({datetime.now().strftime('%d.%m.%Y %H:%M')})\n" + "="*50 + "\n\n"
    content += f"АВТОРИЗОВАНЫ ({len(users)} чел.):\n"
    for i, u in enumerate(users, 1):
        content += f"{i}. {u[0]} | ТГ: {u[1]} | ID: {u[2]} | {u[3]}\n"
    if not_users:
        content += "\nНЕ ЗАХОДИЛИ:\n"
        for i, nu in enumerate(not_users, 1):
            content += f"{i}. {nu[0]}\n"

    doc = BufferedInputFile(content.encode("utf-8"), filename=f"roster_{datetime.now().strftime('%d_%m')}.txt")
    await call.message.answer_document(doc, caption="📁 Выгрузка списка группы.")

# Бан / Разбан
@dp.callback_query(F.data == "adm_ban")
async def cb_ban_start(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await call.message.answer("Введите **Telegram ID** для бана или разбана:")
    await state.set_state(AdminStates.waiting_for_ban_id)

@dp.message(StateFilter(AdminStates.waiting_for_ban_id))
async def process_ban(message: Message, state: FSMContext):
    try:
        t_id = int(message.text.strip())
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT is_blocked FROM users WHERE user_id = ?", (t_id,)) as cur:
                user = await cur.fetchone()
            
            if not user:
                await message.answer(f"⚠️ Пользователь с ID `{t_id}` не найден.", reply_markup=admin_menu_kb())
            else:
                new_status = 0 if user[0] == 1 else 1
                await db.execute("UPDATE users SET is_blocked = ? WHERE user_id = ?", (new_status, t_id))
                await db.commit()
                
                if new_status == 1:
                    await message.answer(f"⛔ Пользователь с ID `{t_id}` заблокирован!", reply_markup=admin_menu_kb())
                else:
                    await message.answer(f"✅ Пользователь с ID `{t_id}` разблокирован!", reply_markup=admin_menu_kb())
    except ValueError:
        await message.answer("⚠️ Введите корректный числовой Telegram ID.")
    await state.clear()

# Рассылка
@dp.callback_query(F.data == "adm_broadcast")
async def cb_broadcast_start(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await call.message.answer("📢 Введите текст объявления:")
    await state.set_state(AdminStates.waiting_for_broadcast)

@dp.message(StateFilter(AdminStates.waiting_for_broadcast))
async def process_broadcast(message: Message, state: FSMContext):
    text = f"📢 **ИНФОРМАЦИЯ:**\n\n{message.text.strip()}"
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id FROM users WHERE is_blocked = 0") as cur:
            users = await cur.fetchall()

    for u in users:
        try:
            await bot.send_message(u[0], text, parse_mode="Markdown")
            await asyncio.sleep(0.05)
        except Exception:
            pass

    await state.clear()
    await message.answer("✅ Отправлено всей группе!", reply_markup=admin_menu_kb())

# ================= ТОЧКА ВХОДА =================
async def main():
    await init_db()
    
    scheduler = AsyncIOScheduler(timezone=TIMEZONE)
    scheduler.add_job(send_daily_hw_reminder, "cron", hour=19, minute=0)
    scheduler.start()

    await bot.delete_webhook(drop_pending_updates=True)
    print("🚀 Система учебной группы успешно запущена!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
