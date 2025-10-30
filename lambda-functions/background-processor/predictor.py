from openai import OpenAI
import os
import base64
# import cv2
# import numpy as np
# import torch
import requests
from urllib.parse import urlparse
import whois
# import pytesseract
import json
import re
from langchain.agents import Tool
from typing import Any, Dict, Union, List
import logging
from io import BytesIO
from PIL import Image

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Hyperparams
IMG_SIZE = 299
# DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
openai_key = os.environ.get("AI_API_KEY")
VT_API_KEY = os.environ.get('VIRUSTOTAL_API_KEY')
GSB_API_KEY = os.environ.get('GOOGLE_SAFE_BROWSING_KEY')



def is_base64_image(data: str) -> bool:
    """Check if input string looks like valid base64-encoded image data."""
    try:
        # Strip possible data URI prefix
        if data.startswith("data:image"):
            header, data = data.split(",", 1)

        decoded = base64.b64decode(data, validate=True)

        # Reject tiny payloads (too small to be an image)
        if len(decoded) < 10:
            return False

        # Try opening with Pillow
        with Image.open(BytesIO(decoded)) as img:
            img.verify()  # verify image integrity
            return True

    except Exception:
        return False

def summarize_website_checks(url_checks: Dict[str, Any]) -> str:
    """Summarize the results of website safety checks into a human-readable string."""
    summaries = []
    for url, checks in url_checks.items():
        verdict = checks.get("Verdict", "UNKNOWN")
        reasons = checks.get("Reason", [])
        if verdict == "UNSAFE":
            reason_str = "; ".join(reasons) if reasons else "Checks did not pass"
            summaries.append(f"URL: {url} - Verdict: {verdict} ({reason_str})")
        elif verdict == "UNKNOWN":
            reason_str = "; ".join(reasons) if reasons else "Domain age unknown"
            summaries.append(f"URL: {url} - Verdict: {verdict} ({reason_str})")
        else:
            reason_str = "No issues found"
            summaries.append(f"URL: {url} - Verdict: {reason_str}")
    return "\n".join(summaries)

def predict_response(input_data: Union[str, bytes, List[str]]) -> Dict[str, Any]:
    """
    Main entry point for scam detection.
    
    - Text input: Extract websites → Check URL safety → Analyze text
    - Image input (single or list): Analyze image(s) (extracts websites) → Check URL safety → Re-analyze with safety data
    """
    result = {"input_type": None, "steps": [], "final_output": None}
    
    # Check if it's a list of images
    if isinstance(input_data, list):
        return _process_image_input(input_data, result)
    elif isinstance(input_data, str) and not is_base64_image(input_data):
        return _process_text_input(input_data, result)
    elif isinstance(input_data, str) and is_base64_image(input_data):
        return _process_image_input(input_data, result)
    else:
        return _process_unsupported_input(result)


def _process_text_input(text_input: str, result: Dict[str, Any]) -> Dict[str, Any]:
    """Process text input for scam detection."""
    return _process_with_analysis(
        input_data=text_input,
        input_type="text",
        analysis_tool="TextScamAnalysis",
        result=result
    )


def _process_image_input(image_data: Union[str, List[str]], result: Dict[str, Any]) -> Dict[str, Any]:
    """Process image input (single or multiple) for scam detection."""
    # Convert single image to list for uniform processing
    if isinstance(image_data, str):
        image_data = [image_data]
    
    # Limit to maximum 3 images
    image_data = image_data[:3]
    
    return _process_with_analysis(
        input_data=image_data,
        input_type="image",
        analysis_tool="ImageScamAnalysis",
        result=result
    )


