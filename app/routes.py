from flask import render_template, request, redirect, Flask, url_for, jsonify
import fitz  # PyMuPDF
import os
import json
from openai import OpenAI
from dotenv import load_dotenv
import re
from app import app
from datetime import datetime

# Load environment variables
load_dotenv()

# Initialize OpenAI client
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY)

# Configure upload folder
app.config['UPLOAD_FOLDER'] = 'app/uploads'

if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

# Default page dimensions and padding
PAGE_HEIGHT_MM = 290  # Default height
PAGE_WIDTH_MM = 210   # Default width
PADDING_MM = 25       # Default padding

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/test')
def test():
    return "Flask is working!"

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return redirect(request.url)
    
    file = request.files['file']
    if file.filename == '':
        return redirect(request.url)
    
    if file and file.filename.endswith('.pdf'):
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
        file.save(filepath)

        # Extract text from the PDF
        text = extract_text_from_pdf(filepath)
        job_title_context = request.form.get('job_title_context')
        target_language = request.form.get('language_selection')
        
        print(f"Job Title Context: {job_title_context}")
        print(f"Target Language: {target_language}")

        # Send the extracted text to the OpenAI API
        result = send_to_openai_api(text, job_title_context, target_language)
        if result:
            # Save the JSON to a file
            json_filepath = os.path.join(app.config['UPLOAD_FOLDER'], 'last_cv.json')
            with open(json_filepath, 'w') as f:
                json.dump(result, f, indent=4)
            
            # Render the editable form with the API response
            return render_template('edit_form.html', data=result)
        else:
            return "Failed to process the CV with OpenAI API."
    
    return "Invalid file format. Please upload a PDF."

def extract_text_from_pdf(filepath):
    text = ""
    try:
        with fitz.open(filepath) as doc:
            for page in doc:
                text += page.get_text()
    except Exception as e:
        print(f"Error extracting text from PDF: {e}")
        return None
    return text

def send_to_openai_api(text, job_title_context, target_language):
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
    "certifications": []
}}

1. **name**: Last name (string).
2. **first_name**: First name (string).
3. **job_title**: Job title (string). This should be the same as the job title provided by the user: "{job_title_context}".

4. **skills**: 
   - An **object** with up to 4 or 5 relevant categories for a professional CV (e.g., 'Programming', 'Cloud & Identity Management', 'Device & Application Management', 'Collaboration & Productivity Tools', 'Networking & Infrastructure', etc.).
   - **Category names** must remain in **English** (do not translate them).
   - Each key is a category name, and each value is a **list** of skill strings. 
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

        # Call the OpenAI API
        response = client.chat.completions.create(
            model="gpt-4-1106-preview",
            messages=[
                {"role": "system", "content": system_content},
                {"role": "user", "content": user_content}
            ]
        )

        raw_content = response.choices[0].message.content

        # Clean up the raw JSON content from GPT
        json_str = re.sub(r'^```json\s*', '', raw_content)  # remove ```json at start
        json_str = re.sub(r'\s*```$', '', json_str)         # remove ``` at end
        json_str = json_str.strip()
        # Fix trailing commas in objects/arrays
        json_str = re.sub(r',\s*}', '}', json_str)
        json_str = re.sub(r',\s*]', ']', json_str)

        # Parse the JSON string into a Python dictionary
        json_data = json.loads(json_str)

        # Overwrite the job_title field with the user-provided context (just to be sure)
        json_data["job_title"] = job_title_context

        print("Raw JSON from OpenAI API:")
        print(json.dumps(json_data, indent=4))  # Pretty-print JSON

        return json_data
    except Exception as e:
        print(f"Error calling OpenAI API: {e}")
        return None


