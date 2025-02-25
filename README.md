# JenAI - Jenkins Log Analyzer

A modern web application for analyzing Jenkins build logs with an intuitive interface and powerful features.

## Features

- Upload Jenkins log files or analyze logs directly from URLs
- Automatic error and warning detection
- Visual error distribution charts
- Critical line highlighting
- Dark/Light mode support
- Analysis history tracking
- Responsive design

## Installation

1. Clone the repository:
```bash
git clone https://github.com/nirwo/JenAI.git
cd JenAI
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

1. Start the application:
```bash
python app.py
```

2. Open your browser and navigate to `http://localhost:8081`

3. Upload a Jenkins log file or paste a Jenkins log URL to analyze

## Contributing

Pull requests are welcome. For major changes, please open an issue first to discuss what you would like to change.

## License

[MIT](https://choosealicense.com/licenses/mit/)
