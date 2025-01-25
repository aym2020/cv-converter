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
PAGE_HEIGHT_MM = 280  # Default height
PAGE_WIDTH_MM = 210   # Default width
PADDING_MM = 30       # Default padding

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

        # Send the extracted text to the OpenAI API
        response = send_to_openai_api(text)
        if response:
            # Save the JSON to a file
            json_filepath = os.path.join(app.config['UPLOAD_FOLDER'], 'last_cv.json')
            with open(json_filepath, 'w') as f:
                json.dump(response, f, indent=4)
            
            # Render the editable form with the API response
            return render_template('edit_form.html', data=response)
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

def send_to_openai_api(text):
    try:
        response = client.chat.completions.create(
            model="gpt-4-1106-preview",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a highly accurate assistant that extracts structured CV data and returns it in a "
                        "fixed JSON format—no extra fields, no missing fields."
                    )
                },
                {
                    "role": "user",
                    "content": f"""
**INSTRUCTIONS:**
Extract the following information from the CV text. **Output must be valid JSON** with **exactly** these top-level fields, in this order (do not add or rename keys):

{{
    "name": "",
    "first_name": "",
    "skills": {{}},
    "languages": {{}},
    "experiences": [],
    "education": [],
    "certifications": []
}}

1. **name**: Last name (string).
2. **first_name**: First name (string).
3. **skills**: An **object** with up to 5 categories (Business Intelligence, Programming, ETL, Cloud, etc.). Keys are category names (capitalized if relevant), each a **list** of skill strings. No blank categories. Example:
   "skills": {{ "Programming": ["Python", "JavaScript"], "Business Intelligence": ["Tableau"] }}
   If no skills, return `"skills": {{}}`.

4. **languages**: An **object** where each key is a Language (capitalized), and value is the proficiency level. Example:
   "languages": {{ "French": "Fluent", "English": "Intermediate" }}
   If none, return `"languages": {{}}`.

5. **experiences**: A **list** of objects, each with:
   - **job_title** (string)
   - **company** (string)
   - **duration** (string, e.g. '11/2023 – 09/2024')
   - **description** (string). Enhance responsibilities, use bullet points (`- `) and line breaks for readability.
   If none, return `"experiences": []`.

6. **education**: A **list** of objects, each with:
   - **degree** (string, capitalized)
   - **institution** (string, empty if unknown)
   - **duration** (string)
   - **description** (string)
   If none, return `"education": []`.

7. **certifications**: A **list** of objects, each with:
   - **name** (string, capitalized)
   - **issuer** (string, empty if unknown)
   If none, return `"certifications": []`.

**Important**:
- Do **not** add extra top-level fields or rename existing fields.
- If a section is not found in the CV, provide an empty object/array for it.
- Return **only** the JSON object, no additional text or explanations.
- All text in **English**.
- Capitalize Language names, Degree names, Name and First Name and Job Title and Certification names.

CV Text:
{text}
"""
                }
            ]
        )
        raw_content = response.choices[0].message.content
        # Clean up the raw JSON content from GPT
        json_str = re.sub(r'^```json\s*', '', raw_content)  # remove ```json
        json_str = re.sub(r'\s*```$', '', json_str)         # remove ending ```
        json_str = json_str.strip()
        # Fix trailing commas in objects/arrays
        json_str = re.sub(r',\s*}', '}', json_str)
        json_str = re.sub(r',\s*]', ']', json_str)

        # Print the JSON in a readable format
        print("Raw JSON from OpenAI API:")
        print(json.dumps(json.loads(json_str), indent=4))  # Pretty-print JSON

        return json.loads(json_str)
    except Exception as e:
        print(f"Error calling OpenAI API: {e}")
        return None

