"""
Unified KabutoAI bot for Telegram, WhatsApp and Website chat.

This script consolidates all the functionality you developed so far into a
single application.  It uses a Flask server to expose both Telegram
webhooks and a simple HTTP API for the website chat widget.  A small
WhatsApp webhook is also included using Twilio's MessagingResponse so
messages from WhatsApp can be handled in the same way as Telegram
messages.  All configurable behaviour (API keys, tokens, prompts etc.)
is pulled from environment variables so that you can deploy the same
code for multiple customers simply by changing the .env file or Render
environment variables.  For each customer you can override the base
system prompt by defining a variable named ``SYSTEM_PROMPT_<CLIENT_ID>``.

If you wish to add further channels (e.g. SMS via Twilio), follow the
pattern used for the WhatsApp webhook: extract the incoming text from
the request, call ``generate_reply_generic`` with a unique channel ID
(phone number or chat ID) and your client identifier, and then return
the reply.  The conversation memory is isolated per client and per
channel ID.

Note: WhatsApp bots require your Twilio account to be approved by
Meta/WhatsApp Business.  You can write and deploy this bot while
waiting for verification, but Twilio will not deliver messages
until your WhatsApp number is authorised.  See Twilio's docs for
details.
"""

import os
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Tuple

from dotenv import load_dotenv
from flask import Flask, request, abort, jsonify, render_template
import telebot
from openai import OpenAI
from langdetect import detect
from flask_cors import CORS

# Twilio: only MessagingResponse is needed for responding to incoming
# WhatsApp messages.  If you also want to send outbound messages via
# Twilio's REST API, you can uncomment the import of Client and use
# the send_message helper below.
try:
    # Try importing Twilio's MessagingResponse for WhatsApp replies.  If
    # the library is not installed, we'll disable WhatsApp support and
    # handle requests gracefully.
    from twilio.twiml.messaging_response import MessagingResponse
    TWILIO_AVAILABLE = True
except ImportError:
    MessagingResponse = None
    TWILIO_AVAILABLE = False
    # Log a warning at startup if Twilio isn't available.  This avoids
    # ModuleNotFoundError during deployment and makes WhatsApp optional.
    print("⚠️ Twilio-Paket nicht installiert – WhatsApp wird deaktiviert.")
# from twilio.rest import Client  # optional, for proactive WhatsApp messages


# ---------------------------------------------------------------------------
# Load environment variables
#
load_dotenv()

