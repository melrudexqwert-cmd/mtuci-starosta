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
ADMIN_ID = 1154469594  # Твой цифровой Telegram ID (узнать в @userinfobot)
DB_PATH = "group_study.db"

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# Дни недели и месяцы на русском
RU_DAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
RU_MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", 
             "июля", "августа", "сентября", "октября", "ноября", "декабря"]

# ТОЧНЫЙ СПИСОК ПРЕДМЕТОВ С ИКОНКАМИ (1 КУРС СПО 11.02.18)
SUBJECTS = {
    "Математика": "📐",
    "Физика": "⚡",
    "Информатика": "💻",
    "Русский язык": "✍️",
    "Литература": "📚",
    "Иностранный язык": "🇬🇧",
    "История": "🏛",
    "Обществознание": "⚖️",
    "ОБЗР": "🛡",
    "Химия": "🧪",
    "Биология": "🧬",
    "География": "🌍",
    "Родной язык": "🗣",
    "Проектная деятельность": "💡"
}

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

class AdminStates(StatesGroup):
    waiting_for_ban_id = State()
    waiting_for_unban_id = State()
    waiting_for_broadcast = State()
    waiting_for_roster_input = State()

# ================= ИНИЦИАЛИЗАЦИЯ БАЗЫ ДАННЫХ =================
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
            INSERT OR IGNORE INTO group_roster (full_name) VALUES ('Хамедов Даниил Алексеевич')
        """)
        await db.commit()

# ================= КЛАВИАТУРЫ =================
def main_menu_kb(is_admin: bool = False):
    kb = [
        [InlineKeyboardButton(text="📚 Домашние задания", callback_data="hw_view")],
        [
            InlineKeyboardButton(text="📖 Учебники", callback_data="books_view"),
            InlineKeyboardButton(text="📅 Расписание", url="https://t.me/vvfsched_bot")
        ],
        [InlineKeyboardButton(text="👤 Мой профиль", callback_data="user_profile")]
    ]
    if is_admin:
        kb.append([InlineKeyboardButton(text="⚙️ Панель управления", callback_data="admin_menu")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def admin_menu_kb():
    kb = [
        [InlineKeyboardButton(text="➕ Добавить ДЗ", callback_data="adm_add_hw")],
        [InlineKeyboardButton(text="📁 Добавить учебник", callback_data="adm_add_book")],
        [InlineKeyboardButton(text="👥 Список группы (кто зашел / нет)", callback_data="adm_roster_status")],
        [InlineKeyboardButton(text="📋 Загрузить список группы", callback_data="adm_import_roster")],
        [InlineKeyboardButton(text="📥 Выгрузить список (.txt)", callback_data="adm_export_txt")],
        [
            InlineKeyboardButton(text="🚫 Блокировка", callback_data="adm_ban"),
            InlineKeyboardButton(text="✅ Разблокировка", callback_data="adm_unban")
        ],
        [InlineKeyboardButton(text="📢 Информация для группы", callback_data="adm_broadcast")],
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
        btn_text = f"{icon} {sub}"
        row.append(InlineKeyboardButton(text=btn_text, callback_data=f"{prefix}:{sub}"))
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
    
    kb.append([InlineKeyboardButton(text=label_tom, callback_data=f"dl_val:{label_tom}")])
    kb.append([InlineKeyboardButton(text=label_after, callback_data=f"dl_val:{label_after}")])
    
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


# ================= СТАРТ И АВТОРИЗАЦИЯ ПО ФИО =================
@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT full_name, is_admin, is_blocked FROM users WHERE user_id = ?", (user_id,)) as cur:
            user = await cur.fetchone()

    if user:
        if user[2] == 1:
            await message.answer("⛔ Доступ к боту ограничен администратором.")
            return
        is_admin = (user[1] == 1) or (user_id == ADMIN_ID)
        await message.answer(
            f"👋 С возвращением, **{user[0]}**!\n\n"
            f"Выберите нужный раздел:",
            reply_markup=main_menu_kb(is_admin),
            parse_mode="Markdown"
        )
    else:
        reg_text = "👋 Привет! Это бот группы для домашних заданий и учебных материалов.\n\n📝 **Для доступа напиши свои Фамилию Имя Отчество**:\n*(Пример: Хамедов Даниил Алексеевич)*"
        await message.answer(reg_text, parse_mode="Markdown")
        await state.set_state(RegStates.waiting_for_fio)

@dp.message(StateFilter(RegStates.waiting_for_fio))
async def process_fio(message: Message, state: FSMContext):
    fio = " ".join(message.text.strip().split())
    
    if len(fio.split()) < 2:
        await message.answer("⚠️ Пожалуйста, укажи как минимум Фамилию и Имя:")
        return

    user_id = message.from_user.id
    username = f"@{message.from_user.username}" if message.from_user.username else "без_ника"
    now_str = datetime.now().strftime("%d.%m.%Y %H:%M")

    is_admin = (
        user_id == ADMIN_ID or 
        fio.lower() == "хамедов даниил алексеевич" or
        fio.lower() == "хамедов даниил"
    )

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO users (user_id, username, full_name, is_admin, is_blocked, joined_at)
            VALUES (?, ?, ?, ?, 0, ?)
            ON CONFLICT(user_id) DO UPDATE SET full_name = ?, is_admin = ?
        """, (user_id, username, fio, 1 if is_admin else 0, now_str, fio, 1 if is_admin else 0))
        
        await db.execute("""
            INSERT INTO group_roster (full_name, is_registered, user_id)
            VALUES (?, 1, ?)
            ON CONFLICT(group_roster.full_name) DO UPDATE SET is_registered = 1, user_id = ?
        """, (fio, user_id, user_id))
        
        await db.commit()

    await state.clear()
    
    await message.answer(
        f"✅ Регистрация успешно завершена!\n👤 Студент: **{fio}**",
        reply_markup=main_menu_kb(is_admin),
        parse_mode="Markdown"
    )

    if not is_admin and ADMIN_ID:
        try:
            await bot.send_message(
                ADMIN_ID,
                f"🔔 **Новый студент в системе!**\n👤 ФИО: {fio}\n📱 ТГ: {username}\n🆔 ID: `{user_id}`",
                parse_mode="Markdown"
            )
        except Exception:
            pass