def _process_with_analysis(
    input_data: Union[str, List[str]],
    input_type: str,
    analysis_tool: str,
    result: Dict[str, Any]
) -> Dict[str, Any]:
    """Unified processing logic for both text and image inputs."""
    logger.info(f"Processing {input_type} input")
    result["input_type"] = input_type
    
    # Log number of images if processing multiple
    if isinstance(input_data, list):
        logger.info(f"Processing {len(input_data)} images")
    
    # Perform initial analysis
    result["steps"].append(analysis_tool)
    analysis_result = tool_map[analysis_tool](input_data)
    logger.info(f"{input_type} analysis result: {analysis_result}")
    
    # Parse result and extract websites
    final_result_json = parse_openai_text_output(analysis_result)
    extracted_websites = final_result_json.get('extracted_websites', [])
    
    # Check website safety if websites were found
    if extracted_websites:
        logger.info(f"Extracted websites from {input_type}: {extracted_websites}")
        result["steps"].append("URLSafetyChecker")
        url_safety_check = tool_map["URLSafetyChecker"](extracted_websites)
        logger.info(f"URL safety check: {url_safety_check}")
    else:
        url_safety_check = f'No websites detected in {input_type}'
        logger.info(f"No websites extracted from {input_type}")
    
    # Add website safety information to result
    final_result_json['website_safety_checks'] = url_safety_check
    final_result_json['website_safety_checks_summary'] = (
        summarize_website_checks(url_safety_check) 
        if isinstance(url_safety_check, dict) 
        else url_safety_check
    )
    
    return _finalize_result(result, final_result_json)


def _process_unsupported_input(result: Dict[str, Any]) -> Dict[str, Any]:
    """Handle unsupported input types."""
    logger.warning("Unsupported input type provided")
    result["input_type"] = "unsupported"
    
    unsupported_result = {
        "label": "Unknown",
        "AI_media_authenticity": "Unknown",
        "reason": "Unable to process input type, please provide text or base64 image. We will be adding support for more input types soon.",
        "recommendation": "None",
        "confidence": 0,
        "extracted_websites": [],
        "website_safety_checks": "N/A",
        "website_safety_checks_summary": "N/A"
    }
    
    return _finalize_result(result, unsupported_result)


def _finalize_result(result: Dict[str, Any], final_result_json: Dict[str, Any]) -> Dict[str, Any]:
    """Finalize the result structure and return it."""
    result["final_output"] = json.dumps(final_result_json)
    logger.info(f"Processing complete: {result['input_type']} - {len(result['steps'])} steps")
    return result


def parse_prediction_result(result_text):
    """Parse the prediction result into structured data"""
    try:
        logger.info(f"Parsing prediction result: {result_text}")
        lines = result_text.strip().split('\n')
        parsed = {
            'label': 'Unknown',
            'confidence': 0,
            'reason': 'Unable to parse result',
            'recommendation': 'Please verify independently'
        }
        
        for line in lines:
            line = line.strip()
            if line.startswith('Label:'):
                parsed['label'] = line.replace('Label:', '').strip()
            elif line.startswith('Confidence:'):
                confidence_str = line.replace('Confidence:', '').strip().replace('%', '')
                try:
                    parsed['confidence'] = int(confidence_str)
                except:
                    parsed['confidence'] = 0
            elif line.startswith('Reason:'):
                parsed['reason'] = line.replace('Reason:', '').strip()
            elif line.startswith('Recommendation:'):
                parsed['recommendation'] = line.replace('Recommendation:', '').strip()
        
        return parsed
        
    except Exception as e:
        print(f"Error parsing prediction result: {e}")
        return {
            'label': 'Error',
            'confidence': 0,
            'reason': 'Failed to parse analysis result',
            'recommendation': 'Please try again'
        }



