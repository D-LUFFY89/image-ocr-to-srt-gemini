# How to use

1. Install [python](https://www.python.org/): Ensure you have Python 3.9+ installed.

2. Install Libraries

    *   pip install google-generativeai Pillow python-dotenv configparser

3. Get GEMINI_API_KEY from Google AI Studio [https://aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey)

4. Export images using [VideoSubFinder](https://sourceforge.net/projects/videosubfinder/) and put them in images folder

5. Run `main.py` Use python code or Download full version [image-ocr-to-srt-gemini](https://github.com/MrGamesKingPro/image-ocr-to-srt-gemini/releases/tag/image-ocr-to-srt-gemini)

![ocr](https://github.com/user-attachments/assets/ff68aa80-94c8-4e34-aecf-36b57b367092)


*   **Input Image Folder**
    *   Click "Browse..." to select the folder containing your timestamped images.
    *   Default: `images` (a folder named 'images' in the same directory as the script).

*   **Output SRT Folder**
    *   Click "Browse..." to select the folder where the generated SRT file will be saved.
    *   The application will create this folder if it doesn't exist.
    *   Default: `subtitle_output` (a folder named 'subtitle_output' in the same directory as the script).

*   **Output SRT Filename**
    *   The name for the generated SRT file (e.g., `my_video_subtitles.srt`).
    *   If you don't include `.srt` at the end, it will be automatically appended.
    *   Default: `output.srt`.

*   **Gemini Model**
    *   A dropdown list to select the Gemini model for OCR.
    *   Available models include:
        *   `gemini-1.5-flash-latest` (Default, generally faster and cost-effective for OCR)
        *   `gemini-1.5-pro-latest`
        *   `gemini-pro-vision` (Older vision-specific model)
        *   `gemini-1.0-pro` (Primarily text, might not be suitable)
    *   It's recommended to use `gemini-1.5-flash-latest` or `gemini-1.5-pro-latest` for best results with vision tasks.

*   **Worker Threads**
    *   The number of concurrent threads to use for processing images. More threads can speed up processing, especially for many images, but also increase API call frequency.
    *   Adjust based on your internet connection and API rate limits.
    *   Range: 1 to 16.
    *   Default: `4`.

## Processing
*   **Process Images to SRT Button:** Starts the image processing and SRT generation.
*   **Progress Bar & Label:** Shows the current progress (e.g., `10/50 images processed`).
*   **Logs:** A text area displays detailed logs of the operations, including image processing status, OCR results, and any errors encountered.

## Troubleshooting & Notes

*   **API Key Errors:** If you encounter errors related to the API key, ensure it's correct, active, and that your Google Cloud project has billing enabled if required for the Gemini API usage tier.
*   **Filename Pattern:** The most common issue will be images not conforming to the strict filename pattern. Double-check your filenames. The log will indicate skipped files.
*   **Internet Connection:** A stable internet connection is required for API calls to Google Gemini.
*   **Blocked Prompts/Content:** The Gemini API might block prompts or return empty responses if the image content violates its safety policies. The log will show messages like `[OCR Blocked]`.
*   **Rate Limits:** If processing a very large number of images quickly, you might encounter API rate limits. Reducing the number of worker threads can help.
*   **Model Selection:** Some models might be better suited for OCR than others. `gemini-1.5-flash-latest` is a good starting point.

  

