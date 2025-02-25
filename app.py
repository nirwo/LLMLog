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
import threading
import markdown
import bleach

requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev_key_for_testing')
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB max upload
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
app.config['APP_NAME'] = 'WolfsLogDebugger'
app.config['APP_DESCRIPTION'] = 'Advanced log analysis and debugging tool powered by AI'
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0  # Disable caching for static files
app.config['DATABASE'] = os.path.join(app.root_path, 'logs.db')

# Precompile regex patterns for performance
ERROR_PATTERN = re.compile(r'\b(ERROR|FAILED|Exception:)\b', re.IGNORECASE)
TIMESTAMP_PATTERN = re.compile(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}')
BUILD_STAGE_PATTERN = re.compile(r'\[Stage : (.+?)\]')
WARNING_PATTERN = re.compile(r'\b(WARNING|WARN:)\b', re.IGNORECASE)

# Simple in-memory cache for development
LOG_CACHE = {}
SESSION_KEY = 'current_log'

# Import LLM service
try:
    from llm_service import check_llm_status, extract_error_context, analyze_error, get_llm_analysis
    LLM_AVAILABLE = check_llm_status()
    app.logger.info(f"LLM service available: {LLM_AVAILABLE}")
except ImportError as e:
    app.logger.warning(f"LLM service import error: {e}")
    LLM_AVAILABLE = False
except Exception as e:
    app.logger.warning(f"LLM service connection error: {e}")
    LLM_AVAILABLE = False

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
    """Initialize the database with schema"""
    try:
        # Ensure instance directory exists
        os.makedirs(app.instance_path, exist_ok=True)
        
        with app.app_context():
            # Get database connection
            db = get_db()
            
            # Read schema file
            with app.open_resource('schema.sql') as f:
                db.executescript(f.read().decode('utf8'))
                
            # Commit changes
            db.commit()
            app.logger.info("Database initialized successfully")
    except Exception as e:
        app.logger.error(f"Error initializing database: {str(e)}")
        import traceback
        app.logger.error(traceback.format_exc())

@app.teardown_appcontext
def close_db(error):
    db = g.pop('db', None)
    if db is not None:
        db.close()

@app.after_request
def add_cache_control(response):
    # Add cache control headers to prevent 304 responses
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

def fetch_log_from_url(url, skip_ssl_verify=False):
    """
    Fetch log content from a URL and save it locally
    """
    try:
        session = requests.Session()
        
        # Configure retry strategy
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        
        # Handle SSL verification
        verify = not skip_ssl_verify
        if not verify:
            # Disable SSL warnings if verification is disabled
            requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
            # Create unverified SSL context
            ssl._create_default_https_context = ssl._create_unverified_context
        
        # Make the request
        app.logger.info(f"Fetching log from URL: {url}")
        response = session.get(url, verify=verify, timeout=30)
        response.raise_for_status()
        
        # Get the content
        log_content = response.text
        
        # Download the file to the server
        file_path = os.path.join(app.instance_path, f"download_{uuid.uuid4()}.log")
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(log_content)
        
        app.logger.info(f"Log downloaded and saved to {file_path}")
        
        return log_content
        
    except requests.exceptions.RequestException as e:
        app.logger.error(f"Error fetching URL {url}: {str(e)}")
        raise Exception(f"Failed to fetch log from URL: {str(e)}")

@app.route('/')
def index():
    return render_template('index.html')