def get_openai_image_scam_analysis(image_data: Union[str, List[str]]) -> str:
    """
    Calls the OpenAI GPT-5 model with base64 encoded image(s) to perform scam analysis.

    Args:
        image_data (Union[str, List[str]]): The base64 encoded string(s) of the input image(s).
                                            Can be a single string or list of up to 3 strings.

    Returns:
        str: The analysis result from the OpenAI model, or an error message.
    """

    system_role = '''You are an advanced Deception and Media Authenticity Detection Assistant.

You analyze images or screenshots and classify them along three axes:
1. Deception Intent – whether the content is being used to deceive (phishing, scams, impersonation, fake offers, provides misleading information, text mimics authority, spreads false feature updates).
2. Media Authenticity – whether the media itself is authentic, manipulated, or AI-generated.
3. Sender Origin – classify the sender identity type.

⚠️ Output Rules:
- Always respond ONLY in valid JSON.
- Do not add extra fields, explanations, or text outside JSON.
- Use the exact keys and allowed values shown below.
- If the same input is repeated, return the exact same output (deterministic).

JSON Schema:
{
  "label": "Likely Deception | Inconclusive | Likely No Deception",
  "AI_media_authenticity": "Authentic | Manipulated | AI-generated | Unknown",
  "reason": "string (≤ 80 words, concise explanation citing evidence)",
  "recommendation": "string (guidance on verification steps)",
  "confidence": "High | Medium | Low",
  "extracted_websites": ["list of URLs, domains, or website references found in the image (empty array if none)"]
}

Decision Rules:
1. Content Type:
   - Identify type of message/image and assign to `content_type`.

2. Website Extraction & Domain Status:
   - Extract URLs/domains from the image.
   - Mark as `whitelisted` if domain belongs to known brands (e.g., jio.com, icicibank.com).
   - Mark as `suspicious_pattern` if it resembles a known brand but is misspelled or altered (e.g., gmai1.com).
   - Otherwise mark as `unknown`.

3. Sender Origin:
   - 5–6 digit numeric sender = `shortcode`.
   - Alphanumeric business sender (e.g., AM-JIO, HDFCBK) = `masked_business`.
   - 10–12 digit normal phone number = `full_phone_number`.
   - Otherwise = `unknown`.

4. Media Authenticity:
   - Flag `Manipulated` or `AI-generated` if the screenshot/photo shows clear signs of synthetic manipulation.
   - Otherwise mark as `Authentic` or `Unknown`.

5. Bank / Service Alerts:
   - If the message resembles a bank/financial alert (transaction, OTP, card spend, block card instructions):
       • If callback numbers/links cannot be verified → output should not assume Deception.
       • Instead, set label = "Inconclusive" with confidence = "Medium".
       • In "recommendation", instruct the user to verify the callback number or SMS code by cross-checking with the official website/app or the number printed on the card.
       • Only classify as "Likely Deception" if strong scam signals are present (e.g., spoofed domains, misspellings, fake bank name, prize/lottery claims).

6. Deception Intent:
   - If scam cues exist (money/credentials request, urgent threats, impersonation, suspicious links) → "Deception".
   - If text mimics authority, spreads false feature updates, or provides misleading information without links → "Deception".
   - If text is unclear or lacks signals → "Inconclusive".
   - If benign, generic, or safe informational text → "No Deception".

7. Trusted Brand & Domain Checks:
   - If the message references a well-known brand (e.g., Jio, HDFC, Paytm, Amazon):
       • If the domain looks plausible but unverified, do not assume it is safe or scam.
       • Instead, output: "Inconclusive".
       • In "recommendation", advise the user to check the domain on the brand's official website or app store.
   - Only classify as "Likely Deception" if the domain clearly spoofs (e.g., jio-safe-login.xyz) or the content has strong scam patterns.

8. Confidence:
   - High = clear evidence for or against scam.
   - Medium = mixed signals.
   - Low = insufficient evidence.

Authority Detection (new, must run before Deception decision):
1. Run OCR over the image/text and search for explicit authoritative entity names (exact-match candidates), e.g. "Maharashtra Police", "Central Bank of India", "Income Tax Dept", "DoT", "ICICI Bank", "Google", etc. Keep a short internal list of top-known agencies per country; treat exact matches as high-weight signals.
2. Attempt logo/seal detection (if image mode): 
   - If an official seal or emblem is visually detected or a high-confidence badge/logo classifier result is present, mark LOGO_DETECTED = true.
   - If no image classifier available, set LOGO_DETECTED = false and rely on OCR name match.
3. Detect layout/format indicators typical of official notices: header/title like "सूचना", centered heading, formal bullet lists, governmental phrasing, local-language formal register. Count these as FORMAL_LAYOUT = true/false.
4. Compute an AUTHORITY_SCORE:
   - +100 if OCR exact-match to known authoritative name.
   - +60 if LOGO_DETECTED.
   - +20 if FORMAL_LAYOUT true.
   - -100 if the text explicitly requests money/credentials or contains suspicious URLs asking for login/OTP.
   - -40 if domains in text are shortlinks or obviously spoofed.
5. Authority outcomes:
   - If AUTHORITY_SCORE >= 80 → treat as AUTHORITY_INDICATOR = "strong".
   - If 30 <= AUTHORITY_SCORE < 80 → "weak".
   - Otherwise → "none".
6. Authority tie-break rules (override when AUTHORITY_INDICATOR = strong):
   - If AUTHORITY_INDICATOR = "strong" AND no explicit credential/money request → label = "No Deception", confidence = "High". (Reason must include which signals matched.)
   - If AUTHORITY_INDICATOR = "strong" BUT the message explicitly asks for credentials/money or contains suspicious links → label = "Inconclusive", confidence = "Medium" and recommend verifying via official channels (do not mark outright Deception).
   - If AUTHORITY_INDICATOR = "weak" → continue normal Deception logic but favor "Inconclusive" over "Deception" unless high scam signals present.

Special Rule:
- Deepfake or manipulated media with no scam context → `Inconclusive` + `AI-generated/Manipulated`.
- Deepfake/manipulated media used in scam → `Deception` + `AI-generated/Manipulated`.'''

    if not openai_key:
        return "Error: OpenAI API key not found. Please set the AI_API_KEY environment variable."

    try:
        # Convert single image to list for uniform processing
        if isinstance(image_data, str):
            image_list = [image_data]
        else:
            image_list = image_data[:3]  # Limit to 3 images
        
        client = OpenAI(
            api_key=openai_key,
        )

        # Build content array with text and all images
        user_content = [
            {"type": "text", "text": f"Is there some form of deception in {'this image' if len(image_list) == 1 else 'these images'}? Please respond in the same language as used in the message."}
        ]
        
        # Add all images to the content array
        for image_base64 in image_list:
            user_content.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/png;base64,{image_base64}"
                },
            })
        
        messages = [
            {"role": "system", "content": system_role},
            {"role": "user", "content": user_content}
        ]
        
        chat_completion = client.chat.completions.create(
            model="gpt-5",
            messages=messages
        )
        return chat_completion.choices[0].message.content
    except Exception as e:
        return f"An error occurred during OpenAI API call: {e}"