TELEGRAM_API_TOKEN = os.getenv("TELEGRAM_API_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
PORT = int(os.getenv("PORT", "8080"))
PUBLIC_BASE_URL = os.getenv(
    "TELEGRAM_WEBHOOK_URL_BASE") or os.getenv("RENDER_EXTERNAL_URL")

# Twilio credentials and WhatsApp settings (optional)
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_NUMBER = os.getenv(
    "TWILIO_WHATSAPP_NUMBER")  # e.g. 'whatsapp:+14155238886'

if not TELEGRAM_API_TOKEN or not OPENAI_API_KEY:
    raise RuntimeError(
        "Bitte TELEGRAM_API_TOKEN und OPENAI_API_KEY in der .env / Render-Env setzen!"
    )

# ---------------------------------------------------------------------------
# OpenAI client
#
client = OpenAI(api_key=OPENAI_API_KEY)


# ---------------------------------------------------------------------------
# Telegram bot and Flask app
#
bot = telebot.TeleBot(TELEGRAM_API_TOKEN, parse_mode="HTML")

# --- Flask app ---
app = Flask(__name__)

# 🟣 Secret key für Sessions (notwendig für Sprachspeicher & Login)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "kabuto_fallback_secret_2025")


# --- Language helper (very small i18n) ---
from flask import g, session, request

TRANSLATIONS = {
    "cta_title": {
        "en": "Learn how KabutoAI works",
        "de": "Erfahre, wie KabutoAI funktioniert",
    },
    "cta_subtitle": {
        "en": "See the full step-by-step setup, what’s included and how we launch your AI agent.",
        "de": "Sieh dir den kompletten Schritt-für-Schritt-Ablauf an – inklusive Setup und Launch deines AI-Agents.",
    },
    "cta_button": {
        "en": "Open Overview",
        "de": "Zur Übersicht",
    },
    # ---- overview page strings ----
    "ov_title": {
        "en": "KabutoAI — Step-by-step Overview",
        "de": "KabutoAI — Übersicht Schritt für Schritt",
    },
    "ov_intro": {
        "en": "This page explains exactly how your AI agent is set up, tested and launched — clear, fast, predictable.",
        "de": "Diese Seite erklärt genau, wie dein AI-Agent eingerichtet, getestet und gelauncht wird — klar, schnell, planbar.",
    },
    "ov_s1_title": {"en": "Step 1 — Goals & Branding", "de": "Schritt 1 — Ziele & Branding"},
    "ov_s1_body": {
        "en": "We clarify tone, goals and examples. Decide what matters first: leads, support or sales. We collect FAQs and key flows.",
        "de": "Wir klären Tonalität, Ziele und Beispiele. Fokus festlegen: Leads, Support oder Sales. Wir sammeln FAQs und Schlüssel-Flows.",
    },
    "ov_s2_title": {"en": "Step 2 — Setup & Training", "de": "Schritt 2 — Setup & Training"},
    "ov_s2_body": {
        "en": "Connect channels (Telegram/WhatsApp/Web), build knowledge base and train prompts. Data privacy defaults included.",
        "de": "Kanäle verbinden (Telegram/WhatsApp/Web), Knowledge Base aufbauen und Prompts trainieren. Datenschutz by default.",
    },
    "ov_s3_title": {"en": "Step 3 — Launch & Tests", "de": "Schritt 3 — Launch & Tests"},
    "ov_s3_body": {
        "en": "Test chats, polish answers, set privacy notes and go live with your branding.",
        "de": "Test-Chats, Antworten feinschleifen, Hinweise setzen und mit deinem Branding live gehen.",
    },
    "ov_s4_title": {"en": "Step 4 — Scale", "de": "Schritt 4 — Skalieren"},
    "ov_s4_body": {
        "en": "Reporting, A/B testing, funnels — we optimize continuously.",
        "de": "Reporting, A/B-Tests, Funnels — kontinuierliche Optimierung.",
    },
}

@app.before_request
def detect_lang():
    lang = request.args.get("lang") or session.get("lang") or "en"
    if lang not in ("de", "en"):
        lang = "en"
    g.lang = lang
    session["lang"] = lang

@app.context_processor
def inject_i18n():
    def t(key):
        return TRANSLATIONS.get(key, {}).get(getattr(g, "lang", "en"), key)
    return {"t": t, "lang": getattr(g, "lang", "en")}

# ✨ CORS aktivieren, damit auch kabutoai-website.onrender.com Zugriff hat
CORS(app, resources={r"/*": {"origins": "*"}})

# ---------------------------------------------------------------------------
# Conversation store and system prompts
#
# We maintain a separate history for each (client_id, channel_id) pair.  The
# channel_id is the Telegram chat id, WhatsApp phone number, or any
# arbitrary string you assign (e.g. session id for web).  Each history
# stores up to MAX_TURNS messages and is reset after INACTIVITY_MINUTES.
MAX_TURNS = 16
INACTIVITY_MINUTES = 30
conversation_store: defaultdict[Tuple[str, str], dict] = defaultdict(
    lambda: {
        "messages": deque(maxlen=MAX_TURNS),
        "last_activity": datetime.now(timezone.utc),
    }
)

# Default system prompt used if no client-specific prompt is set.
DEFAULT_SYSTEM_PROMPT = (
    "You are KabutoAI, a professional multilingual assistant. "
    "Always respond in the user's language (German or English). "
    "Be concise, friendly, and practical. Use short paragraphs and lists when helpful."
)


def get_system_prompt(client_id: str) -> str:
    """Return the system prompt for a given client.

    If an environment variable named SYSTEM_PROMPT_<CLIENT_ID> exists, it
    will be used.  Otherwise the DEFAULT_SYSTEM_PROMPT is returned.

    The client identifier is normalised to uppercase for lookup.
    """
    env_key = f"SYSTEM_PROMPT_{client_id.upper()}"
    override = os.getenv(env_key)
    return override or DEFAULT_SYSTEM_PROMPT


def detect_lang(text: str) -> str:
    """Detect whether the text is German or English using langdetect.

    Returns 'de' for German, 'en' for English.  Falls back to a heuristic
    based on umlauts if detection fails.
    """
    try:
        code = detect(text)
        return "de" if code.startswith("de") else "en"
    except Exception:
        return "de" if any(ch in text for ch in "äöüß") else "en"


def reset_if_inactive(client_id: str, channel_id: str) -> None:
    """Clear the conversation history if inactive for too long."""
    st = conversation_store[(client_id, channel_id)]
    if datetime.now(timezone.utc) - st["last_activity"] > timedelta(minutes=INACTIVITY_MINUTES):
        st["messages"].clear()


def add_message(client_id: str, channel_id: str, role: str, content: str) -> None:
    """Append a message to the history and update last activity timestamp."""
    st = conversation_store[(client_id, channel_id)]
    st["messages"].append({"role": role, "content": content})
    st["last_activity"] = datetime.now(timezone.utc)


def generate_reply_generic(client_id: str, channel_id: str, user_text: str) -> str:
    """Generate a reply for a given client and channel.

    This function encapsulates the logic for resetting inactive histories,
    assembling the prompt, and calling the OpenAI chat API.  It stores
    both user and assistant messages in conversation_store to maintain
    context over multiple turns.
    """
    reset_if_inactive(client_id, channel_id)
    add_message(client_id, channel_id, "user", user_text)

    messages = [{"role": "system", "content": get_system_prompt(client_id)}]
    messages.extend(conversation_store[(client_id, channel_id)]["messages"])

    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            temperature=0.4,
        )
        reply = (resp.choices[0].message.content or "").strip()
    except Exception as e:
        reply = f"⚠️ Fehler bei der Antwortgenerierung: {e}"

    add_message(client_id, channel_id, "assistant", reply)
    return reply