@app.route('/generate_cv', methods=['GET', 'POST'])
def generate_cv():
    # Define global variables for page dimensions
    global PAGE_HEIGHT_MM, PAGE_WIDTH_MM, PADDING_MM

    # Page dimensions and padding (A4 size)
    PAGE_HEIGHT_MM = 270  # A4 height in mm
    PAGE_WIDTH_MM = 210   # A4 width in mm
    PADDING_MM = 30       # Padding around the content

    # Content height after accounting for padding
    CONTENT_HEIGHT_MM = PAGE_HEIGHT_MM - 2 * PADDING_MM

    # Define heights for different elements based on CSS
    SECTION_HEADING_HEIGHT = 20  # Height of section headings in mm
    SKILL_CATEGORY_HEIGHT = 5    # Base height for skill categories
    SKILL_ITEM_HEIGHT = 3        # Height per skill item
    LANGUAGE_ITEM_HEIGHT = 8     # Height per language item
    EDUCATION_BASE_HEIGHT = 8    # Base height for education items
    EDUCATION_LINE_HEIGHT = 4    # Height per line in education descriptions
    EXPERIENCE_BASE_HEIGHT = 15  # Base height for experiences (job title + duration)
    EXPERIENCE_LINE_HEIGHT = 10  # Height per line in experience descriptions
    # Heights for Experiences Section
    EXPERIENCE_SECTION_TITLE_HEIGHT = 8.0  # Increased from 7.4mm (28px)
    EXPERIENCE_TABLE_HEIGHT = 9.0          # Increased from 8.5mm (32px)
    EXPERIENCE_DESCRIPTION_LABEL_HEIGHT = 8.0  # Increased from 7.4mm (28px)
    EXPERIENCE_BULLET_LINE_HEIGHT = 5.5    # Increased from 5mm per line
    EXPERIENCE_BULLET_PADDING_TOP = 6.0    # Increased from 5.3mm (20px)
    EXPERIENCE_BULLET_PADDING_BOTTOM = 6.0 # Increased from 5.3mm (20px)
    EXPERIENCE_CLIENT_REF_TITLE_HEIGHT = 6.0  # Increased from 5.3mm (20px)
    EXPERIENCE_CLIENT_REF_MARGIN_TOP = 3.0    # Increased from 2.6mm (10px)
    EXPERIENCE_CLIENT_REF_MARGIN_BOTTOM = 3.0 # Increased from 2.6mm (10px)
    EXPERIENCE_CLIENT_REF_LINE_HEIGHT = 5.5   # Increased from 5mm per line
    EXPERIENCE_SKIPPED_LINE_HEIGHT = 5.5      # Increased from 5mm for skipped line

    # Helper function to calculate heading height
    def heading_height():
        return SECTION_HEADING_HEIGHT

    # Helper function to calculate item height based on section type
    def item_height(section_type, item):
        if section_type == "skills":
            skill_count = len(item.get("skills", []))
            return SKILL_CATEGORY_HEIGHT + skill_count * SKILL_ITEM_HEIGHT

        elif section_type == "languages":
            return LANGUAGE_ITEM_HEIGHT

        elif section_type == "experiences":
            # Base height for the experience item
            height = (
                EXPERIENCE_TABLE_HEIGHT +  # Table height
                EXPERIENCE_DESCRIPTION_LABEL_HEIGHT  # Description label height
            )

            # Add height for bullet points
            desc = item.get("description", "")
            lines = desc.split("\n")
            line_count = len(lines) if lines else 1
            height += (
                EXPERIENCE_BULLET_PADDING_TOP +  # Padding top
                (line_count * EXPERIENCE_BULLET_LINE_HEIGHT) +  # Bullet lines
                EXPERIENCE_BULLET_PADDING_BOTTOM  # Padding bottom
            )

            # Add height for client references (if they exist)
            client_references = item.get("client_references", [])
            if client_references:
                height += (
                    EXPERIENCE_CLIENT_REF_TITLE_HEIGHT +  # Client references title
                    EXPERIENCE_CLIENT_REF_MARGIN_TOP +    # Margin top
                    (len(client_references) * 3 * EXPERIENCE_CLIENT_REF_LINE_HEIGHT) +  # Client references lines
                    EXPERIENCE_CLIENT_REF_MARGIN_BOTTOM   # Margin bottom
                )

            # Add height for skipped line between experiences
            height += EXPERIENCE_SKIPPED_LINE_HEIGHT

            return height

        elif section_type == "education":
            desc = item.get("description", "")
            lines = desc.split("\n")
            line_count = len(lines) if lines else 1
            return EDUCATION_BASE_HEIGHT + line_count * EDUCATION_LINE_HEIGHT

        return 10  # Default height for other sections

    if request.method == 'POST':
        # Load the last saved JSON data
        json_filepath = os.path.join(app.config['UPLOAD_FOLDER'], 'last_cv.json')
        if not os.path.exists(json_filepath):
            return jsonify({'success': False, 'error': 'No last JSON found.'})

        with open(json_filepath, 'r') as f:
            data = json.load(f)

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
                category = key.replace("skills_", "")
                skill_list = value.split(", ")
                if skill_list and skill_list != [""]:
                    data["skills"][category] = skill_list

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

            # Collect client references for this experience
            client_references = []
            j = 1
            while True:
                first_name = request.form.get(f"client_first_name_{i}_{j}")
                last_name = request.form.get(f"client_last_name_{i}_{j}")
                role = request.form.get(f"client_role_{i}_{j}")
                email = request.form.get(f"client_email_{i}_{j}")
                tel = request.form.get(f"client_tel_{i}_{j}")

                # Break if both first_name and last_name are empty
                if not first_name and not last_name:
                    break

                # Append the client reference
                client_references.append({
                    "first_name": (first_name or "").strip(),
                    "last_name": (last_name or "").strip(),
                    "role": (role or "").strip(),
                    "email": (email or "").strip(),
                    "tel": (tel or "").strip(),
                })

                j += 1

            # Append experience if job title exists
            if job_title:
                experiences.append({
                    "job_title": job_title.strip(),
                    "company": request.form.get(f"company_{i}", "").strip(),
                    "duration": request.form.get(f"duration_{i}", "").strip(),
                    "description": request.form.get(f"description_{i}", "").strip(),
                    "client_references": client_references,  # Add client references
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

        # Save the updated JSON data
        with open(json_filepath, 'w') as f:
            json.dump(data, f, indent=4)
        
        # print("Updated JSON data:", json.dumps(data, indent=4))

        # Pass the hardcoded values to the template
        data["page_height"] = PAGE_HEIGHT_MM
        data["page_width"] = PAGE_WIDTH_MM
        data["page_padding"] = PADDING_MM

        # Build sections in the desired order
        sections = []

        # -- Skills
        if data["skills"]:
            skill_items = []
            for category, skill_list in data["skills"].items():
                skill_items.append({"category": category, "skills": skill_list})
            sections.append({
                "type": "skills",
                "heading": "Technical and Functional Skills.",
                "items": skill_items,
            })

        # -- Education
        if data["education"]:
            sections.append({
                "type": "education",
                "heading": "Education.",
                "items": data["education"],
            })

        # -- Certifications (optional)
        if data["certifications"]:
            sections.append({
                "type": "certifications",
                "heading": "Certifications.",
                "items": data["certifications"],
            })

        # -- Languages
        if data["languages"]:
            lang_items = []
            for lang, level in data["languages"].items():
                lang_items.append({"language": lang, "level": level})
            sections.append({
                "type": "languages",
                "heading": "Languages.",
                "items": lang_items,
            })

        # -- Experiences
        if data["experiences"]:
            sections.append({
                "type": "experiences",
                "heading": "Professional Experiences.",
                "items": data["experiences"],
            })

        # Chunking with bullet point splitting (no repeated headings)
        pages = []
        current_page = []
        current_height = 0

        for section in sections:
            hh = heading_height()  # Height of the section heading
            heading_placed = False  # Flag to track if the heading has been placed

            # If the section is "experiences" and current_height > 0, start a new page
            if section["type"] == "experiences" and current_height > 0:
                pages.append(current_page)
                current_page = []
                current_height = 0

            # Iterate through items in the section
            for single_item in section["items"]:
                # Calculate the height of the current item
                item_h = item_height(section["type"], single_item)

                # Check if the item fits on the current page
                # If the heading hasn't been placed yet, account for its height
                required_height = item_h + (0 if heading_placed else hh)
                if current_height + required_height > CONTENT_HEIGHT_MM:
                    # Save the current page and start a new one
                    pages.append(current_page)
                    current_page = []
                    current_height = 0
                    # Do not reset heading_placed; it remains True for the section

                # If the heading hasn't been placed yet, add it to the current page
                if not heading_placed:
                    new_block = {
                        "type": section["type"],
                        "heading": section["heading"],  # Add the section heading
                        "items": []
                    }
                    current_page.append(new_block)
                    current_height += hh
                    heading_placed = True  # Mark the heading as placed
                else:
                    # If the heading has already been placed, add a new block without a heading
                    # Ensure the block belongs to the same section
                    if not current_page or current_page[-1]["type"] != section["type"]:
                        new_block = {
                            "type": section["type"],
                            "heading": "",  # No repeated heading
                            "items": []
                        }
                        current_page.append(new_block)

                # Add the item to the last block
                current_page[-1]["items"].append(single_item)
                current_height += item_h

        # After processing all sections, save the last page if it has content
        if current_page:
            pages.append(current_page)
        
        data["page_2_content"] = pages
        print("Page 2 Content:", json.dumps(data["page_2_content"], indent=2))
        return render_template('cv_template.html', data=data)

    else:
        # Handle GET requests (e.g., load example data)
        data = {}

        # Pass the hardcoded values to the template
        data["page_height"] = PAGE_HEIGHT_MM
        data["page_width"] = PAGE_WIDTH_MM
        data["page_padding"] = PADDING_MM

        return render_template('cv_template.html', data=data)

@app.route('/reuse_last_json')
def reuse_last_json():
    try:
        # Load the last saved JSON
        json_filepath = os.path.join(app.config['UPLOAD_FOLDER'], 'last_cv.json')
        if not os.path.exists(json_filepath):
            return jsonify({'success': False, 'error': 'No last JSON found.'})

        with open(json_filepath, 'r') as f:
            data = json.load(f)

        # Return the JSON data
        return jsonify({'success': True, 'data': data})
    except Exception as e:
        print(f"Error reusing last JSON: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500  # Return 500 status code for server errors

@app.route('/edit_form')
def edit_form():
    try:
        # Load the last saved JSON
        json_filepath = os.path.join(app.config['UPLOAD_FOLDER'], 'last_cv.json')
        if not os.path.exists(json_filepath):
            return jsonify({'success': False, 'error': 'No last JSON found.'})

        with open(json_filepath, 'r') as f:
            data = json.load(f)

        # Render the edit form with the JSON data
        return render_template('edit_form.html', data=data)
    except Exception as e:
        print(f"Error loading edit form: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)