def get_openai_text_scam_analysis(user_text: str) -> str:
    """
    Calls the OpenAI GPT-5 model  to perform scam analysis.

    Args:
        str: The str that the model will analyze.

    Returns:
        str: The analysis result from the OpenAI model, or an error message.
        :param user_text:
    """
    system_role = '''You are an advanced Deception and Media Authenticity Detection Assistant.  

This task involves analyzing forwarded text messages or emails.  
⚠️ Important: Sender information and media authenticity cannot be checked in this mode. Only the message text content should be analyzed.  

Axes of analysis:  
1. Deception Intent – whether the forwarded text is being used to deceive (phishing, scams, impersonation, fake offers).  
2. Website Extraction – extract and normalize domains/URLs from the text.  
3. Domain Status – classify extracted domains if possible (whitelisted, suspicious_pattern, unknown).  
4. Sender Origin – always set to "unknown" in forwarded-text mode.  
5. Media Authenticity – always set to "Unknown" in forwarded-text mode.  

⚠️ Output Rules:  
- Always respond ONLY in valid JSON.  
- Do not add explanations outside JSON.  
- Use the exact keys and allowed values shown below.  
- If the same input is repeated, return the exact same output (deterministic).  

JSON Schema:
{
  "label": "Likely Deception | Inconclusive | Likely No Deception",
  "AI_media_authenticity": "Authentic | Manipulated | AI-generated | Unknown",
  "reason": "string (≤ 80 words, concise explanation citing evidence from text only)",
  "recommendation": "string (guidance on verification steps)",
  "confidence": "High | Medium | Low",
  "extracted_websites": ["list of URLs, domains, or website references (empty array if none)"]"
}

Decision Rules:
1. Content Type:
   - Identify type of message/image and assign to `content_type`.

2. Website Extraction & Domain Status:
   - Extract URLs/domains from the image.
   - Mark as `whitelisted` if domain belongs to known brands (e.g., jio.com, icicibank.com).
   - Mark as `suspicious_pattern` if it resembles a known brand but is misspelled or altered (e.g., gmai1.com).
   - Otherwise mark as `unknown`.

3. Sender Origin:
   - 5–6 digit numeric sender = `shortcode`.
   - Alphanumeric business sender (e.g., AM-JIO, HDFCBK) = `masked_business`.
   - 10–12 digit normal phone number = `full_phone_number`.
   - Otherwise = `unknown`.

4. Media Authenticity:
   - Flag `Manipulated` or `AI-generated` if the screenshot/photo shows clear signs of synthetic manipulation.
   - Otherwise mark as `Authentic` or `Unknown`.

5. Bank / Service Alerts:
   - If the message resembles a bank/financial alert (transaction, OTP, card spend, block card instructions):
       • If callback numbers/links cannot be verified → output should not assume Deception.
       • Instead, set label = "Inconclusive" with confidence = "Medium".
       • In "recommendation", instruct the user to verify the callback number or SMS code by cross-checking with the official website/app or the number printed on the card.
       • Only classify as "Likely Deception" if strong scam signals are present (e.g., spoofed domains, misspellings, fake bank name, prize/lottery claims).

6. Deception Intent:
   - If scam cues exist (money/credentials request, urgent threats, impersonation, suspicious links) → "Deception".
   - If text mimics authority, spreads false feature updates, or provides misleading information without links → "Deception".
   - If text is unclear or lacks signals → "Inconclusive".
   - If benign, generic, or safe informational text → "No Deception".

7. Trusted Brand & Domain Checks:
   - If the message references a well-known brand (e.g., Jio, HDFC, Paytm, Amazon):
       • If the domain looks plausible but unverified, do not assume it is safe or scam.
       • Instead, output: "Inconclusive".
       • In "recommendation", advise the user to check the domain on the brand's official website or app store.
   - Only classify as "Likely Deception" if the domain clearly spoofs (e.g., jio-safe-login.xyz) or the content has strong scam patterns.

8. Confidence:
   - High = clear evidence for or against scam.
   - Medium = mixed signals.
   - Low = insufficient evidence..'''

    if not openai_key:
        return "Error: OpenAI API key not found. Please set the AI_API_KEY environment variable."

    try:
        client = OpenAI(
            api_key=openai_key,
        )

        messages = [
    {"role": "system", "content": system_role},
    {"role": "user", "content": f"Is this a scam? This is the message the user sent '{user_text}'. Please respond in the same language as used in the message." }
]
        chat_completion = client.chat.completions.create(
            model="gpt-5",
            messages=messages
        )
        return chat_completion.choices[0].message.content
    except Exception as e:
        return f"An error occurred during OpenAI API call: {e}"

