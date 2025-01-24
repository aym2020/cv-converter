from flask import render_template, request, redirect, Flask, url_for
import fitz  # PyMuPDF
import os
import json
from openai import OpenAI
from dotenv import load_dotenv
import re
from app import app

# Load environment variables
load_dotenv()

# Initialize OpenAI client
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY)

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
        # Call the OpenAI API
        response = client.chat.completions.create(
            model="gpt-4-1106-preview",
            messages=[
                {"role": "system", "content": "You are a helpful assistant that extracts structured data from CVs and returns it in valid JSON format."},
                {"role": "user", "content": f"""
                    Extract the following information from this CV text and return it in valid JSON format:
                    - name: Last name of the candidate.
                    - first_name: First name of the candidate.
                    - skills: A dictionary with up to 5 categories of skills. Each category should contain a list of skills. Ensure the categories are relevant (e.g., Programming, Business Intelligence, IDEs, etc.) and do not include any blank categories.
                    - languages: A dictionary where keys are languages and values are proficiency levels (e.g., 'Fluent', 'Intermediate', 'Basic').
                    - experiences: A list of professional experiences. Each experience should include:
                        - job_title: Job title.
                        - company: Company name.
                        - duration: Start and end dates (e.g., '11/2023 – 09/2024').
                        - description: Description of responsibilities. Enhance the description to make it more interesting and relevant.
                    - education: A list of education entries. Each entry should include:
                        - degree: The degree obtained (e.g., Bachelor of Science, Master of Arts).
                        - institution: The name of the educational institution. If the institution is not known, let it blank.
                        - duration: Start and end dates (e.g., '09/2015 – 06/2019').
                    Ensure the JSON is valid and properly structured. Do not include any additional text or explanations.
                    Ensure all the information is in English.
                    Language, Name and Degree must be capitalized (e.g. French, English, etc.)
                    
                    CV Text:
                    {text}
                """}
            ]
        )

        # Extract the response content
        result = response.choices[0].message.content
        print("Raw API Response:", result)  # Debugging: Print the raw response

        # Clean the response (remove triple backticks and non-JSON text)
        result = re.sub(r'^```json\s*', '', result)  # Remove ```json at the start
        result = re.sub(r'\s*```$', '', result)  # Remove ``` at the end
        result = result.strip()  # Remove any leading/trailing whitespace

        # Remove trailing commas in JSON
        result = re.sub(r',\s*}', '}', result)  # Fix trailing commas in objects
        result = re.sub(r',\s*]', ']', result)  # Fix trailing commas in arrays

        # Parse the JSON string and return as a dictionary
        return json.loads(result)
    except Exception as e:
        print(f"Error calling OpenAI API: {e}")
        return None


@app.route('/generate_cv', methods=['GET', 'POST'])
def generate_cv():
    """
    This version does item-by-item chunking so that if there's space left on the page,
    the next items in the same section can appear there, rather than forcing the entire block
    to a new page.
    """
    # 1) Collect or load CV data
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
        }

        # Dynamically process skills
        for key, value in request.form.items():
            if key.startswith("skills_"):
                category = key.replace("skills_", "")
                skills_list = value.split(", ")
                if skills_list:
                    data["skills"][category] = skills_list

        # Dynamically process languages
        for key, value in request.form.items():
            if key.startswith("language_"):
                language = key.replace("language_", "")
                data["languages"][language] = value

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
                    "description": "Provided technical support and resolved IT issues.",
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
        }

    # 2) Build sections
    sections = []
    # -- Skills
    if data["skills"]:
        skill_items = []
        for category, skill_list in data["skills"].items():
            skill_items.append({"category": category, "skills": skill_list})
        sections.append({
            "type": "skills",
            "heading": "Technical and Functional Skills",
            "items": skill_items,
        })

    # -- Languages
    if data["languages"]:
        lang_items = []
        for lang, level in data["languages"].items():
            lang_items.append({"language": lang, "level": level})
        sections.append({
            "type": "languages",
            "heading": "Languages",
            "items": lang_items,
        })

    # -- Experiences
    if data["experiences"]:
        sections.append({
            "type": "experiences",
            "heading": "Professional Experiences",
            "items": data["experiences"],
        })

    # -- Education
    if data["education"]:
        sections.append({
            "type": "education",
            "heading": "Education",
            "items": data["education"],
        })

    # 3) Approximate item heights
    #    Each item in a block might have a different height. We define a small function:
    def heading_height(): 
        return 10  # mm

    def item_height(section_type):
        """
        Return the approximate height for a single item in the section.
        Adjust these values as needed for your layout.
        """
        if section_type == "skills":
            return 12   # Each skill category is small
        elif section_type == "languages":
            return 10   # A single line per language
        elif section_type == "experiences":
            return 35  # Could be multiple lines describing the job
        elif section_type == "education":
            return 30  # Enough space for degree, institution, dates
        return 10

    # 4) Item-by-item chunking
    PAGE_HEIGHT_MM = 297
    PADDING_MM = 20
    CONTENT_HEIGHT_MM = PAGE_HEIGHT_MM - 2 * PADDING_MM

    pages = []              # pages -> list of pages
    current_page = []       # each page -> list of blocks
    current_height = 0.0

    for section in sections:
        # 4a) Try to place the heading
        sec_heading_height = heading_height()
        # If heading won't fit, start a new page
        if current_height + sec_heading_height > CONTENT_HEIGHT_MM:
            pages.append(current_page)
            current_page = []
            current_height = 0

        # Create a new block with an empty items array
        # We'll fill items as they fit
        new_block = {
            "type": section["type"],
            "heading": section["heading"],
            "items": []
        }
        current_page.append(new_block)
        current_height += sec_heading_height  # used some vertical space for heading

        # 4b) chunk each item within the section
        for single_item in section["items"]:
            h = item_height(section["type"])
            if current_height + h > CONTENT_HEIGHT_MM:
                # new page
                pages.append(current_page)
                current_page = []
                current_height = 0

                # Add heading again (with "continued" if you like)
                new_block = {
                    "type": section["type"],
                    "items": []
                }
                current_page.append(new_block)
                current_height += sec_heading_height

            # Now add this item
            current_page[-1]["items"].append(single_item)
            current_height += h

    # Finish up
    if current_page:
        pages.append(current_page)

    # 5) Attach to data
    data["page_2_content"] = pages

    # Debug
    print("Page 2 Content:", json.dumps(data["page_2_content"], indent=2))

    # 6) Render
    return render_template('cv_template.html', data=data)

if __name__ == '__main__':
    app.run(debug=True)