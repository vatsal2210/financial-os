/* Finance OS — Client-side logic */

// --- Brokerage selection on onboarding ---
document.querySelectorAll('.brokerage-option').forEach(el => {
    el.addEventListener('click', () => {
        document.querySelectorAll('.brokerage-option').forEach(o => o.classList.remove('selected'));
        el.classList.add('selected');
        const input = document.getElementById('brokerage-input');
        if (input) input.value = el.dataset.brokerage;
        const typeSelect = document.getElementById('account-type');
        if (typeSelect && el.dataset.types) {
            const types = JSON.parse(el.dataset.types);
            typeSelect.innerHTML = types.map(t => `<option value="${t}">${t}</option>`).join('');
        }
    });
});

// --- File upload drag & drop ---
const uploadArea = document.getElementById('upload-area');
if (uploadArea) {
    const fileInput = document.getElementById('file-input');
    uploadArea.addEventListener('click', () => fileInput.click());
    uploadArea.addEventListener('dragover', (e) => {
        e.preventDefault();
        uploadArea.style.borderColor = 'var(--text-secondary)';
    });
    uploadArea.addEventListener('dragleave', () => { uploadArea.style.borderColor = ''; });
    uploadArea.addEventListener('drop', (e) => {
        e.preventDefault();
        uploadArea.style.borderColor = '';
        if (e.dataTransfer.files.length) {
            fileInput.files = e.dataTransfer.files;
            updateFileName(fileInput.files[0].name);
        }
    });
    if (fileInput) {
        fileInput.addEventListener('change', () => {
            if (fileInput.files.length) updateFileName(fileInput.files[0].name);
        });
    }
}

function updateFileName(name) {
    const label = document.getElementById('file-name');
    if (label) { label.textContent = name; label.style.color = 'var(--green)'; }
}

// --- Auto-submit filter changes ---
document.querySelectorAll('.auto-submit').forEach(el => {
    el.addEventListener('change', () => el.closest('form').submit());
});


// --- AI Side Panel ---
function toggleAIPanel() {
    const panel = document.getElementById('ai-panel');
    const isOpen = panel.classList.toggle('open');
    if (isOpen) {
        loadAIHistory();
        document.getElementById('ai-input').focus();
    }
}

// Close panel with Escape
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        const panel = document.getElementById('ai-panel');
        if (panel && panel.classList.contains('open')) {
            panel.classList.remove('open');
        }
    }
});

function loadAIHistory() {
    fetch('/api/ask/history')
        .then(r => r.json())
        .then(data => {
            const container = document.getElementById('ai-messages');
            if (!data.history.length) return; // keep placeholder
            container.innerHTML = '';
            data.history.forEach(msg => {
                const div = document.createElement('div');
                div.className = `ai-msg ${msg.role}`;
                div.textContent = msg.content;
                container.appendChild(div);
            });
            container.scrollTop = container.scrollHeight;
        })
        .catch(() => {});
}

function sendAIMessage(e) {
    e.preventDefault();
    const input = document.getElementById('ai-input');
    const question = input.value.trim();
    if (!question) return false;

    const container = document.getElementById('ai-messages');

    // Clear placeholder if present
    const placeholder = container.querySelector('.ai-placeholder');
    if (placeholder) placeholder.remove();

    // Show user message
    const userDiv = document.createElement('div');
    userDiv.className = 'ai-msg user';
    userDiv.textContent = question;
    container.appendChild(userDiv);

    // Show loading
    const loadingDiv = document.createElement('div');
    loadingDiv.className = 'ai-msg assistant loading';
    loadingDiv.textContent = 'Thinking...';
    container.appendChild(loadingDiv);
    container.scrollTop = container.scrollHeight;

    input.value = '';

    fetch('/api/ask', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question }),
    })
        .then(r => r.json())
        .then(data => {
            loadingDiv.classList.remove('loading');
            loadingDiv.textContent = data.answer;
            container.scrollTop = container.scrollHeight;
        })
        .catch(() => {
            loadingDiv.classList.remove('loading');
            loadingDiv.textContent = 'Error — check your API key in Settings.';
            container.scrollTop = container.scrollHeight;
        });

    return false;
}