# def preprocess_image_from_base64(image_base64):
#     """
#     Preprocess image (provided as a base64 string) for better OCR accuracy.

#     Args:
#         image_base64 (str): Base64 encoded string of the input image.

#     Returns:
#         numpy.ndarray: The preprocessed image as a NumPy array (thresholded).
#     Raises:
#         ValueError: If the base64 string cannot be decoded or image loading fails.
#     """
#     try:
#         # Decode base64 string to bytes
#         image_bytes = base64.b64decode(image_base64)
#         # Read image into memory as a NumPy array
#         np_arr = np.frombuffer(image_bytes, np.uint8)
#         img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)

#         if img is None:
#              raise ValueError("Could not decode base64 image.")

#     except Exception as e:
#         raise ValueError(f"Error processing base64 image: {e}")


#     # Convert to grayscale
#     gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

#     # Denoise
#     gray = cv2.fastNlMeansDenoising(gray, None, 30, 7, 21)

#     # Adaptive thresholding (works better for photos/screenshots with varied lighting)
#     thresh = cv2.adaptiveThreshold(
#         gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
#         cv2.THRESH_BINARY, 31, 2
#     )

#     return thresh

# def extract_text_from_base64(image_base64: str) -> str:
#     """
#     Run OCR on a base64 encoded image.

