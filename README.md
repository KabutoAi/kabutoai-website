# Kabuto AI (Telegram + WhatsApp Bot)

## 🚀 Beschreibung
Ein KI-gesteuerter Chatbot mit Unterstützung für Telegram **und** WhatsApp (via Twilio), automatisch gehostet auf [Render.com](https://render.com). 

## 🔧 Setup (Lokal oder Render.com)
1. `.env` Datei erstellen auf Basis von `.env.example`
2. API-Keys einfügen
3. Optional: `python kabuto_ai/bot.py` zum lokalen Testen
4. Projekt auf **GitHub** pushen
5. Mit **Render.com** verbinden (Python Web Service)

## 📦 Benötigte Variablen (.env)
```ini
OPENAI_API_KEY=...
TELEGRAM_API_TOKEN=...
TWILIO_AUTH_TOKEN=...
TWILIO_ACCOUNT_SID=...
PORT=8080
```

## ✅ Features
- Telegram + WhatsApp gleichzeitig
- GPT-3.5-Antworten mit Mehrsprachigkeit
- Anti-Spam-System
- Automatisierter Start über Render