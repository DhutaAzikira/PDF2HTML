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
import pdfkit

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
Analyze the following document page image. Your task is to convert the content from the PDF to HTML format following a specific structure and style. Use the provided HTML template as a design guideline, but adjust the final output to match the content from the PDF.

CRITICAL INSTRUCTIONS:

1. Content to Include:
   - All text present in the document, including titles, subtitles, paragraphs, and lists.
   - Contact information such as phone numbers, email addresses, and links to social media profiles or websites.
   - Details of education, work experience, organizational experience, skills, achievements, and projects.
   - Dates and time periods relevant to experiences or education.

2. Content to Ignore:
   - Ignore all charts, graphs, logos, or other generic images that are not relevant to the main text content.
   - Do not include design elements that cannot be represented in simple HTML format.

3. Handling Images:
   - If you identify a space for someone's profile picture, use the exact URL '{PROFILE_PICTURE_PLACEHOLDER}' for the src attribute of the <img> tag.
   - Ensure the profile picture is placed in the appropriate section of the document, usually in the header or near the contact information.

4. Structure and Style:
   - Use the structure and CSS styles defined in the provided HTML template as a design guideline.
   - Ensure to follow the defined HTML structure, including the use of appropriate classes and IDs.
   - Adjust the content from the PDF into the defined HTML structure while maintaining the order and hierarchy of information.

5. HTML Tags to Use:
   - <!DOCTYPE html>: Declaration of the HTML document type.
   - <html lang="en">: Opening tag of the HTML document with the English language attribute.
   - <head>: Head section of the document containing meta information and links to external resources.
     - <meta charset="UTF-8">: Meta tag to set the document's character set.
     - <meta name="viewport" content="width=device-width, initial-scale=1.0">: Meta tag to set the document's display on mobile devices.
     - <title>: Title of the document displayed in the browser tab.
     - <style>: Tag to add internal CSS styles.
   - <body>: Body section of the document containing the main content.
     - <div class="container">: Main container for the content.
       - <div class="header">: Header section containing the title and contact information.
         - <h1>: Main title of the document.
         - <div class="contact-info">: Contact information.
           - <a>: Links to social media profiles or websites.
       - <section class="summary">: Summary or brief profile section.
         - <p>: Paragraph of text.
       - <section class="education">: Education section.
         - <h2>: Subtitle of the section.
         - <div class="education-item">: Education item.
           - <h3>: Title of the education item.
           - <p>: Paragraph of text.
           - <ul>: Unordered list.
             - <li>: List item.
       - <section class="work-experience">: Work experience section.
         - <div class="experience-item">: Work experience item.
           - <h3>: Title of the work experience item.
           - <span class="date">: Date or time period.
           - <ul>: Unordered list.
             - <li>: List item.
       - <section class="organizational-experience">: Organizational experience section.
         - <div class="org-experience-item">: Organizational experience item.
           - <h3>: Title of the organizational experience item.
           - <span class="date">: Date or time period.
           - <ul>: Unordered list.
             - <li>: List item.
       - <section class="skills-achievements">: Skills and achievements section.
         - <ul>: Unordered list.
           - <li>: List item.
             - <strong>: Bold text for emphasis.

6. Final Output:
   - Respond only with raw HTML code.
   - Ensure the generated HTML code is valid and free of syntax errors.
   - Adjust the content from the PDF into the defined HTML structure while maintaining the order and hierarchy of information.
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
    """Converts an uploaded HTML file to a PDF using pdfkit."""
    pdf_path = f"temp/{uuid.uuid4()}.pdf"
    try:
        html_content = await file.read()
        html_content_str = html_content.decode("utf-8")

        # Options to enable external links like CSS
        options = {
            'enable-local-file-access': None,
            'enable-external-links': None
        }

        pdfkit.from_string(html_content_str, pdf_path, options=options)

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
