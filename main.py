import google.generativeai as genai
import os
import re
from PIL import Image
import io
import sys
import configparser

# GOOGLE_API_KEY
config = configparser.ConfigParser()
config.read(r'GEMINI_API_KEY.ini')
gemini_api_key = str(config['section']['gemini_api_key'])

# --- Configuration ---
# !!! IMPORTANT: Set your API key securely via environment variable !!!
API_KEY = (gemini_api_key)
if not API_KEY:
    print("Error: GOOGLE_API_KEY environment variable not set.")
    print("Please set the environment variable before running the script.")
    sys.exit(1) # Exit if API key is not found

INPUT_FOLDER = 'images'  # Folder containing your .jpeg images
OUTPUT_FOLDER = 'subtitle_output'        # Folder where the .srt file will be saved
OUTPUT_SRT_FILE = 'output.srt'
GEMINI_MODEL = 'gemini-1.5-flash-latest' # Or use 'gemini-1.5-flash', 'gemini-1.5-pro' etc.
# --- End Configuration ---

# Configure the Gemini client
genai.configure(api_key=API_KEY)

# Create the vision model instance
model = genai.GenerativeModel(GEMINI_MODEL)

# Regular expression to parse the filename
# Matches H_MM_SS_MS__H_MM_SS_MS_anything.jpeg (or .jpg)
filename_pattern = re.compile(
    r"^(\d+)_(\d{2})_(\d{2})_(\d{3})__(\d+)_(\d{2})_(\d{2})_(\d{3}).*?\.(jpe?g)$",
    re.IGNORECASE # Make .jpeg/.jpg matching case-insensitive
)

def format_srt_time(h, m, s, ms):
    """Converts H, M, S, MS parts to HH:MM:SS,ms SRT format."""
    return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{int(ms):03d}"

def ocr_image_with_gemini(image_path):
    """Performs OCR on an image using Gemini Vision."""
    try:
        img = Image.open(image_path)

        # Gemini can often handle PIL Image objects directly or bytes
        # Let's try sending the PIL Image object
        # Alternatively, you could save to bytes:
        # img_byte_arr = io.BytesIO()
        # img.save(img_byte_arr, format=img.format or 'JPEG') # Use original format or default to JPEG
        # image_bytes = img_byte_arr.getvalue()
        # image_part = {"mime_type": f"image/{img.format.lower() or 'jpeg'}", "data": image_bytes}

        # Using PIL Image directly (often simpler with the library)
        prompt = "Extract the text content from this image. Provide only the text."
        response = model.generate_content([prompt, img], stream=False) # Use stream=False for simpler handling
        response.resolve() # Ensure the response is fully generated if using async/streaming internally

        if response.parts:
             # Filter parts to get text, handle potential lack of text part
            text_parts = [part.text for part in response.parts if hasattr(part, 'text')]
            if text_parts:
                extracted_text = "\n".join(text_parts).strip()
                return extracted_text
            else:
                 print("    > Warning: Gemini response did not contain a text part.")
                 return "" # Return empty string if no text found
        else:
            # Handle cases where the response might be blocked or empty
            print(f"    > Warning: Received empty or blocked response from Gemini for {os.path.basename(image_path)}")
            # You might want to inspect response.prompt_feedback here if needed
            return "" # Return empty string

    except genai.types.generation_types.BlockedPromptException as e:
        print(f"    > Error: Prompt blocked by API for {os.path.basename(image_path)}. Reason: {e}")
        return "[OCR Blocked]"
    except genai.types.generation_types.StopCandidateException as e:
         print(f"    > Error: Generation stopped unexpectedly for {os.path.basename(image_path)}. Reason: {e}")
         return "[OCR Stopped]"
    except FileNotFoundError:
        print(f"    > Error: Image file not found at {image_path}")
        return "[File Not Found]"
    except Exception as e:
        print(f"    > Error during OCR for {e}")
        # Consider more specific error handling for API errors (rate limits, auth, etc.)
        return "[OCR Error]"


def process_images_to_srt():
    """Finds images, parses filenames, performs OCR, and generates SRT."""
    print(f"Starting processing...")
    print(f"Input folder: '{INPUT_FOLDER}'")
    print(f"Output folder: '{OUTPUT_FOLDER}'")

    if not os.path.isdir(INPUT_FOLDER):
        print(f"Error: Input folder '{INPUT_FOLDER}' not found.")
        return

    os.makedirs(OUTPUT_FOLDER, exist_ok=True) # Create output folder if it doesn't exist

    srt_entries = []
    image_files = []

    # List and filter image files first
    for filename in os.listdir(INPUT_FOLDER):
        match = filename_pattern.match(filename)
        if match:
            image_files.append(filename)
        else:
            if filename.lower().endswith(('.jpg', '.jpeg')):
                 print(f"  - Skipping file (doesn't match naming pattern): {filename}")


    # Sort files based on the start time to ensure correct order
    image_files.sort(key=lambda f: filename_pattern.match(f).groups()[:4]) # Sort by H, M, S, MS of start time

    srt_counter = 1
    for filename in image_files:
        match = filename_pattern.match(filename) # Match again after sorting
        if match: # Should always match here, but double-check
            print(f"{filename} Done.")
            groups = match.groups()
            start_h, start_m, start_s, start_ms = groups[0:4]
            end_h, end_m, end_s, end_ms = groups[4:8]
            # file_ext = groups[8] # We don't really need the extension here

            start_time_str = format_srt_time(start_h, start_m, start_s, start_ms)
            end_time_str = format_srt_time(end_h, end_m, end_s, end_ms)

            image_path = os.path.join(INPUT_FOLDER, filename)
            ocr_text = ocr_image_with_gemini(image_path)

            if ocr_text: # Only add entry if OCR returned something meaningful
                srt_entry = f"{srt_counter}\n{start_time_str} --> {end_time_str}\n{ocr_text}\n"
                srt_entries.append(srt_entry)
                srt_counter += 1
            else:
                print(f"  - Skipping SRT entry for {filename} due to empty/error OCR result.")


    # Write the SRT file
    output_path = os.path.join(OUTPUT_FOLDER, OUTPUT_SRT_FILE)
    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write("\n".join(srt_entries)) # Join entries with a single newline (as each entry already ends with one)
        print(f"\nSuccessfully created SRT file: {output_path}")
        print(f"Total subtitle entries written: {len(srt_entries)}")
    except Exception as e:
        print(f"\nError writing SRT file to {output_path}: {e}")

# --- Main Execution ---
if __name__ == "__main__":
    process_images_to_srt()
