import base64
import io
# import cv2
# import numpy as np
# import torch
# import pytesseract
import json
import logging
import os
from typing import Any, Dict, Union
from typing import List
import datetime
import csv
from google import genai
from google.genai import types
import ast


# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Hyperparams
IMG_SIZE = 299
# DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
GEMINI_API_KEY = os.getenv('AI_API_KEY')
MODEL_NAME = "gemini-2.5-pro"

client = genai.Client(api_key=GEMINI_API_KEY)
image_cache = {}

def get_latest_gemini_files(allowed_names_file='cache_static_list.csv'):
    # load allowed names
    if allowed_names_file.endswith(".csv"):
        with open(allowed_names_file, newline='') as f:
            reader = csv.DictReader(f)
            allowed = {row["display_name"].strip() for row in reader if row["display_name"].strip()}
    else:
        with open(allowed_names_file, "r") as f:
            allowed = {line.strip() for line in f if line.strip()}

    files = client.files.list()
    latest = {}
    one_week_ago = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(weeks=1)

    for f in files:
        if f.display_name not in allowed:
            continue  # skip anything not in your static list

        create_time = getattr(f, "create_time", None)
        if not create_time:
            create_time = one_week_ago
        elif isinstance(create_time, str):
            create_time = datetime.datetime.fromisoformat(create_time.replace("Z", "+00:00"))

        if f.display_name not in latest or create_time > latest[f.display_name]["time"]:
            latest[f.display_name] = {"name": f.name, "time": create_time}

    return {k: v["name"] for k, v in latest.items()}


def upload_file_from_base64(base64_image_string_list, mime_type='image/jpeg'):
    """
    Decodes a base64 string and uploads it to the Gemini API for processing.
    """
    user_files = []
    try:
        for base64_image_string in base64_image_string_list:
            # Decode the base64 string into raw binary data
            image_bytes = base64.b64decode(base64_image_string)

            # Wrap the binary data in a file-like object
            image_file_object = io.BytesIO(image_bytes)

            uploaded_file = client.files.upload(
                file=image_file_object,
                config={'display_name': "api_uploaded_image", "mimeType": mime_type}
            )

            logger.info(f"Successfully uploaded file: {uploaded_file.name}")
            user_files.append(uploaded_file)

    except Exception as e:
        logger.error(f"An error occurred while decoding image in upload_file_from_base64(): {e}")
    return user_files

def delete_file(user_files):
    for f in user_files:
        try:
            client.files.delete(name=f.name)
        except Exception:
            logger.warning("Failed cleanup for %s", f.name)
    return


def load_prompts(name: str, prompt_file="prompts.json"):
    if not os.path.exists(prompt_file):
        raise FileNotFoundError(f"Prompt file not found: {prompt_file}")
    with open(prompt_file, "r") as f:
        prompts = json.load(f)
    if name not in prompts:
        raise KeyError(f"Prompt '{name}' not found in {prompt_file}")
    prompt_data = prompts[name]
    return prompt_data["content"]


