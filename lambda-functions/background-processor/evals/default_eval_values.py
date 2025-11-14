import os
import json

def create_default_ground_truth(folder_path):
    """Create a ground truth dict with default values for all image files in the folder."""
    ground_truth = {}
    for filename in os.listdir(folder_path):
        if filename.lower().endswith((".jpg", ".jpeg", ".png")):
            ground_truth[filename] = {
                "is_product_match": False,
                "request_new_image": True,
                "multiple_products": True,
                "partial_or_occluded": True,
                "blurry_or_unclear": True,
            }

    # Save to a JSON file for reference
    with open("RR_FSE_test/ground_truth_default/rr_supergreen_bad.json", "w") as f:
        json.dump(ground_truth, f, indent=2)

    print(f"✅ Ground truth file created for {len(ground_truth)} images.")
    return ground_truth


# Example usage:
ground_truth = create_default_ground_truth("RR_FSE_test/RR-Bad")