# ---------------------------------------------------------------------------
# Telegram handlers
#
@bot.message_handler(commands=["start", "help"])
def cmd_start(message):
    client_id = "default"
    channel_id = str(message.chat.id)
    conversation_store[(client_id, channel_id)]["messages"].clear()
    bot.reply_to(
        message,
        "👋 Willkommen bei KabutoAI!\n\n"
        "Ich kann jetzt auch lokale Suchen durchführen (OpenStreetMap) "
        "und parallel normale KI-Antworten geben.\n\n"
        "<b>Beispiele</b>:\n"
        "• „Suche Dachdecker in MV“\n"
        "• „Finde Restaurants in Rostock“\n"
        "• „Was ist Samhain?“\n\n"
        "➡️ /reset löscht den Gesprächskontext."
    )


@bot.message_handler(commands=["reset"])
def cmd_reset(message):
    client_id = "default"
    channel_id = str(message.chat.id)
    conversation_store[(client_id, channel_id)]["messages"].clear()
    bot.reply_to(message, "🧹 Kontext gelöscht. Neues Gespräch gestartet!")


@bot.message_handler(func=lambda m: True, content_types=["text"])
def handle_text(message):
    client_id = "default"
    channel_id = str(message.chat.id)
    user_text = (message.text or "").strip()
    if not user_text:
        bot.reply_to(message, "Sag mir kurz, wobei ich dir helfen soll. 🙂")
        return
    reply = generate_reply_generic(client_id, channel_id, user_text)
    bot.reply_to(message, reply)


# ---------------------------------------------------------------------------
# WhatsApp webhook (Twilio)
#
@app.route("/whatsapp", methods=["POST"])
def whatsapp_webhook() -> str:
    """Receive incoming WhatsApp messages via Twilio and respond (if available).

    If the Twilio library is not installed, this endpoint returns an error.
    """
    # If Twilio is not available, return an informative error.  This avoids
    # crashing when the package is missing.
    if not TWILIO_AVAILABLE or MessagingResponse is None:
        return "Twilio library not installed; WhatsApp webhook is disabled.", 503
    # Twilio sends form-encoded data.  'From' contains the sender's number,
    # 'Body' contains the message text.  We ignore messages without a body.
    from_number = request.values.get("From")
    body = request.values.get("Body", "").strip()
    # optional client identifier
    client_id = request.values.get("Client", "default")
    resp = MessagingResponse()
    if not body:
        resp.message("Ich habe nichts empfangen.")
        return str(resp)
    if not from_number:
        resp.message("Kein Absender angegeben.")
        return str(resp)
    # Use the phone number as channel_id to maintain history per sender
    channel_id = from_number
    reply = generate_reply_generic(client_id, channel_id, body)
    resp.message(reply)
    return str(resp)


