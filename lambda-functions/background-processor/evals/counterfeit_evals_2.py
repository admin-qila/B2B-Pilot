import os
import json
import base64
from predictor import product_classification, product_counterfeit_testing, upload_file_from_base64
from google import genai

# Optional: for LLM-as-a-judge step
# from openai import OpenAI
# client = OpenAI()  # or Gemini/Claude client depending on setup
GEMINI_API_KEY = os.getenv('AI_API_KEY')
client = genai.Client(api_key=GEMINI_API_KEY)

def read_image_as_base64(image_path):
    """Read image as base64 string."""
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def call_counterfeit_testing(image_path):
    """Upload image and call product classification function."""
    base64_str = read_image_as_base64(image_path)
    uploaded = upload_file_from_base64([base64_str], mime_type="image/jpeg")


    result = product_counterfeit_testing(
        img=uploaded,
        reference_images=[
            "RR_FSE/RR-SuperGreen/SuperexGreenBoxTemplate.jpg",
            "RR_FSE/RR-SuperGreen/SuperexGreenBoxBack0.jpg",
            "RR_FSE/RR-SuperGreen/SuperexGreenBoxFront1.jpg",
        ],
        reference_image_context=["box template", "back of the the box", "front of the box"],
    )
    return result


def llm_judge(field_name, model_output_value, context):
    """Ask an LLM to judge correctness when ground truth is missing."""
    prompt = f"""
    You are an evaluator. The field being evaluated is '{field_name}'.
    Model output: {model_output_value}
    Context: {json.dumps(context, indent=2)}

    Question: Does the model output make logical sense given the rest of the JSON?
    Reply with 'PASS' if it makes sense, 'FAIL' if not.
    """

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0
    )

    return "PASS" in response.choices[0].message.content


def evaluate_image(image_path, ground_truth):
    """Run product classification and evaluate output."""
    result = call_counterfeit_testing(image_path)

    # Load model response JSON
    if isinstance(result, str):
        try:
            result = json.loads(result)
        except json.JSONDecodeError:
            print(f"[ERROR] Invalid JSON from model for {image_path}")
            return None

    image_name = os.path.basename(image_path)
    evaluation = {"image": image_name, "model_output": result, "scores": {}}

    # Evaluate known fields
    for key in ["is_counterfeit"]:
        gt_value = ground_truth.get(image_name, {}).get(key)
        if gt_value is not None:
            model_value = result.get(key)
            evaluation["scores"][key] = (model_value == gt_value)

    # Evaluate unknown fields via LLM judge
    # for key in result:
    #     if key not in ["is_product_match", "request_new_image"]:
    #         model_value = result[key]
    #         pass_judge = llm_judge(key, model_value, result)
    #         evaluation["scores"][key] = pass_judge

    return evaluation


def evaluate_folder(folder_path, ground_truth_dict, output_file="eval_results_counterfeit_test_1.json"):
    """Iterate through all images and evaluate."""
    results = []

    for filename in os.listdir(folder_path):
        if not filename.lower().endswith((".jpg", ".jpeg", ".png")):
            continue

        image_path = os.path.join(folder_path, filename)
        print(f"Evaluating {image_path}...")
        result = evaluate_image(image_path, ground_truth_dict)
        if result:
            results.append(result)

    with open(output_file, "w") as f:
        json.dump(results, f, indent=2)

    print(f"✅ Evaluation complete. Results saved to {output_file}")
    return results

if __name__ == "__main__":
    # Example ground truth dictionary
    with open("../RR_FSE_test/ground_truth_default/rr_supergreen_not_counterfeit.json", "r") as f:
        ground_truth = json.load(f)

    # Evaluate images in the specified folder
    evaluate_folder("../RR_FSE_test/RR-Good", ground_truth)