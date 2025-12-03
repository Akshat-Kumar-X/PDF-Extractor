import streamlit as st
import pdfplumber
import re
import io
import csv
import pandas as pd
from typing import Optional, List

# ---------------------- Helpers ----------------------

PAN_REGEX = re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b")
AADHAAR_REGEX = re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b")
EMAIL_REGEX = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
PHONE_REGEX = re.compile(r"(\+91[-\s]?)?[6-9]\d{9}")
IFSC_REGEX = re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b")
ACCOUNT_REGEX = re.compile(r"\b\d{9,18}\b")

def extract_text_from_pdf_bytes(file_bytes: bytes) -> str:
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        pages_text = [page.extract_text() or "" for page in pdf.pages]
    return "\n".join(pages_text)

def extract_fields_rule_based(text: str, source_file_name: str) -> dict:
    norm = text.replace("\r", "\n")
    lines = [ln.strip() for ln in norm.splitlines() if ln.strip()]

    # -------- Email --------
    email = None
    m = EMAIL_REGEX.search(norm)
    if m:
        email = m.group(0)

    # -------- Primary phone --------
    phone = None
    m = PHONE_REGEX.search(norm)
    if m:
        phone = re.sub(r"\D", "", m.group(0))[-10:]

    # -------- PAN --------
    pan = None
    m = PAN_REGEX.search(norm)
    if m:
        pan = m.group(0)

    # -------- Aadhaar --------
    aadhaar = None
    m = AADHAAR_REGEX.search(norm)
    if m:
        aadhaar = m.group(0)

    # -------- IFSC --------
    ifsc = None
    m = IFSC_REGEX.search(norm)
    if m:
        ifsc = m.group(0)

    # -------- Bank account (raw) --------
    bank_account = None
    aadhaar_digits = re.sub(r"\D", "", aadhaar) if aadhaar else ""
    for m in ACCOUNT_REGEX.finditer(norm):
        digits = m.group(0)
        # skip Aadhaar-like 12-digit number
        if digits == aadhaar_digits and len(digits) == 12:
            continue
        bank_account = digits
        break

    # -------- Emergency contact --------
    emergency_name = None
    emergency_phone = None
    # Strategy:
    #   If there is an "Emergency Contact" block, scan its lines
    ec_start = -1
    for idx, ln in enumerate(lines):
        if "emergency" in ln.lower():
            ec_start = idx
            break

    if ec_start != -1:
        # Look in following few lines for name and phone
        block = lines[ec_start: ec_start + 5]
        # phone
        for ln in block:
            pm = PHONE_REGEX.search(ln)
            if pm:
                emergency_phone = re.sub(r"\D", "", pm.group(0))[-10:]
                break
        # name: line containing "Name" inside emergency block, else next line
        for ln in block:
            if "name" in ln.lower():
                parts = ln.split(":")
                if len(parts) > 1:
                    emergency_name = parts[1].strip()
                else:
                    emergency_name = ln.strip()
                break

    # -------- Candidate name --------
    name = None
    for ln in lines:
        low = ln.lower()
        if "name" in low and "father" not in low and "emergency" not in low:
            parts = ln.split(":")
            if len(parts) > 1:
                name = parts[1].strip()
            else:
                name = ln.strip()
            break

    # -------- Multi-line address --------
    address = None
    addr_start = -1
    for idx, ln in enumerate(lines):
        if "address" in ln.lower():
            addr_start = idx
            break

    if addr_start != -1:
        addr_lines = []
        # If line has text after "Address:", capture that too
        first_line = lines[addr_start]
        parts = first_line.split(":", 1)
        if len(parts) > 1 and parts[1].strip():
            addr_lines.append(parts[1].strip())

        # then take following lines until we hit a new section header
        for ln in lines[addr_start + 1:]:
            low = ln.lower()
            # stop if we hit another section
            if any(
                key in low
                for key in [
                    "bank details",
                    "bank account",
                    "ifsc",
                    "emergency contact",
                    "pan number",
                    "aadhaar number",
                    "candidate information",
                ]
            ):
                break
            addr_lines.append(ln.strip())

        if addr_lines:
            address = ", ".join(addr_lines)

    return {
        "name": name,
        "email": email,
        "phone": phone,
        "pan": pan,
        "aadhaar": aadhaar,
        "address": address,
        "bank_account": bank_account,
        "ifsc": ifsc,
        "emergency_contact_name": emergency_name,
        "emergency_contact_phone": emergency_phone,
        "source_file_name": source_file_name,
    }

# ---------------------- Streamlit UI ----------------------

st.set_page_config(
    page_title="PDF to Excel",
    page_icon="🫧",
    layout="wide",
)

st.markdown(
    """
    <h1 style="
        font-size: 3rem;
        font-weight: 800;
        background: linear-gradient(90deg, #007BFF, #00A8FF, #4F46E5);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 0.2rem;
    ">
        Convert PDF to EXCEL
    </h1>
    <p style="color:#5f6b81; font-size:1.1rem; margin-top:-10px;">
        Upload one or more HR candidate PDFs → Extract clean Excel-ready data with full raw fields (no masking).
    </p>
    """,
    unsafe_allow_html=True,
)

st.markdown("---")

upload_col, help_col = st.columns([2, 1])

with upload_col:
    st.subheader("Step 1 - Upload PDFs")
    uploaded_files = st.file_uploader(
        "Drag & drop PDFs here, or click to browse",
        type=["pdf"],
        accept_multiple_files=True,
        help="You can select multiple PDFs at once.",
    )

with help_col:
    st.subheader("What will be extracted")
    st.markdown(
        "- Name and full address\n"
        "- Email and phone number\n"
        "- PAN & Aadhaar\n"
        "- Bank account (raw) and IFSC\n"
    )

# Gradient button style
st.markdown("""
<style>
div.stButton > button:first-child {
    background: linear-gradient(90deg, #007BFF, #00A8FF, #4F46E5) !important;
    color: white !important;
    border: none !important;
    padding: 0.6rem 1.2rem !important;
    font-weight: 600 !important;
    border-radius: 8px !important;
    transition: 0.2s ease-in-out;
}
div.stButton > button:first-child:hover {
    opacity: 0.9;
    transform: scale(1.02);
}
</style>
""", unsafe_allow_html=True)

st.markdown("---")
st.subheader("Step 2 - Extract and preview")
extract_button = st.button("Run extraction", type="primary", use_container_width=True)

results: List[dict] = []

if extract_button:
    if not uploaded_files:
        st.warning("Please upload at least one PDF first.")
    else:
        with st.spinner("Extracting data from PDFs..."):
            for f in uploaded_files:
                file_bytes = f.read()
                text = extract_text_from_pdf_bytes(file_bytes)
                row = extract_fields_rule_based(text, f.name)
                results.append(row)

        if results:
            df = pd.DataFrame(results, columns=[
                "name",
                "email",
                "phone",
                "pan",
                "aadhaar",
                "address",
                "bank_account",
                "ifsc",
                "emergency_contact_name",
                "emergency_contact_phone",
                "source_file_name",
            ])

            st.success(f"Extracted {len(df)} candidate(s). Preview below:")
            st.dataframe(df, use_container_width=True, height=300)
