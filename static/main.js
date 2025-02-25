// Global state
let currentLogState = {
    fileId: null,
    totalLines: 0,
    currentPosition: 0
};

// HTML escape function for safe rendering
function escapeHtml(unsafe) {
    return unsafe
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

// Theme management
function toggleTheme() {
    const html = document.documentElement;
    const currentTheme = html.getAttribute('data-bs-theme');
    const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
    html.setAttribute('data-bs-theme', newTheme);
    
    // Update theme toggle button icon
    const icon = document.querySelector('.btn-outline-light i');
    icon.className = newTheme === 'dark' ? 'bi bi-moon-stars' : 'bi bi-sun';
}

// Load history on page load
document.addEventListener('DOMContentLoaded', function() {
    // Load history on page load
    loadHistory();

    // Handle URL form submission
    document.getElementById('urlForm').addEventListener('submit', function(e) {
        e.preventDefault();
        const urlInput = document.getElementById('logUrl');
        const url = urlInput.value.trim();
        
        if (!url) {
            alert('Please enter a valid URL');
            return;
        }

        const formData = new FormData();
        formData.append('url', url);

        fetch('/analyze', {
            method: 'POST',
            body: formData
        })
        .then(response => {
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            return response.json();
        })
        .then(analysis => {
            if (analysis.error) {
                throw new Error(analysis.error);
            }
            renderCharts(analysis);
            renderSummary(analysis);
            document.getElementById('results').classList.remove('d-none');
            loadHistory(); // Refresh history after successful analysis
        })
        .catch(error => {
            console.error('Error:', error);
            alert('Error analyzing log: ' + error.message);
        });
    });

    // Handle file form submission
    document.getElementById('uploadForm').addEventListener('submit', function(e) {
        e.preventDefault();
        const fileInput = document.getElementById('logFile');
        const file = fileInput.files[0];
        
        if (!file) {
            alert('Please select a file');
            return;
        }

        const formData = new FormData();
        formData.append('file', file);

        fetch('/analyze', {
            method: 'POST',
            body: formData
        })
        .then(response => {
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            return response.json();
        })
        .then(analysis => {
            if (analysis.error) {
                throw new Error(analysis.error);
            }
            renderCharts(analysis);
            renderSummary(analysis);
            document.getElementById('results').classList.remove('d-none');
            loadHistory(); // Refresh history after successful analysis
        })
        .catch(error => {
            console.error('Error:', error);
            alert('Error analyzing log: ' + error.message);
        });
    });
});

async function loadHistory() {
    try {
        const response = await fetch('/history');
        const history = await response.json();
        
        const historyHtml = history.map(entry => `
            <div class="history-item">
                <div class="history-header">
                    <span class="badge bg-secondary">${entry.source}</span>
                    <span class="text-muted">${new Date(entry.timestamp).toLocaleString()}</span>
                </div>
                <div class="history-name text-truncate">${entry.name}</div>
                <div class="history-stats">
                    <span class="badge bg-danger">Errors: ${entry.error_count}</span>
                    <span class="badge bg-warning text-dark">Warnings: ${entry.warning_count}</span>
                </div>
            </div>
        `).join('');
        
        document.getElementById('logHistory').innerHTML = historyHtml;
    } catch (error) {
        console.error('Failed to load history:', error);
    }
}

async function analyzeLog(source) {
    const formData = new FormData();
    
    if (source === 'file') {
        const fileInput = document.getElementById('logFile');
        if (!fileInput.files.length) {
            alert('Please select a log file');
            return;
        }
        formData.append('log', fileInput.files[0]);
    } else {
        const urlInput = document.getElementById('logUrl');
        if (!urlInput.value) {
            alert('Please enter a Jenkins log URL');
            return;
        }
        formData.append('url', urlInput.value);
    }

    try {
        const response = await fetch('/analyze', {
            method: 'POST',
            body: formData
        });
        
        if (!response.ok) {
            throw new Error('Analysis failed');
        }
        
        const result = await response.json();
        currentLogState = {
            fileId: result.file_id,
            totalLines: result.line_count,
            currentPosition: 0
        };
        
        renderCharts(result.analysis);
        renderSummary(result.analysis);
        loadLogPreview();
        loadHistory();  // Refresh history after new analysis
    } catch (error) {
        console.error('Analysis failed:', error);
        alert('Failed to analyze log: ' + error.message);
    }
}

function renderCharts(analysis) {
    const ctx = document.getElementById('errorChart').getContext('2d');
    const isDark = document.documentElement.getAttribute('data-bs-theme') === 'dark';
    
    new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: Object.keys(analysis.error_counts),
            datasets: [{
                data: Object.values(analysis.error_counts),
                backgroundColor: ['#dc3545', '#ffc107', '#0dcaf0'],
                borderWidth: 1,
                borderColor: isDark ? '#212529' : '#fff'
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: true,
            plugins: {
                legend: { 
                    position: 'right',
                    labels: {
                        boxWidth: 12,
                        font: {
                            size: 11
                        },
                        color: isDark ? '#dee2e6' : '#212529'
                    }
                },
                title: {
                    display: true,
                    text: 'Error Types',
                    font: {
                        size: 14
                    },
                    color: isDark ? '#dee2e6' : '#212529'
                }
            }
        }
    });
}

function renderSummary(analysis) {
    document.getElementById('criticalLines').innerHTML = analysis.critical_lines
        .map(line => `
            <div class="critical-line" data-line="${line.line}" onclick="showLogContext(${line.line})">
                <div class="d-flex justify-content-between align-items-center mb-1">
                    <span class="badge bg-secondary">${line.timestamp || 'No timestamp'}</span>
                    <span class="badge bg-danger">Line ${line.line}</span>
                </div>
                <pre class="mb-0">${escapeHtml(line.content)}</pre>
            </div>
        `).join('');
}

function scrollLog(offset) {
    currentLogState.currentPosition = Math.max(0, 
        Math.min(currentLogState.totalLines - 50, 
        currentLogState.currentPosition + offset));
    loadLogPreview();
}

async function loadLogPreview() {
    if (!currentLogState.fileId) return;

    try {
        const response = await fetch(
            `/log-context/${currentLogState.fileId}/` +
            `${currentLogState.currentPosition}/${currentLogState.currentPosition + 50}`
        );
        
        if (!response.ok) {
            throw new Error('Failed to load log context');
        }

        const context = await response.json();
        renderLogPreview(context);
    } catch (error) {
        console.error('Preview load failed:', error);
    }
}

function renderLogPreview(context) {
    const preview = document.getElementById('logPreview');
    preview.innerHTML = context.lines.map((line, index) => {
        const lineNumber = context.start + index + 1;
        return `
            <div class="log-line ${isErrorLine(line) ? 'error-line' : ''}" 
                 data-line="${lineNumber}">
                <span class="line-number">${lineNumber}</span>
                <pre>${escapeHtml(line)}</pre>
            </div>
        `;
    }).join('');
    
    document.getElementById('currentRange').textContent = 
        `Lines ${context.start + 1}-${context.end} of ${context.total_lines}`;
}

function showLogContext(lineNumber) {
    currentLogState.currentPosition = Math.max(0, lineNumber - 10);
    loadLogPreview();
}

function isErrorLine(line) {
    return ERROR_PATTERN.test(line);
}

// Initialize error pattern
const ERROR_PATTERN = /\b(ERROR|FAILED|Exception:)\b/i;
