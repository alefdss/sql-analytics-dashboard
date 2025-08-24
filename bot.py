import asyncio
import asyncpg
import httpx
import json
import re
import uuid
import os
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from aiogram.filters import Command

# Загружаем переменные окружения
load_dotenv()

API_TOKEN = os.getenv("API_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

DB_USER = os.getenv("POSTGRES_USER")
DB_PASSWORD = os.getenv("POSTGRES_PASSWORD")
DB_NAME = os.getenv("POSTGRES_DB")
DB_HOST = os.getenv("POSTGRES_HOST", "localhost")
DB_PORT = int(os.getenv("POSTGRES_PORT", 5432))

bot = Bot(token=API_TOKEN)
dp = Dispatcher()

questions = [
    {"id": 1, "text": "Как вы оцениваете свою продуктивность сегодня?", "type": "scale_1_5"},
    {"id": 2, "text": "Сколько часов вы посвятили работе или учебе сегодня?", "type": "choice",
     "options": ["<2", "2–4", "4–6", ">6"]},
    {"id": 3, "text": "Как часто вы отвлекались на соцсети или посторонние дела?", "type": "scale_1_5"},
    {"id": 4, "text": "Какое у вас было настроение большую часть дня?", "type": "scale_1_5"},
    {"id": 5, "text": "Чувствовали ли вы стресс или тревогу сегодня?", "type": "scale_1_5"},
    {"id": 6, "text": "Как вы оцениваете свой уровень энергии сегодня?", "type": "scale_1_5"},
    {"id": 7, "text": "Сколько часов вы спали прошлой ночью?", "type": "choice",
     "options": ["<5", "5–6", "6–8", ">8"]},
    {"id": 8, "text": "Уделяли ли вы время физической активности сегодня?", "type": "choice",
     "options": ["Да, более 30 мин", "Да, менее 30 мин", "Нет"]},
    {"id": 9, "text": "Сколько воды вы выпили за день?", "type": "choice",
     "options": ["<1 л", "1–2 л", ">2 л"]},
    {"id": 10, "text": "Медитировали, читали или занимались релаксацией сегодня?", "type": "choice",
     "options": ["Да", "Нет"]}
]

# состояния пользователя
user_states = {}
db_pool = None

start_polling_kb = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="Пройти опрос")]], resize_keyboard=True
)

async def init_db_pool():
    global db_pool
    db_pool = await asyncpg.create_pool(
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        host=DB_HOST,
        port=DB_PORT
    )

async def create_tables():
    async with db_pool.acquire() as conn:
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS users (user_id BIGINT PRIMARY KEY);
        """)
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS responses (
            id SERIAL PRIMARY KEY,
            user_id BIGINT REFERENCES users(user_id),
            question_id INT NOT NULL,
            answer TEXT NOT NULL,
            survey_id UUID NOT NULL,
            created_at TIMESTAMP DEFAULT now()
        );
        """)

def get_keyboard(q):
    if q["type"] == "scale_1_5":
        return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=str(i)) for i in range(1, 6)]], resize_keyboard=True)
    elif q["type"] == "choice":
        return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=opt)] for opt in q["options"]], resize_keyboard=True)
    return None

