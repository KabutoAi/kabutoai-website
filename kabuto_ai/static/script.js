<<<<<<< HEAD
const chatBtn = document.getElementById("chat-button");
const chatBox = document.getElementById("chat-box");
const input = document.getElementById("chat-input");
const messages = document.getElementById("chat-messages");

// API Endpoint deines Backends (Telegram-/KI-Logik)
const API_URL = "https://kabutoai-v1.onrender.com";

chatBtn.onclick = () => {
  chatBox.style.display = chatBox.style.display === "none" ? "flex" : "none";
};

input.addEventListener("keydown", async (e) => {
  if (e.key === "Enter") {
    const msg = input.value.trim();
    if (!msg) return;

    const userMsg = document.createElement("div");
    userMsg.className = "user";
    userMsg.textContent = "🧍 " + msg;
    messages.appendChild(userMsg);
    input.value = "";

    try {
      // Anfrage an dein Backend senden
      const res = await fetch(`${API_URL}/webhook`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: msg }),
      });

      if (!res.ok) throw new Error("Server error");
      const data = await res.json();

      const botMsg = document.createElement("div");
      botMsg.className = "bot";
      botMsg.textContent = "🤖 " + (data.reply || "Fehler beim Empfangen der Antwort.");
      messages.appendChild(botMsg);
      messages.scrollTop = messages.scrollHeight;

    } catch (error) {
      const errMsg = document.createElement("div");
      errMsg.className = "bot";
      errMsg.textContent = "⚠️ Fehler beim Senden — bitte später erneut versuchen.";
      messages.appendChild(errMsg);
      messages.scrollTop = messages.scrollHeight;
      console.error(error);
    }
  }
});
=======
const chatBtn = document.getElementById('chat-button');
const chatBox = document.getElementById('chat-box');
const input = document.getElementById('chat-input');
const messages = document.getElementById('chat-messages');

chatBtn.onclick = () => {
  chatBox.style.display = chatBox.style.display === 'none' ? 'flex' : 'none';
};

input.addEventListener('keydown', function (e) {
  if (e.key === 'Enter') {
    const msg = input.value;
    if (msg.trim() === '') return;
    const userMsg = document.createElement('div');
    userMsg.textContent = "🧑 " + msg;
    messages.appendChild(userMsg);
    input.value = '';

    // Dummy Antwort
    setTimeout(() => {
      const botMsg = document.createElement('div');
      botMsg.className = 'bot';
      botMsg.textContent = "🤖 " + "Das ist nur eine Demo-Antwort.";
      messages.appendChild(botMsg);
      messages.scrollTop = messages.scrollHeight;
    }, 500);
  }
});
>>>>>>> c0f6ec7207e1def3e5c7f2d155537c49c4ab306c