# ================= РАЗДЕЛ: ПРОСМОТР ДЗ =================
@dp.callback_query(F.data == "hw_view")
async def cb_hw_view(call: CallbackQuery):
    await call.answer()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT subject, task, deadline, created_at FROM homework ORDER BY id DESC LIMIT 7") as cur:
            rows = await cur.fetchall()

    if not rows:
        text = "🌴 **На данный момент актуальных заданий нет.** Всё чисто!"
    else:
        text = "📚 **АКТУАЛЬНЫЕ ДОМАШНИЕ ЗАДАНИЯ:**\n\n"
        for r in rows:
            icon = SUBJECTS.get(r[0], "📖")
            text += f"{icon} **{r[0]}**\n📝 **Задание:** {r[1]}\n⏳ **Срок сдачи:** `{r[2]}`\n───────────────\n"

    await call.message.edit_text(text, reply_markup=back_to_main_kb(), parse_mode="Markdown")


# ================= РАЗДЕЛ: УЧЕБНИКИ =================
@dp.callback_query(F.data == "books_view")
async def cb_books_view(call: CallbackQuery):
    await call.answer()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id, subject, title FROM books ORDER BY id DESC") as cur:
            books = await cur.fetchall()

    if not books:
        await call.message.edit_text(
            "📖 **Раздел учебников пуст.**\nМатериалы ещё не загружены.",
            reply_markup=back_to_main_kb(),
            parse_mode="Markdown"
        )
        return

    kb = []
    for b in books:
        icon = SUBJECTS.get(b[1], "📖")
        kb.append([InlineKeyboardButton(text=f"{icon} {b[1]}: {b[2]}", callback_data=f"get_book:{b[0]}")])
    kb.append([InlineKeyboardButton(text="⬅️ Главное меню", callback_data="to_main_menu")])

    await call.message.edit_text(
        "📖 **Учебники и материалы:**\nНажмите на нужный предмет для скачивания:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb),
        parse_mode="Markdown"
    )

@dp.callback_query(F.data.startswith("get_book:"))
async def cb_get_book(call: CallbackQuery):
    book_id = int(call.data.split(":")[1])
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT title, file_id, subject FROM books WHERE id = ?", (book_id,)) as cur:
            b = await cur.fetchone()

    if b:
        await call.answer("Отправляю файл...")
        icon = SUBJECTS.get(b[2], "📖")
        await call.message.answer_document(document=b[1], caption=f"{icon} **{b[2]}**: {b[0]}")
    else:
        await call.answer("Файл не найден.", show_alert=True)