@app.route('/generate_cv', methods=['GET', 'POST'])
def generate_cv():
    global PAGE_HEIGHT_MM, PAGE_WIDTH_MM, PADDING_MM

    if request.method == 'POST':
        data = {
            "first_name": request.form.get("first_name"),
            "name": request.form.get("name"),
            "job_title": request.form.get("job_title"),
            "manager_name": request.form.get("manager_name"),
            "manager_email": request.form.get("manager_email"),
            "skills": {},
            "languages": {},
            "experiences": [],
            "education": [],
            "certifications": [],
        }

        # Dynamically process skills
        for key, value in request.form.items():
            if key.startswith("skills_"):
                # e.g. "skills_Programming" -> "Programming"
                category = key.replace("skills_", "")
                skill_list = value.split(", ")
                # Only add if non-empty
                if skill_list and skill_list != [""]:
                    data["skills"][category] = skill_list

        # Dynamically process languages
        languages = {}
        i = 1
        while True:
            language_name = request.form.get(f"language_{i}")
            proficiency = request.form.get(f"level_{i}")
            if language_name is None:
                # means there's no language_{i} field at all => done
                break
            if not language_name.strip():
                # if the user left the field blank, skip but keep going
                i += 1
                continue

            # we have a real language
            languages[language_name] = proficiency or "Unknown"
            i += 1
            # optional safety check if i is huge
            if i > 50:
                break

        data["languages"] = languages   

        # Experiences
        i = 1
        while True:
            job_title = request.form.get(f"job_title_{i}")
            if not job_title:
                break
            data["experiences"].append({
                "job_title": job_title,
                "company": request.form.get(f"company_{i}", ""),
                "duration": request.form.get(f"duration_{i}", ""),
                "description": request.form.get(f"description_{i}", ""),
            })
            i += 1

        # Education
        j = 1
        while True:
            degree = request.form.get(f"degree_{j}")
            if not degree:
                break
            data["education"].append({
                "degree": degree,
                "institution": request.form.get(f"institution_{j}", ""),
                "duration": request.form.get(f"education_duration_{j}", ""),
                "description": request.form.get(f"education_description_{j}", ""),
            })
            j += 1

        # Certifications
        k = 1
        while True:
            certification_name = request.form.get(f"certification_name_{k}")
            if not certification_name:
                break
            data["certifications"].append({
                "name": certification_name,
                "issuer": request.form.get(f"certification_issuer_{k}", ""),
            })
            k += 1

    else:
        # Example data if GET
        data = {
            "first_name": "Issam",
            "name": "Elafi",
            "job_title": "Support IT & Administratif",
            "manager_name": "John Doe",
            "manager_email": "john.doe@example.com",
            "skills": {
                "Programming": ["Python", "JavaScript", "SQL"],
                "Business Intelligence": ["Tableau", "Power BI"],
            },
            "languages": {
                "French": "Fluent",
                "English": "Intermediate",
            },
            "experiences": [
                {
                    "job_title": "IT Support Specialist",
                    "company": "Company XYZ",
                    "duration": "01/2020 – Present",
                    "description": "Provided technical support\n- Resolved IT issues\n- Assisted in deployments",
                },
            ],
            "education": [
                {
                    "degree": "Bachelor of Science in Computer Science",
                    "institution": "University of Example",
                    "duration": "09/2015 – 06/2019",
                    "description": "Graduated with honors.",
                },
            ],
            "certifications": [
                {
                    "name": "AWS Certified Solutions Architect",
                    "issuer": "Amazon Web Services",
                },
            ],
        }

    # Pass the hardcoded values to the template
    data["page_height"] = PAGE_HEIGHT_MM
    data["page_width"] = PAGE_WIDTH_MM
    data["page_padding"] = PADDING_MM

    # 2) Build sections in the desired order
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

    # 3) heading_height
    def heading_height():
        return 20  # ~10 mm for each section heading

    # 4) item_height (now dynamic based on lines in the description, etc.)
    def item_height(section_type, item):
        if section_type == "skills":
            base_height = 5  # overhead for category line
            skill_count = len(item.get("skills", []))
            return base_height + skill_count * 3  # ~3 mm per skill

        elif section_type == "languages":
            # each item is 1-2 lines at most
            return 8

        elif section_type == "experiences":
            desc = item.get("description", "")
            lines = desc.split("\n")
            line_height = 10  # mm per bullet/line
            base_height = 20  # job title + duration overhead
            line_count = len(lines) if lines else 1
            return base_height + line_count * line_height

        elif section_type == "education":
            desc = item.get("description", "")
            lines = desc.split("\n")
            base_height = 8  # for degree/institution
            line_height = 4
            line_count = len(lines) if lines else 1
            return base_height + line_count * line_height

        return 10

    # 5) Chunking with bullet point splitting (no repeated headings)
    PAGE_HEIGHT_MM = 280
    PADDING_MM = 30
    CONTENT_HEIGHT_MM = PAGE_HEIGHT_MM - 2 * PADDING_MM

    pages = []
    current_page = []
    current_height = 0

    for section in sections:
        hh = heading_height()
        
        if section["type"] == "experiences" and current_height > 0:
            pages.append(current_page)
            current_page = []
            current_height = 0
        
        if current_height + hh > CONTENT_HEIGHT_MM:
            pages.append(current_page)
            current_page = []
            current_height = 0

        # Add the section heading only once
        new_block = {
            "type": section["type"],
            "heading": section["heading"],
            "items": []
        }
        current_page.append(new_block)
        current_height += hh

        for single_item in section["items"]:
            if section["type"] == "experiences":
                desc = single_item.get("description", "")
                lines = desc.split("\n")
                line_height = 12  # mm per bullet/line
                base_height = 30  # job title + duration overhead

                remaining_space = CONTENT_HEIGHT_MM - current_height
                total_height = base_height + len(lines) * line_height

                if total_height <= remaining_space:
                    # Entire item fits on this page
                    current_page[-1]["items"].append(single_item)
                    current_height += total_height

                else:
                    # Not everything fits
                    lines_fit = int((remaining_space - base_height) // line_height)
                    if lines_fit > 0:
                       
                        # Some lines can fit on the current page
                        first_chunk = single_item.copy()
                        # Keep the same title, but only partial lines in description
                        first_chunk["description"] = "\n".join(lines[:lines_fit])

                        current_page[-1]["items"].append(first_chunk)
                        current_height += (base_height + lines_fit * line_height)

                        pages.append(current_page)         # finish this page
                        current_page = []                  # start a new page
                        current_height = 0

                        # leftover lines
                        remaining_lines = lines[lines_fit:]
                        if remaining_lines:
                            # second chunk: only leftover lines, no repeated title
                            second_chunk = single_item.copy()
                            second_chunk["job_title"] = ""
                            second_chunk["company"] = ""
                            second_chunk["duration"] = ""
                            second_chunk["description"] = "\n".join(remaining_lines)

                            new_block = {
                                "type": section["type"],
                                "items": []
                            }
                            current_page.append(new_block)

                            # measure height of leftover chunk
                            leftover_height = len(remaining_lines) * line_height
                            current_page[-1]["items"].append(second_chunk)
                            current_height += leftover_height

                    else:
                        # Nothing fits on this page: move the entire item to the next page
                        pages.append(current_page)
                        current_page = []
                        current_height = 0

                        new_block = {
                            "type": section["type"],
                            "items": []
                        }
                        current_page.append(new_block)

                        # entire item on the new page
                        current_page[-1]["items"].append(single_item)
                        current_height += total_height
            else:
                # Handle other section types as before
                h = item_height(section["type"], single_item)
                if current_height + h > CONTENT_HEIGHT_MM:
                    pages.append(current_page)
                    current_page = []
                    current_height = 0

                    # Add the section heading only once
                    new_block = {
                        "type": section["type"],
                        "heading": section["heading"],
                        "items": []
                    }
                    current_page.append(new_block)
                    current_height += hh

                current_page[-1]["items"].append(single_item)
                current_height += h

    if current_page:
        pages.append(current_page)
    
    data["page_2_content"] = pages
    print("Page 2 Content:", json.dumps(data["page_2_content"], indent=2))
    return render_template('cv_template.html', data=data)


@app.route('/regenerate_cv', methods=['POST'])
def regenerate_cv():
    global PAGE_HEIGHT_MM, PAGE_WIDTH_MM, PADDING_MM

    try:
        # Get the updated values from the request
        PAGE_HEIGHT_MM = int(request.json.get('page_height', 280))
        PAGE_WIDTH_MM = int(request.json.get('page_width', 210))
        PADDING_MM = int(request.json.get('page_padding', 30))

        # Return a success message
        return jsonify({
            'success': True,
            'page_height': PAGE_HEIGHT_MM,
            'page_width': PAGE_WIDTH_MM,
            'page_padding': PADDING_MM,
        })
    except Exception as e:
        print(f"Error regenerating CV: {e}")
        return jsonify({'success': False, 'error': str(e)})

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