def compare_user_images(
    user_files: List,
    user_prompt: str,
    system_prompt_ref: str,
    response_structure: dict,
    reference_images: List[str],
    reference_image_context: List[str],
    model_name: str = "gemini-2.5-pro"
):
    """
    Compare fixed reference images (cached remotely on Gemini) against user-uploaded images.
    Uses latest_files dict (display_name → file.name).
    Uploads missing files, and re-uploads invalid references automatically.
    """
    global image_cache
    ref_files = []
    for img_path, context in zip(reference_images, reference_image_context):

        # CASE 1: already in dict → validate
        if img_path in image_cache:
            file_name = image_cache[img_path]
            try:
                existing = client.files.get(name=file_name)
                logger.info(f"✅ Using cached Gemini file: {img_path} → {file_name}")
                ref_files.append([context, existing])
                continue
            except Exception:
                logger.info(f"⚠️ Cached reference invalid for {img_path}. Re-uploading...")

        # CASE 2: not in dict or invalid → upload
        logger.info(f"⬆️ Uploading {img_path} to Gemini...")
        uploaded = client.files.upload(
            file=img_path,
            config={"display_name": img_path, "mimeType": "image/jpeg"})
        image_cache[img_path] = uploaded.name
        logger.info(f"✅ Uploaded {img_path} → {uploaded.name}")
        ref_files.append([context, uploaded])


    # 2. Build input prompt parts
    parts = [
        "Reference images:",
        *ref_files,
        "User images:",
        *user_files,
        user_prompt
    ]

    # 3. Generate content with deterministic config
    try:
        response = client.models.generate_content(
            model = model_name,
            contents=parts,
            config=types.GenerateContentConfig(
                temperature=0.0,
                top_k=1,
                top_p=1.0,
                system_instruction = system_prompt_ref,
                response_mime_type="application/json",
                response_schema=response_structure,
                thinking_config=types.ThinkingConfig(
                    thinking_budget=128
                )
            )
        )
        logger.info("Model generation successful")
        return response
    except Exception as e:
        logger.error("Model generation failed: %s", e)
        for f in user_files:
            try:
                client.files.delete(name=f.name)
            except Exception:
                logger.warning("Failed cleanup for %s", f.name)
        raise


def product_classification(img,
                           reference_images = ("RR_FSE/RR-SuperGreen/SuperexGreenBoxTemplate.jpg", "RR_FSE/RR-Q1/Q1BoxTemplate.jpg"),
                           reference_image_context = ('RR Kabel SUPEREX GREEN', 'RR Kabel Q1', "Other", "None"),
                           system_prompt_name ="RR_product_classification_system_prompt_v3",
                           user_prompt = "The Reference images shows 2 products. Is the user image showing the same brand, product line and packaging design of either 1? The user is allowed to upload box or reciepts of either of the product",
                           ):


    response_structure = {
        "type": "OBJECT",
        "properties":    {
              "is_product_match": {"type": "BOOLEAN", "nullable": True},
              "multiple_products": {"type": "BOOLEAN", "nullable": False},
              "partial_or_occluded": {"type": "BOOLEAN", "nullable": False},
              "blurry_or_unclear": {"type": "BOOLEAN", "nullable": False},
              "product":{"type": "STRING", "enum": ["RR Kabel SUPEREX GREEN", "RR Kabel Q1", "None"]},
              "reason": {"type": "STRING", "nullable": False},
              "is_receipt_image" : {"type": "BOOLEAN", "nullable": False},
              "barcode_present": {"type": "BOOLEAN", "nullable": False},
            "request_new_image":{"type": "BOOLEAN", "nullable": False},
            "request_new_image_reason":{"type": "STRING", "nullable": True},
            }
    }


    #system prompt
    system_prompt_ref = load_prompts(name= system_prompt_name)
    result = compare_user_images(
                user_files=[img],
                user_prompt=user_prompt,
                system_prompt_ref=system_prompt_ref,
                response_structure=response_structure,
                reference_images=reference_images,
                reference_image_context=reference_image_context,
                model_name=MODEL_NAME
            )
    return result.text