def analyze_log(log_content):
    """
    Analyze a log file to identify errors, warnings, and other patterns
    """
    try:
        lines = log_content.splitlines()
        file_id = str(uuid.uuid4())
        
        # Store in cache for preview and other operations
        LOG_CACHE[file_id] = lines
        
        # Find error and warning lines
        error_lines = []
        warning_lines = []
        build_stages = {}
        timestamps = []
        error_types = {}
        critical_lines = []
        
        # Patterns for error and stage detection
        stage_pattern = re.compile(r'^\[([^\]]+)\]')
        timestamp_pattern = re.compile(r'\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}')
        
        # Analyze each line
        for i, line in enumerate(lines):
            # Extract timestamp if present
            timestamp_match = timestamp_pattern.search(line)
            if timestamp_match:
                timestamps.append(timestamp_match.group(0))
            
            # Check for build stage
            stage_match = stage_pattern.search(line)
            if stage_match:
                stage = stage_match.group(1)
                if stage not in build_stages:
                    build_stages[stage] = {"start": i, "end": i, "errors": 0, "warnings": 0}
                else:
                    build_stages[stage]["end"] = i
            
            # Check for errors
            if ERROR_PATTERN.search(line):
                error_lines.append(i)
                
                # Update stage error count if we're in a stage
                for stage, data in build_stages.items():
                    if data["start"] <= i <= data["end"]:
                        data["errors"] += 1
                
                # Try to determine error type
                error_type = "Unknown Error"
                
                # Java exception pattern
                java_exception_match = re.search(r'([a-zA-Z0-9_$.]+Exception|Error)', line)
                if java_exception_match:
                    error_type = java_exception_match.group(1)
                # Python exception pattern
                elif 'Traceback' in line:
                    error_type = "Python Exception"
                # Generic error pattern
                elif 'ERROR:' in line:
                    error_parts = line.split('ERROR:', 1)
                    if len(error_parts) > 1:
                        error_type = error_parts[1].strip().split()[0]
                # Shell/bash error
                elif 'Command failed' in line or 'exit code' in line:
                    error_type = "Shell Error"
                
                # Count error types for chart
                error_types[error_type] = error_types.get(error_type, 0) + 1
                
                # Add to critical lines
                timestamp = timestamp_match.group(0) if timestamp_match else None
                critical_lines.append({
                    "line": i,
                    "content": line,
                    "timestamp": timestamp,
                    "type": "error"
                })
                
                # Save error line to database
                try:
                    db = get_db()
                    db.execute(
                        'INSERT INTO log_errors (log_id, line_number, level) VALUES (?, ?, ?)',
                        (file_id, i, "Error")
                    )
                    db.commit()
                except Exception as e:
                    app.logger.error(f"Error saving error line to database: {str(e)}")
                
            elif WARNING_PATTERN.search(line):
                warning_lines.append(i)
                
                # Update stage warning count if we're in a stage
                for stage, data in build_stages.items():
                    if data["start"] <= i <= data["end"]:
                        data["warnings"] += 1
                
                # Only include warnings in critical lines if we don't have too many errors
                if len(critical_lines) < 10:
                    timestamp = timestamp_match.group(0) if timestamp_match else None
                    critical_lines.append({
                        "line": i,
                        "content": line,
                        "timestamp": timestamp,
                        "type": "warning"
                    })
                    
                # Save warning line to database
                try:
                    db = get_db()
                    db.execute(
                        'INSERT INTO log_errors (log_id, line_number, level) VALUES (?, ?, ?)',
                        (file_id, i, "Warning")
                    )
                    db.commit()
                except Exception as e:
                    app.logger.error(f"Error saving warning line to database: {str(e)}")
        
        # Sort critical lines by importance (errors first, then warnings)
        critical_lines.sort(key=lambda x: 0 if x["type"] == "error" else 1)
        
        # Limit critical lines to most important ones
        critical_lines = critical_lines[:15]
        
        # Add context to critical lines - Get 2 lines before and after
        for i, critical in enumerate(critical_lines):
            line_num = critical["line"]
            context_before = []
            context_after = []
            
            # Get lines before
            for j in range(max(0, line_num - 2), line_num):
                context_before.append(lines[j])
                
            # Get lines after
            for j in range(line_num + 1, min(len(lines), line_num + 3)):
                context_after.append(lines[j])
                
            critical_lines[i]["context_before"] = context_before
            critical_lines[i]["context_after"] = context_after
        
        # Build the analysis result
        analysis = {
            "error_count": len(error_lines),
            "warning_count": len(warning_lines),
            "error_counts": {
                "Critical": sum(1 for err_type, count in error_types.items() 
                              if "Exception" in err_type or "Error" in err_type),
                "Error": sum(1 for err_type, count in error_types.items() 
                           if "Exception" not in err_type and "Error" not in err_type),
                "Warning": len(warning_lines)
            },
            "error_types": error_types,
            "build_stages": build_stages,
            "critical_lines": critical_lines,
            "start_time": timestamps[0] if timestamps else None,
            "end_time": timestamps[-1] if timestamps else None,
        }
        
        return {
            "file_id": file_id,
            "line_count": len(lines),
            "critical_lines": critical_lines,
            "error_counts": analysis["error_counts"],
            "build_stages": analysis["build_stages"],
            "start_time": analysis["start_time"],
            "end_time": analysis["end_time"]
        }
        
    except Exception as e:
        app.logger.error(f"Error analyzing log: {str(e)}")
        import traceback
        app.logger.error(traceback.format_exc())
        return {
            "error": f"Failed to analyze log: {str(e)}"
        }

