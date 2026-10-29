import os
import re
import time
import asyncio
from fastapi import FastAPI, Request
from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, ContextTypes
import uvicorn

# Your bot token (BotFather) — hardcoded
TOKEN = os.environ.get(
    "TELEGRAM_TOKEN",
    "9157334172:AAHUQaT6mA1OWWzIXBZg2SbeYTwWb8BF6-o",
)
BOT = Bot(token=TOKEN)
SESSIONS = {}  # phone -> (chat_id, expiry)
OTP_RE = re.compile(r"\b(\d{4,8})\b")
PORT = int(os.environ.get("PORT", 10000))

app = FastAPI()

def norm(p: str) -> str:
    return re.sub(r"[^\d+]", "", p)

def set_session(phone: str, chat_id: int, ttl=900):
    SESSIONS[norm(phone)] = (chat_id, time.time() + ttl)

def pop_expired():
    now = time.time()
    for k in list(SESSIONS.keys()):
        if SESSIONS[k][1] < now:
            SESSIONS.pop(k, None)

@app.get("/")
def health():
    return {"ok": True, "sessions": len(SESSIONS)}

@app.post("/sms")
async def sms_in(req: Request):
    pop_expired()
    form = await req.form()
    data = dict(form) if form else {}
    if not data:
        try:
            data = await req.json()
        except Exception:
            data = {}
    to = norm(str(data.get("To") or data.get("to") or ""))
    body = str(data.get("Body") or data.get("body") or data.get("text") or "")
    for phone, (chat_id, exp) in list(SESSIONS.items()):
        if phone[-10:] in to or to.endswith(phone[-10:]) or phone in to:
            if time.time() > exp:
                SESSIONS.pop(phone, None)
                continue
            m = OTP_RE.search(body)
            if m:
                code = m.group(1)
                await BOT.send_message(chat_id, f"OTP: {code}\nRaw: {body}")
                return {"ok": True, "forwarded": code}
    return {"ok": True, "forwarded": None}

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Commands:\n/listen +1NUMBER — capture OTPs for 15m\n/stop — clear\n/status"
    )

async def cmd_listen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /listen +15551234567")
        return
    phone = norm(context.args[0])
    set_session(phone, update.effective_chat.id)
    await update.message.reply_text(f"Listening on {phone} for 15 minutes")

async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    for p, (c, _) in list(SESSIONS.items()):
        if c == cid:
            SESSIONS.pop(p, None)
    await update.message.reply_text("Stopped all listens for you")

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pop_expired()
    mine = [p for p, (c, _) in SESSIONS.items() if c == update.effective_chat.id]
    await update.message.reply_text(f"Active: {mine or 'none'}")

tg_app = None

@app.on_event("startup")
async def startup():
    global tg_app
    tg_app = Application.builder().token(TOKEN).build()
    tg_app.add_handler(CommandHandler("start", cmd_start))
    tg_app.add_handler(CommandHandler("listen", cmd_listen))
    tg_app.add_handler(CommandHandler("stop", cmd_stop))
    tg_app.add_handler(CommandHandler("status", cmd_status))
    await tg_app.initialize()
    await tg_app.start()
    await tg_app.updater.start_polling(drop_pending_updates=True)

@app.on_event("shutdown")
async def shutdown():
    if tg_app:
        await tg_app.updater.stop()
        await tg_app.stop()
        await tg_app.shutdown()

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, reload=False)