def product_counterfeit_testing(img,
                                reference_images,
                                reference_image_context,
                                system_prompt_name ="RR_counterfeit_detection_system_prompt_v4",
                                user_prompt = "Check if the User images are of counterfeit products.",
                                model_name ="gemini-2.5-pro"
                                ):
    response_structure = {
        "type": "OBJECT",
        "properties":    {
              "is_counterfeit": {"type": "STRING", "enum": ["true", "false", "unknown"]},
              "confidence":{"type": "STRING", "enum": ["low", "medium", "high"]},
              "summary": {"type": "STRING", "nullable": False},
              "evidence": {"type": "ARRAY",
                           "items": {
                                "type": "OBJECT",
                                "properties": {
                                        "attribute": {"type": "STRING", "enum": ["logo","color","typography","barcode","seal","finish","dimensions","text","other"]},
                                        "reference_value": {"type": "STRING", "nullable": False},
                                        "image_value": {"type": "STRING", "nullable": False},
                                        "discrepancy": {"type": "STRING", "enum": ["none", "minor", "major", "not_evaluable"]},
                                        "notes":{"type": "STRING", "nullable": True},
                                            }
                                    }
                            },
              "detected_material_finish" : {"type": "STRING", "enum": ["matte","gloss","metallic","plastic","paper","unknown"]},
              "request_new_image": {"type": "BOOLEAN", "nullable": False},
              "request_new_image_reason":  {"type": "STRING", "nullable": False},
              "recommended_action": {"type": "STRING", "nullable": False}
                    }
                }
    #system prompt
    system_prompt_ref = load_prompts(name= system_prompt_name)
    result = compare_user_images(
                user_files=img,
                user_prompt=user_prompt,
                system_prompt_ref=system_prompt_ref,
                response_structure=response_structure,
                reference_images=reference_images,
                reference_image_context=reference_image_context,
                model_name=model_name
            )
    return result.text


def extract_user_images_info(
    user_files: List,
    user_prompt: str,
    response_structure:dict,
    model_name: str = "gemini-2.5-pro"
):
    parts = ["User images:",
        *user_files,
        user_prompt]
    try:
        response = client.models.generate_content(
            model = model_name,
            contents=parts,
            config=types.GenerateContentConfig(
                temperature=0.1,
                top_k=10,
                top_p=0.7,
                max_output_tokens=500,
                stop_sequences=['0' * 100],
                response_mime_type="application/json",
                response_schema=response_structure,
                thinking_config=types.ThinkingConfig(
                    thinking_budget=128)
            )
        )
        logger.info("Model generation successful")
        return response
    except Exception as e:
        logger.error("Model generation failed: %s", e)


def product_barcode_extraction(img: List):
    prompt = """You are a fast and precise barcode and QR code detector.

Task:
- Detect all barcodes and QR codes in the provided image.
- For each detected code, return:
  - "type": one of ["QR", "EAN-13", "UPC-A", "Code128", "Code39", "DataMatrix", "PDF417", "Unknown"]
  - "data": the decoded text. ONLY the first 100 characters.
- If the code is visible but unreadable, return `"data": "present but unreadable"`.
- If the decoded data is suspiciously long (over 100 characters of repeating digits or gibberish), mark it `"present but unreadable"`.
- Never guess or fabricate text.
- Return a compact, valid JSON list **only** — no prose, explanations, or comments.
- If no codes detected, return `[]`.

Example output:
[
  {"type": "QR", "data": "https://example.com"},
  {"type": "Code128", "data": "present but unreadable"}
]
"""
    return_structure = {"type": "ARRAY",
                           "items": {
                                "type": "OBJECT",
                                "properties": {
                                        "type": {"type": "STRING", "nullable": True},
                                        "data":{"type": "STRING", "nullable": True}
                                            }
                                    }
                            }
    try:
        result = extract_user_images_info(
                user_files=img,
                user_prompt=prompt,
                response_structure=return_structure
        )
        logger.info("Barcode extraction successful")
        if not result.text:
            return [{'type': 'Not Extractable', 'data': 'Not Extractable'}]
        return result.text
    except Exception as e:
        logger.error("Model generation failed in product_barcode_extraction: %s", e)
        return [{'type': 'Not Extractable', 'data': 'Not Extractable'}]


def product_receipt_extraction(img: list):
    prompt = f"Extract meta data that is readable from the receipt which include name of the shop name(name of store if available) and location(city of store if available). Keep all reasoning factual and visual, do not include internal thoughts."
    return_structure = {
        "type": "OBJECT",
        "properties": {
            "shop_name": {"type": "STRING", "nullable": True},
            "location": {"type": "STRING", "nullable": True}
        }
    }
    try:
        result = extract_user_images_info(user_files=img, user_prompt=prompt, response_structure=return_structure)
        logger.info("Receipt extraction successful")
        return result.text
    except Exception as e:
        logger.error("Model generation failed in product_barcode_extraction: %s", e)
        return {'shop_name': None, 'location': None}

