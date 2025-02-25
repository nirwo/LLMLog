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
import ssl

requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

app = Flask(__name__)
app.secret_key = 'dev-key-123'  # Required for session management
app.config['DATABASE'] = os.path.join(app.root_path, 'logs.db')

# Precompile regex patterns for performance
ERROR_PATTERN = re.compile(r'\b(ERROR|FAILED|Exception:)\b', re.IGNORECASE)
TIMESTAMP_PATTERN = re.compile(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}')
BUILD_STAGE_PATTERN = re.compile(r'\[Stage : (.+?)\]')
WARNING_PATTERN = re.compile(r'\b(WARNING|WARN:)\b', re.IGNORECASE)

# Simple in-memory cache for development
LOG_CACHE = {}
SESSION_KEY = 'current_log'

# Create a custom SSL context using system certificates
def create_ssl_context(verify=True):
    if not verify:
        return False
        
    context = ssl.create_default_context()
    
    # Try to load system certificates
    try:
        # Try different certificate locations
        cert_paths = [
            '/etc/ssl/certs',  # Debian/Ubuntu
            '/etc/pki/tls/certs',  # RHEL/CentOS
            '/etc/ssl/cert.pem',  # OpenBSD, FreeBSD
            '/etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem',  # Some Linux
            certifi.where()  # certifi's certificates as last resort
        ]
        
        for cert_path in cert_paths:
            if os.path.exists(cert_path):
                app.logger.info(f"Loading certificates from: {cert_path}")
                if os.path.isdir(cert_path):
                    context.load_verify_locations(capath=cert_path)
                else:
                    context.load_verify_locations(cafile=cert_path)
                return context
                
    except Exception as e:
        app.logger.error(f"Error loading certificates: {e}")
    
    return True  # Fall back to requests' default behavior

def create_session(verify=True):
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=[500, 502, 503, 504]
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    
    # Set up SSL verification
    session.verify = create_ssl_context(verify)
    
    return session

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

def fetch_log_from_url(url, skip_ssl_verify=False):
    try:
        session = create_session(verify=not skip_ssl_verify)
        app.logger.info(f"Fetching URL {url} (Skip SSL: {skip_ssl_verify})")
        
        response = session.get(url, timeout=30)
        response.raise_for_status()
        return response.text
    except requests.exceptions.SSLError as ssl_err:
        error_msg = str(ssl_err)
        if "CERTIFICATE_VERIFY_FAILED" in error_msg:
            raise Exception(
                "SSL certificate verification failed. If this is an internal or self-signed certificate, "
                "try enabling 'Skip SSL verification' checkbox."
            )
        else:
            raise Exception(f"SSL Error: {error_msg}")
    except requests.exceptions.RequestException as e:
        raise Exception(f"Failed to fetch log from URL: {str(e)}")

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/analyze', methods=['POST'])
def analyze_log():
    try:
        app.logger.info(f"Received form data: {request.form}")
        app.logger.info(f"Received files: {request.files}")
        
        if 'file' in request.files:
            log_file = request.files['file']
            app.logger.info(f"Processing file: {log_file.filename}")
            if not log_file:
                return jsonify({'error': 'No file provided'}), 400
            log_content = log_file.read().decode('utf-8')
            source = 'file'
            name = log_file.filename
        elif 'url' in request.form:
            url = request.form.get('url', '').strip()
            skip_ssl_verify = request.form.get('skip_ssl_verify') == 'true'
            app.logger.info(f"Processing URL: {url} (Skip SSL: {skip_ssl_verify})")
            
            if not url:
                return jsonify({'error': 'No URL provided'}), 400
            
            if not url.startswith(('http://', 'https://')):
                url = 'https://' + url
                app.logger.info(f"Added https:// prefix. New URL: {url}")
                
            try:
                log_content = fetch_log_from_url(url, skip_ssl_verify)
                app.logger.info(f"Successfully fetched content from URL: {url}")
                source = 'url'
                name = url
            except Exception as e:
                app.logger.error(f"Error fetching URL {url}: {str(e)}")
                return jsonify({'error': str(e)}), 400
        else:
            app.logger.error("No file or URL found in request")
            return jsonify({'error': 'No file or URL provided'}), 400

        # Process the log content
        app.logger.info("Processing log content...")
        error_counts = {'Critical': 0, 'Error': 0, 'Warning': 0}
        critical_lines = []
        lines = log_content.splitlines()
        
        for i, line in enumerate(lines, 1):
            if ERROR_PATTERN.search(line):
                error_counts['Error'] += 1
                if 'Exception' in line or 'FATAL' in line:
                    error_counts['Critical'] += 1
                    critical_lines.append({
                        'line': i,
                        'content': line,
                        'timestamp': extract_timestamp(line)
                    })
            elif WARNING_PATTERN.search(line):
                error_counts['Warning'] += 1

        app.logger.info(f"Analysis complete. Found {error_counts['Error']} errors, {error_counts['Critical']} critical, {error_counts['Warning']} warnings")

        # Store analysis in database
        db = get_db()
        db.execute(
            'INSERT INTO log_history (source, name, error_count, warning_count, summary, timestamp) VALUES (?, ?, ?, ?, ?, ?)',
            (source, name, error_counts['Error'], error_counts['Warning'],
             json.dumps({'error_counts': error_counts, 'critical_lines': critical_lines}),
             datetime.datetime.now())
        )
        db.commit()
        app.logger.info("Analysis saved to database")

        return jsonify({
            'error_counts': error_counts,
            'critical_lines': critical_lines
        })

    except Exception as e:
        app.logger.error(f"Error analyzing log: {str(e)}")
        return jsonify({'error': f'Error analyzing log: {str(e)}'}), 500

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

def extract_timestamp(line):
    ts_match = TIMESTAMP_PATTERN.search(line)
    return ts_match.group(0) if ts_match else None

if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=8081, debug=True)