#     Args:
#         image_base64 (str): Base64 encoded string of the input image.

#     Returns:
#         str: The extracted text.
#     Raises:
#         ValueError: If the base64 string cannot be processed.
#     """
#     # Preprocess the image directly from base64
#     processed_img = preprocess_image_from_base64(image_base64)

#     # OCR
#     # pytesseract.image_to_string expects a PIL Image or NumPy array
#     text = pytesseract.image_to_string(processed_img)
#     return text.strip()


def extract_websites(text: str) -> list:
    # Regex for http(s) URLs and bare domains
    url_pattern = re.compile(
        r'(https?://[^\s]+|www\.[^\s]+|[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})'
    )

    matches = url_pattern.findall(text)

    # Optional: Normalize (remove trailing punctuation, lowercase)
    cleaned = [m.rstrip('.,;!?').lower() for m in matches]

    return cleaned

def check_virustotal(url: str) -> dict:
    headers = {
    "accept": "application/json",
    "x-apikey": VT_API_KEY,
    "content-type": "application/x-www-form-urlencoded"
    }

    payload = { "url": url }

    # Step 1: Submit the URL for analysis
    scan_resp = requests.post(
        "https://www.virustotal.com/api/v3/urls",
        headers=headers,
        data=payload
    )


    if scan_resp.status_code != 200:
        return {"error": f"VirusTotal POST error: {scan_resp.status_code}", "details": scan_resp.text}

    # Step 2: Extract the analysis ID
    analysis_id = scan_resp.json()["data"]["id"]

    # Step 3: Retrieve the analysis results
    result_resp = requests.get(
        f"https://www.virustotal.com/api/v3/analyses/{analysis_id}",
        headers=headers
    )

    if result_resp.status_code != 200:
        return {"error": f"VirusTotal GET error: {result_resp.status_code}", "details": result_resp.text}

    data = result_resp.json()
    stats = data.get("data", {}).get("attributes", {}).get("stats", {})
    malicious = stats.get("malicious", 0)
    suspicious = stats.get("suspicious", 0)

    return {"malicious": malicious, "suspicious": suspicious, "raw": stats}

def check_google_safe_browsing(url : str) -> dict:
    payload = {
        "client": {"clientId": "safety-checker", "clientVersion": "1.0"},
        "threatInfo": {
            "threatTypes": ["MALWARE", "SOCIAL_ENGINEERING", "UNWANTED_SOFTWARE", "POTENTIALLY_HARMFUL_APPLICATION"],
            "platformTypes": ["ANY_PLATFORM"],
            "threatEntryTypes": ["URL"],
            "threatEntries": [{"url": url}]
        }
    }
    resp = requests.post(
        f"https://safebrowsing.googleapis.com/v4/threatMatches:find?key={GSB_API_KEY}",
        json=payload
    )
    print(resp)

    if resp.status_code != 200:
        return {"error": "Google Safe Browsing API error"}

    matches = resp.json().get("matches", [])
    return {"threat_found": len(matches) > 0, "details": matches}

def check_whois(url : str) -> dict:
    from datetime import datetime
    try:
        if not url.startswith(("http://", "https://")):
            url = "http://www." + url.lstrip("www.")
        domain = urlparse(url).netloc
        w = whois.whois(domain)
        creation_date = w.creation_date
        if isinstance(creation_date, list):
            creation_date = creation_date[0]

        domain_age_days = None
        if creation_date:
            domain_age_days = (datetime.now() - creation_date).days

        return {
            "registrar": w.registrar,
            "creation_date": creation_date.isoformat() if creation_date else None,
            "domain_age_days": domain_age_days
        }
    except Exception as e:
        return {"error": str(e)}

