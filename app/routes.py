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
app.config['UPLOAD_FOLDER'] = 'uploads'
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
    with fitz.open(filepath) as doc:
        for page in doc:
            text += page.get_text()
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
                    Ensure the JSON is valid and properly structured. Do not include any additional text or explanations.
                    Ensure all the information is in english.

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

@app.route('/generate_cv', methods=['POST'])
def generate_cv():
    # Get form data
    data = {
        "name": request.form.get("name"),
        "first_name": request.form.get("first_name"),
        "job_title": request.form.get("job_title"),
        "skills": {},  # Initialize an empty dictionary for skills
        "languages": {
            "French": request.form.get("language_FRENCH", ""),
            "English": request.form.get("language_ENGLISH", ""),
        },
        "experiences": []
    }

    # Dynamically process skills from the form data
    for key, value in request.form.items():
        if key.startswith("skills_"):  # Check if the key is a skill category
            category = key.replace("skills_", "")  # Extract the category name
            skills = value.split(", ")  # Split the skills into a list
            if skills:  # Only add the category if there are skills
                data["skills"][category] = skills

    # Dynamically add experiences
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

    # Render the CV template
    return render_template('cv_template.html', data=data)

if __name__ == '__main__':
    app.run(debug=True)