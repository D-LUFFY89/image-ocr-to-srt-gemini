import google.generativeai as genai
import os
import re
from PIL import Image # ImageTk for displaying logo if desired (ImageTk not used in this version)
import io
import sys
import configparser
import tkinter as tk
from tkinter import ttk, filedialog, scrolledtext, messagebox
import threading
import queue # For thread-safe communication
import concurrent.futures # For thread pool

# --- Modern UI Color Palette (Dark Theme) ---
BG_COLOR = "#2E2E2E"  # Main background
FG_COLOR = "#E0E0E0"  # Main text/foreground
WIDGET_BG_COLOR = "#3C3C3C"  # Background for Entry, Text, Listbox
WIDGET_FG_COLOR = "#E0E0E0"  # Text color for widgets
ACCENT_COLOR = "#009688"  # Teal - for buttons, progress bar, highlights
ACCENT_HOVER_COLOR = "#00796B" # Darker Teal for button hover
BUTTON_TEXT_COLOR = "#FFFFFF"
BORDER_COLOR = "#4A4A4A" # Borders for frames and widgets
DISABLED_FG_COLOR = "#707070"
DISABLED_BG_COLOR = "#353535" # Background for disabled elements
SELECT_BG_COLOR = ACCENT_COLOR # Background for selected items in lists/combos
SELECT_FG_COLOR = BUTTON_TEXT_COLOR # Text color for selected items

# --- Font Configuration ---
FONT_FAMILY = "Segoe UI" # Or "Helvetica", "Arial"
FONT_SIZE_NORMAL = 10
FONT_SIZE_LARGE = 11
FONT_BOLD = (FONT_FAMILY, FONT_SIZE_NORMAL, "bold")
FONT_NORMAL = (FONT_FAMILY, FONT_SIZE_NORMAL)
FONT_LARGE_BOLD = (FONT_FAMILY, FONT_SIZE_LARGE, "bold")


# --- Configuration (Defaults, can be overridden by GUI) ---
DEFAULT_INPUT_FOLDER = 'images'
DEFAULT_OUTPUT_FOLDER = 'subtitle_output'
DEFAULT_OUTPUT_SRT_FILE = 'output.srt'
DEFAULT_GEMINI_MODEL = 'gemini-1.5-flash-latest'
DEFAULT_NUM_THREADS = 4
GEMINI_MODELS = ['gemini-1.5-flash-latest', 'gemini-1.5-pro-latest', 'gemini-pro-vision', 'gemini-1.0-pro']
INI_FILE_PATH = r'GEMINI_API_KEY.ini'

# Regular expression to parse the filename
filename_pattern = re.compile(
    r"^(\d+)_(\d{2})_(\d{2})_(\d{3})__(\d+)_(\d{2})_(\d{2})_(\d{3}).*?\.(jpe?g)$",
    re.IGNORECASE
)

# --- Core Logic (adapted for GUI logging and parallel processing) ---
def format_srt_time(h, m, s, ms):
    return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{int(ms):03d}"

def ocr_image_with_gemini(model, image_path, log_callback):
    try:
        # Small log to indicate which image this particular call is for, useful in parallel context
        # log_callback(f"    > Attempting OCR for: {os.path.basename(image_path)}")
        img = Image.open(image_path)
        prompt = "Extract the text content from this image. Provide only the text."
        response = model.generate_content([prompt, img], stream=False)
        response.resolve() # Ensure completion if any async behavior

        if response.parts:
            text_parts = [part.text for part in response.parts if hasattr(part, 'text')]
            if text_parts:
                extracted_text = "\n".join(text_parts).strip()
                # log_callback(f"    > OCR success for {os.path.basename(image_path)}")
                return extracted_text
            else:
                 log_callback(f"    > Warning: Gemini response for {os.path.basename(image_path)} did not contain a text part.")
                 return ""
        else:
            log_callback(f"    > Warning: Received empty or blocked response from Gemini for {os.path.basename(image_path)}")
            return ""
    except genai.types.generation_types.BlockedPromptException as e:
        log_callback(f"    > Error: Prompt blocked by API for {os.path.basename(image_path)}. Reason: {e}")
        return "[OCR Blocked]"
    except genai.types.generation_types.StopCandidateException as e:
         log_callback(f"    > Error: Generation stopped unexpectedly for {os.path.basename(image_path)}. Reason: {e}")
         return "[OCR Stopped]"
    except FileNotFoundError:
        log_callback(f"    > Error: Image file not found at {image_path}")
        return "[File Not Found]"
    except Exception as e:
        log_callback(f"    > Error during OCR for {os.path.basename(image_path)}: {e}")
        return "[OCR Error]"