def is_valid_image_set(product: List[str], reciept_images: List[str]):
    # Rules: 1. Max 1 product 2. Max 1 receipt image
    if len(reciept_images)<=1:
        if len(product)==1:
            return True
    return False


def predict_response(input_data: Union[str, bytes, List[str]]) -> Dict[str, Any]:
    """
    Main entry point for counterfeit detection.
    - Image input (single or list): Analyze image(s) for counterfeit indicators.
    """
    result = {"input_type": None, "steps": [], "final_output": None}
    
    try:
        # Check if it's a list of images
        if isinstance(input_data, list):
            return _process_image_input(input_data, result)
        elif isinstance(input_data, str):
            return _process_image_input(input_data, result)
        else:
            return _process_unsupported_input(result)
    except Exception as e:
        logger.exception(f"Error during predict_response: {e}")

def safe_json_parse(raw: str, context: str = "") -> dict:
    """Safely parse JSON or Python dict string with fallback."""
    try:
        # Clean up if model returns Markdown-style code blocks
        cleaned = raw.strip().strip("```json").strip("```").strip()
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        logger.warning(f"[safe_json_parse] JSONDecodeError in {context}: {e}")
        logger.info(f"Raw content from {context}: {raw}")
        try:
            # Try Python literal parsing as fallback
            return ast.literal_eval(cleaned)
        except Exception as inner_e:
            logger.error(f"[safe_json_parse] Failed literal_eval in {context}: {inner_e}")
            return {}

def _process_image_input(image_data: Union[str, List[str]], result: Dict[str, Any]) -> Dict[str, Any]:
    """Process image input (single or multiple) for scam detection."""
    if isinstance(image_data, str):
        image_data = [image_data]

    image_data = image_data[:3]  # limit to 3 images

    return _process_with_analysis(
        input_data=image_data,
        input_type="image",
        result=result
    )


