# WolfsLogDebugger

A modern web application for analyzing log files with AI-powered insights and an intuitive interface.

## Features

- Upload log files or analyze logs directly from URLs
- Automatic error and warning detection
- Visual error distribution charts
- Critical line highlighting
- AI-powered error analysis and suggestions
- Interactive chat interface for log analysis questions
- Dark/Light mode support
- Analysis history tracking
- Responsive design

## Installation

1. Clone the repository:
```bash
git clone https://github.com/nirwo/LLMLog.git
cd LLMLog
```

2. Create a virtual environment and activate it:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

## Usage

### Running with HTTP (default)

1. Start the application:
```bash
python app.py
```

2. Open your browser and navigate to `http://localhost:8086`

### Running with HTTPS

1. The application includes self-signed certificates in the `certs` directory. To run with HTTPS:
```bash
python app.py --https
```

2. Open your browser and navigate to `https://localhost:8086`

3. Since the certificates are self-signed, you may need to accept the security warning in your browser.

### Creating Your Own SSL Certificates

If you want to create your own SSL certificates:

```bash
mkdir -p certs
cd certs
openssl req -x509 -newkey rsa:4096 -nodes -out cert.pem -keyout key.pem -days 365 -subj "/CN=localhost"
```

## Using the Application

1. Upload a log file or paste a log URL to analyze
2. View the automatic analysis results, including error counts and critical lines
3. Use the AI chat interface to ask questions about your log file
4. Click on error lines to get AI-powered analysis and suggested fixes

## Contributing

Pull requests are welcome. For major changes, please open an issue first to discuss what you would like to change.

## License

[MIT](https://choosealicense.com/licenses/mit/)
