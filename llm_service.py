"""
LLM Service for Jenkins Log Analyzer
Connects to local LLM instance (e.g., Ollama, LocalAI) to analyze error logs
"""

import os
import re
import json
import logging
import requests
from typing import Dict, List, Optional, Any, Union
from pydantic import BaseModel, Field, validator
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Default values if not provided in environment
DEFAULT_LLM_API_URL = "http://localhost:11434/api/chat"
DEFAULT_LLM_MODEL = "llama3"  # Changed to llama2 which is more likely to be available
DEFAULT_LLM_TIMEOUT = 30

# Get configuration from environment or use defaults
LLM_API_URL = os.environ.get("LLM_API_URL", DEFAULT_LLM_API_URL)
LLM_MODEL = os.environ.get("LLM_MODEL", DEFAULT_LLM_MODEL)
LLM_TIMEOUT = int(os.environ.get("LLM_TIMEOUT", DEFAULT_LLM_TIMEOUT))

class ErrorAnalysisRequest(BaseModel):
    model: str
    prompt: str
    stream: bool = False
    options: Optional[Dict[str, Any]] = None
    
class ErrorAnalysisResponse(BaseModel):
    error_summary: str = Field(..., description="A concise summary of the error")
    probable_cause: str = Field(..., description="The likely root cause of the error")
    suggested_fix: str = Field(..., description="Recommended actions to resolve the issue")
    additional_context: Optional[str] = Field(None, description="Any additional information or explanation")

def check_llm_status() -> Dict[str, Union[bool, str]]:
    """
    Check if the LLM service is available and responding
    """
    try:
        # First try the health endpoint
        health_url = "http://localhost:11434/api/version"
        response = requests.get(health_url, timeout=5)
        
        if response.status_code == 200:
            logger.info(f"LLM service is running: {response.json()}")
            
            # Now check if the model is available by sending a minimal request
            test_request = {
                "model": LLM_MODEL,
                "messages": [
                    {"role": "user", "content": "Hello"}
                ],
                "stream": False
            }
            
            response = requests.post(
                LLM_API_URL, 
                json=test_request,
                timeout=5
            )
            
            if response.status_code == 200:
                return {
                    "available": True,
                    "status": "LLM service is available and model is loaded",
                    "message": f"Using model: {LLM_MODEL}"
                }
            else:
                logger.warning(f"LLM model test failed: {response.status_code} - {response.text}")
                return {
                    "available": False,
                    "status": f"LLM service returned status code {response.status_code}",
                    "message": f"The model {LLM_MODEL} may not be available. Try loading it with 'ollama pull {LLM_MODEL}'."
                }
        else:
            logger.warning(f"LLM health check failed: {response.status_code}")
            return {
                "available": False,
                "status": f"LLM service returned status code {response.status_code}",
                "message": "The LLM service is not responding correctly."
            }
    except requests.RequestException as e:
        logger.error(f"Failed to connect to LLM service: {str(e)}")
        return {
            "available": False,
            "status": "Connection failed",
            "message": f"Make sure Ollama is running on your system. Error: {str(e)}"
        }

def extract_error_context(lines: List[str], line_number: int, context_lines: int = 5) -> Dict[str, Any]:
    """
    Extract the error line and surrounding context
    
    Args:
        lines: List of log lines
        line_number: Index of the error line
        context_lines: Number of lines to include before and after
        
    Returns:
        Dictionary with error line and context
    """
    if not lines or line_number >= len(lines):
        return {
            "error": "Invalid line number or empty log"
        }
    
    # Get the error line
    error_line = lines[line_number]
    
    # Get context before
    start_idx = max(0, line_number - context_lines)
    context_before = lines[start_idx:line_number]
    
    # Get context after
    end_idx = min(len(lines), line_number + context_lines + 1)
    context_after = lines[line_number + 1:end_idx]
    
    # Try to identify error type
    error_type = "Unknown"
    for pattern, err_type in ERROR_PATTERNS.items():
        if re.search(pattern, error_line):
            error_type = err_type
            break
    
    # Try to identify more context by looking for related messages
    related_lines = []
    
    # Look for common patterns like stack traces, exception causes, etc.
    if "Exception" in error_line or "Error:" in error_line:
        # Search for stack trace lines
        for i in range(line_number + 1, min(len(lines), line_number + 20)):
            if re.search(r'^\s+at\s+[\w$.]+\(.*\)', lines[i]):  # Java stack trace pattern
                related_lines.append(lines[i])
            elif re.search(r'File ".*", line \d+', lines[i]):   # Python stack trace pattern
                related_lines.append(lines[i])
            elif re.search(r'Caused by:', lines[i]):            # Java cause indication
                related_lines.append(lines[i])
            elif len(related_lines) > 0 and lines[i].strip() == "":  # Empty line after stack trace
                break
    
    return {
        "error_line": error_line,
        "line_number": line_number,
        "context_before": context_before,
        "context_after": context_after,
        "error_type": error_type,
        "related_lines": related_lines
    }

