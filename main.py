import os
import io
import uuid
import base64

import fitz  # PyMuPDF
import google.generativeai as genai
import google.auth.transport.requests
import urllib.parse
from fastapi import FastAPI, File, UploadFile, HTTPException, Depends, BackgroundTasks
from fastapi.responses import HTMLResponse, FileResponse
from PIL import Image
from dotenv import load_dotenv
from xhtml2pdf import pisa

# --- Configuration ---
load_dotenv()
# Create a .env file in the same directory as main.py and add:
# GOOGLE_API_KEY="your_api_key_here"
# HTTPS_PROXY="http://your-proxy.com:port"
API_KEY = os.getenv("GOOGLE_API_KEY")
HTTPS_PROXY = os.getenv("HTTPS_PROXY")

if HTTPS_PROXY:
    os.environ['https_proxy'] = HTTPS_PROXY
    os.environ['http_proxy'] = HTTPS_PROXY
PROFILE_PICTURE_PLACEHOLDER = "https://www.gravatar.com/avatar/00000000000000000000000000000000?d=mp&f=y"

# --- Gemini API Initialization ---
try:
    transport = None
    if HTTPS_PROXY:
        proxy_url = urllib.parse.urlparse(HTTPS_PROXY)
        transport = google.auth.transport.requests.ProxiedTransport(
            proxy_url.geturl(),
        )
    genai.configure(api_key=API_KEY, transport=transport)
except Exception as e:
    print(f"Warning: Could not configure Gemini API. {e}")

# --- FastAPI App Initialization ---
app = FastAPI(title="PDF Conversion API")

# Create a temporary directory for file storage
if not os.path.exists("temp"):
    os.makedirs("temp")

# --- Gemini Vision Prompt ---
GEMINI_PROMPT = f"""
Analyze the following image of a document page. Your task is to reconstruct its content and layout into a single, clean HTML file. Use appropriate semantic tags and CSS.

**CRITICAL INSTRUCTION**: Ignore all charts, graphs, logos, or other generic images. However, if you identify a space for a person's profile picture, you MUST use the exact URL '{PROFILE_PICTURE_PLACEHOLDER}' for the `src` attribute of the `<img>` tag.

Respond with only the raw HTML code.
"""

# --- Dependency for File Validation ---
async def validate_pdf(file: UploadFile = File(...)) -> UploadFile:
    if file.content_type != "application/pdf":
        raise HTTPException(400, detail="Invalid file type. Please upload a PDF.")
    return file

async def validate_html(file: UploadFile = File(...)) -> UploadFile:
    if file.content_type != "text/html":
        raise HTTPException(400, detail="Invalid file type. Please upload an HTML file.")
    return file

# --- API Endpoints ---
@app.post("/html-to-pdf/", summary="Convert HTML to PDF")
async def html_to_pdf(background_tasks: BackgroundTasks, file: UploadFile = Depends(validate_html)):
    """Converts an uploaded HTML file to a PDF using xhtml2pdf."""
    pdf_path = f"temp/{uuid.uuid4()}.pdf"
    try:
        html_content = await file.read()
        html_content_str = html_content.decode("utf-8")

        # Custom CSS to reduce bullet point margins
        css = """
        <style>
            @page {
                margin: 2cm;
            }
            ul, li {
                margin: 0;
                padding: 0;
                padding-left: 1em; /* Adjust indentation */
            }
            li {
                margin-bottom: 0.5em; /* Space between bullet points */
            }
        </style>
        """
        
        # Prepend the CSS to the HTML content
        html_with_css = css + html_content_str

        with open(pdf_path, "w+b") as pdf_file:
            pisa_status = pisa.CreatePDF(
                io.StringIO(html_with_css),
                dest=pdf_file
            )

        if pisa_status.err:
            raise HTTPException(500, detail=f"PDF conversion error: {pisa_status.err}")

        background_tasks.add_task(os.remove, pdf_path)
        return FileResponse(pdf_path, media_type='application/pdf', filename="converted.pdf")
    except Exception as e:
        if os.path.exists(pdf_path):
            os.remove(pdf_path)
        raise HTTPException(500, detail=f"An error occurred during PDF conversion: {e}")

@app.post("/pdf-to-html-gemini/", response_class=HTMLResponse, summary="Convert PDF to HTML using Gemini")
async def pdf_to_html_gemini_vision(file: UploadFile = Depends(validate_pdf)):
    """
    Converts a PDF to HTML using Gemini Vision. It ignores all embedded
    images and only inserts a specific URL for a profile picture.
    """
    try:
        model_id = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
        model = genai.GenerativeModel(model_id)
        pdf_bytes = await file.read()
        pdf_document = fitz.open(stream=pdf_bytes, filetype="pdf")

        final_html = ""
        for page_num in range(len(pdf_document)):
            page = pdf_document.load_page(page_num)
            pix = page.get_pixmap(dpi=150)
            page_image_pil = Image.open(io.BytesIO(pix.tobytes("png")))

            prompt_parts = [GEMINI_PROMPT, page_image_pil]

            print(f"Sending page {page_num + 1}/{len(pdf_document)} to Gemini...")
            response = model.generate_content(prompt_parts)

            page_html = response.text.replace("```html", "").replace("```", "").strip()
            final_html += page_html + "\n\n"

        return HTMLResponse(content=final_html)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An error occurred: {str(e)}")

@app.post("/pdf-to-html/", response_class=HTMLResponse, summary="Convert PDF to HTML using PyMuPDF")
async def pdf_to_html(file: UploadFile = Depends(validate_pdf)):
    """Converts a PDF to HTML using the built-in PyMuPDF text extraction."""
    try:
        pdf_bytes = await file.read()
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            html_content = "".join(page.get_text("html") for page in doc)
        return HTMLResponse(content=html_content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An error occurred: {str(e)}")

# --- Main Execution ---
if __name__ == "__main__":
    import uvicorn
    PORT = os.getenv("PORT")
    print("Starting FastAPI server...")
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")
