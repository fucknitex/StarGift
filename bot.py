#!/usr/bin/env python3
import os, json, time, random, sqlite3, logging, requests, threading
from datetime import datetime
from threading import Lock

BOT_TOKEN = "8426205197:AAE7LoNhVNA5WqYv3-m3lTTse9WlWcscf2s"
BOT_USERNAME = "IsayGiftBot"
ADMIN_USERNAME = "wyebu"
REFERRAL_REWARD_STEP = 25
TOPUP_OPTIONS = [10, 25, 50, 100, 250, 500]
REQUIRED_CHANNELS = [
    {"title": "IsayDev", "link": "https://t.me/+qoibIAmZWjdmOGNi", "id": None},
    {"title": "KOTVPN",  "link": "https://t.me/c4tvpn",             "id": "@c4tvpn"},
]
API = f"https://api.telegram.org/bot{BOT_TOKEN}"
DB_PATH = "isay_gift.db"
ADMIN_STATE = {}
USER_STATE  = {}
CHECK_LOCKS = {}

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)


def db_connect():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def db_scalar(conn, sql, params=()):
    row = conn.execute(sql, params).fetchone()
    return row[0] if row else None


def db_init():
    conn = db_connect()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id       INTEGER PRIMARY KEY,
            username      TEXT,
            first_name    TEXT,
            balance       REAL    DEFAULT 0,
            deposit       REAL    DEFAULT 0,
            prizes        INTEGER DEFAULT 0,
            notifications INTEGER DEFAULT 1,
            registered    TEXT    DEFAULT (date('now')),
            subscribed    INTEGER DEFAULT 0,
            referrer_id   INTEGER DEFAULT NULL,
            total_spent   REAL    DEFAULT 0,
            last_reward_level INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS gifts (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            name             TEXT    NOT NULL,
            emoji            TEXT    NOT NULL,
            price_stars      INTEGER,
            category         TEXT    DEFAULT 'regular',
            color            TEXT    DEFAULT 'dark',
            telegram_gift_id TEXT    DEFAULT NULL
        );
        CREATE TABLE IF NOT EXISTS cases (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT    NOT NULL,
            emoji       TEXT    NOT NULL,
            price_stars INTEGER,
            description TEXT,
            bear_chance REAL    NOT NULL
        );
        CREATE TABLE IF NOT EXISTS case_items (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id INTEGER NOT NULL,
            gift_id INTEGER,
            weight  INTEGER NOT NULL DEFAULT 1,
            FOREIGN KEY(case_id) REFERENCES cases(id),
            FOREIGN KEY(gift_id) REFERENCES gifts(id)
        );
        CREATE TABLE IF NOT EXISTS transactions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL,
            type        TEXT    NOT NULL,
            amount      REAL    NOT NULL,
            description TEXT,
            created_at  TEXT    DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS invoice_log (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL,
            payload    TEXT    NOT NULL,
            amount     INTEGER NOT NULL,
            status     TEXT    DEFAULT 'pending',
            created_at TEXT    DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS checks (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            code               TEXT    NOT NULL UNIQUE,
            sender_id          INTEGER NOT NULL,
            gift_id            INTEGER NOT NULL,
            recipient_username TEXT    DEFAULT NULL,
            max_activations    INTEGER NOT NULL DEFAULT 1,
            activations        INTEGER NOT NULL DEFAULT 0,
            status             TEXT    NOT NULL DEFAULT 'active',
            created_at         TEXT    DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS check_activations (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            check_id     INTEGER NOT NULL,
            user_id      INTEGER NOT NULL,
            activated_at TEXT    DEFAULT (datetime('now')),
            UNIQUE(check_id, user_id)
        );
        CREATE TABLE IF NOT EXISTS pending_rewards (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            referrer_id  INTEGER NOT NULL,
            referred_id  INTEGER NOT NULL,
            reward_level INTEGER NOT NULL,
            claimed      INTEGER DEFAULT 0,
            created_at   TEXT    DEFAULT (datetime('now')),
            UNIQUE(referrer_id, referred_id, reward_level)
        );
        CREATE INDEX IF NOT EXISTS idx_checks_code   ON checks(code);
        CREATE INDEX IF NOT EXISTS idx_checks_status ON checks(status);
    """)
    conn.commit()
    for sql in [
        "ALTER TABLE users ADD COLUMN referrer_id INTEGER DEFAULT NULL",
        "ALTER TABLE users ADD COLUMN total_spent REAL DEFAULT 0",
        "ALTER TABLE users ADD COLUMN last_reward_level INTEGER DEFAULT 0",
        "ALTER TABLE gifts ADD COLUMN telegram_gift_id TEXT DEFAULT NULL",
    ]:
        try:
            conn.execute(sql)
            conn.commit()
        except Exception:
            pass
    _seed_gifts(conn)
    _seed_cases(conn)
    conn.close()
    log.info("Database initialised")


def _seed_gifts(conn):
    if db_scalar(conn, "SELECT COUNT(*) FROM gifts") > 0:
        return
    gifts = [
        (1,  "мишка",           "🧸",  12,  "regular", "dark",  "5170233102089322756"),
        (2,  "сердце",          "💝",  12,  "regular", "dark",  "5170145012310081615"),
        (3,  "подарок",         "🎁",  25,  "regular", "dark",  "5170250947678437525"),
        (4,  "роза",            "🌹",  25,  "regular", "dark",  "5168103777563050263"),
        (5,  "торт",            "🎂",  50,  "regular", "dark",  "5170144170496491616"),
        (6,  "букет",           "💐",  50,  "regular", "dark",  "5170314324215857265"),
        (7,  "ракета",          "🚀",  50,  "regular", "dark",  "5170564780938756245"),
        (8,  "бутылка",         "🍾",  50,  "regular", "dark",  "6028601630662853006"),
        (9,  "алмаз",           "💎",  100, "regular", "dark",  "5168043875654172773"),
        (10, "кольцо",          "💍",  100, "regular", "dark",  "5170690322832818290"),
        (11, "кубок",           "🏆",  100, "regular", "dark",  "5170521118301225164"),
        (12, "ёлка",            "🎄",  55,  "special", "red",   None),
        (13, "мишка 14 февраля","🐻",   55,  "special", "blue",  None),
        (14, "сердце 14 февраля","💌",  55,  "special", "blue",  None),
        (15, "Новогодний мишка","🎅🧸", 55,  "special", "red",   None),
        (16, "мишка 8 марта",   "🌸🧸", 55,  "special", "red",   None),
        (17, "Лепрекон мишка",  "🍀🧸", 55,  "special", "green", None),
        (18, "Клоун медведь",   "🤡🧸", 55,  "special", "green", None),
        (19, "Кролик мишка",    "🐰🧸", 55,  "special", "green", None),
        (20, "Первомайский мишка","🌷🧸",55, "special", "green", None),
    ]
    for g in gifts:
        conn.execute(
            "INSERT INTO gifts (id,name,emoji,price_stars,category,color,telegram_gift_id) VALUES (?,?,?,?,?,?,?)", g
        )
    conn.commit()
    log.info("Gifts seeded")


def _seed_cases(conn):
    if db_scalar(conn, "SELECT COUNT(*) FROM cases") > 0:
        return
    conn.execute(
        "INSERT INTO cases (name,emoji,price_stars,description,bear_chance) VALUES (?,?,?,?,?)",
        ("Фарм медведя", "🌾🧸", 1, "Попробуй выиграть мишку за 1 звезду! Удачи!", 0.05)
    )
    farm_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute(
        "INSERT INTO cases (name,emoji,price_stars,description,bear_chance) VALUES (?,?,?,?,?)",
        ("Удалённые медведи", "🗑🧸", 25, "5 случайных редких медведей среди хлама. Испытай удачу!", 0.25)
    )
    rare_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    bear_row = conn.execute("SELECT id FROM gifts WHERE name='мишка' AND category='regular'").fetchone()
    if bear_row:
        conn.execute("INSERT INTO case_items (case_id,gift_id,weight) VALUES (?,?,?)", (farm_id, bear_row["id"], 5))
    conn.execute("INSERT INTO case_items (case_id,gift_id,weight) VALUES (?,NULL,?)", (farm_id, 95))

    special = conn.execute("SELECT id FROM gifts WHERE category='special'").fetchall()
    chosen = random.sample([r["id"] for r in special], min(5, len(special)))
    for gid in chosen:
        conn.execute("INSERT INTO case_items (case_id,gift_id,weight) VALUES (?,?,?)", (rare_id, gid, 5))
    base, rem = divmod(75, 11)
    for i in range(11):
        conn.execute("INSERT INTO case_items (case_id,gift_id,weight) VALUES (?,NULL,?)", (rare_id, base + (1 if i < rem else 0)))

    conn.commit()
    log.info("Cases seeded")


def tg(method, **kwargs):
    for attempt in range(3):
        try:
            r = requests.post(f"{API}/{method}", json=kwargs, timeout=30)
            return r.json()
        except Exception as e:
            log.warning(f"tg({method}) attempt {attempt+1}: {e}")
            if attempt == 2:
                return {}
            time.sleep(2)
    return {}


def send(chat_id, text, reply_markup=None, parse_mode="HTML"):
    params = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
    if reply_markup:
        params["reply_markup"] = reply_markup
    return tg("sendMessage", **params)


def edit_msg(chat_id, message_id, text, reply_markup=None, parse_mode="HTML"):
    params = {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": parse_mode}
    if reply_markup:
        params["reply_markup"] = reply_markup
    return tg("editMessageText", **params)


def answer_cb(cb_id, text="", alert=False):
    tg("answerCallbackQuery", callback_query_id=cb_id, text=text, show_alert=alert)


def send_invoice(chat_id, title, description, payload, amount_stars):
    return tg("sendInvoice", chat_id=chat_id, title=title, description=description,
              payload=payload, currency="XTR", prices=[{"label": title, "amount": amount_stars}],
              provider_token="")


def answer_pre_checkout(pq_id, ok=True, error_message=None):
    params = {"pre_checkout_query_id": pq_id, "ok": ok}
    if error_message:
        params["error_message"] = error_message
    tg("answerPreCheckoutQuery", **params)


def answer_inline(iq_id, results, cache_time=0):
    tg("answerInlineQuery", inline_query_id=iq_id,
       results=json.dumps(results), cache_time=cache_time)


def inline(rows):
    keyboard = []
    for row in rows:
        kb_row = []
        for btn in row:
            if len(btn) == 3 and btn[2] == "url":
                kb_row.append({"text": btn[0], "url": btn[1]})
            else:
                kb_row.append({"text": btn[0], "callback_data": btn[1]})
        keyboard.append(kb_row)
    return {"inline_keyboard": keyboard}


def get_check_lock(code):
    if code not in CHECK_LOCKS:
        CHECK_LOCKS[code] = Lock()
    return CHECK_LOCKS[code]


def get_or_create_user(user, referrer_id=None):
    conn = db_connect()
    uid = user["id"]
    row = conn.execute("SELECT * FROM users WHERE user_id=?", (uid,)).fetchone()
    if not row:
        conn.execute(
            "INSERT INTO users (user_id,username,first_name,referrer_id) VALUES (?,?,?,?)",
            (uid, user.get("username", ""), user.get("first_name", ""), referrer_id)
        )
        conn.commit()
        row = conn.execute("SELECT * FROM users WHERE user_id=?", (uid,)).fetchone()
        if referrer_id:
            conn.close()
            _check_referral_rewards(referrer_id, uid)
            return dict(row)
    conn.close()
    return dict(row)


def get_user(uid):
    conn = db_connect()
    row = conn.execute("SELECT * FROM users WHERE user_id=?", (uid,)).fetchone()
    conn.close()
    return dict(row) if row else None


def update_balance(uid, delta):
    conn = db_connect()
    conn.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (delta, uid))
    conn.commit()
    conn.close()


def add_transaction(uid, ttype, amount, desc=""):
    conn = db_connect()
    conn.execute(
        "INSERT INTO transactions (user_id,type,amount,description) VALUES (?,?,?,?)",
        (uid, ttype, amount, desc)
    )
    conn.commit()
    conn.close()
    if amount < 0:
        _update_spent(uid, -amount)


def _update_spent(uid, amount):
    conn = db_connect()
    conn.execute("UPDATE users SET total_spent=total_spent+? WHERE user_id=?", (amount, uid))
    conn.commit()
    row = conn.execute("SELECT referrer_id FROM users WHERE user_id=?", (uid,)).fetchone()
    conn.close()
    if row and row["referrer_id"]:
        _check_referral_rewards(row["referrer_id"], uid)


def _check_referral_rewards(referrer_id, referred_id):
    conn = db_connect()
    row = conn.execute(
        "SELECT total_spent, last_reward_level FROM users WHERE user_id=?", (referred_id,)
    ).fetchone()
    if not row:
        conn.close()
        return
    new_rewards = int(row["total_spent"] // REFERRAL_REWARD_STEP) - row["last_reward_level"]
    if new_rewards <= 0:
        conn.close()
        return
    conn.execute(
        "UPDATE users SET last_reward_level=last_reward_level+? WHERE user_id=?",
        (new_rewards, referred_id)
    )
    for i in range(new_rewards):
        level = row["last_reward_level"] + i + 1
        try:
            conn.execute(
                "INSERT OR IGNORE INTO pending_rewards (referrer_id,referred_id,reward_level) VALUES (?,?,?)",
                (referrer_id, referred_id, level)
            )
        except Exception:
            pass
    conn.commit()
    conn.close()
    ref_user = get_user(referred_id)
    ref_name = f"@{ref_user['username']}" if ref_user and ref_user.get("username") else f"#{referred_id}"
    send(referrer_id,
         f"🎉 <b>Реферальная награда!</b>\n\n{ref_name} потратил ещё {REFERRAL_REWARD_STEP}⭐!\n"
         f"Доступно наград: <b>{new_rewards}</b>\n\nЗабери в профиле!",
         inline([[("🎁 Забрать награды", f"claim_rewards_{referrer_id}")]]))


def add_prize(uid):
    conn = db_connect()
    conn.execute("UPDATE users SET prizes=prizes+1 WHERE user_id=?", (uid,))
    conn.commit()
    conn.close()


def is_admin(username):
    return bool(username) and username.lower() == ADMIN_USERNAME.lower()


def check_subscription(uid):
    for ch in REQUIRED_CHANNELS:
        if not ch["id"]:
            continue
        try:
            r = tg("getChatMember", chat_id=ch["id"], user_id=uid)
            if r.get("result", {}).get("status", "left") in ("left", "kicked", "banned"):
                return False
        except Exception:
            pass
    return True


def get_pending_rewards_count(uid):
    conn = db_connect()
    count = db_scalar(conn, "SELECT COUNT(*) FROM pending_rewards WHERE referrer_id=? AND claimed=0", (uid,)) or 0
    conn.close()
    return count


def get_pending_rewards_list(uid):
    conn = db_connect()
    rows = conn.execute(
        "SELECT id,referred_id,reward_level FROM pending_rewards WHERE referrer_id=? AND claimed=0", (uid,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def claim_reward(referrer_id, reward_id):
    conn = db_connect()
    row = conn.execute(
        "SELECT referred_id FROM pending_rewards WHERE id=? AND referrer_id=? AND claimed=0",
        (reward_id, referrer_id)
    ).fetchone()
    if not row:
        conn.close()
        return None
    conn.execute("UPDATE pending_rewards SET claimed=1 WHERE id=?", (reward_id,))
    conn.commit()
    conn.close()
    return row["referred_id"]


def send_reward_gift(uid, gift_type):
    gift_id = 1 if gift_type == "bear" else 2
    conn = db_connect()
    gift = conn.execute("SELECT * FROM gifts WHERE id=?", (gift_id,)).fetchone()
    conn.close()
    if gift:
        return _deliver_gift(uid, dict(gift), uid, silent=False)
    return False


def _deliver_gift(uid, gift, chat_id, silent=False):
    tg_id = gift.get("telegram_gift_id")
    if not tg_id and gift.get("id"):
        conn = db_connect()
        row = conn.execute("SELECT telegram_gift_id FROM gifts WHERE id=?", (gift["id"],)).fetchone()
        conn.close()
        if row:
            tg_id = row["telegram_gift_id"]
    if not tg_id:
        send(chat_id, f"❌ Подарок {gift.get('name')} не привязан к Telegram")
        return False
    result = tg("sendGift", user_id=uid, gift_id=tg_id, text=f"держи {gift.get('name')} от Исая")
    if result.get("ok"):
        if not silent:
            send(chat_id, f"🎁 {gift['emoji']} {gift['name']} отправлен!")
        return True
    err = result.get("description", "ошибка")
    update_balance(uid, gift.get("price_stars") or 0)
    add_transaction(uid, "refund", gift.get("price_stars") or 0, "Возврат")
    send(chat_id, f"❌ Ошибка: {err}\n💰 Средства возвращены")
    return False


def weighted_choice(items, weights):
    total = sum(weights)
    r = random.uniform(0, total)
    cum = 0
    for item, w in zip(items, weights):
        cum += w
        if r <= cum:
            return item
    return items[-1]


def spin_case(uid, case_id, chat_id, payment_method="balance"):
    conn = db_connect()
    case = conn.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone()
    user = conn.execute("SELECT * FROM users WHERE user_id=?", (uid,)).fetchone()
    if not case:
        conn.close()
        return
    if payment_method == "balance":
        if user["balance"] < case["price_stars"]:
            conn.close()
            send(chat_id, f"❌ Не хватает {case['price_stars']}⭐ на балансе!")
            return
        conn.execute("UPDATE users SET balance=balance-? WHERE user_id=?", (case["price_stars"], uid))
        conn.commit()
        add_transaction(uid, "case_open", -case["price_stars"], f"Кейс: {case['name']}")
    items = conn.execute(
        "SELECT ci.weight,ci.gift_id,g.name,g.emoji,g.category FROM case_items ci "
        "LEFT JOIN gifts g ON g.id=ci.gift_id WHERE ci.case_id=?", (case_id,)
    ).fetchall()
    conn.close()
    if not items:
        return
    item_list = [dict(i) for i in items]
    won = weighted_choice(item_list, [i["weight"] for i in item_list])
    reel = [random.choice(item_list) for _ in range(8)]
    reel[5] = won
    msg = send(chat_id, "🎰 Прокрутка...")
    msg_id = msg.get("result", {}).get("message_id")
    if not msg_id:
        return

    def label(it):
        return "💨 Ничего" if it.get("gift_id") is None else f"{it['emoji']} {it['name']}"

    for i in range(1, 9):
        frame = "🎰 <b>Прокрутка...</b>\n\n" + "\n".join(f"  {label(f)}" for f in reel[:i][-4:]) + "\n\n⏳ " + "▓" * i + "░" * (8 - i)
        edit_msg(chat_id, msg_id, frame)
        time.sleep(0.4)

    if won.get("gift_id") is None:
        result_text = "🎰 <b>Результат!</b>\n\n💨 <b>Ничего</b>"
    elif won.get("category") == "special":
        result_text = f"🎰 <b>Результат!</b>\n\n🎉 {won['emoji']} {won['name']}\n\n🧸 Поздравляем!"
        add_prize(uid)
        _deliver_gift(uid, won, chat_id)
    else:
        result_text = f"🎰 <b>Результат!</b>\n\n😢 {won['emoji']} {won['name']}"

    edit_msg(chat_id, msg_id, result_text, inline([
        [(f"🎰 Ещё ({case['price_stars']}⭐)", f"open_case_{case_id}")],
        [("◀️ В меню", "main_menu")],
    ]))


def purchase_gift_balance(chat_id, uid, gift_id):
    conn = db_connect()
    gift = conn.execute("SELECT * FROM gifts WHERE id=?", (gift_id,)).fetchone()
    user = conn.execute("SELECT * FROM users WHERE user_id=?", (uid,)).fetchone()
    if not gift or not user or user["balance"] < gift["price_stars"]:
        conn.close()
        send(chat_id, "❌ Не хватает Stars!")
        return
    conn.execute("UPDATE users SET balance=balance-?,prizes=prizes+1 WHERE user_id=?", (gift["price_stars"], uid))
    conn.commit()
    conn.close()
    add_transaction(uid, "gift_purchase", -gift["price_stars"], f"Покупка: {gift['name']}")
    if _deliver_gift(uid, dict(gift), chat_id, silent=True):
        send(chat_id, f"✅ {gift['emoji']} {gift['name']} отправлен!", inline([
            [("🎁 Купить ещё", "buy_gifts")],
            [("◀️ В меню", "main_menu")],
        ]))


def set_admin_state(uid, action, step=1, data=None):
    ADMIN_STATE[uid] = {"action": action, "step": step, "data": data or {}}

def clear_admin_state(uid):
    ADMIN_STATE.pop(uid, None)

def get_admin_state(uid):
    return ADMIN_STATE.get(uid)

def set_user_state(uid, action, step=1, data=None):
    USER_STATE[uid] = {"action": action, "step": step, "data": data or {}}

def clear_user_state(uid):
    USER_STATE.pop(uid, None)

def get_user_state(uid):
    return USER_STATE.get(uid)


def show_subscription_prompt(chat_id):
    send(chat_id,
         "🔒 <b>Для использования бота подпишитесь на каналы:</b>\n\n1️⃣ IsayDev\n2️⃣ KOTVPN\n\nПосле подписки нажмите кнопку ниже",
         inline([
             [("📢 IsayDev", "https://t.me/+qoibIAmZWjdmOGNi", "url")],
             [("🐱 KOTVPN",  "https://t.me/c4tvpn",             "url")],
             [("✅ Проверить подписку", "check_sub")],
         ]))


def show_main_menu(chat_id):
    send(chat_id, "👇 Выбирай", inline([
        [("🎰 Кейсы",           "cases_menu")],
        [("🎁 Купить подарки",   "buy_gifts")],
        [("👤 Профиль / Баланс", "profile")],
        [("📢 Мой канал",       "https://t.me/+qoibIAmZWjdmOGNi", "url")],
    ]))


def show_profile(chat_id, uid):
    u = get_user(uid)
    if not u:
        return
    pending = get_pending_rewards_count(uid)
    notif_label = "🔔 Вкл" if u["notifications"] else "🔕 Выкл"
    text = (f"👤 <b>Профиль</b>\n"
            f"🆔: <code>{uid}</code>\n"
            f"💰 Баланс: {u['balance']:.1f}⭐\n"
            f"💳 Депозит: {u['deposit']:.1f}⭐\n"
            f"🎁 Призов: {u['prizes']}\n"
            f"🎁 Доступно наград: {pending}\n"
            f"📅 Регистрация: {u['registered']}")
    kb_rows = [("💳 Пополнить", "topup")]
    if pending > 0:
        kb_rows.append((f"🎁 Забрать награду ({pending})", f"claim_rewards_{uid}"))
    kb_rows.append((f"Уведомления: {notif_label}", "toggle_notif"))
    kb_rows.append(("◀️ В меню", "main_menu"))
    send(chat_id, text, inline([[r] for r in kb_rows]))


def show_admin_menu(chat_id):
    send(chat_id, "🛠 Админ-панель", inline([
        [("💰 Выдать Stars",          "admin_give_stars")],
        [("🎰 Выдать кейс",           "admin_give_case")],
        [("📊 Статистика",             "admin_stats")],
        [("📋 Список пользователей",  "admin_users")],
        [("📣 Рассылка",              "admin_broadcast")],
        [("👥 Рефералы",              "admin_ref_stats")],
        [("◀️ В меню",                "main_menu")],
    ]))


def show_admin_stats(chat_id):
    conn = db_connect()
    total_users   = db_scalar(conn, "SELECT COUNT(*) FROM users") or 0
    total_prizes  = db_scalar(conn, "SELECT SUM(prizes) FROM users") or 0
    total_dep     = db_scalar(conn, "SELECT SUM(deposit) FROM users") or 0
    total_refs    = db_scalar(conn, "SELECT COUNT(*) FROM users WHERE referrer_id IS NOT NULL") or 0
    total_pending = db_scalar(conn, "SELECT COUNT(*) FROM pending_rewards WHERE claimed=0") or 0
    conn.close()
    send(chat_id,
         f"📊 Статистика\n\n"
         f"👥 Пользователей: {total_users}\n"
         f"🎁 Призов: {total_prizes}\n"
         f"💰 Депозитов: {total_dep:.1f}⭐\n"
         f"🔗 Рефералов: {total_refs}\n"
         f"🎁 Ожидает наград: {total_pending}",
         inline([[("◀️ Назад", "admin_menu")]]))


def show_admin_ref_stats(chat_id):
    conn = db_connect()
    top = conn.execute("""
        SELECT u.user_id, u.username,
               COUNT(r.referred_id) as referred_count,
               COALESCE(SUM(CASE WHEN pr.claimed=1 THEN 1 ELSE 0 END),0) as rewards_given,
               COALESCE(SUM(CASE WHEN pr.claimed=0 THEN 1 ELSE 0 END),0) as rewards_pending
        FROM users u
        LEFT JOIN users r ON r.referrer_id=u.user_id
        LEFT JOIN pending_rewards pr ON pr.referrer_id=u.user_id
        GROUP BY u.user_id
        ORDER BY referred_count DESC LIMIT 10
    """).fetchall()
    conn.close()
    text = "👥 <b>Топ рефереров</b>\n\n"
    for i, t in enumerate(top, 1):
        text += f"{i}. @{t['username'] or t['user_id']} — приглашено: {t['referred_count']}, наград: {t['rewards_given']}, ждёт: {t['rewards_pending']}\n"
    send(chat_id, text, inline([[("◀️ Назад", "admin_menu")]]))


def _gen_check_code():
    while True:
        code = f"CHK{random.randint(100000, 999999)}"
        conn = db_connect()
        exists = conn.execute("SELECT id FROM checks WHERE code=?", (code,)).fetchone()
        conn.close()
        if not exists:
            return code


def _activate_check(uid, uname, chat, code):
    lock = get_check_lock(code)
    if not lock.acquire(blocking=True, timeout=5):
        send(chat, "❌ Слишком много запросов, попробуй снова")
        return
    try:
        conn = db_connect()
        check = conn.execute("SELECT * FROM checks WHERE code=?", (code,)).fetchone()
        if not check:
            conn.close()
            send(chat, "❌ Чек не найден")
            return
        if check["status"] != "active":
            conn.close()
            send(chat, "❌ Чек уже не активен")
            return
        if check["recipient_username"] and (not uname or uname.lower() != check["recipient_username"].lower()):
            conn.close()
            send(chat, f"❌ Этот чек только для @{check['recipient_username']}")
            return
        if check["sender_id"] == uid:
            conn.close()
            send(chat, "❌ Нельзя активировать свой чек")
            return
        if check["activations"] >= check["max_activations"]:
            conn.close()
            send(chat, "❌ Все активации использованы")
            return
        try:
            conn.execute("INSERT INTO check_activations (check_id,user_id) VALUES (?,?)", (check["id"], uid))
        except sqlite3.IntegrityError:
            conn.close()
            send(chat, "❌ Ты уже активировал этот чек")
            return
        new_act = check["activations"] + 1
        new_status = "used" if new_act >= check["max_activations"] else "active"
        conn.execute("UPDATE checks SET activations=?,status=? WHERE id=?", (new_act, new_status, check["id"]))
        conn.commit()
        check_id = check["id"]
        gift_id = check["gift_id"]
        sender_id = check["sender_id"]
        max_act = check["max_activations"]
        conn.close()

        conn2 = db_connect()
        gift = conn2.execute("SELECT * FROM gifts WHERE id=?", (gift_id,)).fetchone()
        conn2.close()
        if not gift:
            send(chat, "❌ Подарок не найден")
            return

        ok = _deliver_gift(uid, dict(gift), chat, silent=True)
        user_label = f"@{uname}" if uname else f"#{uid}"
        remaining = max_act - new_act

        if ok:
            add_prize(uid)
            send(chat, f"🎉 Чек активирован!\n{gift['emoji']} <b>{gift['name']}</b> отправлен!")
            sender_u = get_user(sender_id)
            if sender_u:
                send(sender_id, f"✅ Чек <code>{code}</code> активировал {user_label}\n🎁 {gift['emoji']} {gift['name']}\n📊 Осталось: {remaining}")
        else:
            conn3 = db_connect()
            conn3.execute("UPDATE checks SET activations=activations-1,status='active' WHERE id=?", (check_id,))
            conn3.execute("DELETE FROM check_activations WHERE check_id=? AND user_id=?", (check_id, uid))
            conn3.commit()
            conn3.close()
    except Exception as e:
        log.error(f"Activate check error: {e}")
        send(chat, "❌ Ошибка активации")
    finally:
        lock.release()


def _finalize_check(uid, chat, data):
    gift_id    = data["gift_id"]
    check_type = data["check_type"]
    recipient  = data.get("recipient")
    max_act    = data["max_activations"]
    sender_u   = get_user(uid)
    conn = db_connect()
    gift = conn.execute("SELECT * FROM gifts WHERE id=?", (gift_id,)).fetchone()
    conn.close()
    if not gift or not sender_u or gift["price_stars"] is None:
        send(chat, "❌ Ошибка")
        return
    total_cost = gift["price_stars"] * max_act
    if sender_u["balance"] < total_cost:
        send(chat, f"❌ Не хватает Stars. Нужно {total_cost}⭐")
        return
    code = _gen_check_code()
    conn = db_connect()
    conn.execute("UPDATE users SET balance=balance-? WHERE user_id=?", (total_cost, uid))
    conn.execute(
        "INSERT INTO checks (code,sender_id,gift_id,recipient_username,max_activations,status) VALUES (?,?,?,?,?,'active')",
        (code, uid, gift_id, recipient if check_type == "personal" else None, max_act)
    )
    conn.commit()
    conn.close()
    add_transaction(uid, "check_send", -total_cost, f"Чек {code}")
    sender_name  = f"@{sender_u['username']}" if sender_u.get("username") else f"#{uid}"
    activate_url = f"https://t.me/{BOT_USERNAME}?start={code}"
    kb_url = {"inline_keyboard": [[{"text": "🎁 Забрать подарок!", "url": activate_url}]]}
    if check_type == "personal":
        text = (f"🧾 <b>Личный чек от {sender_name}</b>\n\n"
                f"{gift['emoji']} {gift['name']}\n"
                f"💰 {gift['price_stars']}⭐ × {max_act} = {total_cost}⭐\n"
                f"👤 Получатель: @{recipient}\n"
                f"🔑 Код: <code>{code}</code>")
        send(chat, f"✅ Чек создан!\n\n{text}", kb_url)
        conn3 = db_connect()
        rec = conn3.execute("SELECT user_id FROM users WHERE username=?", (recipient,)).fetchone()
        conn3.close()
        if rec:
            send(rec["user_id"], f"🎁 Тебе прислали чек!\n\n{text}", kb_url)
    else:
        text = (f"🧾 <b>Публичный чек от {sender_name}</b>\n\n"
                f"{gift['emoji']} {gift['name']}\n"
                f"💰 {gift['price_stars']}⭐ каждому · 🔢 активаций: {max_act}\n"
                f"🕒 {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
                f"👇 Нажми кнопку и получи подарок!")
        send(chat, f"✅ Публичный чек создан!\n🔑 Код: <code>{code}</code>\n\nОтправь это сообщение в любой чат:")
        send(chat, text, kb_url)


def handle_inline_query(iq):
    uid   = iq["from"]["id"]
    uname = iq["from"].get("username", "")
    query = iq.get("query", "").strip()
    iq_id = iq["id"]

    sender_u = get_user(uid)
    if not sender_u or not sender_u.get("subscribed"):
        answer_inline(iq_id, [{
            "type": "article", "id": "not_reg",
            "title": "❌ Сначала запусти бота",
            "description": f"/start в @{BOT_USERNAME}",
            "input_message_content": {"message_text": f"Сначала запусти @{BOT_USERNAME}!"},
        }])
        return

    parts = query.split()
    if not parts:
        conn = db_connect()
        gifts = conn.execute(
            "SELECT id,name,emoji,price_stars FROM gifts WHERE price_stars IS NOT NULL ORDER BY price_stars"
        ).fetchall()
        conn.close()
        results = [{
            "type": "article",
            "id": f"hint_{g['id']}",
            "title": f"{g['emoji']} {g['name']} — {g['price_stars']}⭐",
            "description": f"@{BOT_USERNAME} {g['id']} <кол-во> [username]",
            "input_message_content": {"message_text": f"@{BOT_USERNAME} {g['id']} <кол-во> [username]"},
        } for g in gifts]
        answer_inline(iq_id, results[:20], cache_time=30)
        return

    def err(title, desc=""):
        answer_inline(iq_id, [{"type": "article", "id": "e", "title": title,
            "description": desc,
            "input_message_content": {"message_text": title}}])

    try:
        gift_id = int(parts[0])
    except ValueError:
        return err("❌ ID подарка — число", f"Пример: @{BOT_USERNAME} 1 3")

    if len(parts) < 2:
        return err("❌ Укажи кол-во активаций", f"Пример: @{BOT_USERNAME} {gift_id} 3")

    try:
        max_act = int(parts[1])
        if not (1 <= max_act <= 100):
            raise ValueError
    except ValueError:
        return err("❌ Активации: число 1–100")

    recipient  = parts[2].lstrip("@") if len(parts) >= 3 else None
    check_type = "personal" if recipient else "public"

    conn = db_connect()
    gift = conn.execute("SELECT * FROM gifts WHERE id=? AND price_stars IS NOT NULL", (gift_id,)).fetchone()
    conn.close()
    if not gift:
        return err("❌ Подарок не найден", "Напиши @IsayGiftBot без аргументов — список")

    total_cost = gift["price_stars"] * max_act
    if sender_u["balance"] < total_cost:
        return err(f"❌ Нужно {total_cost}⭐, у тебя {sender_u['balance']:.0f}⭐", "Пополни баланс")

    code = _gen_check_code()
    conn = db_connect()
    conn.execute("UPDATE users SET balance=balance-? WHERE user_id=?", (total_cost, uid))
    conn.execute(
        "INSERT INTO checks (code,sender_id,gift_id,recipient_username,max_activations,status) VALUES (?,?,?,?,?,'active')",
        (code, uid, gift_id, recipient, max_act)
    )
    conn.commit()
    conn.close()

    sender_name  = f"@{uname}" if uname else f"#{uid}"
    activate_url = f"https://t.me/{BOT_USERNAME}?start={code}"
    kb_url = {"inline_keyboard": [[{"text": "🎁 Забрать подарок!", "url": activate_url}]]}

    if check_type == "public":
        msg_text = (f"🧾 <b>Публичный чек от {sender_name}</b>\n\n"
                    f"{gift['emoji']} <b>{gift['name']}</b>\n"
                    f"💰 {gift['price_stars']}⭐ каждому · 🔢 активаций: {max_act}\n"
                    f"🕒 {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
                    f"👇 Нажми кнопку и получи подарок!")
        title = f"🎁 Публичный чек: {gift['emoji']} {gift['name']} ×{max_act}"
        descr = f"{gift['price_stars']}⭐ каждому · {max_act} активаций · спишется {total_cost}⭐"
    else:
        msg_text = (f"🧾 <b>Чек для @{recipient} от {sender_name}</b>\n\n"
                    f"{gift['emoji']} <b>{gift['name']}</b>\n"
                    f"💰 {gift['price_stars']}⭐ · 🔢 активаций: {max_act}\n"
                    f"🕒 {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
                    f"👇 Нажми кнопку чтобы забрать!")
        title = f"👤 Чек для @{recipient}: {gift['emoji']} {gift['name']}"
        descr = f"{gift['price_stars']}⭐ · только для @{recipient}"

    answer_inline(iq_id, [{
        "type": "article", "id": code,
        "title": title, "description": descr,
        "input_message_content": {"message_text": msg_text, "parse_mode": "HTML"},
        "reply_markup": kb_url,
    }])


def handle_message(msg):
    uid   = msg["from"]["id"]
    text  = msg.get("text", "")
    chat  = msg["chat"]["id"]
    user  = msg["from"]
    uname = user.get("username", "")

    if text.startswith("/start"):
        parts = text.split(maxsplit=1)
        param = parts[1].strip() if len(parts) > 1 else ""
        referrer_id = None
        if param.startswith("ref_"):
            try:
                referrer_id = int(param[4:])
            except ValueError:
                pass
        get_or_create_user(user, referrer_id)
        if param.startswith("CHK"):
            db_user = get_user(uid)
            if not db_user or not db_user.get("subscribed"):
                set_user_state(uid, "pending_check", data={"code": param})
                show_subscription_prompt(chat)
            else:
                _activate_check(uid, uname, chat, param)
        else:
            db_user = get_user(uid)
            if not db_user or not db_user.get("subscribed"):
                show_subscription_prompt(chat)
            else:
                show_main_menu(chat)
        return

    get_or_create_user(user)

    if is_admin(uname):
        state = get_admin_state(uid)
        if state:
            handle_admin_state(uid, chat, text, state)
            return
        if text == "/admin":
            show_admin_menu(chat)
            return
        if text == "/gifts":
            conn = db_connect()
            gifts = conn.execute("SELECT id,emoji,name,price_stars FROM gifts ORDER BY price_stars").fetchall()
            conn.close()
            lines = ["🎁 <b>Подарки:</b>\n"]
            for g in gifts:
                lines.append(f"<code>{g['id']}</code> — {g['emoji']} {g['name']} — {g['price_stars']}⭐")
            send(chat, "\n".join(lines))
            return
        if text == "/check_refs":
            show_admin_ref_stats(chat)
            return
        if text.startswith("/setgift"):
            parts = text.split()
            if len(parts) == 3:
                try:
                    conn = db_connect()
                    conn.execute("UPDATE gifts SET telegram_gift_id=? WHERE id=?", (parts[2], int(parts[1])))
                    conn.commit()
                    conn.close()
                    send(chat, f"✅ Подарок ID {parts[1]} привязан к <code>{parts[2]}</code>")
                except Exception as e:
                    send(chat, f"❌ Ошибка: {e}")
            else:
                send(chat, "❌ Формат: /setgift <id> <telegram_gift_id>")
            return

    user_state = get_user_state(uid)
    if user_state:
        handle_user_state(uid, uname, chat, text, user_state)
        return

    db_user = get_user(uid)
    if not db_user or not db_user.get("subscribed"):
        show_subscription_prompt(chat)
    else:
        show_main_menu(chat)


def handle_admin_state(uid, chat, text, state):
    action = state["action"]
    step   = state["step"]
    data   = state["data"]

    if action == "give_stars":
        if step == 1:
            data["target_uid"] = text.strip()
            set_admin_state(uid, "give_stars", 2, data)
            send(chat, "⭐ Сколько Stars выдать?")
        elif step == 2:
            try:
                amount = float(text.strip())
                target = int(data["target_uid"])
                update_balance(target, amount)
                add_transaction(target, "admin_gift", amount, "Админ")
                clear_admin_state(uid)
                send(chat, f"✅ Выдано {amount}⭐ пользователю {target}")
                target_user = get_user(target)
                if target_user:
                    send(target, f"🎉 Вам выдано {amount}⭐ от администратора!")
            except Exception:
                send(chat, "❌ Ошибка. Проверь данные.")

    elif action == "give_case":
        if step == 1:
            data["target_uid"] = text.strip()
            set_admin_state(uid, "give_case", 2, data)
            conn = db_connect()
            cases = conn.execute("SELECT * FROM cases").fetchall()
            conn.close()
            send(chat, "Выбери кейс:", inline([[(f"{c['emoji']} {c['name']}", f"admin_case_pick_{c['id']}")] for c in cases]))

    elif action == "broadcast":
        conn = db_connect()
        users = conn.execute("SELECT user_id FROM users").fetchall()
        conn.close()
        count = 0
        for u in users:
            try:
                send(u["user_id"], f"📣 <b>Рассылка:</b>\n\n{text}")
                count += 1
                time.sleep(0.05)
            except Exception:
                pass
        clear_admin_state(uid)
        send(chat, f"✅ Рассылка отправлена {count} пользователям")


def handle_user_state(uid, uname, chat, text, state):
    action = state["action"]
    step   = state["step"]
    data   = state["data"]

    if action == "pending_check":
        clear_user_state(uid)
        code = data.get("code")
        if code:
            _activate_check(uid, uname, chat, code)
        return

    if action == "custom_topup":
        clear_user_state(uid)
        try:
            amount = int(text.strip())
            if not (1 <= amount <= 10000):
                send(chat, "❌ Сумма от 1 до 10000")
                return
            payload = f"topup_{amount}_{uid}_{int(time.time())}"
            conn = db_connect()
            conn.execute("INSERT INTO invoice_log (user_id,payload,amount) VALUES (?,?,?)", (uid, payload, amount))
            conn.commit()
            conn.close()
            send_invoice(chat, f"Пополнение {amount}⭐", "Пополнение баланса", payload, amount)
        except Exception:
            send(chat, "❌ Введите целое число")
        return

    if action == "create_check":
        if step == 2 and data.get("check_type") == "personal":
            recipient = text.strip().lstrip("@")
            if not recipient:
                send(chat, "❌ Введите username")
                return
            data["recipient"] = recipient
            set_user_state(uid, "create_check", 3, data)
            send(chat, f"👤 Получатель: @{recipient}\n\nСколько активаций? (1–100)")

        elif step == 2 and data.get("check_type") == "public":
            try:
                max_act = int(text.strip())
                if not (1 <= max_act <= 100):
                    raise ValueError
            except ValueError:
                send(chat, "❌ Число от 1 до 100")
                return
            data["max_activations"] = max_act
            set_user_state(uid, "create_check", 4, data)
            conn = db_connect()
            gift = conn.execute("SELECT * FROM gifts WHERE id=?", (data["gift_id"],)).fetchone()
            conn.close()
            total = gift["price_stars"] * max_act
            u = get_user(uid)
            send(chat, f"🧾 Подтверди:\n\n{gift['emoji']} {gift['name']}\n"
                       f"💰 {gift['price_stars']}⭐ × {max_act} = {total}⭐\n"
                       f"💳 Баланс: {u['balance']:.1f}⭐\n\nОтправь <b>да</b> для подтверждения")

        elif step == 3 and data.get("check_type") == "personal":
            try:
                max_act = int(text.strip())
                if not (1 <= max_act <= 100):
                    raise ValueError
            except ValueError:
                send(chat, "❌ Число от 1 до 100")
                return
            data["max_activations"] = max_act
            set_user_state(uid, "create_check", 4, data)
            conn = db_connect()
            gift = conn.execute("SELECT * FROM gifts WHERE id=?", (data["gift_id"],)).fetchone()
            conn.close()
            total = gift["price_stars"] * max_act
            u = get_user(uid)
            send(chat, f"🧾 Подтверди:\n\n{gift['emoji']} {gift['name']}\n"
                       f"👤 @{data['recipient']}\n"
                       f"💰 {gift['price_stars']}⭐ × {max_act} = {total}⭐\n"
                       f"💳 Баланс: {u['balance']:.1f}⭐\n\nОтправь <b>да</b> для подтверждения")

        elif step == 4:
            clear_user_state(uid)
            if text.strip().lower() in ("да", "yes", "д", "y"):
                _finalize_check(uid, chat, data)
            else:
                send(chat, "❌ Отменено")
        return

    clear_user_state(uid)


def handle_callback(cb):
    uid   = cb["from"]["id"]
    chat  = cb["message"]["chat"]["id"]
    msg_id = cb["message"]["message_id"]
    data  = cb.get("data", "")
    uname = cb["from"].get("username", "")

    answer_cb(cb["id"])
    get_or_create_user(cb["from"])
    db_user = get_user(uid)

    if data == "check_sub":
        if check_subscription(uid):
            conn = db_connect()
            conn.execute("UPDATE users SET subscribed=1 WHERE user_id=?", (uid,))
            conn.commit()
            conn.close()
            edit_msg(chat, msg_id, "✅ Подписка подтверждена!")
            state = get_user_state(uid)
            if state and state["action"] == "pending_check":
                code = state["data"].get("code")
                clear_user_state(uid)
                if code:
                    _activate_check(uid, uname, chat, code)
                    return
            show_main_menu(chat)
        else:
            edit_msg(chat, msg_id, "❌ Вы не подписаны на все каналы!", inline([
                [("📢 IsayDev", "https://t.me/+qoibIAmZWjdmOGNi", "url")],
                [("🐱 KOTVPN",  "https://t.me/c4tvpn",             "url")],
                [("✅ Проверить", "check_sub")],
            ]))
        return

    if not db_user or not db_user.get("subscribed"):
        show_subscription_prompt(chat)
        return

    if data.startswith("claim_rewards_"):
        referrer_id = int(data.split("_")[2])
        if uid != referrer_id:
            send(chat, "❌ Это не твои награды")
            return
        pending = get_pending_rewards_list(uid)
        if pending:
            reward = pending[0]
            send(chat, "🎁 <b>Выбери подарок</b>", inline([
                [("🧸 Мишка",    f"claim_gift_{reward['id']}_bear")],
                [("💝 Сердечко", f"claim_gift_{reward['id']}_heart")],
                [("◀️ Назад",    "profile")],
            ]))
        else:
            send(chat, "🎁 У тебя нет доступных наград!")
        return

    if data.startswith("claim_gift_"):
        parts = data.split("_")
        reward_id = int(parts[2])
        gift_type = parts[3]
        referred_id = claim_reward(uid, reward_id)
        if referred_id:
            if send_reward_gift(uid, gift_type):
                gift_emoji = "🧸" if gift_type == "bear" else "💝"
                gift_name  = "Мишка" if gift_type == "bear" else "Сердечко"
                ref_user   = get_user(referred_id)
                ref_name   = f"@{ref_user['username']}" if ref_user and ref_user.get("username") else f"#{referred_id}"
                send(chat, f"✅ {gift_emoji} <b>{gift_name}</b> отправлен!\n\nСпасибо за приглашение {ref_name}!")
                remaining = get_pending_rewards_count(uid)
                if remaining > 0:
                    send(chat, f"🎁 Ещё <b>{remaining}</b> наград ждут!", inline([[("🎁 Забрать", f"claim_rewards_{uid}")]]))
            else:
                send(chat, "❌ Ошибка при отправке. Обратитесь к администратору.")
        else:
            send(chat, "❌ Награда уже получена.")
        return

    if data == "main_menu":
        show_main_menu(chat)

    elif data == "profile":
        show_profile(chat, uid)

    elif data == "toggle_notif":
        conn = db_connect()
        conn.execute("UPDATE users SET notifications=1-notifications WHERE user_id=?", (uid,))
        conn.commit()
        conn.close()
        show_profile(chat, uid)

    elif data == "topup":
        rows, row = [], []
        for amount in TOPUP_OPTIONS:
            row.append((f"⭐ {amount}", f"topup_{amount}"))
            if len(row) == 3:
                rows.append(row)
                row = []
        if row:
            rows.append(row)
        rows.append([("✏️ Своя сумма", "topup_custom")])
        rows.append([("◀️ Назад", "profile")])
        edit_msg(chat, msg_id, "💳 <b>Пополнение баланса</b>", inline(rows))

    elif data == "topup_custom":
        set_user_state(uid, "custom_topup")
        send(chat, "✏️ Введите сумму от 1 до 10000 Stars:")

    elif data.startswith("topup_"):
        amount = int(data.split("_")[1])
        payload = f"topup_{amount}_{uid}_{int(time.time())}"
        conn = db_connect()
        conn.execute("INSERT INTO invoice_log (user_id,payload,amount) VALUES (?,?,?)", (uid, payload, amount))
        conn.commit()
        conn.close()
        send_invoice(chat, f"Пополнение {amount}⭐", "Пополнение баланса", payload, amount)

    elif data == "cases_menu":
        conn = db_connect()
        cases = conn.execute("SELECT * FROM cases").fetchall()
        conn.close()
        rows = [[(f"{c['emoji']} {c['name']}  {c['price_stars']}⭐", f"open_case_{c['id']}")] for c in cases]
        rows.append([("◀️ Назад", "main_menu")])
        edit_msg(chat, msg_id, "🎰 <b>Кейсы</b>", inline(rows))

    elif data.startswith("open_case_"):
        case_id = int(data.split("_")[-1])
        conn = db_connect()
        case = conn.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone()
        conn.close()
        if case:
            edit_msg(chat, msg_id,
                     f"{case['emoji']} <b>{case['name']}</b>\n\n{case['description']}\n💰 Цена: {case['price_stars']}⭐",
                     inline([
                         [(f"💰 С баланса ({case['price_stars']}⭐)", f"pay_case_balance_{case_id}")],
                         [("⭐ Оплатить Stars",                        f"pay_case_stars_{case_id}")],
                         [("◀️ Назад",                                 "cases_menu")],
                     ]))

    elif data.startswith("pay_case_balance_"):
        case_id = int(data.split("_")[-1])
        threading.Thread(target=spin_case, args=(uid, case_id, chat, "balance"), daemon=True).start()

    elif data.startswith("pay_case_stars_"):
        case_id = int(data.split("_")[-1])
        conn = db_connect()
        case = conn.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone()
        conn.close()
        if case:
            payload = f"case_{case_id}_{uid}"
            conn2 = db_connect()
            conn2.execute("INSERT INTO invoice_log (user_id,payload,amount) VALUES (?,?,?)", (uid, payload, case["price_stars"]))
            conn2.commit()
            conn2.close()
            send_invoice(chat, f"🎰 {case['name']}", f"Открытие кейса {case['name']}", payload, case["price_stars"])

    elif data == "buy_gifts":
        conn = db_connect()
        gifts = conn.execute("SELECT * FROM gifts WHERE price_stars IS NOT NULL ORDER BY price_stars").fetchall()
        conn.close()
        rows, row = [], []
        for g in gifts:
            row.append((f"{g['emoji']} {g['name']} — {g['price_stars']}⭐", f"buy_gift_{g['id']}"))
            if len(row) == 2:
                rows.append(row)
                row = []
        if row:
            rows.append(row)
        rows.append([("🧾 Создать чек", "create_check")])
        rows.append([("◀️ Назад",       "main_menu")])
        edit_msg(chat, msg_id, "🎁 <b>Подарки</b>", inline(rows))

    elif data.startswith("buy_gift_"):
        gift_id = int(data.split("_")[-1])
        conn = db_connect()
        gift = conn.execute("SELECT * FROM gifts WHERE id=?", (gift_id,)).fetchone()
        conn.close()
        u = get_user(uid)
        edit_msg(chat, msg_id,
                 f"{gift['emoji']} <b>{gift['name']}</b>\n\n💰 {gift['price_stars']}⭐\n💳 Баланс: {u['balance']:.1f}⭐\n\nВыбери способ оплаты:",
                 inline([
                     [("💰 С баланса",   f"pay_balance_{gift_id}")],
                     [("⭐ Оплатить Stars", f"pay_stars_{gift_id}")],
                     [("◀️ Назад",        "buy_gifts")],
                 ]))

    elif data.startswith("pay_balance_"):
        gift_id = int(data.split("_")[-1])
        purchase_gift_balance(chat, uid, gift_id)

    elif data.startswith("pay_stars_"):
        gift_id = int(data.split("_")[-1])
        conn = db_connect()
        gift = conn.execute("SELECT * FROM gifts WHERE id=?", (gift_id,)).fetchone()
        conn.close()
        if gift and gift["price_stars"]:
            payload = f"gift_{gift_id}_{uid}"
            conn2 = db_connect()
            conn2.execute("INSERT INTO invoice_log (user_id,payload,amount) VALUES (?,?,?)", (uid, payload, gift["price_stars"]))
            conn2.commit()
            conn2.close()
            send_invoice(chat, f"{gift['emoji']} {gift['name']}", f"Покупка {gift['name']}", payload, gift["price_stars"])

    elif data == "create_check":
        conn = db_connect()
        gifts = conn.execute("SELECT * FROM gifts WHERE price_stars IS NOT NULL ORDER BY price_stars").fetchall()
        conn.close()
        rows, row = [], []
        for g in gifts:
            row.append((f"{g['emoji']} {g['name']} {g['price_stars']}⭐", f"check_gift_{g['id']}"))
            if len(row) == 2:
                rows.append(row)
                row = []
        if row:
            rows.append(row)
        rows.append([("◀️ Назад", "buy_gifts")])
        send(chat, "🧾 <b>Создать чек</b>\n\nВыбери подарок:", inline(rows))

    elif data.startswith("check_gift_"):
        gift_id = int(data.split("_")[-1])
        conn = db_connect()
        gift = conn.execute("SELECT * FROM gifts WHERE id=?", (gift_id,)).fetchone()
        conn.close()
        u = get_user(uid)
        send(chat,
             f"🧾 Чек на {gift['emoji']} {gift['name']} ({gift['price_stars']}⭐)\n"
             f"💰 Баланс: {u['balance']:.1f}⭐\n\nТип чека:",
             inline([
                 [("👤 Личный",    f"check_type_personal_{gift_id}")],
                 [("🌐 Публичный", f"check_type_public_{gift_id}")],
                 [("◀️ Назад",     "create_check")],
             ]))

    elif data.startswith("check_type_personal_"):
        gift_id = int(data.split("_")[-1])
        set_user_state(uid, "create_check", 2, {"gift_id": gift_id, "check_type": "personal"})
        send(chat, "👤 Введите @username получателя:")

    elif data.startswith("check_type_public_"):
        gift_id = int(data.split("_")[-1])
        set_user_state(uid, "create_check", 2, {"gift_id": gift_id, "check_type": "public"})
        send(chat, "🌐 Введите количество активаций (1–100):")

    elif data == "admin_menu" and is_admin(uname):
        show_admin_menu(chat)
    elif data == "admin_stats" and is_admin(uname):
        show_admin_stats(chat)
    elif data == "admin_ref_stats" and is_admin(uname):
        show_admin_ref_stats(chat)
    elif data == "admin_give_stars" and is_admin(uname):
        set_admin_state(uid, "give_stars")
        send(chat, "👤 Введите User ID:")
    elif data == "admin_give_case" and is_admin(uname):
        set_admin_state(uid, "give_case")
        send(chat, "👤 Введите User ID:")
    elif data.startswith("admin_case_pick_") and is_admin(uname):
        case_id = int(data.split("_")[-1])
        state   = get_admin_state(uid)
        if state:
            try:
                target = int(state["data"].get("target_uid", 0))
            except ValueError:
                target = 0
            clear_admin_state(uid)
            if target:
                conn = db_connect()
                case = conn.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone()
                conn.close()
                if case:
                    update_balance(target, case["price_stars"])
                    add_transaction(target, "admin_gift", case["price_stars"], f"Выдан кейс: {case['name']}")
                    send(chat, f"✅ Пользователю {target} выдан кейс {case['emoji']} {case['name']}!")
                    target_user = get_user(target)
                    if target_user:
                        send(target, f"🎉 Вам выдан кейс {case['emoji']} {case['name']}!\nБаланс +{case['price_stars']}⭐")
    elif data == "admin_users" and is_admin(uname):
        conn = db_connect()
        users = conn.execute(
            "SELECT user_id,username,balance,prizes FROM users ORDER BY prizes DESC LIMIT 10"
        ).fetchall()
        conn.close()
        text = "📋 <b>Топ-10</b>\n\n"
        for i, u in enumerate(users, 1):
            text += f"{i}. <code>{u['user_id']}</code> @{u['username'] or '—'} | 💰{u['balance']:.0f}⭐ | 🎁{u['prizes']}\n"
        send(chat, text, inline([[("◀️ Назад", "admin_menu")]]))
    elif data == "admin_broadcast" and is_admin(uname):
        set_admin_state(uid, "broadcast")
        send(chat, "📣 Введите текст рассылки:")


def handle_pre_checkout(pq):
    answer_pre_checkout(pq["id"], ok=True)


def handle_successful_payment(msg):
    uid     = msg["from"]["id"]
    chat    = msg["chat"]["id"]
    payment = msg["successful_payment"]
    payload = payment["invoice_payload"]
    amount  = payment["total_amount"]

    if payload.startswith("topup_"):
        conn = db_connect()
        conn.execute("UPDATE users SET balance=balance+?,deposit=deposit+? WHERE user_id=?", (amount, amount, uid))
        conn.commit()
        conn.close()
        add_transaction(uid, "topup", amount, "Пополнение")
        send(chat, f"✅ Баланс пополнен на {amount}⭐!")

    elif payload.startswith("gift_"):
        parts   = payload.split("_")
        gift_id = int(parts[1])
        conn = db_connect()
        gift = conn.execute("SELECT * FROM gifts WHERE id=?", (gift_id,)).fetchone()
        conn.execute("UPDATE users SET prizes=prizes+1,deposit=deposit+? WHERE user_id=?", (amount, uid))
        conn.commit()
        conn.close()
        add_transaction(uid, "gift_purchase", amount, f"Stars: {gift['name'] if gift else gift_id}")
        if gift:
            _deliver_gift(uid, dict(gift), chat)

    elif payload.startswith("case_"):
        parts   = payload.split("_")
        case_id = int(parts[1])
        conn = db_connect()
        case = conn.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone()
        conn.close()
        if case:
            add_transaction(uid, "case_open", -amount, f"Кейс (Stars): {case['name']}")
            threading.Thread(target=spin_case, args=(uid, case_id, chat, "stars_paid"), daemon=True).start()


def poll():
    offset      = 0
    retry_delay = 2
    session     = requests.Session()
    log.info("Bot started")
    while True:
        try:
            r = session.get(
                f"{API}/getUpdates",
                params={
                    "offset": offset,
                    "timeout": 25,
                    "allowed_updates": json.dumps(
                        ["message", "callback_query", "pre_checkout_query", "inline_query"]
                    ),
                },
                timeout=30,
            )
            data = r.json()
            if not data.get("ok"):
                log.warning(f"getUpdates not ok: {data}")
                time.sleep(retry_delay)
                continue
            retry_delay = 2
            for upd in data.get("result", []):
                offset = upd["update_id"] + 1
                try:
                    if "message" in upd:
                        msg = upd["message"]
                        if "successful_payment" in msg:
                            handle_successful_payment(msg)
                        elif "text" in msg:
                            handle_message(msg)
                    elif "callback_query" in upd:
                        handle_callback(upd["callback_query"])
                    elif "pre_checkout_query" in upd:
                        handle_pre_checkout(upd["pre_checkout_query"])
                    elif "inline_query" in upd:
                        threading.Thread(target=handle_inline_query, args=(upd["inline_query"],), daemon=True).start()
                except Exception as e:
                    log.exception(f"Handler error: {e}")
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            log.warning(f"Connection error: {e}, retry in {retry_delay}s")
            session = requests.Session()
            time.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, 30)
        except Exception as e:
            log.exception(f"Poll error: {e}")
            time.sleep(retry_delay)


if __name__ == "__main__":
    db_init()
    poll()
