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
from playwright.async_api import async_playwright

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
GEMINI_PROMPT_CONVERTER = f"""
ROLE
Anda adalah seorang 'AI Pixel-Perfect UI Replicator'. Peran Anda adalah menganalisis tata letak visual dari serangkaian gambar dokumen (halaman-halaman CV) dan mereplikasinya menjadi satu file HTML tunggal yang identik secara visual, seolah-olah Anda sedang mengonversi desain Figma menjadi kode.

OBJECTIVE
Tujuan utama Anda adalah untuk memproses beberapa gambar yang merepresentasikan halaman-halaman berurutan dari sebuah dokumen tunggal dan menghasilkan satu file HTML mentah tunggal yang menggabungkan konten dari semua halaman tersebut. Gunakan Tailwind CSS untuk semua kebutuhan styling dan tata letak untuk mencapai replikasi visual 1:1.

INSTRUCTIONS
A. Mandat Replikasi Visual (ATURAN PALING PENTING)

Prioritas Utama Adalah Akurasi Visual: Tugas Anda yang paling penting adalah membuat output HTML terlihat persis seperti gambar yang diberikan. Abaikan struktur HTML konvensional jika itu menghalangi replikasi visual.

Perhatikan Tata Letak Secara Detail:

Kolom dan Baris: Identifikasi dengan cermat jika ada tata letak multi-kolom (seperti pada bagian "KEY ASSETS & SKILL"). Gunakan flexbox (flex, justify-between) atau grid (grid, grid-cols-2, gap-8) dari Tailwind untuk menirunya dengan presisi.

Perataan (Alignment): Untuk elemen seperti tanggal yang berada di sisi kanan, gunakan flex dengan justify-between pada elemen pembungkusnya untuk memastikan perataan yang sempurna. Hindari float.

Identifikasi dan Gunakan Warna yang Tepat:

Perhatikan warna spesifik yang digunakan dalam dokumen, seperti warna biru tua untuk garis bawah judul bagian.

Gunakan sintaks nilai arbitrer Tailwind untuk mencocokkan warna tersebut. Contoh: border-b-2 border-[#2A4D69] jika Anda mengidentifikasi warna biru tersebut.

Tiru Tipografi dengan Tepat: Cocokkan ukuran font (text-base, text-lg), ketebalan font (font-semibold, font-bold), dan spasi antar huruf jika memungkinkan.

B. Analisis Konten & Ekstraksi

Ekstraksi Konten: Ekstrak semua konten yang relevan dari setiap gambar, termasuk semua teks, informasi kontak, dan detail profesional.

Abaikan Elemen Non-Teks: Abaikan grafik, bagan, atau logo.

Penanganan Gambar Profil: Jika ada foto profil, gunakan URL {PROFILE_PICTURE_PLACEHOLDER} untuk atribut src pada tag <img>.

C. Aturan Penggabungan & Output

BUAT SATU DOKUMEN HTML TUNGGAL: Anda akan menerima beberapa gambar secara berurutan. Buat SATU file HTML dengan struktur utama (<!DOCTYPE>, <head>, <body>) hanya sekali.

Gabungkan Konten: Analisis konten dari setiap gambar dan tambahkan HTML yang sesuai ke dalam satu tag <body> yang sama.

Sertakan Tailwind CDN: Pastikan untuk menyertakan tautan CDN Tailwind CSS di dalam tag <head> tunggal.

BUNGKUS DENGAN MARKDOWN: Seluruh output HTML Anda HARUS dibungkus dalam blok kode markdown. Mulai dengan ```html di baris pertama dan akhiri dengan ``` di baris terakhir.

FORMAT DATA INPUT
Anda akan menerima satu atau lebih gambar (.png) dari halaman-halaman dokumen sebagai input visual utama, secara berurutan.

FORMAT OUTPUT YANG DIBUTUHKAN
Output Anda harus berupa file HTML mentah tunggal yang merupakan replikasi visual akurat dari semua gambar, dibungkus dalam blok kode markdown.

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Nama Kandidat - CV</title>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-white text-gray-800 font-sans">
    <div class="container mx-auto p-12 max-w-4xl">
        <!-- Konten dari Gambar Halaman 1 ditempatkan di sini dengan gaya yang presisi -->
        <!-- Contoh: <div class="flex justify-between items-center">...</div> -->
        <!-- Contoh: <h2 class="text-xl font-bold border-b-2 border-[#2A4D69] pb-1">PROFILE</h2> -->

        <!-- Konten dari Gambar Halaman 2 ditempatkan di sini -->
    </div>
</body>
</html>
```

"""