# ---------------------------------------------------------------------------
# Web chat widget
#
@app.route("/widget.js")
def serve_widget_js():
    """Serve the JavaScript for the embedded chat widget.

    The widget displays a floating button and a chat window.  When the user
    sends a message, it posts to ``/api/chat`` on the same host.  You can
    customise colours and text by overriding the CSS and the header text
    below.  To target a specific client, set the ``data-client-id`` attribute
    on the script tag that loads this file and it will be passed through to
    the API requests.
    """
    # The following JavaScript implements a dual-mode chat widget.  If the
    # page contains an element with id="kabuto-chat-widget", the chat
    # window is embedded inside that container and displayed by default.
    # Otherwise, a floating button appears in the bottom right corner
    # that toggles the chat window.  The script reads the API base URL
    # from the ``data-api`` attribute of the script tag and an
    # optional ``data-client-id`` to identify the tenant.
    js_code = """
    (() => {
      const scriptEl = document.currentScript || document.querySelector('script[src*="widget.js"]');
      const apiUrl = scriptEl && scriptEl.getAttribute('data-api') ? scriptEl.getAttribute('data-api') : '';
      const clientId = scriptEl && scriptEl.getAttribute('data-client-id') ? scriptEl.getAttribute('data-client-id') : 'default';
      // Shared function to post a message and update UI with styled bubbles
      async function postAndRender(text, msgsEl, inputEl) {
        if (!text) return;
        msgsEl.innerHTML += `<div class="kabuto-msg kabuto-user"><strong>Du:</strong> ${text}</div>`;
        inputEl.value = '';
        try {
          const res = await fetch(apiUrl + '/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: text, client_id: clientId })
          });
          const data = await res.json();
          msgsEl.innerHTML += `<div class="kabuto-msg kabuto-bot"><strong>Kabuto:</strong> ${data.reply}</div>`;
          msgsEl.scrollTop = msgsEl.scrollHeight;
        } catch(err) {
          msgsEl.innerHTML += `<div><b>Fehler:</b> ${err}</div>`;
        }
      }
      // Attempt to mount inside existing placeholder
      const placeholder = document.getElementById('kabuto-chat-widget');
      if (placeholder) {
        // Build embedded chat window with glass effect and gradient header
        const container = document.createElement('div');
        container.id = 'kabuto-embedded';
        container.innerHTML = `
          <style>
            #kabuto-embedded { display: flex; flex-direction: column; max-width: 320px; margin-left: auto; margin-right: auto; height: 100%; backdrop-filter: blur(8px); background: rgba(17,17,27,0.6); border-radius: 16px; border: 1px solid rgba(255,255,255,0.08); box-shadow: 0 10px 30px rgba(0,0,0,0.5); font-family: 'Segoe UI', sans-serif; }
            #kabuto-embedded-header { background: linear-gradient(90deg,#9d4edd,#5f0cff,#3b0764); padding: 12px; color: #f0f0f0; text-align: center; font-weight: 600; border-bottom: 1px solid rgba(255,255,255,0.06); }
            #kabuto-embedded-messages { flex: 1; padding: 12px; overflow-y: auto; font-size: 14px; color: #e0e0e0; }
            #kabuto-embedded-input { display: flex; border-top: 1px solid rgba(255,255,255,0.06); }
            #kabuto-embedded-input input { flex: 1; padding: 12px; border: none; background: rgba(17,17,27,0.8); color: #fff; font-family: inherit; }
            #kabuto-embedded-input button { background: linear-gradient(135deg,#9d4edd,#5f0cff); color: #fff; border: none; padding: 12px 18px; cursor: pointer; transition: transform 0.2s ease; font-size: 14px; }
            #kabuto-embedded-input button:hover { transform: scale(1.05); }
            /* Colour-coded messages */
            #kabuto-embedded-messages .kabuto-msg { margin-bottom: 0.5rem; }
            #kabuto-embedded-messages .kabuto-user { color: #9d4edd; }
            #kabuto-embedded-messages .kabuto-bot { color: #7dd3fc; }
          </style>
          <div id="kabuto-embedded-header">Kabuto AI Chat</div>
          <div id="kabuto-embedded-messages"></div>
          <div id="kabuto-embedded-input">
            <input type="text" placeholder="Nachricht eingeben..."/>
            <button>➤</button>
          </div>
        `;
        placeholder.innerHTML = '';
        placeholder.appendChild(container);
        const msgs = container.querySelector('#kabuto-embedded-messages');
        const input = container.querySelector('#kabuto-embedded-input input');
        const sendBtn = container.querySelector('#kabuto-embedded-input button');
        sendBtn.onclick = () => postAndRender(input.value.trim(), msgs, input);
        input.addEventListener('keypress', e => { if (e.key === 'Enter') postAndRender(input.value.trim(), msgs, input); });
        return;
      }
      // Otherwise create floating button and window with neon gradient and glass effect
      const widget = document.createElement('div');
      widget.id = 'kabuto-widget';
      widget.innerHTML = `
        <style>
          #kabuto-chat-btn {
            position: fixed;
            bottom: 20px; right: 20px;
            background: linear-gradient(135deg,#9d4edd,#5f0cff,#3b0764);
            color: white; border: none;
            border-radius: 50%; width: 64px; height: 64px;
            font-size: 26px; cursor: pointer;
            box-shadow: 0 0 20px rgba(157,78,221,0.6), 0 0 40px rgba(95,12,255,0.4);
            transition: transform 0.3s ease, box-shadow 0.3s ease; z-index: 9999;
          }
          #kabuto-chat-btn:hover { transform: scale(1.1) translateY(-2px); box-shadow: 0 0 25px rgba(157,78,221,0.8), 0 0 50px rgba(95,12,255,0.6); }
          #kabuto-window {
            position: fixed; bottom: 100px; right: 20px;
            width: 320px; height: 460px;
            backdrop-filter: blur(8px);
            background: rgba(17,17,27,0.6);
            border-radius: 16px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.5);
            display: none; flex-direction: column;
            overflow: hidden; z-index: 9999;
            border: 1px solid rgba(255,255,255,0.08);
            font-family: 'Segoe UI', sans-serif;
          }
          #kabuto-header {
            background: linear-gradient(90deg,#9d4edd,#5f0cff,#3b0764);
            padding: 12px; color: #f0f0f0; text-align: center;
            font-weight: 600;
            border-bottom: 1px solid rgba(255,255,255,0.06);
          }
          #kabuto-messages { flex: 1; padding: 12px; overflow-y: auto; font-size: 14px; color: #e0e0e0; }
          #kabuto-input { display: flex; border-top: 1px solid rgba(255,255,255,0.06); }
          #kabuto-input input { flex: 1; padding: 12px; border: none; background: rgba(17,17,27,0.8); color: #fff; font-family: inherit; }
          #kabuto-input button { background: linear-gradient(135deg,#9d4edd,#5f0cff); color: #fff; border: none; padding: 12px 18px; cursor: pointer; transition: transform 0.2s ease; font-size: 14px; }
          #kabuto-input button:hover { transform: scale(1.05); }
          /* Colour-coded messages */
          #kabuto-messages .kabuto-msg { margin-bottom: 0.5rem; }
          #kabuto-messages .kabuto-user { color: #9d4edd; }
          #kabuto-messages .kabuto-bot { color: #7dd3fc; }
        </style>
        <button id='kabuto-chat-btn'>💬</button>
        <div id='kabuto-window'>
          <div id='kabuto-header'>Kabuto AI Chat</div>
          <div id='kabuto-messages'></div>
          <div id='kabuto-input'>
            <input type='text' placeholder='Nachricht eingeben...'/>
            <button>➤</button>
          </div>
        </div>
      `;
      document.body.appendChild(widget);
      const btn = widget.querySelector('#kabuto-chat-btn');
      const win = widget.querySelector('#kabuto-window');
      const msgs = widget.querySelector('#kabuto-messages');
      const input = widget.querySelector('#kabuto-input input');
      const sendBtn = widget.querySelector('#kabuto-input button');
      btn.onclick = () => win.style.display = win.style.display === 'flex' ? 'none' : 'flex';
      sendBtn.onclick = () => postAndRender(input.value.trim(), msgs, input);
      input.addEventListener('keypress', e => { if (e.key === 'Enter') postAndRender(input.value.trim(), msgs, input); });
    })();
    """
    # Permit cross-origin access to the widget script so it can be loaded
    # from static sites hosted on different domains (e.g. your static render app).
    return js_code, 200, {
        'Content-Type': 'application/javascript',
        'Access-Control-Allow-Origin': '*'
    }