def save_log_to_db(file_id, log_content):
    db = get_db()
    db.execute(
        'INSERT INTO logs (file_id, log_content) VALUES (?, ?)',
        (file_id, log_content)
    )
    db.commit()
    app.logger.info("Log saved to database")

def save_log_analysis_to_db(file_id, file_name, source_type, error_count, warning_count, content):
    """
    Save log analysis results to the database
    """
    try:
        db = get_db()
        db.execute(
            '''INSERT INTO log_files 
               (log_id, file_name, source_type, error_count, warning_count, content) 
               VALUES (?, ?, ?, ?, ?, ?)''',
            (file_id, file_name, source_type, error_count, warning_count, json.dumps(content))
        )
        db.commit()
        app.logger.info(f"Log analysis saved to database with ID: {file_id}")
        return True
    except Exception as e:
        app.logger.error(f"Error saving log analysis to database: {str(e)}")
        return False

@app.route('/analyze', methods=['POST'])
def analyze():
    try:
        log_content = None
        source = None
        
        if 'file' in request.files:
            file = request.files['file']
            
            if file.filename == '':
                return jsonify({"error": "No file selected"}), 400
                
            # Read file content
            log_content = file.read().decode('utf-8', errors='replace')
            source = 'file'
            name = file.filename
            
        elif 'url' in request.form:
            url = request.form['url']
            
            if not url:
                return jsonify({"error": "No URL provided"}), 400
                
            # Fetch log from URL
            response = fetch_log_from_url(url)
            
            if 'error' in response:
                return jsonify(response), 400
                
            log_content = response
            source = 'url'
            name = url
            
        else:
            return jsonify({"error": "No file or URL provided"}), 400
            
        # Analyze log content
        analysis_result = analyze_log(log_content)
        
        if 'error' in analysis_result:
            return jsonify(analysis_result), 500
            
        # Store analysis in database
        analysis_id = save_log_analysis_to_db(analysis_result['file_id'], name, source, analysis_result['error_counts']['Error'], analysis_result['error_counts']['Warning'], analysis_result)
        analysis_result['id'] = analysis_id
        
        # Automatically analyze error lines in the background
        if 'error_lines' in analysis_result and analysis_result['error_lines']:
            file_id = analysis_result['file_id']
            threading.Thread(
                target=auto_analyze_errors,
                args=(file_id, analysis_result['error_lines'])
            ).start()
        
        return jsonify(analysis_result)
        
    except Exception as e:
        app.logger.error(f"Analysis error: {str(e)}")
        return jsonify({"error": f"Failed to analyze log: {str(e)}"}), 500

@app.route('/llm/status', methods=['GET'])
def llm_status():
    """
    Check if the LLM service is available
    """
    try:
        # Import here to avoid errors if LLM dependencies are missing
        from llm_service import check_llm_status
        status = check_llm_status()
        app.logger.info(f"LLM service available: {status}")
        return jsonify(status)
    except ImportError as e:
        app.logger.warning(f"LLM service import error: {str(e)}")
        return jsonify({
            "available": False,
            "status": "LLM service unavailable",
            "message": f"Failed to import LLM service: {str(e)}"
        })
    except Exception as e:
        app.logger.error(f"Error checking LLM status: {str(e)}")
        return jsonify({
            "available": False,
            "status": "Error",
            "message": f"Error checking LLM status: {str(e)}"
        })