GEMINI_PROMPT_TAGGER = f"""
#ROLE
Anda adalah seorang 'AI HTML Post-Processor'. Peran Anda adalah memproses kode HTML yang ada dan secara cerdas menambahkan atribut fungsional tanpa mengubah struktur atau gaya visualnya.

#OBJECTIVE
Tujuan utama Anda adalah untuk menerima sebuah blok kode HTML mentah, mengidentifikasi semua elemen yang berisi konten teks yang dapat diedit oleh pengguna (seperti nama, deskripsi pekerjaan, keahlian), dan menambahkan atribut id="editable" ke elemen-elemen tersebut.

#INSTRUCTIONS
A. Aturan Analisis & Modifikasi

1. Analisis HTML: Baca dan pahami struktur kode HTML yang diberikan.
2. Identifikasi Target: Cari elemen-elemen yang berisi konten teks utama yang kemungkinan besar ingin diedit oleh pengguna di CV mereka.
3. Elemen yang WAJIB Diberi ID: Tambahkan id="editable" ke tag-tag berikut yang berisi teks:
 - Judul utama (biasanya <h1> atau <h2> untuk nama dan posisi).
 - Paragraf deskriptif (tag <p>).
 - Judul bagian atau item (biasanya <h3> untuk nama perusahaan, sekolah, atau proyek).
 - Item dalam daftar (semua tag <li>), karena ini biasanya berisi detail pekerjaan, tanggung jawab, atau keahlian.
 - Elemen teks spesifik lainnya seperti <span> jika berisi data penting (misalnya, tanggal atau lokasi).

4. Elemen yang JANGAN Diberi ID: Jangan tambahkan ID ke elemen-elemen berikut:
 - Tag struktural utama seperti <body>, <header>, <main>, <aside>, <section>.
 - Div pembungkus yang hanya digunakan untuk tata letak (misalnya, <div class="container...">, <div class="grid...">).
 - Tag gambar (<img>).

*ATURAN KRITIS - JAGA KEUTUHAN: Anda TIDAK BOLEH mengubah apa pun selain menambahkan atribut id="editable". Jangan mengubah konten teks, kelas CSS, atau struktur HTML. Output harus identik dengan input, kecuali penambahan ID.*

B. Aturan Output

1. HANYA HTML MENTAH: Output Anda HARUS berupa kode HTML mentah tunggal yang dimulai dengan <!DOCTYPE html> dan diakhiri dengan </html>.
2. BUNGKUS DENGAN MARKDOWN: Seluruh output HTML Anda HARUS dibungkus dalam blok kode markdown. Mulai dengan ```html di baris pertama dan akhiri dengan ``` di baris terakhir. Jangan tambahkan teks lain di luar blok ini.

#FORMAT DATA INPUT
Anda akan menerima kode HTML mentah tunggal yang dihasilkan oleh agen sebelumnya sebagai input.

<!-- CONTOH INPUT -->
<h1 class="text-4xl font-bold text-gray-800">John Doe</h1>
<p class="text-xl text-gray-600">Software Engineer</p>
<div class="mt-4">
    <h3 class="text-xl font-semibold">Senior Developer at TechCorp</h3>
    <span class="date text-sm text-gray-500">2020 - Present</span>
    <ul class="list-disc list-inside mt-2">
        <li>Led the development of a new microservices architecture.</li>
        <li>Mentored junior developers.</li>
    </ul>
</div>

#FORMAT OUTPUT YANG DIBUTUHKAN
Output Anda harus berupa kode HTML yang sama persis, tetapi dengan id="editable" ditambahkan ke elemen-elemen yang sesuai.

<!-- CONTOH OUTPUT -->
<h1 class="text-4xl font-bold text-gray-800" id="editable">John Doe</h1>
<p class="text-xl text-gray-600" id="editable">Software Engineer</p>
<div class="mt-4">
    <h3 class="text-xl font-semibold" id="editable">Senior Developer at TechCorp</h3>
    <span class="date text-sm text-gray-500" id="editable">2020 - Present</span>
    <ul class="list-disc list-inside mt-2">
        <li id="editable">Led the development of a new microservices architecture.</li>
        <li id="editable">Mentored junior developers.</li>
    </ul>
</div>

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
    """Converts an uploaded HTML file to a PDF using Playwright."""
    pdf_path = f"temp/{uuid.uuid4()}.pdf"
    try:
        html_content = await file.read()
        html_content_str = html_content.decode("utf-8")

        async with async_playwright() as p:
            browser = await p.chromium.launch()
            page = await browser.new_page()
            await page.set_content(html_content_str, wait_until="networkidle")

            # ADD THIS LINE FOR DEBUGGING
            await page.screenshot(path="debug_screenshot.png")

            await page.pdf(path=pdf_path, format="A4", print_background=True)
            await browser.close()

        background_tasks.add_task(os.remove, pdf_path)
        print(pdf_path)
        return FileResponse(pdf_path, media_type='application/pdf', filename="converted.pdf")
    except Exception as e:
        if os.path.exists(pdf_path):
            os.remove(pdf_path)
        raise HTTPException(500, detail=f"An error occurred during PDF conversion: {e}")
@app.post("/html-to-pdf/", summary="Convert HTML to PDF")
async def html_to_pdf(background_tasks: BackgroundTasks, file: UploadFile = Depends(validate_html)):
    """Converts an uploaded HTML file to a PDF with a continuous page."""
    pdf_path = f"temp/{uuid.uuid4()}.pdf"
    try:
        html_content = await file.read()
        html_content_str = html_content.decode("utf-8")

        style_injection = """
        <style>
          @page {
            size: 210mm auto; /* A4 width, content height */
            margin: 0;
          }
          body {
            margin: 0;
          }
        </style>
        """
        # Add this style block right before the closing </head> tag
        html_content_str = html_content_str.replace('</head>', f'{style_injection}</head>')

        async with async_playwright() as p:
            browser = await p.chromium.launch()
            page = await browser.new_page()
            await page.set_content(html_content_str, wait_until="networkidle")

            await page.pdf(
                path=pdf_path,
                print_background=True
            )
            await browser.close()

        background_tasks.add_task(os.remove, pdf_path)
        return FileResponse(pdf_path, media_type='application/pdf', filename="converted.pdf")
    except Exception as e:
        if os.path.exists(pdf_path):
            os.remove(pdf_path)
        raise HTTPException(500, detail=f"An error occurred during PDF conversion: {e}")


# --- Main Execution ---
if __name__ == "__main__":
    import uvicorn
    PORT = os.getenv("PORT")
    print("Starting FastAPI server...")
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")
