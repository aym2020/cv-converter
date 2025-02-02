# CV Generator Application

A web-based application for creating, editing, and managing professional CVs with real-time Firestore synchronization and PDF export capabilities.

![CV Generator Screenshot](static/screenshot.png)

## Features

### **Dynamic Form Interface**
- Add/remove multiple sections (experiences, education, certifications, etc.)
- Real-time field validation
- Auto-save to Firebase Firestore

### **Interactive Section Management**
- Drag-free reordering with up/down buttons
- Automatic scroll tracking during reordering
- Dynamic numbering updates

### **Multi-Format Export**
- HTML preview generation
- PDF export with responsive layout
- Print-friendly styling

### **Professional Templates**
- Multiple page designs
- Company branding support
- Responsive CSS layouts

### **Advanced Features**
- Client reference management
- Multi-language support
- Layout configuration panel
- Automatic content pagination

## Technologies Used

- **Backend**: Python + Flask
- **Database**: Firebase Firestore
- **PDF Generation**: html2canvas + jsPDF
- **Frontend**:
  - Modern CSS Grid/Flex layouts
  - Interactive JavaScript
  - Font Awesome icons
  - Google Fonts

## Installation

### **1. Prerequisites**
- Python 3.8+
- Firebase project
- Node.js (for PDF libraries)

### **2. Clone Repository**
```bash
git clone https://github.com/yourusername/cv-generator.git
cd cv-generator
```

### **3. Install Dependencies**
```bash
pip install -r requirements.txt
```

## Configuration

### **Firebase Setup**

#### **1. Create `.env` file:**
```ini
FIREBASE_PROJECT_ID=your-project-id
FIREBASE_API_KEY=your-api-key
FIREBASE_AUTH_DOMAIN=your-project.firebaseapp.com
FIREBASE_STORAGE_BUCKET=your-bucket.appspot.com
```

#### **2. Download service account key as `serviceAccountKey.json`**
- Go to Firebase Console → Project Settings → Service Accounts
- Generate a new private key and save it as `serviceAccountKey.json`
- Place it in the root of the project

#### **3. Set Environment Variables**
```bash
export GOOGLE_APPLICATION_CREDENTIALS="serviceAccountKey.json"
```

## Usage

### **Start Application**
```bash
python app.py
```

### **Access Interfaces**
- **Form Editor**: [http://localhost:5000/edit](http://localhost:5000/edit)
- **CV Preview**: [http://localhost:5000/generate_cv](http://localhost:5000/generate_cv)

### **Key Functions**
- **Section Reordering**: Click ↑/↓ buttons while maintaining visibility
- **PDF Export**: Use the print button (CTRL+P) for PDF conversion
- **Layout Settings**: Adjust spacing parameters via the settings panel (gear icon)

## Development

### **Run in Debug Mode**
```bash
FLASK_DEBUG=1 flask run
```

### **Run Tests**
```bash
python -m pytest tests/
```

### **Build Docker Image**
```bash
docker build -t cv-generator .
```

## Contributing
Pull requests are welcome. For major changes, please open an issue first to discuss what you would like to change.

## License
MIT License - See [LICENSE](LICENSE) for details.

## Acknowledgements
- **Firebase** for database and authentication
- **Flask** for backend API
- **html2canvas & jsPDF** for PDF export
- **Font Awesome & Google Fonts** for UI enhancements

