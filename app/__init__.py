from flask import Flask
import os

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'app/uploads'

# Ensure the upload folder exists
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])
    
@app.after_request
def add_security_headers(response):
    response.headers['Permissions-Policy'] = "geolocation=(), microphone=(), camera=()"
    return response

from app import routes