def process_images_to_srt_core(api_key, input_folder, output_folder, output_srt_file, gemini_model_name, num_threads, log_callback, progress_callback):
    log_callback(f"Starting processing with {num_threads} worker thread(s)...")
    log_callback(f"Input folder: '{input_folder}'")
    log_callback(f"Output folder: '{output_folder}'")
    log_callback(f"Output SRT file: '{output_srt_file}'")
    log_callback(f"Using Gemini model: '{gemini_model_name}'")

    if not api_key:
        log_callback("Error: Google API Key is not set.")
        return False

    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(gemini_model_name)
    except Exception as e:
        log_callback(f"Error configuring Gemini or creating model: {e}")
        return False

    if not os.path.isdir(input_folder):
        log_callback(f"Error: Input folder '{input_folder}' not found.")
        return False

    os.makedirs(output_folder, exist_ok=True)

    image_files_temp = []
    all_files_in_input = os.listdir(input_folder)
    for filename in all_files_in_input:
        match = filename_pattern.match(filename)
        if match:
            image_files_temp.append(filename)
        else:
            if filename.lower().endswith(('.jpg', '.jpeg')):
                 log_callback(f"  - Skipping file (doesn't match naming pattern): {filename}")

    if not image_files_temp:
        log_callback("No images found matching the required filename pattern.")
        progress_callback(0,0)
        return False

    # Sort files before creating metadata for tasks
    image_files_temp.sort(key=lambda f: filename_pattern.match(f).groups()[:4]) # Sort by start time

    image_tasks_metadata = []
    for filename in image_files_temp:
        match = filename_pattern.match(filename) # Should always match
        groups = match.groups()
        start_h, start_m, start_s, start_ms = groups[0:4]
        end_h, end_m, end_s, end_ms = groups[4:8]
        image_tasks_metadata.append({
            'filename': filename,
            'image_path': os.path.join(input_folder, filename),
            'start_time_str': format_srt_time(start_h, start_m, start_s, start_ms),
            'end_time_str': format_srt_time(end_h, end_m, end_s, end_ms)
        })

    total_images = len(image_tasks_metadata)
    if total_images == 0:
        log_callback("No valid image tasks to process after filtering and sorting.") # Should be caught earlier
        progress_callback(0,0)
        return False
    
    log_callback(f"Found {total_images} images to process.")
    progress_callback(0, total_images) # Initial progress

    srt_entries = []
    srt_counter = 1
    processed_image_count = 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
        # Submit all OCR tasks
        # log_callback("Submitting OCR tasks to thread pool...")
        future_to_ocr = [
            executor.submit(ocr_image_with_gemini, model, task_meta['image_path'], log_callback)
            for task_meta in image_tasks_metadata
        ]

        # Process results as they are completed, but in the original order
        for i, task_meta in enumerate(image_tasks_metadata):
            future = future_to_ocr[i]
            filename = task_meta['filename']
            log_callback(f"Done : {filename} ({i+1}/{total_images})")
            
            try:
                ocr_text = future.result() # This blocks until this specific future completes

                if ocr_text and ocr_text not in ["[OCR Blocked]", "[OCR Stopped]", "[File Not Found]", "[OCR Error]"]:
                    srt_entry = f"{srt_counter}\n{task_meta['start_time_str']} --> {task_meta['end_time_str']}\n{ocr_text}\n"
                    srt_entries.append(srt_entry)
                    srt_counter += 1
                else:
                    log_callback(f"  - Skipping SRT entry for {filename} due to empty/error OCR result: {ocr_text}")
            
            except Exception as e: # Catch exceptions from future.result() itself if ocr_image_with_gemini fails unexpectedly
                log_callback(f"    > Critical Error processing result for {filename}: {e}")
                # This ocr_text will be treated as an error by the logic above if it's one of the bracketed strings

            processed_image_count += 1
            progress_callback(processed_image_count, total_images)

    output_path = os.path.join(output_folder, output_srt_file)
    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write("\n".join(srt_entries))
        log_callback(f"\nSuccessfully created SRT file: {output_path}")
        log_callback(f"Total subtitle entries written: {len(srt_entries)}")
        return True
    except Exception as e:
        log_callback(f"\nError writing SRT file to {output_path}: {e}")
        return False