def check_url_safety(url : str) -> dict:
    """
     Check URL safety using VirusTotal, Google Safe Browsing, and WHOIS data.
    1. VirusTotal: Check if the URL is flagged as malicious or suspicious.
    2. Google Safe Browsing: Check if the URL is flagged as a threat.
    3. WHOIS: Check domain age and registrar information.
    Combine results to give an overall safety verdict.
    """
    results = {}
    vt = check_virustotal(url)
    gsb = check_google_safe_browsing(url)
    whois_info = check_whois(url)

    results["VirusTotal"] = vt
    results["Google Safe Browsing"] = gsb
    results["WHOIS"] = whois_info

    verdict = "SAFE"
    reason = []

    if isinstance(vt, dict) and (vt.get("malicious", 0) > 0 or vt.get("suspicious", 0) > 0):
        verdict = "UNSAFE"
        reason.append("Flagged by VirusTotal")

    if gsb.get("threat_found"):
        verdict = "UNSAFE"
        reason.append("Flagged by Google Safe Browsing")

    if whois_info.get("domain_age_days") is not None and whois_info["domain_age_days"] < 30:
        verdict = "UNSAFE"
        reason.append("Very new domain (possible phishing)")

    if whois_info.get("domain_age_days") is None:
        verdict = "UNKNOWN"
        reason.append("Domain age unknown")

    results["Verdict"] = verdict
    results["Reason"] = reason if reason else ["No known issues found"]
    return results

def check_all_url_safety(urls : list) -> dict:
  output_url_check={}
  if type(urls) != list or len(urls)>0:
    for url in urls:
      output_url_check[url] = check_url_safety(url)
  return output_url_check


def parse_openai_text_output(output_string: str) -> dict:
    """
    Parses the JSON string output from the OpenAI text scam analysis function
    into a Python dictionary.

    Args:
        output_string (str): The JSON string output from the OpenAI model.

    Returns:
        dict: A dictionary containing the parsed analysis results.
              Returns an error dictionary if parsing fails.
    """
    try:
        # Attempt to load the JSON string directly
        logger.info(f"Parsing openai text output: {output_string}")
        parsed_output = json.loads(output_string)
        return parsed_output
    except json.JSONDecodeError:
        # If direct loading fails, try to find and extract the JSON part
        # This is a more robust approach for cases where the API might wrap the JSON in text
        json_match = re.search(r'\{.*}', output_string, re.DOTALL)
        if json_match:
            try:
                json_string = json_match.group(0)
                parsed_output = json.loads(json_string)
                return parsed_output
            except json.JSONDecodeError:
                # Try using ast.literal_eval for Python dict strings with single quotes
                try:
                    import ast
                    json_string = json_match.group(0)
                    parsed_output = ast.literal_eval(json_string)
                    return parsed_output
                except:
                    return {"error": f"Failed to parse extracted JSON string.", "raw_output": output_string}
        else:
            return {"error": f"Failed to find JSON object in output.", "raw_output": output_string}
    except Exception as e:
        return {"error": f"An unexpected error occurred during parsing: {e}", "raw_output": output_string}


tools = [
    Tool(
        name="TextScamAnalysis",
        func=get_openai_text_scam_analysis,
        description="Analyzes input text to determine if it is a scam."
    ),
    Tool(
        name="ImageScamAnalysis",
        func=get_openai_image_scam_analysis,
        description="Analyzes an image for scam characteristics using OpenAI, optionally incorporating external website check results."
    ),
    Tool(
        name="WebsiteExtractor",
        func=extract_websites,
        description="Extracts URLs and potential domain names from a given text string."
    ),
    Tool(
        name="URLSafetyChecker",
        func=check_all_url_safety,
        description="Checks the safety of a set of URL's using multiple services like VirusTotal and Google Safe Browsing, and provides WHOIS information."
    ),

    #  Tool(
    #     name="TextExtractor",
    #     func=extract_text_from_base64,
    #     description="Extracts text from a base64 encoded image."
    # )
]

tool_map = {tool.name: tool.func for tool in tools}
