import streamlit as st
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import fitz  # PyMuPDF for PDF parsing
import google.generativeai as genai
import os
import tempfile
import json
from datetime import datetime

# ==== PAGE CONFIG ====
st.set_page_config(
    page_title="AR/VR Surgery Research Extractor",
    page_icon="🏥",
    layout="wide"
)

# ==== TITLE ====
st.title("🏥 AR/VR Surgery Research Extractor")
st.markdown("Upload PDF documents to extract AR/VR surgery information and automatically update your Google Sheet")

# ==== LOAD SECRETS FROM STREAMLIT SECRETS ====
try:
    # Load from Streamlit secrets
    GEMINI_API_KEY = st.secrets["gemini"]["api_key"]
    SERVICE_ACCOUNT_DATA = dict(st.secrets["gcp_service_account"])
except Exception as e:
    st.error(f"⚠️ Error loading secrets: {str(e)}")
    st.error("Please ensure .streamlit/secrets.toml is properly configured")
    st.stop()

# ==== SIDEBAR CONFIG ====
st.sidebar.header("⚙️ Configuration")

# Google Sheets Config
st.sidebar.subheader("Google Sheets Setup")
spreadsheet_name = st.sidebar.text_input(
    "Spreadsheet Name",
    value="VR-FOR-SURGERIES",
    help="Name of your Google Spreadsheet"
)

document_base_link = st.sidebar.text_input(
    "Document Base Link (Optional)",
    placeholder="https://docs.google.com/spreadsheets/d/...",
    help="Base link for your Google Sheets document"
)

# Set default values
gemini_api_key = GEMINI_API_KEY
service_account_data = SERVICE_ACCOUNT_DATA

# ==== MAIN FUNCTIONS ====
@st.cache_data
def read_pdf_text(pdf_bytes):
    """Extract text from PDF bytes"""
    try:
        # Create temporary file
        with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp_file:
            tmp_file.write(pdf_bytes)
            tmp_path = tmp_file.name
        
        # Read PDF
        doc = fitz.open(tmp_path)
        text = "\n".join([page.get_text() for page in doc])
        doc.close()
        
        # Clean up
        os.unlink(tmp_path)
        
        return text
    except Exception as e:
        st.error(f"Error reading PDF: {str(e)}")
        return None

def extract_info_with_gemini(text, api_key):
    """Extract information using Gemini AI"""
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("models/gemini-1.5-flash")
        
        prompt = f"""
You are an AI assistant helping a team building an AR/VR solution for performing surgeries.

From the document below, extract and summarize:

1. **Existing AR/VR Solutions in Surgery** – Any tools, systems, or research already using AR/VR for surgical training, planning, or execution.

2. **Problems to be Solved** – Gaps, limitations, or open challenges in the field that need to be addressed.

3. **Proposed Problem Statement** – Based on these gaps, suggest a clear and concise problem statement that an AR/VR-based surgical solution could address.

Format exactly like this:

Existing AR/VR Solutions:
- ...

Problems to be Solved:
- ...

Proposed Problem Statement:
...

TEXT:
{text[:30000]}
"""
        
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        st.error(f"Error with Gemini AI: {str(e)}")
        return None

def parse_response(response_text):
    """Parse AI response into structured data"""
    info = {"solutions": "", "to_solve": "", "pps": ""}
    current_key = None
    
    for line in response_text.split('\n'):
        if "Existing AR/VR Solutions" in line:
            current_key = "solutions"
        elif "Problems to be Solved" in line:
            current_key = "to_solve"
        elif "Proposed Problem Statement" in line:
            current_key = "pps"
        elif current_key:
            if current_key == "pps":
                info["pps"] += line.strip() + " "
            elif line.strip().startswith("-"):
                info[current_key] += line.strip() + "\n"
    
    return info

def setup_google_sheets(service_account_data, spreadsheet_name):
    """Setup Google Sheets connection"""
    try:
        # Setup Google Sheets using direct credentials
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_dict(service_account_data, scope)
        client = gspread.authorize(creds)
        sheet = client.open(spreadsheet_name).sheet1
        
        return sheet
    except Exception as e:
        st.error(f"Error setting up Google Sheets: {str(e)}")
        return None

