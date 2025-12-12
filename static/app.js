document.addEventListener('DOMContentLoaded', () => {
    // === Chat Logic ===
    const userInput = document.getElementById('user-input');
    const sendBtn = document.getElementById('send-btn');
    const chatContainer = document.getElementById('chat-container');

    // Auto-focus input
    userInput.focus();

    function appendMessage(text, className) {
        const msgDiv = document.createElement('div');
        msgDiv.className = `message ${className}`;
        const bubble = document.createElement('div');
        bubble.className = 'bubble';
        bubble.innerHTML = text.replace(/\n/g, '<br>'); // Basic formatting
        msgDiv.appendChild(bubble);
        chatContainer.appendChild(msgDiv);

        // Scroll to bottom
        setTimeout(() => {
            msgDiv.scrollIntoView({ behavior: 'smooth', block: 'end' });
        }, 50);

        return msgDiv;
    }

    async function sendMessage() {
        const text = userInput.value.trim();
        if (!text) return;

        appendMessage(text, 'user');
        userInput.value = '';

        // Typing indicator
        const loadingDiv = document.createElement('div');
        loadingDiv.className = 'message bot';
        loadingDiv.innerHTML = '<div class="bubble">...</div>';
        chatContainer.appendChild(loadingDiv);
        loadingDiv.scrollIntoView({ behavior: 'smooth', block: 'end' });

        try {
            const res = await fetch('/api/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message: text })
            });
            const data = await res.json();

            loadingDiv.remove();

            if (data.messages && data.messages.length > 0) {
                // Filtered messages from server
                data.messages.forEach(msg => appendMessage(msg, 'bot'));
            } else {
                appendMessage("I'm sorry, I didn't get a response.", 'bot');
            }

        } catch (err) {
            loadingDiv.remove();
            appendMessage("Error: " + err.message, 'system');
        }
    }

    sendBtn.addEventListener('click', sendMessage);
    userInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') sendMessage();
    });
});
