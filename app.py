from flask import Flask, request, jsonify, render_template, session, g
import re
import datetime
import uuid
import sqlite3
import json
import requests
from urllib.parse import urlparse
import os
import certifi
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry
from urllib3.exceptions import InsecureRequestWarning

requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

app = Flask(__name__)
app.secret_key = 'dev-key-123'  # Required for session management
app.config['DATABASE'] = os.path.join(app.root_path, 'logs.db')

# Precompile regex patterns for performance
ERROR_PATTERN = re.compile(r'\b(ERROR|FAILED|Exception:)\b', re.IGNORECASE)
TIMESTAMP_PATTERN = re.compile(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}')
BUILD_STAGE_PATTERN = re.compile(r'\[Stage : (.+?)\]')

# Simple in-memory cache for development
LOG_CACHE = {}
SESSION_KEY = 'current_log'

def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(
            app.config['DATABASE'],
            detect_types=sqlite3.PARSE_DECLTYPES
        )
        g.db.row_factory = sqlite3.Row
    return g.db

def init_db():
    with app.app_context():
        db = get_db()
        with app.open_resource('schema.sql') as f:
            db.executescript(f.read().decode('utf8'))
        db.commit()

@app.teardown_appcontext
def close_db(error):
    db = g.pop('db', None)
    if db is not None:
        db.close()

def create_session():
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=[500, 502, 503, 504]
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    session.verify = certifi.where()  # Use certifi's certificate bundle
    return session

def fetch_log_from_url(url):
    try:
        session = create_session()
        response = session.get(url, timeout=30)
        response.raise_for_status()
        return response.text
    except requests.exceptions.SSLError:
        # If SSL verification fails, try without verification but log a warning
        session.verify = False
        try:
            response = session.get(url, timeout=30)
            response.raise_for_status()
            app.logger.warning(f"SSL verification failed for {url}, proceeded with insecure connection")
            return response.text
        except Exception as e:
            raise Exception(f"Failed to fetch log from URL (even with SSL verification disabled): {str(e)}")
    except Exception as e:
        raise Exception(f"Failed to fetch log from URL: {str(e)}")

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
        log_content = fetch_log_from_url(url)
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
