// Global state
let currentLogState = {
    fileId: null,
    fileName: null,
    totalLines: 0,
    currentPosition: 0,
    hasAnalysis: false,
    errorCount: 0,
    warningCount: 0
};

// LLM connection state
let llmState = {
    available: false,
    model: null,
    checking: false
};

// Utility function to escape HTML
function escapeHtml(unsafe) {
    if (!unsafe) return '';
    return unsafe
        .toString()
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

// Check LLM Status and update UI
function checkLlmStatus() {
    fetch('/llm/status')
        .then(response => response.json())
        .then(data => {
            const statusElement = document.getElementById('llmStatus');
            if (!statusElement) return;
            
            if (data.available) {
                statusElement.innerHTML = `<span class="text-success"><i class="bi bi-check-circle-fill me-1"></i>Connected to ${data.message.split(': ')[1] || 'LLM'}</span>`;
                statusElement.classList.remove('text-danger', 'text-warning');
                statusElement.classList.add('text-success');
                
                // Enable LLM features
                llmState.available = true;
                enableLlmFeatures();
            } else {
                statusElement.innerHTML = `<span class="text-danger"><i class="bi bi-exclamation-circle-fill me-1"></i>${data.message}</span>`;
                statusElement.classList.remove('text-success', 'text-warning');
                statusElement.classList.add('text-danger');
                
                // Disable LLM features
                llmState.available = false;
                disableLlmFeatures();
            }
        })
        .catch(error => {
            console.error('Error checking LLM status:', error);
            const statusElement = document.getElementById('llmStatus');
            if (statusElement) {
                statusElement.innerHTML = '<span class="text-warning"><i class="bi bi-exclamation-triangle-fill me-1"></i>LLM status check failed</span>';
                statusElement.classList.remove('text-success', 'text-danger');
                statusElement.classList.add('text-warning');
            }
        });
}

// Document ready handler
document.addEventListener('DOMContentLoaded', function() {
    console.log("Document loaded, initializing...");
    
    // Initialize the application
    checkLlmStatus();
    
    // Load history on page load
    loadHistory();
    
    // Setup theme toggle
    const themeToggle = document.getElementById('themeToggle');
    if (themeToggle) {
        themeToggle.addEventListener('click', toggleTheme);
    }
    
    // Setup form submission
    setupUploadForm();
    
    // Setup tab behavior
    setupTabBehavior();
    
    // Hide any error displays
    hideErrors();
    
    // Chat functionality
    const chatForm = document.getElementById('chatForm');
    const chatInput = document.getElementById('chatInput');
    const chatMessages = document.getElementById('chatMessages');
    const clearChatBtn = document.getElementById('clearChatBtn');
    
    if (chatForm) {
        chatForm.addEventListener('submit', function(e) {
            e.preventDefault();
            
            const message = chatInput.value.trim();
            if (!message) return;
            
            // Add user message to chat
            appendMessage('user', message);
            
            // Clear input
            chatInput.value = '';
            
            // Show typing indicator
            const typingIndicator = document.createElement('div');
            typingIndicator.className = 'chat-message chat-message-bot';
            typingIndicator.innerHTML = `
                <div class="chat-bubble">
                    <div class="typing-dots"><span></span><span></span><span></span></div>
                </div>
            `;
            chatMessages.appendChild(typingIndicator);
            chatMessages.scrollTop = chatMessages.scrollHeight;
            
            // Send to server
            sendChatMessage(message, typingIndicator);
        });
    }
    
    if (clearChatBtn) {
        clearChatBtn.addEventListener('click', function() {
            if (chatMessages) {
                // Keep only the welcome message
                chatMessages.innerHTML = `
                    <div class="chat-welcome">
                        <p><i class="bi bi-robot me-2"></i>Hello! I'm your log analysis assistant. I can help you understand the errors in your logs and suggest solutions.</p>
                        <p>Ask me anything about the log you've analyzed!</p>
                    </div>
                `;
            }
        });
    }
});

// Function to append a message to the chat
function appendMessage(sender, message) {
    const chatMessages = document.getElementById('chatMessages');
    if (!chatMessages) return;
    
    const messageElement = document.createElement('div');
    messageElement.className = `chat-message chat-message-${sender}`;
    
    messageElement.innerHTML = `
        <div class="chat-bubble">
            ${escapeHtml(message)}
        </div>
    `;
    
    chatMessages.appendChild(messageElement);
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

// Function to send a chat message to the server
function sendChatMessage(message, typingIndicator) {
    if (!currentLogState.fileId) {
        // Remove typing indicator
        if (typingIndicator) typingIndicator.remove();
        
        // Add error message
        const chatMessages = document.getElementById('chatMessages');
        if (chatMessages) {
            const errorElement = document.createElement('div');
            errorElement.className = 'chat-message chat-message-bot';
            errorElement.innerHTML = `
                <div class="chat-bubble text-danger">
                    <i class="bi bi-exclamation-triangle-fill me-2"></i>
                    Please upload and analyze a log file first so I can help you with specific issues.
                </div>
            `;
            chatMessages.appendChild(errorElement);
            chatMessages.scrollTop = chatMessages.scrollHeight;
        }
        return;
    }
    
    // Send to server
    fetch('/chat', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            message: message,
            fileId: currentLogState.fileId
        })
    })
    .then(response => {
        if (!response.ok) {
            throw new Error('Failed to send message');
        }
        return response.json();
    })
    .then(data => {
        // Remove typing indicator
        if (typingIndicator) typingIndicator.remove();
        
        // Process the response and format code blocks
        const formattedResponse = formatChatResponse(data.response);
        
        // Add bot message
        const chatMessages = document.getElementById('chatMessages');
        if (chatMessages) {
            const messageElement = document.createElement('div');
            messageElement.className = 'chat-message chat-message-bot';
            messageElement.innerHTML = `
                <div class="chat-bubble">
                    ${formattedResponse}
                </div>
            `;
            chatMessages.appendChild(messageElement);
            chatMessages.scrollTop = chatMessages.scrollHeight;
            
            // Apply syntax highlighting to code blocks
            messageElement.querySelectorAll('pre code').forEach((block) => {
                hljs.highlightElement(block);
            });
        }
    })
    .catch(error => {
        console.error('Error sending message:', error);
        
        // Remove typing indicator
        if (typingIndicator) typingIndicator.remove();
        
        // Add error message
        const chatMessages = document.getElementById('chatMessages');
        if (chatMessages) {
            const errorElement = document.createElement('div');
            errorElement.className = 'chat-message chat-message-bot';
            errorElement.innerHTML = `
                <div class="chat-bubble text-danger">
                    <i class="bi bi-exclamation-triangle-fill me-2"></i>
                    Sorry, I encountered an error while processing your message. Please try again.
                </div>
            `;
            chatMessages.appendChild(errorElement);
            chatMessages.scrollTop = chatMessages.scrollHeight;
        }
    });
}

