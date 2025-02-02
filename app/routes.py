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

# Initialize Firestore based on environment
if os.getenv('ENV') == 'local':
    # Use local service account key
    firestore_client = firestore.Client.from_service_account_json(
        os.getenv('GOOGLE_APPLICATION_CREDENTIALS'),
        project="cv-converter-449021",
        database="cv-converter-db"
    )
else:
    # Fetch secret from GCP Secret Manager
    secret_client = secretmanager.SecretManagerServiceClient()
    secret_name = "projects/cv-converter-449021/secrets/firestore-account-key/versions/latest"
    response = secret_client.access_secret_version(request={"name": secret_name})
    secret_payload = response.payload.data.decode("UTF-8")
    credentials_info = json.loads(secret_payload)
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

# Translations for all hardcoded text in cv_template.html
translations = {
    "en": {
        "skills_title": "Technical and Functional Skills.",
        "education_title": "Education.",
        "certifications_title": "Certifications.",
        "languages_title": "Languages.",
        "experiences_title": "Professional Experiences.",
        "description_label": "Description of the role:",
        "client_references_label": "Client References:",
        "we_are_randstad": "we are randstad digital.",
        "randstad_paragraph": """Randstad Digital is a leading technology partner that accelerates digital
transformation for businesses by providing talent, production capabilities, and
packaged solutions in specialized fields. Our expertise enables you to
strengthen your team while connecting you with skilled professionals worldwide
who align with the technologies you’ve chosen.<br><br>
We focus on packaged solutions, empowering businesses to achieve their
objectives quickly and efficiently. We operate across four service lines:
customer experience (UX/UI), digital engineering and product engineering, data
& analytics, and cloud & infrastructure. To achieve this, we offer our clients
three engagement models: expertise, competency centers, and packaged
solutions.<br><br>
Launched on August 30, 2023, Randstad Digital has an in-depth understanding
of the labor market, enabling us to support our clients in their digital
transformation projects with our diversified and agile expertise and
methodologies. Our 46,000 employees worldwide positively impact society by
helping people achieve their full potential throughout their professional lives.<br><br>
Randstad was founded in 1960, with its headquarters in Diemen, the
Netherlands. In 2022, across our 39 markets, we helped over 2 million people
find jobs that suited them and advised more than 230,000 clients on their
talent needs. We generated €27.6 billion in revenue. Randstad N.V. is listed on
Euronext Amsterdam.""",
        "our_solutions": "our solutions",
        "customer_experience": "customer experience",
        "customer_experience_desc": """We help you improve the way you interact with your customers by designing and
creating a differentiated digital experience, giving meaning to every step of the
customer journey.""",
        "data_analytics": "data & analytics",
        "data_analytics_desc": """We help you catalog, gather, and structure your data, transforming it into actionable
insights for your organization.""",
        "product_engineering": "product & digital engineering",
        "product_engineering_desc": """We provide the expertise needed to accelerate digital innovation, from product design
to tailor-made solutions.""",
        "cloud_infrastructure": "cloud & infrastructure",
        "cloud_infrastructure_desc": """We provide the expertise to accelerate cloud migration and help you create an agile,
digitally-focused infrastructure."""
    },

    "fr": {
        "skills_title": "Compétences techniques et fonctionnelles.",
        "education_title": "Formations.",
        "certifications_title": "Certifications.",
        "languages_title": "Langues.",
        "experiences_title": "Expériences professionnelles.",
        "description_label": "Description du rôle :",
        "client_references_label": "Référence du client :",
        "we_are_randstad": "nous sommes randstad digital",
        "randstad_paragraph": """Randstad Digital est un partenaire technologique de référence qui facilite la
transformation digitale accélérée des entreprises en fournissant des talents,
des capacités de production et des solutions packagées dans des domaines
spécialisés. Notre expertise vous permet de renforcer votre équipe, tout en vous
mettant en relation avec des professionnels qualifiés dans le monde entier qui
s'alignent sur les technologies que vous avez choisies.<br><br>
Nous nous concentrons sur les solutions packagées et nous donnons aux entreprises
les moyens d'atteindre leurs objectifs rapidement et efficacement. Nous intervenons
autour de quatre lignes de services : l'expérience client (UX/UI), l'ingénierie
numérique et l'ingénierie produit, les datas & analytics et le cloud & infrastructures.
Pour ce faire, nous proposons à nos clients trois modèles d'engagement : l'expertise,
des centres de compétences et des solutions packagées.<br><br>
Lancée le 30 août 2023, Randstad Digital possède une connaissance approfondie du
marché du travail pour accompagner ses clients dans leurs projets de transformation
digitale grâce à son expertise et ses méthodologies diversifiées et agiles. Nos
46 000 collaborateurs dans le monde ont un impact positif sur la société en aidant
les gens à réaliser leur véritable potentiel tout au long de leur vie professionnelle.<br><br>
Randstad a été fondée en 1960 et son siège social se trouve à Diemen, aux Pays-Bas.
En 2022, sur nos 39 marchés, nous avons aidé plus de 2 millions de personnes à
trouver un emploi qui leur convient et conseillé plus de 230 000 clients sur leurs
besoins en talents. Nous avons généré un chiffre d'affaires de 27,6 milliards d'euros.
Randstad N.V. est cotée à l'Euronext Amsterdam.""",
        "our_solutions": "nos solutions",
        "customer_experience": "expérience client",
        "customer_experience_desc": """Nous vous aidons à améliorer la façon dont vous interagissez avec vos clients,
en concevant et en créant une expérience digitale différenciante et en donnant
du sens à chaque étape du parcours client.""",
        "data_analytics": "data & analytics",
        "data_analytics_desc": """Nous vous aidons à répertorier, rassembler et structurer vos données et à
les transformer en informations exploitables pour votre organisation.""",
        "product_engineering": "ingénierie produit & digital",
        "product_engineering_desc": """Nous fournissons l'expertise nécessaire pour accélérer l'innovation digitale,
de la conception du produit aux solutions élaborées sur mesure.""",
        "cloud_infrastructure": "cloud & infrastructure",
        "cloud_infrastructure_desc": """Nous fournissons l'expertise pour accélérer la migration vers le cloud et vous
aider à créer une infrastructure agile axée sur le numérique."""
    }
}

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
    
    # Save chosen language in the result so we know what user selected
    result["chosen_language"] = target_language

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
            lang_code = data.get("chosen_language", "en")

            for section in sections:
                hh = heading_height()
                heading_placed = False
                heading_str = translations[lang_code]["experiences_title"]

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
                            "heading": heading_str,
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
            
            # 1) Determine the chosen language
            lang_code = data.get("chosen_language", "en")

            # 2) Get localized text
            localized_text = translations.get(lang_code, translations["en"])

            # 3) Render with text=localized_text
            print(f"Rendering with language: {lang_code}, Localized text exists: {bool(localized_text)}")
            return render_template('cv_template.html', data=data, text=localized_text)

        except Exception as e:
            print(f"Error updating CV: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    else:
        # Handle GET request: Load from Firestore
        try:
            doc = doc_ref.get()
            if doc.exists:
                data = doc.to_dict()
                
                # If no language stored, default to "en"
                lang_code = data.get("chosen_language", "en")
                localized_text = translations.get(lang_code, translations["en"])
                
                print(f"Rendering with language: {lang_code}, Localized text exists: {bool(localized_text)}")
                return render_template('cv_template.html', data=data, text=localized_text)
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