def clean_report(text: str) -> str:
    text = re.sub(r'^\s*\*\s+', '• ', text, flags=re.MULTILINE)
    text = re.sub(r'\*\*(.*?)\*\*', r'\1', text)
    text = re.sub(r'^#{1,6}\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'([А-Яа-яA-Za-z0-9])\:([^\s])', r'\1: \2', text)

    lines = text.splitlines()
    cleaned = []
    headers = ["Отчёт о состоянии пользователя", "Общий вывод:", "Рекомендации:",
               "Настроение 😄:", "Продуктивность 📈:", "Энергия ⚡️:"]
    for line in lines:
        line = line.strip()
        if line in headers:
            if cleaned and cleaned[-1] != "": cleaned.append("")
            cleaned.append(line); cleaned.append("")
        elif line != "":
            cleaned.append(line)
        else:
            if cleaned and cleaned[-1] != "": cleaned.append("")
    return "\n".join(cleaned)

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    survey_id = str(uuid.uuid4())
    user_states[user_id] = {"q_index": 0, "survey_id": survey_id}

    async with db_pool.acquire() as conn:
        await conn.execute("INSERT INTO users (user_id) VALUES ($1) ON CONFLICT DO NOTHING", user_id)

    await message.answer(
        f"Привет, {message.from_user.first_name}! 👋\n\n"
        "Я бот для отслеживания вашей продуктивности, настроения и привычек.\n\n"
        "Отвечайте на 10 коротких вопросов с помощью кнопок.\n\n"
        "В конце вы получите аналитический отчёт с практическими рекомендациями.\n\nНачнем!",
        reply_markup=ReplyKeyboardRemove()
    )
    await message.answer(questions[0]["text"], reply_markup=get_keyboard(questions[0]))

@dp.message(Command("results"))
async def cmd_results(message: types.Message):
    user_id = message.from_user.id
    async with db_pool.acquire() as conn:
        survey_row = await conn.fetchrow("""
            SELECT survey_id
            FROM responses
            WHERE user_id = $1
            ORDER BY created_at DESC
            LIMIT 1
        """, user_id)

        if not survey_row:
            await message.answer("Пока нет данных для отчёта 🙃 Нажми «Пройти опрос».")
            return

        survey_id = survey_row["survey_id"]
        rows = await conn.fetch("""
            SELECT question_id, answer
            FROM responses
            WHERE user_id = $1 AND survey_id = $2
            ORDER BY id
        """, user_id, survey_id)

    if not rows:
        await message.answer("Ответов по последнему опросу не найдено 😕")
        return

    user_data = [
        f"Вопрос: {next(q['text'] for q in questions if q['id']==row['question_id'])} Ответ: {row['answer']}"
        for row in rows
    ]

    prompt_text = (
        "Сделай отчёт о состоянии пользователя на основе данных **за один день** (только этот набор ответов).\n"
        "Добавь общий вывод в начале и рекомендации в категориях: Настроение 😄, Продуктивность 📈, Энергия ⚡️.\n"
        "Каждую рекомендацию оформи в виде списка с • и добавь пустые строки между блоками.\n\n"
        + "\n\n".join(user_data)
    )

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            json_data = {"contents": [{"parts": [{"text": prompt_text}]}]}
            response = await client.post(
                "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent",
                headers={"Content-Type": "application/json", "X-goog-api-key": GEMINI_API_KEY},
                content=json.dumps(json_data, ensure_ascii=False).encode("utf-8")
            )
            result_json = response.json()
            candidates = result_json.get("candidates", [])
            if candidates and "content" in candidates[0]:
                gemini_text = "\n".join([part.get("text", "") for part in candidates[0]["content"].get("parts", [])])
            else:
                gemini_text = "❌ Ошибка: не удалось получить отчёт от Gemini."
    except Exception as e:
        gemini_text = "❌ Ошибка при генерации отчёта: " + str(e)

    await message.answer("📝 Ваш отчёт по последнему опросу:")
    await message.answer(clean_report(gemini_text))

@dp.message()
async def process_answer(message: types.Message):
    user_id = message.from_user.id

    if message.text == "Пройти опрос":
        await cmd_start(message)
        return

    if user_id not in user_states:
        await message.answer("Напиши /start чтобы начать опрос.")
        return

    q_index = user_states[user_id]["q_index"]
    survey_id = user_states[user_id]["survey_id"]
    q = questions[q_index]

    if (q["type"] == "scale_1_5" and message.text not in [str(i) for i in range(1, 6)]) or \
       (q["type"] == "choice" and message.text not in q["options"]):
        await message.answer("Пожалуйста, выберите вариант с кнопок ниже.", reply_markup=get_keyboard(q))
        return

    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO responses (user_id, question_id, answer, survey_id) VALUES ($1, $2, $3, $4)",
            user_id, q["id"], message.text, survey_id
        )

    q_index += 1
    if q_index < len(questions):
        user_states[user_id]["q_index"] = q_index
        await message.answer(questions[q_index]["text"], reply_markup=get_keyboard(questions[q_index]))
    else:
        await message.answer("Генерация отчёта... ⏳", reply_markup=ReplyKeyboardRemove())

        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT question_id, answer FROM responses WHERE user_id = $1 AND survey_id = $2 ORDER BY id",
                user_id, survey_id
            )

        user_data = [f"Вопрос: {next(q['text'] for q in questions if q['id']==row['question_id'])} Ответ: {row['answer']}" for row in rows]

        prompt_text = (
            "Сделай отчёт о состоянии пользователя на основе данных **за один день**.\n"
            "Добавь общий вывод в начале и рекомендации в категориях: Настроение 😄, Продуктивность 📈, Энергия ⚡️.\n"
            "Каждую рекомендацию оформи в виде списка с • и добавь пустые строки между блоками.\n\n"
            + "\n\n".join(user_data)
        )

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                json_data = {"contents": [{"parts": [{"text": prompt_text}]}]}
                response = await client.post(
                    "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent",
                    headers={"Content-Type": "application/json", "X-goog-api-key": GEMINI_API_KEY},
                    content=json.dumps(json_data, ensure_ascii=False).encode("utf-8")
                )
                result_json = response.json()
                candidates = result_json.get("candidates", [])
                if candidates and "content" in candidates[0]:
                    gemini_text = "\n".join([part.get("text", "") for part in candidates[0]["content"].get("parts", [])])
                else:
                    gemini_text = "❌ Ошибка: не удалось получить отчёт от Gemini."
        except Exception as e:
            gemini_text = "❌ Ошибка при генерации отчёта: " + str(e)

        await message.answer("📝 Ваш отчёт и рекомендации:")
        await message.answer(clean_report(gemini_text))
        del user_states[user_id]
        await message.answer("Вы можете пройти опрос снова:", reply_markup=start_polling_kb)

async def main():
    await init_db_pool()
    await create_tables()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