# --- GUI Application ---
class App:
    def __init__(self, root):
        self.root = root
        self.root.title("Image to SRT Converter (Gemini Vision)")
        self.root.geometry("750x800") # Slightly taller for new field
        self.root.configure(bg=BG_COLOR)

        self.loaded_api_key = self._load_api_key_from_ini()

        self.style = ttk.Style()
        self.style.theme_use('clam')

        self.style.configure('.', background=BG_COLOR, foreground=FG_COLOR, font=FONT_NORMAL)
        self.style.configure('TFrame', background=BG_COLOR)
        self.style.configure('TLabelframe', background=BG_COLOR, foreground=FG_COLOR, bordercolor=BORDER_COLOR, font=FONT_BOLD, relief=tk.SOLID, borderwidth=1)
        self.style.configure('TLabelframe.Label', background=BG_COLOR, foreground=FG_COLOR, font=FONT_BOLD)
        self.style.configure('TLabel', background=BG_COLOR, foreground=FG_COLOR, font=FONT_NORMAL)
        self.style.configure('Status.TLabel', foreground=FG_COLOR, background=BG_COLOR, font=(FONT_FAMILY, FONT_SIZE_NORMAL-1))
        self.style.configure('TButton', background=ACCENT_COLOR, foreground=BUTTON_TEXT_COLOR, font=FONT_BOLD, padding=(10, 5), borderwidth=0, relief=tk.FLAT, focuscolor=ACCENT_COLOR)
        self.style.map('TButton', background=[('active', ACCENT_HOVER_COLOR), ('disabled', DISABLED_BG_COLOR)], foreground=[('disabled', DISABLED_FG_COLOR)], relief=[('pressed', tk.FLAT), ('active', tk.FLAT)], borderwidth=[('pressed', 0), ('active', 0)])
        self.style.configure('TEntry', fieldbackground=WIDGET_BG_COLOR, foreground=WIDGET_FG_COLOR, bordercolor=BORDER_COLOR, insertcolor=FG_COLOR, borderwidth=1, font=FONT_NORMAL, padding=5)
        self.style.map('TEntry', bordercolor=[('focus', ACCENT_COLOR)], fieldbackground=[('disabled', DISABLED_BG_COLOR), ('readonly', WIDGET_BG_COLOR)], foreground=[('disabled', DISABLED_FG_COLOR),('readonly', WIDGET_FG_COLOR)])
        self.style.configure('TCombobox', fieldbackground=WIDGET_BG_COLOR, background=WIDGET_BG_COLOR, foreground=WIDGET_FG_COLOR, arrowcolor=FG_COLOR, bordercolor=BORDER_COLOR, selectbackground=WIDGET_BG_COLOR, selectforeground=WIDGET_FG_COLOR, insertcolor=FG_COLOR, font=FONT_NORMAL, padding=5)
        self.style.map('TCombobox', bordercolor=[('focus', ACCENT_COLOR)], fieldbackground=[('readonly', WIDGET_BG_COLOR), ('disabled', DISABLED_BG_COLOR)], foreground=[('readonly', WIDGET_FG_COLOR), ('disabled', DISABLED_FG_COLOR)], selectbackground=[('readonly', WIDGET_BG_COLOR)], selectforeground=[('readonly', WIDGET_FG_COLOR)], arrowcolor=[('disabled', DISABLED_FG_COLOR)])
        self.root.option_add('*TCombobox*Listbox.background', WIDGET_BG_COLOR)
        self.root.option_add('*TCombobox*Listbox.foreground', WIDGET_FG_COLOR)
        self.root.option_add('*TCombobox*Listbox.selectBackground', SELECT_BG_COLOR)
        self.root.option_add('*TCombobox*Listbox.selectForeground', SELECT_FG_COLOR)
        self.root.option_add('*TCombobox*Listbox.font', FONT_NORMAL)
        self.root.option_add('*TCombobox*Listbox.borderWidth', 0)
        self.root.option_add('*TCombobox*Listbox.relief', tk.FLAT)
        self.style.configure('Horizontal.TProgressbar', background=ACCENT_COLOR, troughcolor=WIDGET_BG_COLOR, bordercolor=BORDER_COLOR, thickness=20)
        
        # Spinbox styling (basic, inherits from TEntry for field)
        self.style.configure('TSpinbox',
                             fieldbackground=WIDGET_BG_COLOR,
                             foreground=WIDGET_FG_COLOR,
                             bordercolor=BORDER_COLOR,
                             insertcolor=FG_COLOR,
                             arrowcolor=FG_COLOR,
                             borderwidth=1,
                             padding=5,
                             font=FONT_NORMAL,
                             relief=tk.FLAT) # Or tk.SOLID if border needed
        self.style.map('TSpinbox',
                       bordercolor=[('focus', ACCENT_COLOR)],
                       fieldbackground=[('disabled', DISABLED_BG_COLOR)],
                       foreground=[('disabled', DISABLED_FG_COLOR)],
                       arrowcolor=[('disabled', DISABLED_FG_COLOR)])


        main_frame = ttk.Frame(root, padding="15 15 15 15", style='TFrame')
        main_frame.pack(fill=tk.BOTH, expand=True)

        config_frame = ttk.LabelFrame(main_frame, text="Configuration", padding="15")
        config_frame.pack(fill=tk.X, pady=10)
        config_frame.columnconfigure(1, weight=1)

        ttk.Label(config_frame, text="Gemini API Key:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=8)
        self.api_key_var = tk.StringVar(value=self.loaded_api_key)
        api_key_entry = ttk.Entry(config_frame, textvariable=self.api_key_var, width=60, show="*")
        api_key_entry.grid(row=0, column=1, columnspan=2, sticky=tk.EW, padx=5, pady=8)

        ttk.Label(config_frame, text="Input Image Folder:").grid(row=1, column=0, sticky=tk.W, padx=5, pady=8)
        self.input_folder_var = tk.StringVar(value=DEFAULT_INPUT_FOLDER)
        ttk.Entry(config_frame, textvariable=self.input_folder_var, width=50).grid(row=1, column=1, sticky=tk.EW, padx=5, pady=8)
        ttk.Button(config_frame, text="Browse...", command=self.browse_input_folder).grid(row=1, column=2, padx=(10,5), pady=8)

        ttk.Label(config_frame, text="Output SRT Folder:").grid(row=2, column=0, sticky=tk.W, padx=5, pady=8)
        self.output_folder_var = tk.StringVar(value=DEFAULT_OUTPUT_FOLDER)
        ttk.Entry(config_frame, textvariable=self.output_folder_var, width=50).grid(row=2, column=1, sticky=tk.EW, padx=5, pady=8)
        ttk.Button(config_frame, text="Browse...", command=self.browse_output_folder).grid(row=2, column=2, padx=(10,5), pady=8)

        ttk.Label(config_frame, text="Output SRT Filename:").grid(row=3, column=0, sticky=tk.W, padx=5, pady=8)
        self.output_filename_var = tk.StringVar(value=DEFAULT_OUTPUT_SRT_FILE)
        ttk.Entry(config_frame, textvariable=self.output_filename_var, width=50).grid(row=3, column=1, sticky=tk.EW, padx=5, pady=8)

        ttk.Label(config_frame, text="Gemini Model:").grid(row=4, column=0, sticky=tk.W, padx=5, pady=8)
        self.gemini_model_var = tk.StringVar(value=DEFAULT_GEMINI_MODEL)
        model_combo = ttk.Combobox(config_frame, textvariable=self.gemini_model_var, values=GEMINI_MODELS, state="readonly", font=FONT_NORMAL)
        model_combo.grid(row=4, column=1, sticky=tk.EW, padx=5, pady=8)

        # Number of Worker Threads
        ttk.Label(config_frame, text="Worker Threads:").grid(row=5, column=0, sticky=tk.W, padx=5, pady=8)
        self.num_threads_var = tk.IntVar(value=DEFAULT_NUM_THREADS)
        self.num_threads_spinbox = ttk.Spinbox(
            config_frame,
            from_=1,
            to=16, # Max 16 threads, a reasonable upper bound for API calls
            textvariable=self.num_threads_var,
            width=7, # Allows for 2 digits comfortably
            font=FONT_NORMAL,
            style='TSpinbox'
        )
        self.num_threads_spinbox.grid(row=5, column=1, sticky=tk.W, padx=5, pady=8) # sticky tk.W


        self.process_button = ttk.Button(main_frame, text="Process Images to SRT", command=self.start_processing_thread, style='TButton')
        self.process_button.pack(pady=(20,10), fill=tk.X, ipady=5)

        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(main_frame, orient="horizontal", length=300, mode="determinate", variable=self.progress_var, style='Horizontal.TProgressbar')
        self.progress_bar.pack(pady=5, fill=tk.X)
        self.progress_label_var = tk.StringVar(value="0/0")
        self.progress_label = ttk.Label(main_frame, textvariable=self.progress_label_var, anchor=tk.CENTER)
        self.progress_label.pack(pady=(2,10))

        log_frame = ttk.LabelFrame(main_frame, text="Logs", padding="10")
        log_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        self.log_text = scrolledtext.ScrolledText(log_frame, wrap=tk.WORD, height=15, bg=WIDGET_BG_COLOR, fg=WIDGET_FG_COLOR, font=FONT_NORMAL, relief=tk.FLAT, borderwidth=0, insertbackground=FG_COLOR, selectbackground=SELECT_BG_COLOR, selectforeground=SELECT_FG_COLOR, state=tk.DISABLED)
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)

        self.status_var = tk.StringVar()
        self.status_bar = ttk.Label(main_frame, textvariable=self.status_var, style='Status.TLabel', relief=tk.FLAT, anchor=tk.W, padding=(5,3))
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X, pady=(5,0))
        self.set_status("Ready.")

        self.log_queue = queue.Queue()
        self.check_log_queue()

    def _load_api_key_from_ini(self):
        try:
            config = configparser.ConfigParser()
            if os.path.exists(INI_FILE_PATH):
                config.read(INI_FILE_PATH)
                return str(config['section']['gemini_api_key'])
            return ""
        except Exception as e:
            print(f"Could not load API key from {INI_FILE_PATH}: {e}")
            return ""

    def log_message(self, message, error=False):
        self.log_queue.put(message)
        if error:
            print(f"ERROR: {message}", file=sys.stderr) # Still print critical errors to console
        # else:
            # print(message) # Optional: print all to console too

    def _update_log_display(self):
        while not self.log_queue.empty():
            try:
                message = self.log_queue.get_nowait()
                if message.startswith("PROGRESS:"):
                    self._process_progress_update(message)
                else:
                    self.log_text.config(state=tk.NORMAL)
                    self.log_text.insert(tk.END, message + "\n")
                    self.log_text.config(state=tk.DISABLED)
                    self.log_text.see(tk.END)
            except queue.Empty:
                break
            except Exception as e:
                print(f"Error updating log display: {e}")

    def check_log_queue(self):
        self._update_log_display()
        self.root.after(100, self.check_log_queue)

    def update_progress(self, current, total):
        self.log_queue.put(f"PROGRESS:{current}:{total}")

    def _process_progress_update(self, progress_data):
        try:
            _, current_str, total_str = progress_data.split(":")
            current = int(current_str)
            total = int(total_str)
            if total > 0:
                self.progress_var.set((current / total) * 100)
                self.progress_label_var.set(f"{current}/{total}")
            else:
                self.progress_var.set(0)
                self.progress_label_var.set("0/0")
        except Exception as e:
            print(f"Error processing progress update: {e}")

    def set_status(self, message):
        self.status_var.set(message)

    def browse_input_folder(self):
        folder_selected = filedialog.askdirectory(initialdir=self.input_folder_var.get(), parent=self.root)
        if folder_selected:
            self.input_folder_var.set(folder_selected)
            self.log_message(f"Input folder set to: {folder_selected}")

    def browse_output_folder(self):
        folder_selected = filedialog.askdirectory(initialdir=self.output_folder_var.get(), parent=self.root)
        if folder_selected:
            self.output_folder_var.set(folder_selected)
            self.log_message(f"Output folder set to: {folder_selected}")

    def start_processing_thread(self):
        api_key = self.api_key_var.get()
        input_folder = self.input_folder_var.get()
        output_folder = self.output_folder_var.get()
        output_filename = self.output_filename_var.get()
        gemini_model = self.gemini_model_var.get()
        num_threads = self.num_threads_var.get()

        if not api_key:
            messagebox.showerror("API Key Missing", "Please enter your Google API Key.", parent=self.root)
            return
        if not input_folder or not os.path.isdir(input_folder):
            messagebox.showerror("Input Folder Invalid", "Please select a valid input image folder.", parent=self.root)
            return
        if not output_folder: # Directory will be created, but base path should be reasonable
             try:
                os.makedirs(output_folder, exist_ok=True)
                self.log_message(f"Output folder '{output_folder}' created or already exists.")
             except OSError as e:
                messagebox.showerror("Output Folder Error", f"Cannot create or access output folder: {output_folder}\n{e}", parent=self.root)
                return
        if not output_filename:
            messagebox.showerror("Output Filename Missing", "Please enter an output SRT filename.", parent=self.root)
            return
        if not output_filename.lower().endswith(".srt"):
            output_filename += ".srt"
            self.output_filename_var.set(output_filename)
            self.log_message(f"Appended .srt to filename: {output_filename}")
        
        if num_threads < 1:
            messagebox.showwarning("Invalid Thread Count", "Number of worker threads must be at least 1. Using 1 thread.", parent=self.root)
            num_threads = 1
            self.num_threads_var.set(1)


        self.process_button.config(state=tk.DISABLED)
        self.set_status("Processing... Please wait.")
        self.log_text.config(state=tk.NORMAL)
        self.log_text.delete(1.0, tk.END)
        self.log_text.config(state=tk.DISABLED)
        self.progress_var.set(0)
        self.progress_label_var.set("0/0")

        thread = threading.Thread(target=self.run_core_processing,
                                  args=(api_key, input_folder, output_folder, output_filename, gemini_model, num_threads),
                                  daemon=True)
        thread.start()

    def run_core_processing(self, api_key, input_f, output_f, output_srt_f, model_n, num_threads):
        final_message_type = "info"
        final_message_title = "Processing Status"
        final_message_details = ""
        success_flag = False

        try:
            success_flag = process_images_to_srt_core(
                api_key, input_f, output_f, output_srt_f, model_n,
                num_threads, self.log_message, self.update_progress
            )
            if success_flag:
                self.set_status("Processing complete!")
                final_message_type = "info"
                final_message_title = "Success"
                final_message_details = f"SRT file created successfully at:\n{os.path.join(output_f, output_srt_f)}"
            else:
                self.set_status("Processing finished with issues or no suitable images.")
                # Check logs for specific error type (crude check)
                log_content = self.log_text.get("1.0", tk.END)
                if "API Key is not set" in log_content or "Error configuring Gemini" in log_content :
                    final_message_type = "error"
                    final_message_title = "API/Configuration Error"
                    final_message_details = "There was an issue with the API key or model configuration. Please check logs."
                elif "Input folder" in log_content and "not found" in log_content:
                    final_message_type = "error"
                    final_message_title = "Input Error"
                    final_message_details = f"Input folder '{input_f}' not found."
                elif "No images found" in log_content or "No valid image tasks" in log_content:
                    final_message_type = "info"
                    final_message_title = "No Images Processed"
                    final_message_details = "No images matching the pattern were found or processed."
                else:
                    final_message_type = "warning"
                    final_message_title = "Processing Incomplete"
                    final_message_details = "Processing finished, but some operations may have failed. Check logs for details."

        except Exception as e:
            self.log_message(f"An unexpected error occurred in run_core_processing: {e}", error=True)
            self.set_status(f"Critical Error: {e}")
            final_message_type = "error"
            final_message_title = "Critical Processing Error"
            final_message_details = f"An unexpected critical error occurred: {e}"
        finally:
            def update_gui_on_finish():
                self.process_button.config(state=tk.NORMAL)
                if final_message_details:
                    if final_message_type == "info":
                        messagebox.showinfo(final_message_title, final_message_details, parent=self.root)
                    elif final_message_type == "warning":
                        messagebox.showwarning(final_message_title, final_message_details, parent=self.root)
                    elif final_message_type == "error":
                        messagebox.showerror(final_message_title, final_message_details, parent=self.root)

                # Update progress label based on outcome
                current_progress_val, total_progress_val = self.progress_label_var.get().split('/')
                is_complete_progress = current_progress_val == total_progress_val and total_progress_val != "0"

                if not success_flag and not is_complete_progress:
                    self.progress_label_var.set("Finished with issues")
                elif not success_flag and is_complete_progress : # All items "processed" but overall process failed (e.g. write error)
                     self.progress_label_var.set(f"{current_progress_val}/{total_progress_val} (Failed)")
                # If successful and complete, it should already show X/X

            self.root.after(0, update_gui_on_finish)


# --- Main Execution ---
if __name__ == "__main__":
    root = tk.Tk()
    app = App(root)
    if app.loaded_api_key:
        app.log_message(f"API Key loaded from {INI_FILE_PATH}.")
    elif os.path.exists(INI_FILE_PATH):
         app.log_message(f"API Key file {INI_FILE_PATH} found, but could not load key. Check file format.", error=True)
    else:
        app.log_message(f"API Key file {INI_FILE_PATH} not found. Please enter API key manually.", error=True)

    root.mainloop()
