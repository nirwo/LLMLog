from flask import Flask, request, jsonify, render_template, session
import re
import datetime
import uuid
import sqlite3
import json
import requests
from urllib.parse import urlparse

app = Flask(__name__)
app.secret_key = 'dev-key-123'  # Required for session management

# Precompile regex patterns for performance
ERROR_PATTERN = re.compile(r'\b(ERROR|FAILED|Exception:)\b', re.IGNORECASE)
TIMESTAMP_PATTERN = re.compile(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}')
BUILD_STAGE_PATTERN = re.compile(r'\[Stage : (.+?)\]')

# Simple in-memory cache for development
LOG_CACHE = {}
SESSION_KEY = 'current_log'

# Database initialization
def init_db():
    with sqlite3.connect('logs.db') as conn:
        with open('schema.sql') as f:
            conn.executescript(f.read())

def get_db():
    db = sqlite3.connect('logs.db')
    db.row_factory = sqlite3.Row
    return db

# Initialize database on startup
with app.app_context():
    init_db()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/analyze', methods=['POST'])
def analyze_log():
    file_id = str(uuid.uuid4())
    
    if 'log' in request.files:
        log_file = request.files['log']
        log_content = log_file.read().decode('utf-8')
        source = 'file'
        name = log_file.filename
    elif 'url' in request.form:
        url = request.form['url']
        response = requests.get(url)
        response.raise_for_status()
        log_content = response.text
        source = 'url'
        name = url
    else:
        return jsonify({'error': 'No log file or URL provided'}), 400

    lines = log_content.split('\n')
    LOG_CACHE[file_id] = lines
    session[SESSION_KEY] = file_id
    
    analysis = analyze_log_content(lines)
    
    # Save to history
    with get_db() as db:
        db.execute('''
            INSERT INTO log_history 
            (source, name, error_count, warning_count, summary)
            VALUES (?, ?, ?, ?, ?)
        ''', (
            source,
            name,
            len([l for l in analysis['critical_lines'] if 'ERROR' in l['content'].upper()]),
            len([l for l in analysis['critical_lines'] if 'WARNING' in l['content'].upper()]),
            json.dumps(analysis)
        ))
        db.commit()

    return jsonify({
        'file_id': file_id,
        'line_count': len(lines),
        'analysis': analysis
    })

def analyze_log_content(lines):
    analysis = {
        'error_counts': {},
        'timeline': [],
        'stages': {},
        'critical_lines': []
    }

    for line_number, line in enumerate(lines, 1):
        ts_match = TIMESTAMP_PATTERN.search(line)
        timestamp = ts_match.group(0) if ts_match else None
        
        if ERROR_PATTERN.search(line):
            error_type = 'ERROR' if 'ERROR' in line.upper() else 'FAILURE'
            if error_type not in analysis['error_counts']:
                analysis['error_counts'][error_type] = 0
            analysis['error_counts'][error_type] += 1
            
            context_start = max(0, line_number - 6)
            context_end = min(len(lines), line_number + 5)
            
            analysis['critical_lines'].append({
                'line': line_number,
                'content': line.strip(),
                'timestamp': timestamp,
                'context': lines[context_start:context_end],
                'context_range': (context_start + 1, context_end)
            })
    
    return analysis

@app.route('/log-context/<file_id>/<int:start>/<int:end>')
def get_log_context(file_id, start, end):
    if file_id not in LOG_CACHE:
        return jsonify({'error': 'Log session expired'}), 404
    
    lines = LOG_CACHE[file_id]
    start = max(0, start)
    end = min(len(lines), end)
    
    return jsonify({
        'lines': lines[start:end],
        'start': start,
        'end': end,
        'total_lines': len(lines)
    })

@app.route('/history')
def get_history():
    with get_db() as db:
        history = db.execute('''
            SELECT id, source, name, error_count, warning_count, timestamp
            FROM log_history
            ORDER BY timestamp DESC
            LIMIT 10
        ''').fetchall()
    
    return jsonify([dict(row) for row in history])

if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=8081, debug=True)