@app.route("/api/chat", methods=["POST"])
def chat_api():
    """Handle messages from the web chat widget.

    Expects JSON payload with ``message`` and optional ``client_id``.
    Returns a JSON response with the assistant's reply.  If no client_id is
    supplied, 'default' is used.  The channel_id for web chat is the
    combination of client_id and the remote IP address, which groups
    messages per user session.
    """
    data = request.get_json(silent=True) or {}
    user_msg = (data.get("message") or "").strip()
    client_id = data.get("client_id", "default")
    if not user_msg:
        return jsonify({"reply": "Ich habe nichts empfangen."})
    # Use remote address to group messages from the same browser
    remote_ip = request.remote_addr or "anon"
    channel_id = f"web-{remote_ip}"
    reply = generate_reply_generic(client_id, channel_id, user_msg)
    response = jsonify({"reply": reply})
    # Add CORS header to allow cross-origin AJAX calls from static sites
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
    response.headers.add('Access-Control-Allow-Methods', 'POST')
    return response

# ---------------------------------------------------------------------------
# Landing page route
#
# Serve the landing page at /index.html instead of the bare root.  The root
# path is reserved for a health check/webhook status.  Serving at /index.html
# allows links back to the home page without clashing with the webhook.



# Explicit routes for the legal pages.  Use distinct function names to avoid
# duplicate endpoint collisions (Flask uses the function name as endpoint).

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/imprint.html")
def imprint_html():
    return render_template("imprint.html")