# ================= ПРОФИЛЬ =================
@dp.callback_query(F.data == "user_profile")
async def cb_profile(call: CallbackQuery):
    await call.answer()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT full_name, joined_at FROM users WHERE user_id = ?", (call.from_user.id,)) as cur:
            u = await cur.fetchone()

    await call.message.edit_text(
        f"👤 **Карточка студента:**\n\n• **ФИО:** {u[0]}\n• **Дата входа:** {u[1]}\n• **Статус:** Активен ✅",
        reply_markup=back_to_main_kb(),
        parse_mode="Markdown"
    )

@dp.callback_query(F.data == "to_main_menu")
async def cb_to_main(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await state.clear()
    is_admin = False
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT is_admin FROM users WHERE user_id = ?", (call.from_user.id,)) as cur:
            u = await cur.fetchone()
            if u and (u[0] == 1 or call.from_user.id == ADMIN_ID):
                is_admin = True

    await call.message.edit_text("Главное меню:", reply_markup=main_menu_kb(is_admin))


# ================= ПАНЕЛЬ УПРАВЛЕНИЯ (АДМИНКА) =================
@dp.callback_query(F.data == "admin_menu")
async def cb_admin_menu(call: CallbackQuery):
    is_admin = False
    if call.from_user.id == ADMIN_ID:
        is_admin = True
    else:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT is_admin FROM users WHERE user_id = ?", (call.from_user.id,)) as cur:
                u = await cur.fetchone()
                if u and u[0] == 1:
                    is_admin = True

    if not is_admin:
        await call.answer("Доступ ограничен.", show_alert=True)
        return

    await call.answer()
    await call.message.edit_text(
        "⚙️ **Панель управления группой:**\nВыберите действие:",
        reply_markup=admin_menu_kb(),
        parse_mode="Markdown"
    )


# --- 1. ДОБАВЛЕНИЕ ДЗ ---
@dp.callback_query(F.data == "adm_add_hw")
async def cb_add_hw(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await call.message.edit_text(
        "📖 **Выберите предмет из списка:**",
        reply_markup=subjects_selection_kb("sub_hw")
    )
    await state.set_state(AddHwStates.waiting_for_subject_choice)

@dp.callback_query(StateFilter(AddHwStates.waiting_for_subject_choice), F.data.startswith("sub_hw:"))
async def cb_hw_subject_selected(call: CallbackQuery, state: FSMContext):
    await call.answer()
    subject_name = call.data.split(":")[1]
    await state.update_data(subject=subject_name)
    icon = SUBJECTS.get(subject_name, "📖")
    
    await call.message.edit_text(
        f"{icon} Предмет: **{subject_name}**\n\n📝 Теперь напишите **само задание** (номера задач, страницы):",
        parse_mode="Markdown"
    )
    await state.set_state(AddHwStates.waiting_for_task)

@dp.message(StateFilter(AddHwStates.waiting_for_task))
async def hw_task_input(message: Message, state: FSMContext):
    await state.update_data(task=message.text.strip())
    await message.answer("⏳ **Выберите дату сдачи кнопкой:**", reply_markup=deadline_selection_kb())
    await state.set_state(AddHwStates.waiting_for_deadline_choice)

@dp.callback_query(StateFilter(AddHwStates.waiting_for_deadline_choice), F.data.startswith("dl_val:"))
async def hw_deadline_chosen(call: CallbackQuery, state: FSMContext):
    await call.answer()
    deadline = call.data.replace("dl_val:", "")
    data = await state.get_data()
    subject = data["subject"]
    task = data["task"]
    created = datetime.now().strftime("%d.%m.%Y")
    icon = SUBJECTS.get(subject, "📖")

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO homework (subject, task, deadline, created_at) VALUES (?, ?, ?, ?)",
            (subject, task, deadline, created)
        )
        await db.commit()
        
        async with db.execute("SELECT user_id FROM users WHERE is_blocked = 0") as cur:
            students = await cur.fetchall()

    await state.clear()
    await call.message.edit_text("✅ Задание сохранено! Рассылаю уведомления всей группе...")

    alert_msg = f"🚨 **НОВОЕ ДОМАШНЕЕ ЗАДАНИЕ!**\n\n{icon} **Предмет:** {subject}\n📝 **Задание:** {task}\n⏳ **Сдать до:** `{deadline}`\n"

    sent = 0
    for s in students:
        try:
            await bot.send_message(s[0], alert_msg, parse_mode="Markdown")
            sent += 1
            await asyncio.sleep(0.05)
        except Exception:
            pass

    await call.message.answer(
        f"🚀 Уведомление доставлено: **{sent}** студентам!",
        reply_markup=admin_menu_kb(),
        parse_mode="Markdown"
    )


# --- 2. ДОБАВЛЕНИЕ УЧЕБНИКА ---
@dp.callback_query(F.data == "adm_add_book")
async def cb_add_book_start(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await call.message.edit_text(
        "📖 **Выберите предмет для учебника:**",
        reply_markup=subjects_selection_kb("sub_book")
    )
    await state.set_state(BookStates.waiting_for_subject_choice)

@dp.callback_query(StateFilter(BookStates.waiting_for_subject_choice), F.data.startswith("sub_book:"))
async def cb_book_subject_selected(call: CallbackQuery, state: FSMContext):
    await call.answer()
    subject_name = call.data.split(":")[1]
    await state.update_data(subject=subject_name)
    icon = SUBJECTS.get(subject_name, "📖")
    
    await call.message.edit_text(
        f"{icon} Предмет: **{subject_name}**\n\n📖 Введите краткое **название книги / части** (например: *Часть 1 (Боголюбов)*):",
        parse_mode="Markdown"
    )
    await state.set_state(BookStates.waiting_for_name)

@dp.message(StateFilter(BookStates.waiting_for_name))
async def process_book_name(message: Message, state: FSMContext):
    await state.update_data(book_title=message.text.strip())
    await message.answer("📄 Теперь отправьте **PDF файл** учебника сюда:")
    await state.set_state(BookStates.waiting_for_file)

@dp.message(StateFilter(BookStates.waiting_for_file), F.document)
async def process_book_file(message: Message, state: FSMContext):
    data = await state.get_data()
    subject = data["subject"]
    title = data["book_title"]
    file_id = message.document.file_id
    file_name = message.document.file_name
    icon = SUBJECTS.get(subject, "📖")

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO books (subject, title, file_id, file_name) VALUES (?, ?, ?, ?)",
            (subject, title, file_id, file_name)
        )
        await db.commit()

    await state.clear()
    await message.answer(f"✅ Учебник {icon} **{subject}: {title}** добавлен!", reply_markup=admin_menu_kb(), parse_mode="Markdown")


# --- 3. СТАТИСТИКА РОСТЕРА ---
@dp.callback_query(F.data == "adm_roster_status")
async def cb_roster_status(call: CallbackQuery):
    await call.answer()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT full_name, is_registered FROM group_roster ORDER BY full_name") as cur:
            roster = await cur.fetchall()
        async with db.execute("SELECT full_name, username, is_blocked FROM users ORDER BY full_name") as cur:
            registered = await cur.fetchall()

    reg_count = len(registered)
    roster_count = len(roster)

    text = f"📊 **СПИСОК ГРУППЫ:**\nВсего в списке: **{roster_count}** | Зашли: **{reg_count}**\n\n"
    text += "✅ **АВТОРИЗОВАЛИСЬ В БОТЕ:**\n"
    for idx, r in enumerate(registered, 1):
        status = " [⛔ БАН]" if r[2] == 1 else ""
        text += f"{idx}. {r[0]} ({r[1]}){status}\n"

    not_reg = [x[0] for x in roster if x[1] == 0]
    if not_reg:
        text += "\n❌ **НЕ ЗАХОДИЛИ В БОТА:**\n"
        for idx, name in enumerate(not_reg, 1):
            text += f"{idx}. {name}\n"
    else:
        text += "\n🎉 Все студенты из списка авторизованы!\n"

    if len(text) > 4000:
        text = text[:4000] + "\n...список сокращен."

    await call.message.edit_text(text, reply_markup=admin_menu_kb(), parse_mode="Markdown")


# --- 4. ЗАГРУЗКА СПИСКА ГРУППЫ ---
@dp.callback_query(F.data == "adm_import_roster")
async def cb_import_roster(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await call.message.answer(
        "📋 **Загрузка списка группы:**\n\nОтправьте мне **.txt файл** со списком ФИО или просто **текстовое сообщение** (каждый студент с новой строки):\n\nПример:\nИванов Иван Иванович\nПетров Петр Сергеевич\nСмирнов Алексей Игоревич"
    )
    await state.set_state(AdminStates.waiting_for_roster_input)

@dp.message(StateFilter(AdminStates.waiting_for_roster_input))
async def process_roster_input(message: Message, state: FSMContext):
    lines = []
    if message.document:
        if not message.document.file_name.endswith(".txt"):
            await message.answer("⚠️ Пожалуйста, отправьте файл в формате `.txt`")
            return
        file = await bot.get_file(message.document.file_id)
        f_content = await bot.download_file(file.file_path)
        lines = f_content.read().decode("utf-8").splitlines()
    elif message.text:
        lines = message.text.splitlines()

    names = [" ".join(l.strip().split()) for l in lines if len(l.strip().split()) >= 2]
    if not names:
        await message.answer("⚠️ Не удалось распознать ФИО. Попробуйте еще раз:")
        return

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
    await message.answer(
        f"✅ Список успешно обновлен!\nДобавлено записей: **{added}**",
        reply_markup=admin_menu_kb()
    )


# --- 5. ВЫГРУЗКА СПИСКА (.TXT) ---
@dp.callback_query(F.data == "adm_export_txt")
async def cb_export_txt(call: CallbackQuery):
    await call.answer()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT full_name, username, user_id, joined_at, is_blocked FROM users ORDER BY full_name") as cur:
            users = await cur.fetchall()
        async with db.execute("SELECT full_name FROM group_roster WHERE is_registered = 0 ORDER BY full_name") as cur:
            not_users = await cur.fetchall()

    content = f"СПИСОК ГРУППЫ (Экспорт от {datetime.now().strftime('%d.%m.%Y %H:%M')})\n"
    content += "="*50 + "\n\n"
    content += f"АВТОРИЗОВАННЫЕ В БОТЕ ({len(users)} чел.):\n"
    for i, u in enumerate(users, 1):
        st = "АКТИВЕН" if u[4] == 0 else "ЗАБЛОКИРОВАН"
        content += f"{i}. {u[0]} | ТГ: {u[1]} | ID: {u[2]} | Дата: {u[3]} | [{st}]\n"

    if not_users:
        content += "\n" + "="*50 + "\n"
        content += f"НЕ ЗАХОДИЛИ В БОТА ({len(not_users)} чел.):\n"
        for i, nu in enumerate(not_users, 1):
            content += f"{i}. {nu[0]}\n"

    doc = BufferedInputFile(content.encode("utf-8"), filename=f"spisok_gruppy_{datetime.now().strftime('%d_%m')}.txt")
    await call.message.answer_document(doc, caption="📁 Список группы в текстовом формате.")


# --- 6. БЛОКИРОВКА / РАЗБЛОКИРОВКА ---
@dp.callback_query(F.data == "adm_ban")
async def cb_ban_start(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await call.message.answer("Введите **Telegram ID** для блокировки:")
    await state.set_state(AdminStates.waiting_for_ban_id)

@dp.message(StateFilter(AdminStates.waiting_for_ban_id))
async def process_ban(message: Message, state: FSMContext):
    try:
        t_id = int(message.text.strip())
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE users SET is_blocked = 1 WHERE user_id = ?", (t_id,))
            await db.commit()
        await message.answer(f"⛔ Пользователь `{t_id}` заблокирован!", reply_markup=admin_menu_kb())
        try:
            await bot.send_message(t_id, "⛔ Доступ к боту ограничен администратором.")
        except Exception:
            pass
    except ValueError:
        await message.answer("⚠️ ID должен состоять только из цифр!")
    await state.clear()

@dp.callback_query(F.data == "adm_unban")
async def cb_unban_start(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await call.message.answer("Введите **Telegram ID** для разблокировки:")
    await state.set_state(AdminStates.waiting_for_unban_id)

@dp.message(StateFilter(AdminStates.waiting_for_unban_id))
async def process_unban(message: Message, state: FSMContext):
    try:
        t_id = int(message.text.strip())
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE users SET is_blocked = 0 WHERE user_id = ?", (t_id,))
            await db.commit()
        await message.answer(f"✅ Пользователь `{t_id}` разблокирован!", reply_markup=admin_menu_kb())
        try:
            await bot.send_message(t_id, "✅ Доступ восстановлен. Нажмите /start")
        except Exception:
            pass
    except ValueError:
        await message.answer("⚠️ ID должен состоять только из цифр!")
    await state.clear()


# --- 7. ИНФОРМАЦИЯ ДЛЯ ГРУППЫ ---
@dp.callback_query(F.data == "adm_broadcast")
async def cb_broadcast_start(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await call.message.answer("📢 Напишите текст **Информации для группы**:")
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
    await message.answer("✅ Информация отправлена всей группе!", reply_markup=admin_menu_kb())


# ================= ТОЧКА ВХОДА =================
async def main():
    await init_db()
    await bot.delete_webhook(drop_pending_updates=True)
    print("🚀 Система учебной группы успешно запущена!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
```,send_attachment_attachment_filename_2413:
