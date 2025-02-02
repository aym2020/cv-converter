from flask import render_template, request, redirect, Flask, url_for, jsonify
import fitz  # PyMuPDF
import os
import json
from openai import OpenAI
from dotenv import load_dotenv
import re
from app import app
from datetime import datetime
import uuid
from google.cloud import firestore
from google.cloud import secretmanager
import google.auth
from google.auth import impersonated_credentials

# Load environment variables
load_dotenv()

# Fetch the secret from Secret Manager
secret_client = secretmanager.SecretManagerServiceClient()
secret_name = "projects/cv-converter-449021/secrets/firestore-account-key/versions/latest"
response = secret_client.access_secret_version(request={"name": secret_name})
secret_payload = response.payload.data.decode("UTF-8")

# Parse the secret (service account JSON)
credentials_info = json.loads(secret_payload)

# Initialize Firestore with explicit credentials
firestore_client = firestore.Client.from_service_account_info(
    credentials_info, 
    project="cv-converter-449021", 
    database="cv-converter-db"
)

# Initialize OpenAI client
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY)

# Get the path to the service account key
credentials_path = os.getenv('GOOGLE_APPLICATION_CREDENTIALS')

# Configure upload folder
app.config['UPLOAD_FOLDER'] = 'app/uploads'

if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/test')
def test():
    return "Flask is working!"

@app.route('/upload', methods=['POST'])
def upload_file():
    # Ensure a file is present in the request
    if 'file' not in request.files:
        return "No file part in the request", 400

    pdf_file = request.files['file']
    if pdf_file.filename == '':
        return "No selected file", 400

    # Optional check for .pdf extension
    if not pdf_file.filename.lower().endswith('.pdf'):
        return "Invalid file format. Please upload a PDF.", 400

    # 1) Read the PDF into memory (bytes)
    pdf_bytes = pdf_file.read()

    # 2) Extract text from the in-memory PDF bytes
    text = extract_text_from_pdf_bytes(pdf_bytes)
    if not text:
        return "Failed to extract text from PDF", 500

    # 3) Process the text with OpenAI or other logic
    job_title_context = request.form.get('job_title_context')
    target_language = request.form.get('language_selection')
    manager_id = request.form.get('sales_manager_selection') or ""

    # Get manager info (if needed)
    manager_name = manager_email = manager_tel = manager_role = ""
    if manager_id:
        managers = load_sales_managers()
        manager = next((m for m in managers if m.get('id') == manager_id), None)
        if manager:
            manager_name = f"{manager['first_name']} {manager['name']}"
            manager_email = manager['email']
            manager_tel = manager['tel']
            manager_role = manager['role']

    # 4) Send to OpenAI
    result = send_to_openai_api(
        text, 
        job_title_context, 
        target_language,
        manager_name, 
        manager_email, 
        manager_tel,
        manager_role
    )

    if not result:
        return "Failed to process the CV with OpenAI API.", 500

    # 5) Store JSON result in Firestore
    firestore_client.collection('cvs').document('last_cv').set(result)
    print("CV stored in Firestore as 'last_cv'")

    # 6) Render the editable form with the AI response
    return render_template('edit_form.html', data=result)

def extract_text_from_pdf_bytes(pdf_bytes):
    """
    Extracts text from a PDF in memory using PyMuPDF.
    """
    try:
        # Open the PDF from memory
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            text = ""
            for page in doc:
                text += page.get_text()
        return text
    except Exception as e:
        print(f"Error extracting text from in-memory PDF: {e}")
        return None

def send_to_openai_api(text, job_title_context, target_language, manager_name, manager_email, manager_tel, manager_role):
    """
    Sends the extracted CV text to OpenAI, requesting a structured JSON output.
    The 'job_title_context' is the position for which the CV is tailored.
    The 'target_language' indicates whether the CV text should be translated (e.g. 'English', 'French').
    Skills categories remain in English, while the rest of the CV is translated if needed.
    """
    try:
        # System role content: Provide high-level instructions on behavior
        system_content = (
            "You are a highly accurate assistant that extracts structured CV data from potentially French or other-language text "
            "and returns it in a fixed JSON format—no extra fields, no missing fields. "
            f"The CV is for the job title: {job_title_context}. "
            "If the CV is not in English, translate the content (descriptions, experiences, education, certifications, etc.) "
            f"into {target_language}. However, the skills category names (e.g., 'Programming', 'Cloud & Identity Management') "
            "must remain in English. Skill items can be translated if they are general text, but brand or software names typically remain as-is. "
            "Ensure the JSON structure is exactly as specified."
        )

        # User role content: Detailed instructions for JSON structure
        user_content = f"""
**INSTRUCTIONS:**
Extract the following information from this CV text and, if needed, translate it to {target_language}. **Output must be valid JSON** with **exactly** these top-level fields, in this order (do not add or rename keys):

{{
    "name": "",
    "first_name": "",
    "job_title": "{job_title_context}",
    "skills": {{}},
    "languages": {{}},
    "experiences": [],
    "education": [],
    "certifications": [],
    "manager_name": "{manager_name}",
    "manager_email": "{manager_email}",
    "manager_tel": "{manager_tel}",
    "manager_role": "{manager_role}"
}}

1. **name**: Last name (string).
2. **first_name**: First name (string).
3. **job_title**: Job title (string). This should be the same as the job title provided by the user: "{job_title_context}".

4. **skills**: 
   - An **object** with up to 4 or 5 relevant categories for a professional CV (e.g., 'Programming', 'Cloud & Identity Management', 'Device & Application Management', 'Collaboration & Productivity Tools', 'Networking & Infrastructure', etc.).
   - **3 categories minimum**
   - **Category names** must remain in **English** (do not translate them).
   - Each key is a category name, and each value is a **list** of skill strings.
   - Do your best to create the most accurate categories
   - Avoids creating overcrowded groups
   - Include **all found skills** in the parsed text, placing them into these categories. 
   - **No blank categories**. Example:
     "skills": {{ 
       "Programming": ["Python", "JavaScript"], 
       "Cloud & Identity Management": ["Azure AD", "Okta"]
     }}
   If no skills, return `"skills": {{}}`.

5. **languages**: 
   - An **object** where each key is a **Language** (capitalized), 
   - The value is the proficiency level, restricted to these patterns:
     - "Native or bilingual proficiency – C2"
     - "Professional working proficiency – B2"
     - "Basic knowledge – A2"
   Example:
     "languages": {{ "French": "Native or bilingual proficiency – C2", "Italian": "Professional working proficiency – B2" }}
   If none, return `"languages": {{}}`.

6. **experiences**: A **list** of objects, each with:
   - **job_title** (string)
   - **company** (string)
   - **duration** (string, e.g. '11/2023 – 09/2024')
   - **description** (string). Enhance responsibilities, use bullet points (`- `) and line breaks for readability. Description must be in {target_language} if original is not English.
   - **client_references** (list of objects, optional). Each reference has:
     - **first_name** (string)
     - **last_name** (string)
     - **role** (string)
     - **email** (string)
     - **tel** (string)
   If no experiences, return `"experiences": []`.

7. **education**: A **list** of objects, each with:
   - **degree** (string, capitalized)
   - **institution** (string, empty if unknown)
   - **duration** (string)
   - **description** (string)
   If no education, return `"education": []`.

8. **certifications**: A **list** of objects, each with:
   - **name** (string, capitalized)
   - **issuer** (string, empty if unknown)
   If none, return `"certifications": []`.

**Important**:
- Do **not** add extra top-level fields or rename existing fields.
- If a section is not found in the CV, provide an empty object/array for it.
- Return **only** the JSON object, with no additional text or explanations.
- All text (except skill category headings) in **{target_language}**.
- Capitalize Language names, Degree names, Name and First Name, Job Title, and Certification names if appropriate.

CV Text:
{text}
"""

        response = client.chat.completions.create(
            model="gpt-4-1106-preview",
            messages=[
                {"role": "system", "content": system_content},
                {"role": "user", "content": user_content}
            ]
        )

        raw_content = response.choices[0].message.content

        # Clean up the raw JSON content from GPT
        json_str = re.sub(r'^```json\s*', '', raw_content)  # remove ```json
        json_str = re.sub(r'\s*```$', '', json_str)         # remove ```
        json_str = json_str.strip()
        # Fix trailing commas
        json_str = re.sub(r',\s*}', '}', json_str)
        json_str = re.sub(r',\s*]', ']', json_str)

        # Parse the JSON string
        json_data = json.loads(json_str)

        # Overwrite the job_title field just to be sure
        json_data["job_title"] = job_title_context

        print("Raw JSON from OpenAI API:")
        print(json.dumps(json_data, indent=4))
        return json_data
    except Exception as e:
        print(f"Error calling OpenAI API: {e}")
        return None

@app.route('/generate_cv', methods=['GET', 'POST'])
def generate_cv():
    """
    Loads the 'last_cv' from Firestore, updates it with form data, 
    and renders 'cv_template.html' with the updated data.
    """
    # Define global variables for page dimensions
    global PAGE_HEIGHT_MM, PAGE_WIDTH_MM, PADDING_MM

    # Page dimensions and padding (A4 size)
    PAGE_HEIGHT_MM = 290  # A4 height in mm
    PAGE_WIDTH_MM = 210   # A4 width in mm
    PADDING_MM = 30       # Padding around the content

    # Content height after accounting for padding
    CONTENT_HEIGHT_MM = PAGE_HEIGHT_MM - 2 * PADDING_MM

    # Define heights for different elements based on CSS
    SECTION_HEADING_HEIGHT = 20
    SKILL_CATEGORY_HEIGHT = 5
    SKILL_ITEM_HEIGHT = 3
    LANGUAGE_ITEM_HEIGHT = 3
    EDUCATION_BASE_HEIGHT = 8
    EDUCATION_LINE_HEIGHT = 4
    EXPERIENCE_BASE_HEIGHT = 15
    EXPERIENCE_LINE_HEIGHT = 10
    EXPERIENCE_SECTION_TITLE_HEIGHT = 8
    EXPERIENCE_TABLE_HEIGHT = 8.5
    EXPERIENCE_DESCRIPTION_LABEL_HEIGHT = 7.4
    EXPERIENCE_BULLET_LINE_HEIGHT = 8
    EXPERIENCE_BULLET_PADDING_TOP = 7
    EXPERIENCE_BULLET_PADDING_BOTTOM = 7
    EXPERIENCE_CLIENT_REF_TITLE_HEIGHT = 6
    EXPERIENCE_CLIENT_REF_MARGIN_TOP = 3
    EXPERIENCE_CLIENT_REF_MARGIN_BOTTOM = 3
    EXPERIENCE_CLIENT_REF_LINE_HEIGHT = 5.0
    EXPERIENCE_SKIPPED_LINE_HEIGHT = 5.0

    def heading_height():
        return SECTION_HEADING_HEIGHT

    def item_height(section_type, item):
        """
        Calculates dynamic height (for demonstration / chunking logic).
        """
        if section_type == "skills":
            skill_count = len(item.get("skills", []))
            return SKILL_CATEGORY_HEIGHT + (skill_count / 4) * SKILL_ITEM_HEIGHT

        elif section_type == "languages":
            return LANGUAGE_ITEM_HEIGHT

        elif section_type == "experiences":
            # Base
            height = (
                EXPERIENCE_TABLE_HEIGHT +
                EXPERIENCE_DESCRIPTION_LABEL_HEIGHT
            )
            desc = item.get("description", "")
            lines = desc.split("\n")
            line_count = len(lines) if lines else 1
            height += (
                EXPERIENCE_BULLET_PADDING_TOP +
                (line_count * EXPERIENCE_BULLET_LINE_HEIGHT) +
                EXPERIENCE_BULLET_PADDING_BOTTOM
            )
            # client references
            client_references = item.get("client_references", [])
            if client_references:
                height += (
                    EXPERIENCE_CLIENT_REF_TITLE_HEIGHT +
                    EXPERIENCE_CLIENT_REF_MARGIN_TOP +
                    (len(client_references) * 3 * EXPERIENCE_CLIENT_REF_LINE_HEIGHT) +
                    EXPERIENCE_CLIENT_REF_MARGIN_BOTTOM
                )

            height += EXPERIENCE_SKIPPED_LINE_HEIGHT
            return height

        elif section_type == "education":
            desc = item.get("description", "")
            lines = desc.split("\n")
            line_count = len(lines) if lines else 1
            return EDUCATION_BASE_HEIGHT + line_count * EDUCATION_LINE_HEIGHT

        return 10  # Default

    # Firestore reference
    doc_ref = firestore_client.collection('cvs').document('last_cv')

    if request.method == 'POST':
        try:
            # Fetch last saved CV from Firestore
            doc = doc_ref.get()
            if not doc.exists:
                return jsonify({'success': False, 'error': 'No last CV found in Firestore'}), 404

            data = doc.to_dict()

            # Update the JSON data with form inputs
            data["first_name"] = request.form.get("first_name", data.get("first_name", ""))
            data["name"] = request.form.get("name", data.get("name", ""))
            data["job_title"] = request.form.get("job_title", data.get("job_title", ""))
            data["manager_name"] = request.form.get("manager_name", data.get("manager_name", ""))
            data["manager_email"] = request.form.get("manager_email", data.get("manager_email", ""))
            data["manager_tel"] = request.form.get("manager_tel", data.get("manager_tel", ""))
            data["manager_role"] = request.form.get("manager_role", data.get("manager_role", ""))

            # Update skills
            data["skills"] = {}
            for key, value in request.form.items():
                if key.startswith("skills_"):
                    index = key.replace("skills_", "")
                    category_name = request.form.get(f"category_name_{index}", "").strip()
                    if category_name:
                        skill_list = value.split(", ")
                        if skill_list and skill_list != [""]:
                            data["skills"][category_name] = skill_list

            # Update languages
            languages = {}
            i = 1
            while True:
                language_name = request.form.get(f"language_{i}")
                proficiency = request.form.get(f"level_{i}")
                if language_name is None:
                    break
                if not language_name.strip():
                    i += 1
                    continue
                languages[language_name] = proficiency or "Unknown"
                i += 1
                if i > 50:
                    break
            data["languages"] = languages

            # Update experiences with client references
            experiences = []
            i = 1
            while True:
                job_title = request.form.get(f"job_title_{i}")
                if not job_title:
                    break

                # Collect client references
                client_references = []
                j = 1
                while True:
                    first_name = request.form.get(f"client_first_name_{i}_{j}")
                    last_name = request.form.get(f"client_last_name_{i}_{j}")
                    role = request.form.get(f"client_role_{i}_{j}")
                    email = request.form.get(f"client_email_{i}_{j}")
                    tel = request.form.get(f"client_tel_{i}_{j}")

                    if not first_name and not last_name:
                        break

                    client_references.append({
                        "first_name": (first_name or "").strip(),
                        "last_name": (last_name or "").strip(),
                        "role": (role or "").strip(),
                        "email": (email or "").strip(),
                        "tel": (tel or "").strip(),
                    })
                    j += 1

                # Append the experience with references
                experiences.append({
                    "job_title": job_title.strip(),
                    "company": request.form.get(f"company_{i}", "").strip(),
                    "duration": request.form.get(f"duration_{i}", "").strip(),
                    "description": request.form.get(f"description_{i}", "").strip(),
                    "client_references": client_references
                })
                i += 1
            data["experiences"] = experiences

            # Update education
            education = []
            j = 1
            while True:
                degree = request.form.get(f"degree_{j}")
                if not degree:
                    break
                education.append({
                    "degree": degree,
                    "institution": request.form.get(f"institution_{j}", ""),
                    "duration": request.form.get(f"education_duration_{j}", ""),
                    "description": request.form.get(f"education_description_{j}", ""),
                })
                j += 1
            data["education"] = education

            # Update certifications
            certifications = []
            k = 1
            while True:
                certification_name = request.form.get(f"certification_name_{k}")
                if not certification_name:
                    break
                certifications.append({
                    "name": certification_name,
                    "issuer": request.form.get(f"certification_issuer_{k}", ""),
                })
                k += 1
            data["certifications"] = certifications

            # Save updated CV back to Firestore
            doc_ref.set(data)
            print("Updated CV saved to Firestore.")

            # ----- Build sections for chunking / pagination -----
            sections = []

            # Skills
            if data["skills"]:
                skill_items = []
                for category, skill_list in data["skills"].items():
                    skill_items.append({"category": category, "skills": skill_list})
                sections.append({
                    "type": "skills",
                    "heading": "Technical and Functional Skills.",
                    "items": skill_items,
                })

            # Education
            if data["education"]:
                sections.append({
                    "type": "education",
                    "heading": "Education.",
                    "items": data["education"],
                })

            # Certifications
            if data["certifications"]:
                sections.append({
                    "type": "certifications",
                    "heading": "Certifications.",
                    "items": data["certifications"],
                })

            # Languages
            if data["languages"]:
                lang_items = []
                for lang, level in data["languages"].items():
                    lang_items.append({"language": lang, "level": level})
                sections.append({
                    "type": "languages",
                    "heading": "Languages.",
                    "items": lang_items,
                })

            # Experiences
            if data["experiences"]:
                sections.append({
                    "type": "experiences",
                    "heading": "Professional Experiences.",
                    "items": data["experiences"],
                })

            # ----- Page chunking logic -----
            pages = []
            current_page = []
            current_height = 0

            for section in sections:
                hh = heading_height()
                heading_placed = False

                # Start a new page for experiences if there's already content
                if section["type"] == "experiences" and current_height > 0:
                    pages.append(current_page)
                    current_page = []
                    current_height = 0

                for single_item in section["items"]:
                    item_h = item_height(section["type"], single_item)

                    required_height = item_h + (0 if heading_placed else hh)
                    if current_height + required_height > CONTENT_HEIGHT_MM:
                        pages.append(current_page)
                        current_page = []
                        current_height = 0

                    if not heading_placed:
                        new_block = {
                            "type": section["type"],
                            "heading": section["heading"],
                            "items": []
                        }
                        current_page.append(new_block)
                        current_height += hh
                        heading_placed = True
                    else:
                        # If heading already placed, but new block needed for a different item
                        if not current_page or current_page[-1]["type"] != section["type"]:
                            new_block = {
                                "type": section["type"],
                                "heading": "",
                                "items": []
                            }
                            current_page.append(new_block)

                    current_page[-1]["items"].append(single_item)
                    current_height += item_h

            if current_page:
                pages.append(current_page)

            data["page_2_content"] = pages
            print("Page 2 Content:", json.dumps(data["page_2_content"], indent=2))

            return render_template('cv_template.html', data=data)

        except Exception as e:
            print(f"Error updating CV: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    else:
        # Handle GET request: Load from Firestore
        try:
            doc = doc_ref.get()
            if doc.exists:
                data = doc.to_dict()
                return render_template('cv_template.html', data=data)
            else:
                return jsonify({'success': False, 'error': 'No last CV found in Firestore'}), 404
        except Exception as e:
            print(f"Error fetching CV: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/reuse_last_json')
def reuse_last_json():
    """
    Reuses the 'last_cv' from Firestore instead of a local file.
    """
    try:
        doc_ref = firestore_client.collection('cvs').document('last_cv')
        doc = doc_ref.get()

        if doc.exists:
            return jsonify({'success': True, 'data': doc.to_dict()}), 200
        else:
            return jsonify({'success': False, 'error': 'No last JSON found.'}), 404

    except Exception as e:
        print(f"Error fetching last CV: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/edit_form')
def edit_form():
    """
    Loads the 'last_cv' from Firestore and displays the edit form.
    """
    try:
        doc_ref = firestore_client.collection('cvs').document('last_cv')
        doc = doc_ref.get()
        if not doc.exists:
            return jsonify({'success': False, 'error': 'No last JSON found.'}), 404

        data = doc.to_dict()
        return render_template('edit_form.html', data=data)

    except Exception as e:
        print(f"Error loading edit form: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

# Helper functions to load and save sales managers
def load_sales_managers():
    managers_ref = firestore_client.collection('sales_managers')
    managers = [doc.to_dict() for doc in managers_ref.stream()]
    return managers

def save_sales_managers(managers):
    """
    If you want to store each manager individually in Firestore:
    """
    managers_ref = firestore_client.collection('sales_managers')
    for manager in managers:
        managers_ref.document(manager['id']).set(manager)

@app.route('/sales_managers')
def get_sales_managers():
    try:
        managers_ref = firestore_client.collection('sales_managers')
        managers = [doc.to_dict() for doc in managers_ref.stream()]
        return jsonify({'success': True, 'data': managers})
    except Exception as e:
        print(f"Error fetching sales managers: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/get_sales_manager/<manager_id>', methods=['GET'])
def get_sales_manager(manager_id):
    try:
        doc_ref = firestore_client.collection('sales_managers').document(manager_id)
        doc = doc_ref.get()
        if not doc.exists:
            return jsonify({'success': False, 'error': 'Sales manager not found.'}), 404

        return jsonify({'success': True, 'data': doc.to_dict()}), 200
    except Exception as e:
        print(f"Error fetching sales manager: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/add_sales_manager', methods=['POST'])
def add_sales_manager():
    """
    Adds a new sales manager to Firestore.
    """
    try:
        data = request.get_json()
        first_name = data.get('first_name')
        name = data.get('name')
        role = data.get('role')
        email = data.get('email', "")
        tel = data.get('tel', "")

        if not all([first_name, name, role]):
            return jsonify({'success': False, 'error': 'First name, last name, and role are required.'}), 400

        new_id = str(uuid.uuid4())
        manager_data = {
            "id": new_id,
            "first_name": first_name,
            "name": name,
            "role": role,
            "email": email,
            "tel": tel
        }

        firestore_client.collection('sales_managers').document(new_id).set(manager_data)
        return jsonify({'success': True, 'id': new_id}), 200

    except Exception as e:
        print(f"Error adding sales manager: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/remove_sales_manager', methods=['POST'])
def remove_sales_manager():
    try:
        data = request.get_json()
        manager_id = data.get('id')
        if not manager_id:
            return jsonify({'success': False, 'error': 'No ID provided.'}), 400

        firestore_client.collection('sales_managers').document(manager_id).delete()
        return jsonify({'success': True}), 200
    except Exception as e:
        print(f"Error removing sales manager: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/update_sales_manager/<manager_id>', methods=['PUT'])
def update_sales_manager(manager_id):
    """
    If you want to update the manager data directly in Firestore.
    Otherwise, if you rely on a local JSON file, keep the local references.
    """
    try:
        data = request.get_json()
        first_name = data.get('first_name')
        name = data.get('name')
        role = data.get('role')
        email = data.get('email')
        tel = data.get('tel')

        if not all([first_name, name, role, email, tel]):
            return jsonify({'success': False, 'error': 'All fields are required.'}), 400

        # Direct Firestore approach
        manager_data = {
            "id": manager_id,
            "first_name": first_name,
            "name": name,
            "role": role,
            "email": email,
            "tel": tel
        }

        doc_ref = firestore_client.collection('sales_managers').document(manager_id)
        if not doc_ref.get().exists:
            return jsonify({'success': False, 'error': 'Sales manager not found in Firestore.'}), 404

        doc_ref.update(manager_data)
        return jsonify({'success': True}), 200

    except Exception as e:
        print(f"Error editing sales manager: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)