// Function to format chat response with code blocks
function formatChatResponse(text) {
    if (!text) return '';
    
    // First escape HTML to prevent XSS
    let safeText = escapeHtml(text);
    
    // Format markdown code blocks
    safeText = safeText.replace(/```([a-z]*)\n([\s\S]*?)\n```/g, function(match, language, code) {
        const lang = language || 'plaintext';
        return `<pre><code class="language-${lang}">${code}</code></pre>`;
    });
    
    // Format inline code blocks
    safeText = safeText.replace(/`([^`]+)`/g, '<code>$1</code>');
    
    // Convert line breaks to <br>
    safeText = safeText.replace(/\n/g, '<br>');
    
    return safeText;
}

// Function to update chat context based on current log
function updateChatContext() {
    // Nothing to do if no log is loaded
    if (!currentLogState.fileId) return;
    
    // Update welcome message with context
    const chatMessages = document.getElementById('chatMessages');
    if (!chatMessages) return;
    
    // Check if we already have messages (not just the welcome message)
    if (chatMessages.querySelectorAll('.chat-message').length > 0) {
        return; // Don't update if user has already started chatting
    }
    
    // Update welcome message
    chatMessages.innerHTML = `
        <div class="chat-welcome">
            <p><i class="bi bi-robot me-2"></i>Hello! I'm analyzing <strong>${escapeHtml(currentLogState.fileName)}</strong>.</p>
            <p>I found ${currentLogState.errorCount} errors and ${currentLogState.warningCount} warnings. Ask me anything about these issues!</p>
        </div>
    `;
}

// Setup the upload form handlers
function setupUploadForm() {
    const uploadForm = document.getElementById('uploadForm');
    const urlForm = document.getElementById('urlForm');
    
    if (uploadForm) {
        uploadForm.addEventListener('submit', function(e) {
            e.preventDefault();
            analyzeLog('file');
        });
    }
    
    if (urlForm) {
        urlForm.addEventListener('submit', function(e) {
            e.preventDefault();
            analyzeLog('url');
        });
    }
}

// Setup tab behavior
function setupTabBehavior() {
    // Listen for tab changes
    const tabs = document.querySelectorAll('button[data-bs-toggle="tab"]');
    tabs.forEach(tab => {
        tab.addEventListener('shown.bs.tab', function(event) {
            const targetId = event.target.getAttribute('id');
            if (targetId === 'history-tab') {
                loadHistory();
            } else if (targetId === 'chat-tab') {
                updateChatContext();
            }
        });
    });
}

// Hide any error displays
function hideErrors() {
    const errorElements = document.querySelectorAll('.error-message');
    errorElements.forEach(el => {
        el.style.display = 'none';
    });
}

// Load history on page load
async function loadHistory() {
    const historyTable = document.getElementById('historyTable');
    if (!historyTable) {
        console.error('History table not found');
        return;
    }
    
    // Show loading state
    historyTable.innerHTML = `
        <tr>
            <td colspan="6" class="text-center p-5">
                <div class="d-flex justify-content-center">
                    <div class="spinner-border text-primary" role="status">
                        <span class="visually-hidden">Loading...</span>
                    </div>
                </div>
            </td>
        </tr>
    `;
    
    // Fetch history data
    fetch('/history')
        .then(response => {
            if (!response.ok) {
                throw new Error('Failed to load history');
            }
            return response.json();
        })
        .then(data => {
            if (data.length === 0) {
                historyTable.innerHTML = `
                    <tr>
                        <td colspan="6" class="text-center p-5">
                            <div class="text-muted">
                                <i class="bi bi-clock-history me-2"></i>
                                No log analysis history found
                            </div>
                        </td>
                    </tr>
                `;
                return;
            }
            
            // Render history items
            let html = '';
            data.forEach(item => {
                const date = new Date(item.upload_time * 1000);
                const formattedDate = date.toLocaleString();
                
                html += `
                    <tr>
                        <td>${escapeHtml(item.file_name || 'Unnamed Log')}</td>
                        <td class="text-center">${item.source_type || 'File'}</td>
                        <td class="text-center">${item.error_count || 0}</td>
                        <td class="text-center">${item.warning_count || 0}</td>
                        <td class="text-center">${formattedDate}</td>
                        <td class="text-center">
                            <button class="btn btn-sm btn-primary" onclick="loadLogById('${item.id}')">
                                <i class="bi bi-eye"></i> View
                            </button>
                        </td>
                    </tr>
                `;
            });
            
            historyTable.innerHTML = html;
        })
        .catch(error => {
            console.error('Error loading history:', error);
            historyTable.innerHTML = `
                <tr>
                    <td colspan="6" class="text-center p-5">
                        <div class="alert alert-danger mb-0">
                            <i class="bi bi-exclamation-triangle-fill me-2"></i>
                            Failed to load history: ${error.message}
                        </div>
                    </td>
                </tr>
            `;
        });
}

// Function to update the chat context with current log info
function updateChatContext() {
    const chatWelcome = document.querySelector('.chat-welcome');
    if (chatWelcome && currentLogState.hasAnalysis) {
        chatWelcome.innerHTML = `
            <p><i class="bi bi-robot me-2"></i>Hello! I'm your log analysis assistant.</p>
            <p>You're currently working with: <strong>${currentLogState.fileName}</strong></p>
            <p>This log has ${currentLogState.errorCount} errors and ${currentLogState.warningCount} warnings.</p>
            <p>Ask me anything about the errors or how to fix them!</p>
        `;
    }
}

function renderCharts(analysis) {
    const ctx = document.getElementById('errorChart').getContext('2d');
    const isDark = document.documentElement.getAttribute('data-bs-theme') === 'dark';
    
    // Prepare data for the chart
    const labels = ['Critical', 'Error', 'Warning'];
    const data = [
        analysis.error_counts.Critical || 0,
        analysis.error_counts.Error || 0,
        analysis.error_counts.Warning || 0
    ];
    
    // Create or update chart - Fix for "destroy is not a function" error
    try {
        // Check if chart exists and is a valid Chart.js instance
        if (window.errorChart && typeof window.errorChart.destroy === 'function') {
            window.errorChart.destroy();
        } else if (window.errorChart) {
            // If exists but isn't a proper Chart instance, remove the reference
            window.errorChart = null;
            
            // Clear the canvas to prevent ghost charts
            const canvas = document.getElementById('errorChart');
            canvas.getContext('2d').clearRect(0, 0, canvas.width, canvas.height);
        }
    } catch (e) {
        console.warn('Error destroying previous chart:', e);
        // Ensure we don't have a broken reference
        window.errorChart = null;
    }
    
    // Create new chart with error handling
    try {
        window.errorChart = new Chart(ctx, {
            type: 'bar',  
            data: {
                labels: labels,
                datasets: [{
                    label: 'Count',
                    data: data,
                    backgroundColor: ['#dc3545', '#fd7e14', '#ffc107'],
                    borderWidth: 1,
                    borderRadius: 4,
                    borderColor: isDark ? '#212529' : '#fff'
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: true,
                indexAxis: 'y',  
                scales: {
                    x: {
                        beginAtZero: true,
                        ticks: {
                            precision: 0,  
                            color: isDark ? '#dee2e6' : '#212529'
                        },
                        grid: {
                            color: isDark ? 'rgba(255, 255, 255, 0.1)' : 'rgba(0, 0, 0, 0.1)'
                        }
                    },
                    y: {
                        ticks: {
                            color: isDark ? '#dee2e6' : '#212529'
                        },
                        grid: {
                            display: false
                        }
                    }
                },
                plugins: {
                    legend: {
                        display: false  
                    },
                    title: {
                        display: true,
                        text: 'Error Distribution',
                        font: { size: 14 },
                        color: isDark ? '#dee2e6' : '#212529'
                    }
                }
            }
        });
    } catch (chartError) {
        console.error('Failed to create chart:', chartError);
        document.getElementById('errorChart').insertAdjacentHTML('afterend', 
            `<div class="alert alert-warning">Failed to render chart: ${chartError.message}</div>`);
    }
}

function renderSummary(result) {
    // Update error and warning counts
    const errorCountElement = document.getElementById('errorCount');
    const warningCountElement = document.getElementById('warningCount');
    
    if (errorCountElement) {
        errorCountElement.textContent = result.error_counts.Error || 0;
    }
    
    if (warningCountElement) {
        warningCountElement.textContent = result.error_counts.Warning || 0;
    }
    
    // Render critical lines
    renderCriticalLines(result);
}

function renderCriticalLines(result) {
    const criticalLinesContainer = document.getElementById('criticalLines');
    if (!criticalLinesContainer) return;
    
    criticalLinesContainer.innerHTML = '';
    
    if (!result.critical_lines || result.critical_lines.length === 0) {
        criticalLinesContainer.innerHTML = `
            <div class="text-center p-4">
                <div class="text-muted">
                    <i class="bi bi-emoji-smile fs-1 mb-3"></i>
                    <p>No critical lines found in this log.</p>
                </div>
            </div>
        `;
        return;
    }
    
    // Create a list of critical lines with context
    let html = '<div class="list-group">';
    
    result.critical_lines.forEach(item => {
        const lineNumber = item.line;
        const content = item.content;
        const type = item.type;
        const typeClass = type === 'error' ? 'danger' : 'warning';
        
        html += `
            <div class="list-group-item list-group-item-action flex-column align-items-start" data-line="${lineNumber}" onclick="jumpToLine(${lineNumber})">
                <div class="d-flex w-100 justify-content-between">
                    <h6 class="mb-1">Line ${lineNumber + 1}</h6>
                    <div>
                        <span class="badge bg-${typeClass}">${type.toUpperCase()}</span>
                        <button class="btn btn-sm btn-outline-primary ms-2 analyze-line-btn" onclick="analyzeErrorWithLlm(${lineNumber}); event.stopPropagation();">
                            <i class="bi bi-magic"></i> Analyze
                        </button>
                    </div>
                </div>
                <p class="mb-1 text-${typeClass}"><code>${escapeHtml(content)}</code></p>
                
                ${item.context_before && item.context_before.length > 0 ? `
                    <div class="context-before small text-muted mt-2">
                        <div class="context-label">Context Before:</div>
                        ${item.context_before.map(line => `<div class="context-line">${escapeHtml(line)}</div>`).join('')}
                    </div>
                ` : ''}
                
                ${item.context_after && item.context_after.length > 0 ? `
                    <div class="context-after small text-muted mt-2">
                        <div class="context-label">Context After:</div>
                        ${item.context_after.map(line => `<div class="context-line">${escapeHtml(line)}</div>`).join('')}
                    </div>
                ` : ''}
            </div>
        `;
    });
    
    html += '</div>';
    criticalLinesContainer.innerHTML = html;
}

// Analyze an error line with the LLM
async function analyzeErrorWithLlm(lineNumber) {
    // Check if we have a file ID
    if (!currentLogState.fileId) {
        showToast('No log file loaded for analysis', 'error');
        return;
    }

    // Check LLM availability first
    fetch('/llm/status')
        .then(response => response.json())
        .then(data => {
            // Update LLM state
            llmState.available = data.available;
            
            if (!llmState.available) {
                showToast('LLM service is not available', 'error');
                return;
            }
            
            // Proceed with analysis
            const llmAnalysisResults = document.getElementById('llmAnalysisResults');
            if (llmAnalysisResults) {
                llmAnalysisResults.innerHTML = `
                    <div class="d-flex justify-content-center my-3">
                        <div class="spinner-border text-primary" role="status">
                            <span class="visually-hidden">Loading...</span>
                        </div>
                    </div>
                    <p class="text-center">Analyzing error with AI...</p>
                `;
            }
            
            // Store the selected line for refresh functionality
            currentLogState.selectedLine = lineNumber;
            
            // Make API call to analyze the error
            fetch(`/llm/analyze/${currentLogState.fileId}/${lineNumber}`)
                .then(response => {
                    if (!response.ok) {
                        throw new Error(`Error: ${response.status} - ${response.statusText}`);
                    }
                    return response.json();
                })
                .then(result => {
                    if (llmAnalysisResults) {
                        // Format the analysis result
                        llmAnalysisResults.innerHTML = `
                            <div class="card mb-3">
                                <div class="card-header bg-primary text-white">
                                    <i class="bi bi-lightbulb-fill me-2"></i>Error Analysis
                                </div>
                                <div class="card-body">
                                    <h5 class="card-title">Summary</h5>
                                    <p>${escapeHtml(result.result?.error_summary || "No summary available")}</p>
                                    
                                    <h5 class="card-title mt-3">Probable Cause</h5>
                                    <p>${escapeHtml(result.result?.probable_cause || "No probable cause identified")}</p>
                                    
                                    <h5 class="card-title mt-3">Suggested Fix</h5>
                                    <p>${escapeHtml(result.result?.suggested_fix || "No fix suggested")}</p>
                                    
                                    ${result.result?.additional_context ? `
                                        <h5 class="card-title mt-3">Additional Context</h5>
                                        <p>${escapeHtml(result.result.additional_context)}</p>
                                    ` : ''}
                                </div>
                            </div>
                        `;
                    }
                })
                .catch(error => {
                    console.error('Error analyzing with LLM:', error);
                    if (llmAnalysisResults) {
                        llmAnalysisResults.innerHTML = `
                            <div class="alert alert-danger">
                                <i class="bi bi-exclamation-triangle-fill me-2"></i>
                                Failed to analyze error: ${escapeHtml(error.message)}
                            </div>
                        `;
                    }
                });
        })
        .catch(error => {
            console.error('Error checking LLM status:', error);
            showToast('Failed to check LLM availability', 'error');
        });
}

// Function to load log preview showing the context
async function loadLogPreview() {
    if (!currentLogState.fileId) {
        console.error('No file ID available for preview');
        const logPreviewElement = document.getElementById('logPreview');
        if (logPreviewElement) {
            logPreviewElement.innerHTML = `
                <div class="alert alert-warning">
                    <i class="bi bi-exclamation-triangle-fill me-2"></i>
                    No log file loaded. Please analyze a log file first.
                </div>
            `;
        }
        return;
    }

    try {
        const logPreviewElement = document.getElementById('logPreview');
        if (logPreviewElement) {
            logPreviewElement.innerHTML = `
                <div class="d-flex justify-content-center my-4">
                    <div class="spinner-border text-primary" role="status">
                        <span class="visually-hidden">Loading...</span>
                    </div>
                </div>
            `;
        }

        const response = await fetch(
            `/log/${currentLogState.fileId}/preview?position=${currentLogState.currentPosition}`
        );
        
        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.error || 'Failed to load log preview');
        }

        const preview = await response.json();
        
        if (preview.error) {
            throw new Error(preview.error);
        }
        
        renderLogPreview(preview);
    } catch (error) {
        console.error('Preview load failed:', error);
        const logPreviewElement = document.getElementById('logPreview');
        if (logPreviewElement) {
            logPreviewElement.innerHTML = `
                <div class="alert alert-danger">
                    <i class="bi bi-exclamation-triangle-fill me-2"></i>
                    Failed to load log preview: ${error.message}
                </div>
            `;
        }
    }
}

// Function to render log preview
function renderLogPreview(context) {
    const previewContainer = document.getElementById('logPreview');
    if (!previewContainer) return;
    
    let html = '<div class="log-preview-container">';
    
    if (context.lines && context.lines.length > 0) {
        html += '<table class="log-preview-table">';
        
        context.lines.forEach((line, index) => {
            const lineNumber = context.start_line + index;
            const isError = context.error_lines && context.error_lines.includes(lineNumber);
            const isWarning = context.warning_lines && context.warning_lines.includes(lineNumber);
            
            const lineClass = isError ? 'log-line error-line' : 
                            isWarning ? 'log-line warning-line' : 
                            'log-line';
            
            html += `
                <tr class="${lineClass}" data-line="${lineNumber}" onclick="jumpToLine(${lineNumber})">
                    <td class="line-number">${lineNumber + 1}</td>
                    <td class="line-content">${escapeHtml(line)}</td>
                </tr>
            `;
        });
        
        html += '</table>';
        
        // Add navigation controls
        html += `
            <div class="log-preview-controls mt-3">
                <button class="btn btn-sm btn-secondary me-2" onclick="scrollLog(-20)">
                    <i class="bi bi-arrow-up"></i> Previous
                </button>
                <button class="btn btn-sm btn-secondary" onclick="scrollLog(20)">
                    <i class="bi bi-arrow-down"></i> Next
                </button>
            </div>
        `;
    } else {
        html += '<div class="text-center p-4">No log content available</div>';
    }
    
    html += '</div>';
    previewContainer.innerHTML = html;
}

// Function to jump to a specific line in the log
function jumpToLine(lineNumber) {
    if (!currentLogState.fileId) return;
    
    // Calculate position to ensure the line is visible
    currentLogState.currentPosition = Math.max(0, lineNumber - 10);
    
    // Load the log preview centered on the requested line
    loadLogPreview();
    
    // Highlight the line after the preview loads
    setTimeout(() => {
        const lineElement = document.querySelector(`.log-line[data-line="${lineNumber}"]`);
        if (lineElement) {
            lineElement.classList.add('highlighted-line');
            lineElement.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
    }, 100);
}

// Function to scroll the log up and down
function scrollLog(offset) {
    if (!currentLogState.fileId) return;
    
    // Calculate new position
    const newPosition = Math.max(0, currentLogState.currentPosition + offset);
    
    // Don't scroll past the end of the file
    if (newPosition >= currentLogState.totalLines) {
        showToast('End of log file reached');
        return;
    }
    
    // Update the current position
    currentLogState.currentPosition = newPosition;
    
    // Load the new log preview
    loadLogPreview();
}

// Function to load history
function loadHistory() {
    const historyTable = document.getElementById('historyTable');
    if (!historyTable) {
        console.error('History table not found');
        return;
    }
    
    // Show loading state
    historyTable.innerHTML = `
        <tr>
            <td colspan="6" class="text-center p-5">
                <div class="d-flex justify-content-center">
                    <div class="spinner-border text-primary" role="status">
                        <span class="visually-hidden">Loading...</span>
                    </div>
                </div>
            </td>
        </tr>
    `;
    
    // Fetch history data
    fetch('/history')
        .then(response => {
            if (!response.ok) {
                throw new Error('Failed to load history');
            }
            return response.json();
        })
        .then(data => {
            if (data.length === 0) {
                historyTable.innerHTML = `
                    <tr>
                        <td colspan="6" class="text-center p-5">
                            <div class="text-muted">
                                <i class="bi bi-clock-history me-2"></i>
                                No log analysis history found
                            </div>
                        </td>
                    </tr>
                `;
                return;
            }
            
            // Render history items
            let html = '';
            data.forEach(item => {
                const date = new Date(item.upload_time * 1000);
                const formattedDate = date.toLocaleString();
                
                html += `
                    <tr>
                        <td>${escapeHtml(item.file_name || 'Unnamed Log')}</td>
                        <td class="text-center">${item.source_type || 'File'}</td>
                        <td class="text-center">${item.error_count || 0}</td>
                        <td class="text-center">${item.warning_count || 0}</td>
                        <td class="text-center">${formattedDate}</td>
                        <td class="text-center">
                            <button class="btn btn-sm btn-primary" onclick="loadLogById('${item.id}')">
                                <i class="bi bi-eye"></i> View
                            </button>
                        </td>
                    </tr>
                `;
            });
            
            historyTable.innerHTML = html;
        })
        .catch(error => {
            console.error('Error loading history:', error);
            historyTable.innerHTML = `
                <tr>
                    <td colspan="6" class="text-center p-5">
                        <div class="alert alert-danger mb-0">
                            <i class="bi bi-exclamation-triangle-fill me-2"></i>
                            Failed to load history: ${error.message}
                        </div>
                    </td>
                </tr>
            `;
        });
}

// Function to load a log by ID from history
function loadLogById(logId) {
    fetch(`/log/${logId}`)
        .then(response => {
            if (!response.ok) {
                throw new Error('Failed to load log');
            }
            return response.json();
        })
        .then(result => {
            console.log("Retrieved log:", result);
            
            // Set current log state
            currentLogState = {
                fileId: result.file_id,
                fileName: result.name,
                totalLines: result.line_count,
                currentPosition: 0,
                hasAnalysis: true,
                errorCount: result.error_counts.Error || 0,
                warningCount: result.error_counts.Warning || 0
            };
            
            // Render charts and summary
            renderCharts(result);
            renderSummary(result);
            
            // Load log preview
            loadLogPreview();
            
            // Show results card
            const resultsCard = document.getElementById('resultsCard');
            if (resultsCard) resultsCard.style.display = 'block';
            
            // Show LLM section
            showLlmSection(result);
            
            // Update chat context
            updateChatContext();
            
            // Show toast
            showToast(`Log loaded successfully: ${result.name}`);
            
            // Switch to Analysis tab
            const analysisTab = document.getElementById('analysis-tab');
            if (analysisTab) {
                const tabInstance = new bootstrap.Tab(analysisTab);
                tabInstance.show();
            }
        })
        .catch(error => {
            console.error('Error loading log:', error);
            showToast(`Failed to load log: ${error.message}`, 'error');
        });
}

// Show error message
function showError(message) {
    const errorAlert = document.getElementById('errorAlert');
    const errorText = document.getElementById('errorText');
    
    if (errorAlert && errorText) {
        errorText.textContent = message;
        errorAlert.classList.remove('d-none');
    } else {
        console.error('Error display elements not found');
        console.error(message);
    }
}

// Hide errors
function hideErrors() {
    const errorAlert = document.getElementById('errorAlert');
    if (errorAlert) {
        errorAlert.classList.add('d-none');
    }
}

// Show toast notification
function showToast(message, type = 'info') {
    // Create toast container if it doesn't exist
    let toastContainer = document.getElementById('toastContainer');
    if (!toastContainer) {
        toastContainer = document.createElement('div');
        toastContainer.id = 'toastContainer';
        toastContainer.className = 'toast-container position-fixed bottom-0 end-0 p-3';
        document.body.appendChild(toastContainer);
    }
    
    // Create toast element
    const toastId = 'toast-' + Date.now();
    const toast = document.createElement('div');
    toast.className = `toast align-items-center text-white bg-${type}`;
    toast.id = toastId;
    toast.setAttribute('role', 'alert');
    toast.setAttribute('aria-live', 'assertive');
    toast.setAttribute('aria-atomic', 'true');
    
    // Create toast content
    toast.innerHTML = `
        <div class="d-flex">
            <div class="toast-body">
                ${escapeHtml(message)}
            </div>
            <button type="button" class="btn-close me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button>
        </div>
    `;
    
    // Add toast to container
    toastContainer.appendChild(toast);
    
    // Initialize and show toast
    const bsToast = new bootstrap.Toast(toast, {
        autohide: true,
        delay: 5000
    });
    bsToast.show();
    
    // Remove from DOM after hidden
    toast.addEventListener('hidden.bs.toast', function () {
        toast.remove();
    });
}

// Function to generate automatic summary with LLM
function generateAutoSummary(analysis) {
    if (!analysis || !analysis.file_id) return;
    
    // Add a section for auto-summary in the chat tab
    const chatMessages = document.getElementById('chatMessages');
    if (!chatMessages) return;
    
    // Show thinking indicator
    const thinkingMessage = document.createElement('div');
    thinkingMessage.className = 'chat-message chat-message-bot';
    thinkingMessage.innerHTML = `
        <div class="chat-bubble">
            <div class="typing-dots"><span></span><span></span><span></span></div>
            <div class="small text-muted">Analyzing log and generating summary...</div>
        </div>
    `;
    chatMessages.appendChild(thinkingMessage);
    chatMessages.scrollTop = chatMessages.scrollHeight;
    
    // Prepare prompt for the LLM
    const message = "Please analyze the log file and provide a summary of the main issues found";
    
    // Send to server
    fetch('/chat', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            message: message,
            fileId: analysis.file_id
        })
    })
    .then(response => {
        if (!response.ok) {
            throw new Error('Failed to generate summary');
        }
        return response.json();
    })
    .then(data => {
        // Remove thinking indicator
        thinkingMessage.remove();
        
        // Add bot message with summary
        const messageElement = document.createElement('div');
        messageElement.className = 'chat-message chat-message-bot';
        messageElement.innerHTML = `
            <div class="chat-bubble">
                <strong>Automatic Log Analysis Summary:</strong><br>
                ${data.response}
            </div>
        `;
        chatMessages.appendChild(messageElement);
        
        // Scroll to bottom
        chatMessages.scrollTop = chatMessages.scrollHeight;
        
        // Switch to the chat tab to show the summary
        const chatTab = document.getElementById('chat-tab');
        if (chatTab) {
            const tabInstance = new bootstrap.Tab(chatTab);
            tabInstance.show();
        }
    })
    .catch(error => {
        console.error('Error generating summary:', error);
        // Remove thinking indicator
        thinkingMessage.remove();
        
        // Add error message
        const errorElement = document.createElement('div');
        errorElement.className = 'chat-message chat-message-bot';
        errorElement.innerHTML = `
            <div class="chat-bubble text-danger">
                <i class="bi bi-exclamation-triangle-fill me-2"></i>
                Sorry, I couldn't generate a summary for this log file.
            </div>
        `;
        chatMessages.appendChild(errorElement);
        chatMessages.scrollTop = chatMessages.scrollHeight;
    });
}

// Function to show the LLM section if LLM is available
function showLlmSection(result) {
    // Check LLM status again to ensure we have the latest status
    fetch('/llm/status')
        .then(response => response.json())
        .then(data => {
            // Update the LLM state based on the latest status
            llmState.available = data.available;
            
            if (!llmState.available) {
                console.log('LLM not available, hiding section');
                const llmSection = document.getElementById('llmSection');
                if (llmSection) {
                    llmSection.style.display = 'none';
                }
                return;
            }
            
            // Show the LLM section
            const llmSection = document.getElementById('llmSection');
            if (llmSection) {
                llmSection.style.display = 'block';
            }
            
            // Clear previous analysis results
            const llmAnalysisResults = document.getElementById('llmAnalysisResults');
            if (llmAnalysisResults) {
                llmAnalysisResults.innerHTML = `
                    <div class="alert alert-info">
                        <i class="bi bi-info-circle-fill me-2"></i>
                        Click on an error line to analyze it with AI.
                    </div>
                `;
            }
            
            // Set up refresh button
            const refreshLlmBtn = document.getElementById('refreshLlmBtn');
            if (refreshLlmBtn) {
                refreshLlmBtn.onclick = function() {
                    if (currentLogState.selectedLine) {
                        analyzeErrorWithLlm(currentLogState.selectedLine);
                    } else if (result.error_lines && result.error_lines.length > 0) {
                        analyzeErrorWithLlm(result.error_lines[0]);
                    } else {
                        showToast('No error lines to analyze', 'warning');
                    }
                };
            }
        })
        .catch(error => {
            console.error('Error checking LLM status:', error);
            // If we can't check LLM status, assume it's not available
            llmState.available = false;
            const llmSection = document.getElementById('llmSection');
            if (llmSection) {
                llmSection.style.display = 'none';
            }
        });
}

async function analyzeLog(source) {
    const formData = new FormData();
    let isValid = false;
    
    if (source === 'file') {
        const fileInput = document.getElementById('logFile');
        const file = fileInput.files[0];
        
        if (!file) {
            showToast('No file selected', 'error');
            return;
        }
        
        formData.append('file', file);
        isValid = true;
    } else if (source === 'url') {
        const urlInput = document.getElementById('logUrl');
        const url = urlInput.value.trim();
        
        if (!url) {
            showToast('No URL provided', 'error');
            return;
        }
        
        formData.append('url', url);
        // Add the skip SSL checkbox value
        const skipSSL = document.getElementById('skipSSLVerification').checked;
        formData.append('skip_ssl_verify', skipSSL);
        
        isValid = true;
    }
    
    if (!isValid) {
        return;
    }
    
    // Show loading spinner and hide previous results
    const spinner = document.getElementById('analyzeSpinner');
    const resultsCard = document.getElementById('resultsCard');
    
    if (spinner) spinner.style.display = 'inline-block';
    if (resultsCard) resultsCard.style.display = 'none';
    
    // Hide the LLM section until we have analysis
    const llmSection = document.getElementById('llmSection');
    if (llmSection) {
        llmSection.style.display = 'none';
    }
    
    // Clear previous results
    const errorCountEl = document.getElementById('errorCount');
    const warningCountEl = document.getElementById('warningCount');
    const criticalLinesContainerEl = document.getElementById('criticalLinesContainer');
    const logPreviewEl = document.getElementById('logPreview');
    
    if (errorCountEl) errorCountEl.textContent = '0';
    if (warningCountEl) warningCountEl.textContent = '0';
    if (criticalLinesContainerEl) criticalLinesContainerEl.innerHTML = '';
    if (logPreviewEl) logPreviewEl.innerHTML = '';
    
    // Send the log for analysis
    fetch('/analyze', {
        method: 'POST',
        body: formData
    })
    .then(response => {
        if (!response.ok) {
            return response.json().then(err => {
                throw new Error(err.error || 'Failed to analyze log');
            });
        }
        return response.json();
    })
    .then(result => {
        console.log("Analysis result:", result); // Debug
        
        // Update current log state
        currentLogState.fileId = result.file_id;
        currentLogState.fileName = result.name || (source === 'file' ? 
            document.getElementById('logFile').files[0].name : 
            document.getElementById('logUrl').value.trim());
        currentLogState.errorCount = result.error_counts.Error || 0;
        currentLogState.warningCount = result.error_counts.Warning || 0;
        currentLogState.totalLines = result.line_count;
        currentLogState.hasAnalysis = true;
        
        // Update error count
        const errorCounter = document.getElementById('errorCount');
        if (errorCounter) {
            errorCounter.textContent = result.error_counts.Error;
            // Add red text for errors
            if (result.error_counts.Error > 0) {
                errorCounter.classList.add('text-danger');
            } else {
                errorCounter.classList.remove('text-danger');
            }
        }
        
        // Update warning count
        const warningCounter = document.getElementById('warningCount');
        if (warningCounter) {
            warningCounter.textContent = result.error_counts.Warning;
            // Add yellow text for warnings
            if (result.error_counts.Warning > 0) {
                warningCounter.classList.add('text-warning');
            } else {
                warningCounter.classList.remove('text-warning');
            }
        }
        
        // Render charts and summary
        renderCharts(result);
        renderSummary(result);
        
        // Load log preview to show context
        loadLogPreview();
        
        // Show results card
        if (resultsCard) resultsCard.style.display = 'block';
        
        // Show toast for successful analysis
        showToast(`Log analyzed successfully. Found ${result.error_counts.Error} errors and ${result.error_counts.Warning} warnings.`);
        
        // Show LLM section if available and auto-analyze the first error
        showLlmSection(result);
        if (result.error_lines && result.error_lines.length > 0) {
            // Auto analyze the first error
            setTimeout(() => {
                analyzeErrorWithLlm(result.error_lines[0]);
            }, 1000);
        }
        
        // Update the chat context and generate auto-summary
        updateChatContext();
        generateAutoSummary(result);
        
        // Refresh history
        loadHistory();
    })
    .catch(error => {
        console.error('Error:', error);
        showToast(error.message, 'error');
    })
    .finally(() => {
        // Hide spinner
        if (spinner) spinner.style.display = 'none';
    });
}