@app.route('/llm/analyze/<file_id>/<int:line_number>', methods=['GET'])
def llm_analyze(file_id, line_number):
    """
    Analyze an error line using LLM
    """
    try:
        # Check if file_id exists in cache
        if file_id not in LOG_CACHE:
            return jsonify({
                "error": "Log file not found in cache. Please re-upload the file."
            }), 404
            
        # Get the log lines
        log_lines = LOG_CACHE[file_id]
        
        # Validate line number
        if line_number < 0 or line_number >= len(log_lines):
            return jsonify({
                "error": f"Invalid line number: {line_number}. Log has {len(log_lines)} lines."
            }), 400
        
        # Extract error context
        from llm_service import extract_error_context, analyze_error
        context = extract_error_context(log_lines, line_number)
        if "error" in context:
            return jsonify({
                "error": context["error"]
            }), 400
            
        # Analyze error with LLM
        analysis = analyze_error(context)
        
        if "error" in analysis:
            return jsonify({
                "error": analysis["error"]
            }), 500
        
        # Return the analysis result
        return jsonify({
            "line_number": line_number,
            "error_line": log_lines[line_number],
            "result": analysis
        })
        
    except Exception as e:
        app.logger.error(f"Error in LLM analysis: {str(e)}")
        import traceback
        app.logger.error(traceback.format_exc())
        return jsonify({
            "error": f"Error analyzing with LLM: {str(e)}"
        }), 500

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

@app.route('/log/<file_id>/preview')
def log_preview(file_id):
    """Get a preview of the log file content with pagination"""
    try:
        if file_id not in LOG_CACHE:
            return jsonify({
                "error": "Log file not found"
            }), 404
            
        lines = LOG_CACHE[file_id]
        position = int(request.args.get('position', 0))
        
        # Calculate start and end positions
        start_line = max(0, position)
        end_line = min(len(lines), start_line + 40)  # Show 40 lines at a time
        
        # Get the preview lines
        preview_lines = lines[start_line:end_line]
        
        # Get error and warning lines
        error_lines = []
        warning_lines = []
        
        for i in range(start_line, end_line):
            line = lines[i] if i < len(lines) else ""
            if is_error_line(line):
                error_lines.append(i)
            elif is_warning_line(line):
                warning_lines.append(i)
        
        return jsonify({
            "start_line": start_line,
            "end_line": end_line,
            "total_lines": len(lines),
            "lines": preview_lines,
            "error_lines": error_lines,
            "warning_lines": warning_lines
        })
    except Exception as e:
        app.logger.error(f"Error getting log preview: {str(e)}")
        return jsonify({
            "error": f"Failed to get log preview: {str(e)}"
        }), 500

# Helper functions for error and warning detection
def is_error_line(line):
    """Check if a line contains an error pattern"""
    return ERROR_PATTERN.search(line) is not None

def is_warning_line(line):
    """Check if a line contains a warning pattern"""
    return WARNING_PATTERN.search(line) is not None

@app.route('/history')
def get_history():
    with get_db() as db:
        try:
            cursor = db.cursor()
            cursor.execute('''
                SELECT log_id, file_name, source_type, upload_time, error_count, warning_count 
                FROM log_files
                ORDER BY upload_time DESC
                LIMIT 10
            ''')
            
            records = cursor.fetchall()
            history = []
            
            for record in records:
                history.append({
                    'id': record[0],
                    'file_name': record[1],
                    'source_type': record[2],
                    'upload_time': record[3],
                    'error_count': record[4],
                    'warning_count': record[5]
                })
                
            return jsonify(history)
            
        except sqlite3.Error as e:
            app.logger.error(f"Database error retrieving history: {str(e)}")
            return jsonify([])