def _process_with_analysis(
    input_data: Union[str, List[str]],
    input_type: str,
    result: Dict[str, Any]
) -> Dict[str, Any]:
    logger.info(f"Processing {input_type} input")
    global image_cache
    global client
    client = genai.Client(api_key=GEMINI_API_KEY)
    result["input_type"] = input_type

    if isinstance(input_data, list):
        logger.info(f"Processing {len(input_data)} images")

    product = []
    product_images = []
    barcode_images = []
    receipt_images = []
    rejected_images = []
    rejected_images_reason = ""
    return_dict = {
        "sku": None,
        "analysis": None,
        "confidence": None,
        "summary": None,
        "barcodes": [],
        "receipt": {"shop_name": None, "location": None},
    }

    image_cache = get_latest_gemini_files()
    user_files = upload_file_from_base64(input_data)

    # ---- MAIN LOOP ----
    for img in user_files:
        raw_result = product_classification(img)
        parsed = safe_json_parse(raw_result, context="product_classification")
        result = parsed
        logger.info(f"product_classification: {result}")

        if result["is_receipt_image"]:
            if result["partial_or_occluded"] or result["blurry_or_unclear"]:
                rejected_images.append(img.name)
                rejected_images_reason += f"{len(rejected_images)}. {result['reason']}"
                if result["request_new_image"]:
                    rejected_images_reason += result["request_new_image_reason"]
            else:
                receipt_images.append(img)
        elif result["multiple_products"]:
            rejected_images.append(img.name)
            rejected_images_reason += f"{len(rejected_images)}. {result['reason']}"
            continue
        elif result["is_product_match"]:
            if result["partial_or_occluded"] or result["blurry_or_unclear"]:
                rejected_images.append(img.name)
                rejected_images_reason += f"{len(rejected_images)}. {result['reason']}"
                if result["request_new_image"]:
                    rejected_images_reason += result["request_new_image_reason"]
            else:
                product.append(result["product"])
                product_images.append(img)
                if result["barcode_present"]:
                    barcode_images.append(img)
            continue
        else:
            rejected_images.append(img.name)
            rejected_images_reason += f"{len(rejected_images)}. {result['reason']}"

    # ---- REJECTED IMAGE SUMMARY ----
    rejected_images_text = (
        f" *Rejected Images* : {len(rejected_images)} of {len(user_files)}.\n*Reason* : {rejected_images_reason}"
        if len(rejected_images) > 0
        else ""
    )

    if not is_valid_image_set(product, receipt_images):
        return_dict["summary"] = (
            "Cannot Process, we can only process 1 product box image of SUPEREX GREEN or Q1 "
            "and maximum 1 receipt image. \n" + rejected_images_text
        )
        return return_dict

    # ---- PRODUCT COUNTERFEIT TEST ----
    if product[0] == "RR Kabel SUPEREX GREEN":
        reference_images = [
            "RR_FSE/RR-SuperGreen/SuperexGreenBoxTemplate.jpg",
            "RR_FSE/RR-SuperGreen/SuperexGreenBoxBack0.jpg",
            "RR_FSE/RR-SuperGreen/SuperexGreenBoxFront1.jpg",
        ]
        reference_image_context = ["box template", "back of the the box", "front of the box"]

        raw_result = product_counterfeit_testing(product_images, reference_images, reference_image_context)
        parsed = safe_json_parse(raw_result, context="product_counterfeit_testing")
        logger.info(f"product_counterfeit_testing: {parsed}")

        return_dict["sku"] = "RR Kabel SUPEREX GREEN"
        return_dict["analysis"] = parsed["is_counterfeit"]
        return_dict["confidence"] = parsed["confidence"]
        return_dict["summary"] = parsed["summary"] + rejected_images_text

    elif product[0] == "RR Kabel Q1":
        reference_images = [
            "RR_FSE/RR-Q1/Q1BoxTemplate.jpg",
            "RR_FSE/RR-Q1/Q1BoxBack0.jpg",
            "RR_FSE/RR-Q1/Q1BoxFront0.jpg",
        ]
        reference_image_context = ["box template", "back of the the box", "front of the box"]

        raw_result = product_counterfeit_testing(product_images, reference_images, reference_image_context)
        parsed = safe_json_parse(raw_result, context="product_counterfeit_testing")
        return_dict["sku"] = "RR Kabel Q1"
        return_dict["analysis"] = parsed["is_counterfeit"]
        return_dict["confidence"] = parsed["confidence"]
        return_dict["summary"] = parsed["summary"] + rejected_images_text

    # ---- BARCODE EXTRACTION ----
    if len(barcode_images) > 0:
        raw_barcodes = product_barcode_extraction(barcode_images)
        barcodes = safe_json_parse(raw_barcodes, context="product_barcode_extraction")
        return_dict["barcodes"] = barcodes

    # ---- RECEIPT EXTRACTION ----
    if len(receipt_images) > 0:
        raw_receipt = product_receipt_extraction(receipt_images)
        receipt = safe_json_parse(raw_receipt, context="product_receipt_extraction")
        logger.info(f"Receipt: {receipt}")
        return_dict["receipt"] = receipt

    # ---- CLEANUP ----
    delete_file(user_files)
    logger.info("Processing complete")
    return return_dict



def _process_unsupported_input(result: Dict[str, Any]) -> Dict[str, Any]:
    """Handle unsupported input types."""
    logger.warning("Unsupported input type provided")
    result["input_type"] = "unsupported"
    
    unsupported_result = {"sku": None,
                   "analysis": None,
                   "confidence": None,
                   "summary": "Unable to process input type, please provide text or base64 image. We will be adding support for more input types soon.",
                   "barcodes": [],
                   "receipt": {"shop_name": None, "location": None}}

    
    return  unsupported_result