@app.route("/privacy.html")
def privacy_html():
    return render_template("privacy.html")


@app.route("/terms.html")
def terms_html():
    return render_template("terms.html")

# ---------------------------------------------------------------------------
# Overview / Brand Documentation Page
# ---------------------------------------------------------------------------
@app.route("/overview")
def overview():
    """Renders the KabutoAI overview & brand document page."""
    return render_template("overview.html")



# ---------------------------------------------------------------------------
# Optional helper to send proactive WhatsApp messages via Twilio
#
def send_whatsapp_message(to_number: str, body_text: str) -> None:
    """Send a WhatsApp message using Twilio's REST API.

    Requires TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN and TWILIO_WHATSAPP_NUMBER
    to be set.  If any are missing, the function logs an error and does
    nothing.  Use this helper to send notifications or proactive messages
    outside of webhook context.  Note that Twilio will only deliver
    messages once your WhatsApp number is verified by Meta.
    """
    if not (TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_WHATSAPP_NUMBER):
        print("⚠️ Twilio Credentials fehlen — kann keine WhatsApp-Nachricht senden.")
        return
    try:
        from twilio.rest import Client  # imported here to avoid dependency if unused
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        message = client.messages.create(
            from_=TWILIO_WHATSAPP_NUMBER,
            body=body_text,
            to=f"whatsapp:{to_number}"
        )
        print(f"✅ WhatsApp-Nachricht gesendet an {to_number}: {message.sid}")
    except Exception as e:
        print(f"⚠️ Fehler beim Senden der WhatsApp-Nachricht: {e}")


# ---------------------------------------------------------------------------
# Telegram webhook setup
#
WEBHOOK_PATH = f"/telegram/{TELEGRAM_API_TOKEN}"


@app.get("/health")
def health():
    """Health check endpoint for Render."""
    return "KabutoAI webhook OK", 200



@app.post(WEBHOOK_PATH)
def telegram_webhook():
    if request.headers.get("content-type") != "application/json":
        abort(403)
    update_json = request.get_json(silent=True, force=True)
    if not update_json:
        return "no json", 400
    update = telebot.types.Update.de_json(update_json)
    bot.process_new_updates([update])
    return "ok", 200


def ensure_webhook() -> None:
    """Ensure Telegram webhook is set on startup."""
    if not PUBLIC_BASE_URL:
        print("⚠️ Kein PUBLIC_BASE_URL gesetzt – kein Telegram-Webhook!")
        return
    url = PUBLIC_BASE_URL.rstrip("/") + WEBHOOK_PATH
    try:
        bot.remove_webhook()
        if bot.set_webhook(url=url):
            print(f"✅ Telegram Webhook gesetzt: {url}")
        else:
            print(f"⚠️ Konnte Webhook nicht setzen: {url}")
    except Exception as e:
        print(f"⚠️ set_webhook Fehler: {e}")


if __name__ == "__main__":
    print("🚀 KabutoAI startet...")
    try:
        ensure_webhook()
    except Exception as e:
        print(f"⚠️ Fehler beim Setzen des Telegram-Webhooks: {e}")

    app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False)