@app.route('/log/<log_id>')
def get_log_by_id(log_id):
    """Get a log analysis by its ID from the database"""
    try:
        with get_db() as db:
            cursor = db.cursor()
            
            # Get the log file record
            cursor.execute('''
                SELECT log_id, file_name, source_type, upload_time, error_count, warning_count, content 
                FROM log_files 
                WHERE log_id = ?
            ''', (log_id,))
            
            log_record = cursor.fetchone()
            
            if not log_record:
                return jsonify({"error": "Log not found"}), 404
                
            # Get the error lines
            cursor.execute('''
                SELECT line_number, level
                FROM log_errors
                WHERE log_id = ?
            ''', (log_id,))
            
            error_lines = cursor.fetchall()
            
            # Process the stored data
            lines = json.loads(log_record[6])  # Content column
            
            # Store in cache for preview and other operations
            file_id = log_record[0]
            LOG_CACHE[file_id] = lines
            
            # Count errors by type
            error_counts = {"Error": 0, "Warning": 0, "Info": 0}
            error_lines_list = []
            warning_lines_list = []
            
            for line_number, level in error_lines:
                if level in error_counts:
                    error_counts[level] += 1
                
                if level == "Error":
                    error_lines_list.append(line_number)
                elif level == "Warning":
                    warning_lines_list.append(line_number)
            
            # Prepare the result
            result = {
                "file_id": file_id,
                "name": log_record[1],
                "source_type": log_record[2],
                "upload_time": log_record[3],
                "line_count": len(lines),
                "error_counts": error_counts,
                "error_lines": error_lines_list,
                "warning_lines": warning_lines_list
            }
            
            return jsonify(result)
    
    except Exception as e:
        app.logger.error(f"Error retrieving log by ID: {str(e)}")
        return jsonify({"error": f"Failed to retrieve log: {str(e)}"}), 500

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

