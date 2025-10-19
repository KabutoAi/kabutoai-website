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
