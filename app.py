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

def analyze_log(log_content):
    app.logger.info("Starting log analysis")
    
    # Initialize counters and storage
    error_counts = {"Critical": 0, "Error": 0, "Warning": 0}
    critical_lines = []
    line_number = 0
    
    try:
        # Split log into lines and analyze each line
        lines = log_content.splitlines()
        
        for line in lines:
            line_number += 1
            line = line.strip()
            
            if not line:  # Skip empty lines
                continue
                
            # Convert line to lowercase for case-insensitive matching
            line_lower = line.lower()
            
            # Check for different types of errors
            if any(critical in line_lower for critical in ['fatal error', 'critical', 'panic']):
                error_counts["Critical"] += 1
                # Store critical line with context
                critical_lines.append({
                    "line": line_number,
                    "content": line,
                    "timestamp": extract_timestamp(line)
                })
            elif 'error' in line_lower:
                error_counts["Error"] += 1
            elif 'warning' in line_lower:
                error_counts["Warning"] += 1
        
        app.logger.info(f"Analysis complete. Found {error_counts}")
        
        # Return analysis results
        return {
            "error_counts": error_counts,
            "critical_lines": critical_lines,
            "total_lines": line_number,
            "error": None
        }
        
    except Exception as e:
        app.logger.error(f"Error during log analysis: {str(e)}")
        return {
            "error": f"Failed to analyze log: {str(e)}",
            "error_counts": error_counts,
            "critical_lines": [],
            "total_lines": 0
        }

def extract_timestamp(line):
    """Extract timestamp from a log line using common patterns."""
    import re
    
    # Common timestamp patterns
    patterns = [
        r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:\.\d+)?',  # 2024-02-25 10:30:45.123
        r'\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2}',           # 2024/02/25 10:30:45
        r'\w{3} \d{2} \d{2}:\d{2}:\d{2}',                 # Feb 25 10:30:45
        r'\d{2}:\d{2}:\d{2}(?:\.\d+)?'                    # 10:30:45.123
    ]
    
    for pattern in patterns:
        match = re.search(pattern, line)
        if match:
            return match.group(0)
    
    return None

@app.route('/analyze', methods=['POST'])
def analyze():
    try:
        if 'file' in request.files:
            file = request.files['file']
            if file.filename == '':
                return jsonify({"error": "No file selected"}), 400
            log_content = file.read().decode('utf-8', errors='replace')
            source = f"File: {file.filename}"
        elif 'url' in request.form:
            url = request.form['url']
            skip_ssl_verify = request.form.get('skip_ssl_verify', 'false').lower() == 'true'
            log_content = fetch_log_from_url(url, skip_ssl_verify)
            source = f"URL: {url}"
        else:
            return jsonify({"error": "No file or URL provided"}), 400
            
        # Analyze the log
        analysis = analyze_log(log_content)
        
        if analysis.get("error"):
            return jsonify(analysis), 400
            
        # Store in history
        store_analysis(source, analysis)
        
        return jsonify(analysis)
        
    except Exception as e:
        app.logger.error(f"Error in /analyze endpoint: {str(e)}")
        return jsonify({"error": str(e)}), 400

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

def store_analysis(source, analysis):
    db = get_db()
    db.execute(
        'INSERT INTO log_history (source, name, error_count, warning_count, summary, timestamp) VALUES (?, ?, ?, ?, ?, ?)',
        (source, 'Log Analysis', analysis['error_counts']['Error'], analysis['error_counts']['Warning'],
         json.dumps({'error_counts': analysis['error_counts'], 'critical_lines': analysis['critical_lines']}),
         datetime.datetime.now())
    )
    db.commit()
    app.logger.info("Analysis saved to database")

if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=8081, debug=True)