def analyze_error(error_context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Send the error context to the LLM for analysis
    
    Args:
        error_context: Dictionary with error information
        
    Returns:
        Analysis results from the LLM
    """
    # Build a prompt for the LLM
    prompt = f"""You are an expert in Jenkins and CI/CD troubleshooting.
Analyze the following error from a Jenkins log and provide detailed insights.

ERROR LINE: {error_context["error_line"]}

CONTEXT BEFORE:
{os.linesep.join(error_context["context_before"])}

CONTEXT AFTER:
{os.linesep.join(error_context["context_after"])}

ADDITIONAL RELATED LINES:
{os.linesep.join(error_context["related_lines"]) if error_context["related_lines"] else "None"}

ERROR TYPE: {error_context["error_type"]}

Provide a comprehensive analysis in JSON format with these fields:
- error_summary: A concise summary of what went wrong
- probable_cause: The most likely root cause of this error
- suggested_fix: Step-by-step recommendations to resolve the issue
- additional_context: Any helpful context about this type of error

Format your response as valid JSON. Be specific and practical in your suggested fixes.
"""
    
    try:
        logger.info(f"Sending error analysis request to LLM at {LLM_API_URL}")
        
        # Create the request payload for chat API format
        request_data = {
            "model": LLM_MODEL,
            "messages": [
                {"role": "system", "content": "You are an expert in Jenkins and CI/CD troubleshooting who provides concise, accurate JSON responses."},
                {"role": "user", "content": prompt}
            ],
            "stream": False
        }
        
        # Send request to LLM API
        response = requests.post(
            LLM_API_URL,
            json=request_data,
            timeout=LLM_TIMEOUT
        )
        
        if response.status_code != 200:
            logger.error(f"LLM API returned error: {response.status_code} - {response.text}")
            return {
                "error": f"LLM API returned status code {response.status_code}",
                "details": response.text
            }
            
        response_data = response.json()
        
        # Extract content from the chat API response
        if "message" in response_data:
            content = response_data["message"]["content"]
        elif "choices" in response_data and len(response_data["choices"]) > 0:
            content = response_data["choices"][0]["message"]["content"]
        else:
            logger.error(f"Unexpected response format: {response_data}")
            return {"error": "Unable to parse LLM response", "details": str(response_data)}
        
        # Try to parse the JSON from the response
        try:
            # Extract just the JSON part if there's surrounding text
            json_match = re.search(r'({[\s\S]*})', content)
            if json_match:
                json_str = json_match.group(1)
                analysis_result = json.loads(json_str)
            else:
                analysis_result = json.loads(content)
                
            # Validate against our expected schema
            return {
                "error_summary": analysis_result.get("error_summary", "No summary provided"),
                "probable_cause": analysis_result.get("probable_cause", "No cause identified"),
                "suggested_fix": analysis_result.get("suggested_fix", "No fix suggested"),
                "additional_context": analysis_result.get("additional_context", "")
            }
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM response as JSON: {str(e)}")
            
            # Fall back to a simpler analysis if JSON parsing fails
            return {
                "error_summary": "Error analysis could not be structured properly",
                "probable_cause": "The error appears to be in the log line shown",
                "suggested_fix": "Please check the error message manually and look for common solutions",
                "additional_context": f"Raw LLM response: {content[:500]}..."
            }
    except requests.RequestException as e:
        logger.error(f"Request to LLM failed: {str(e)}")
        return {
            "error": f"Failed to connect to LLM service: {str(e)}"
        }

def get_llm_analysis(prompt):
    """
    Generic function to get analysis from LLM for any prompt
    """
    try:
        # Use the chat API endpoint which is more likely to work with modern LLMs
        llm_url = os.environ.get('LLM_API_URL', 'http://localhost:11434/api/chat')
        model = os.environ.get('LLM_MODEL', 'llama3')
        timeout = int(os.environ.get('LLM_TIMEOUT', 30))
        
        # Format payload for the chat endpoint
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "stream": False
        }
        
        logger.info(f"Sending request to LLM service: {llm_url}")
        response = requests.post(llm_url, json=payload, timeout=timeout)
        
        if response.status_code == 200:
            data = response.json()
            # Extract the response based on the API's response format
            message = data.get('message', {})
            content = message.get('content', "I couldn't analyze this properly.")
            logger.info(f"Got response from LLM service: {content[:50]}...")
            return content
        else:
            error_msg = f"Error from LLM API: {response.status_code} - {response.text}"
            logger.error(error_msg)
            return "Sorry, I encountered an error while analyzing."
    
    except Exception as e:
        error_msg = f"LLM analysis error: {str(e)}"
        logger.error(error_msg)
        return "Sorry, I encountered an error while analyzing the log. Please try again later."

# Common error patterns and their types
ERROR_PATTERNS = {
    r"java\.lang\.[A-Za-z]+Exception": "Java Exception",
    r"java\.io\.[A-Za-z]+Exception": "Java IO Exception",
    r"java\.net\.[A-Za-z]+Exception": "Java Network Exception",
    r"org\.springframework\.[A-Za-z]+Exception": "Spring Framework Exception",
    r"org\.hibernate\.[A-Za-z]+Exception": "Hibernate Exception",
    r"javax\.[A-Za-z]+Exception": "Java EE Exception",
    r"com\.amazonaws\.[A-Za-z]+Exception": "AWS SDK Exception",
    r"Traceback \(most recent call last\)": "Python Exception",
    r"ImportError|ModuleNotFoundError": "Python Import Error",
    r"SyntaxError": "Python Syntax Error",
    r"TypeError|ValueError|KeyError|IndexError": "Python Type/Value Error",
    r"npm ERR!": "NPM Error",
    r"yarn error": "Yarn Error",
    r"error: .* failed with exit code": "Build/Shell Error",
    r"Execution failed for task": "Gradle Task Error",
    r"Failed to execute goal": "Maven Goal Error",
    r"FATAL:": "Fatal Error",
    r"ERROR:": "Generic Error",
    r"WARNING:": "Warning Message",
    r"docker: Error": "Docker Error",
    r"kubectl.* error": "Kubernetes Error",
    r"SQLSTATE\[\d+\]": "SQL Error",
    r"ORA-\d+": "Oracle Database Error",
    r"Error \d+ \(\d+\)": "MySQL Error",
    r"error MSB\d+": "MSBuild Error",
    r"error CS\d+": "C# Compiler Error",
    r"error TS\d+": "TypeScript Error"
}