def update_sheet(sheet, info, pdf_name, document_link=""):
    """Update Google Sheet with extracted information"""
    try:
        # Add timestamp
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        sheet.append_row([
            pdf_name,
            document_link,
            info["pps"].strip(),         # Proposed Problem Statement
            info["solutions"].strip(),   # Existing AR/VR Solutions
            info["to_solve"].strip(),    # Problems to be Solved
            timestamp                    # Timestamp
        ])
        return True
    except Exception as e:
        st.error(f"Error updating sheet: {str(e)}")
        return False

# ==== MAIN APP ====
def main():
    # PDF Upload Section
    st.header("📄 Upload PDF Document")
    uploaded_file = st.file_uploader(
        "Choose a PDF file",
        type=['pdf'],
        help="Upload a PDF document containing AR/VR surgery research"
    )
    
    if uploaded_file is not None:
        # Display file info
        st.success(f"✅ File uploaded: {uploaded_file.name}")
        pdf_name = os.path.splitext(uploaded_file.name)[0]
        
        # Process button
        if st.button("🚀 Process Document", type="primary"):
            try:
                # Progress bar
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                # Step 1: Read PDF
                status_text.text("📖 Reading PDF content...")
                progress_bar.progress(20)
                
                pdf_text = read_pdf_text(uploaded_file.read())
                if not pdf_text:
                    st.error("Failed to extract text from PDF")
                    return
                
                # Step 2: Extract info with AI
                status_text.text("🤖 Extracting information with AI...")
                progress_bar.progress(40)
                
                ai_response = extract_info_with_gemini(pdf_text, gemini_api_key)
                if not ai_response:
                    st.error("Failed to extract information with AI")
                    return
                
                # Step 3: Parse response
                status_text.text("📝 Parsing AI response...")
                progress_bar.progress(60)
                
                info_data = parse_response(ai_response)
                
                # Step 4: Setup Google Sheets
                status_text.text("📊 Setting up Google Sheets...")
                progress_bar.progress(80)
                
                sheet = setup_google_sheets(service_account_data, spreadsheet_name)
                if not sheet:
                    st.error("Failed to setup Google Sheets connection")
                    return
                
                # Step 5: Update sheet
                status_text.text("✅ Updating Google Sheet...")
                progress_bar.progress(100)
                
                success = update_sheet(sheet, info_data, pdf_name, document_base_link)
                
                if success:
                    status_text.text("🎉 Process completed successfully!")
                    st.balloons()
                    
                    # Display extracted information
                    st.header("📋 Extracted Information")
                    
                    col1, col2 = st.columns(2)
                    
                    with col1:
                        st.subheader("🔧 Existing AR/VR Solutions")
                        st.text_area("", info_data["solutions"], height=200, disabled=True)
                        
                        st.subheader("❓ Problems to be Solved")
                        st.text_area("", info_data["to_solve"], height=200, disabled=True)
                    
                    with col2:
                        st.subheader("💡 Proposed Problem Statement")
                        st.text_area("", info_data["pps"], height=200, disabled=True)
                        
                        st.subheader("📄 Document Info")
                        st.info(f"**File Name:** {pdf_name}")
                        if document_base_link:
                            st.info(f"**Document Link:** {document_base_link}")
                        st.info(f"**Processed:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                    
                else:
                    status_text.text("❌ Failed to update Google Sheet")
                    
            except Exception as e:
                st.error(f"An error occurred: {str(e)}")
                progress_bar.empty()
                status_text.empty()

# ==== SIDEBAR INFO ====
st.sidebar.markdown("---")
st.sidebar.subheader("ℹ️ How to Use")
st.sidebar.markdown("""
1. **Set Spreadsheet**: Enter your Google Spreadsheet name
2. **Upload PDF**: Choose a PDF document to process
3. **Process**: Click the process button to extract and update

**Note**: Make sure your Google Sheet has the following columns:
- Document Name
- Document Link
- Proposed Problem Statement
- Existing AR/VR Solutions
- Problems to be Solved
- Timestamp

**Security**: Credentials loaded securely from Streamlit secrets.
""")

st.sidebar.markdown("---")

# Display connection status
st.sidebar.markdown("---")
st.sidebar.subheader("🔗 Connection Status") 
if 'GEMINI_API_KEY' in locals() and 'SERVICE_ACCOUNT_DATA' in locals():
    st.sidebar.success("✅ Credentials loaded successfully")
else:
    st.sidebar.error("❌ Error loading credentials")

if __name__ == "__main__":
    main()