@app.route('/chat', methods=['POST'])
def chat():
    """
    Handle chat messages with the LLM
    """
    try:
        data = request.json
        message = data.get('message', '')
        file_id = data.get('file_id', '')
        
        if not message:
            return jsonify({
                "error": "No message provided"
            }), 400
        
        # Get log context if file_id is provided
        context = None
        if file_id:
            try:
                # Get log analysis from database
                db = get_db()
                cursor = db.cursor()
                cursor.execute(
                    "SELECT analysis FROM log_analysis WHERE file_id = ?", 
                    (file_id,)
                )
                result = cursor.fetchone()
                
                if result and result[0]:
                    analysis = json.loads(result[0])
                    
                    # Create a context for the LLM
                    context = {
                        "log_name": analysis.get("name", "Unknown"),
                        "error_count": analysis.get("error_counts", {}).get("Error", 0),
                        "warning_count": analysis.get("error_counts", {}).get("Warning", 0),
                        "build_stages": analysis.get("build_stages", {}),
                        "critical_lines": analysis.get("critical_lines", [])[:5]  # Limit to 5 critical lines
                    }
            except Exception as e:
                app.logger.error(f"Error getting log context: {str(e)}")
        
        # Check if LLM is available
        if not LLM_AVAILABLE:
            return jsonify({
                "response": "I'm sorry, the AI service is currently unavailable. Please try again later."
            })
        
        # Send message to LLM
        from llm_service import get_llm_analysis
        
        # Prepare prompt with context if available
        if context:
            prompt = f"""You are an AI assistant helping with Jenkins log analysis. 
            
The user has analyzed a log file with the following information:
- Log name: {context['log_name']}
- Error count: {context['error_count']}
- Warning count: {context['warning_count']}
- Build stages: {json.dumps(context['build_stages'], indent=2)}
- Some critical lines: {json.dumps(context['critical_lines'], indent=2)}

The user's message is: "{message}"

Provide a helpful response based on this context. If the user is asking about errors or issues in the log, 
refer to the critical lines and build stages information. If you don't know the answer, say so.
"""
        else:
            prompt = f"""You are an AI assistant helping with Jenkins log analysis. 
            
The user's message is: "{message}"

Provide a helpful response. If you don't know the answer, say so.
"""
        
        # Get response from LLM
        llm_response = get_llm_analysis(prompt)
        
        # Check if the response contains HTML tags
        contains_html = '<ul>' in llm_response or '<ol>' in llm_response or '<li>' in llm_response
        
        if contains_html:
            # If it contains HTML, just clean it with bleach but don't process with markdown
            cleaned_response = bleach.clean(llm_response, tags=['ul', 'ol', 'li', 'p', 'pre', 'code', 'em', 'strong', 'a', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'])
        else:
            # Otherwise, render markdown and then clean
            rendered_response = markdown.markdown(llm_response, extensions=['extra'])
            cleaned_response = bleach.clean(rendered_response, tags=['p', 'pre', 'code', 'em', 'strong', 'a', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'ul', 'ol', 'li'])
        
        # Store the chat in the database for future training
        store_chat_message(file_id, message, llm_response)
        
        return jsonify({
            "response": cleaned_response
        })
        
    except Exception as e:
        app.logger.error(f"Chat error: {str(e)}")
        return jsonify({"error": f"Failed to process chat: {str(e)}"}), 500

def store_chat_message(file_id, user_message, llm_message):
    """
    Store chat messages in the database
    """
    try:
        db = get_db()
        db.execute(
            'INSERT INTO chat_history (file_id, user_message, llm_message) VALUES (?, ?, ?)',
            (file_id, user_message, llm_message)
        )
        db.commit()
    except Exception as e:
        app.logger.error(f"Failed to store chat message: {str(e)}")

def auto_analyze_errors(file_id, error_lines):
    """
    Automatically analyze error lines and store solutions
    """
    if not error_lines or not file_id in LOG_CACHE:
        return
    
    lines = LOG_CACHE[file_id]
    
    for error_line_num in error_lines[:5]:  # Limit to first 5 errors to avoid overloading
        if error_line_num < len(lines):
            error_text = lines[error_line_num]
            
            # Get context around the error
            start_idx = max(0, error_line_num - 5)
            end_idx = min(len(lines), error_line_num + 5)
            context = "\n".join(lines[start_idx:end_idx])
            
            # Create prompt for error analysis
            prompt = f"""
You are a Jenkins log error analyzer. 
Analyze this error and provide a precise solution:

Error line: {error_text}

Context:
{context}

Provide a concrete solution for this error. Be specific and practical. If possible, include code examples or commands that could fix the issue.
"""
            
            # Call LLM service
            solution = get_llm_analysis(prompt)
            
            # Store solution in database
            store_error_solution(file_id, error_line_num, error_text, solution)

def store_error_solution(file_id, line_number, error_text, solution):
    """
    Store error solutions in the database
    """
    try:
        db = get_db()
        db.execute(
            'INSERT INTO error_solutions (file_id, line_number, error_text, solution) VALUES (?, ?, ?, ?)',
            (file_id, line_number, error_text, solution)
        )
        db.commit()
    except Exception as e:
        app.logger.error(f"Failed to store error solution: {str(e)}")

def save_analysis_to_db(source, name, analysis):
    db = get_db()
    cursor = db.cursor()
    cursor.execute(
        'INSERT INTO log_history (source, name, error_count, warning_count, summary, timestamp) VALUES (?, ?, ?, ?, ?, ?)',
        (source, name, analysis['error_counts']['Error'], analysis['error_counts']['Warning'],
         json.dumps({'error_counts': analysis['error_counts'], 'critical_lines': analysis['critical_lines']}),
         datetime.datetime.now())
    )
    db.commit()
    return cursor.lastrowid

if __name__ == '__main__':
    # Parse command line arguments
    import argparse
    parser = argparse.ArgumentParser(description='WolfsLogDebugger')
    parser.add_argument('--port', type=int, default=8086, help='Port to run the server on')
    parser.add_argument('--https', action='store_true', help='Run with HTTPS')
    args = parser.parse_args()
    
    # Initialize database
    with app.app_context():
        init_db()
    
    # Check if SSL certificates exist
    cert_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'certs', 'cert.pem')
    key_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'certs', 'key.pem')
    
    ssl_context = None
    if args.https and os.path.exists(cert_path) and os.path.exists(key_path):
        ssl_context = (cert_path, key_path)
        app.logger.info(f"Running with HTTPS using certificates: {cert_path}, {key_path}")
    elif args.https:
        app.logger.warning("HTTPS requested but certificates not found. Running in HTTP mode.")
    
    # Start the Flask server
    app.run(debug=True, host='0.0.0.0', port=args.port, ssl_context=ssl_context)
