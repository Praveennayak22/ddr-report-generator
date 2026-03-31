#!/usr/bin/env python3
"""
Enhanced DDR Generator with Image Extraction

Now includes image extraction from PDFs and embeds them in the DDR output.
"""

import os
import json
import sys
import base64
import argparse
from pathlib import Path
from typing import Optional

try:
    import pdfplumber
    import anthropic
except ImportError as e:
    print(f"ERROR: Missing required package: {e}")
    print("Install with: pip install pdfplumber anthropic")
    sys.exit(1)

# Configuration
if os.path.exists("C:\\Users\\prave\\Downloads\\Intern"):
    INPUT_DIR = Path("C:\\Users\\prave\\Downloads\\Intern")
else:
    INPUT_DIR = Path("/c/Users/prave/Downloads/Intern")

SAMPLE_REPORT = INPUT_DIR / "Sample Report.pdf"
THERMAL_IMAGES = INPUT_DIR / "Thermal Images.pdf"
REFERENCE_DDR = INPUT_DIR / "Main DDR.pdf"
OUTPUT_FILE = INPUT_DIR / "Generated_DDR_with_Images.json"

# API Configuration
MODEL = "claude-opus-4-6"
MAX_TOKENS = 16000


def extract_pdf_text(pdf_path: Path, max_chars: Optional[int] = None) -> str:
    """Extract all text from a PDF file."""
    text = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page_num, page in enumerate(pdf.pages, 1):
                page_text = page.extract_text()
                if page_text:
                    header = f"--- Page {page_num} ---\n"
                    text.append(header + page_text)
                    if max_chars and len("\n".join(text)) > max_chars:
                        break
    except Exception as e:
        print(f"  [X] Error extracting text from {pdf_path.name}: {e}")
        return ""

    result = "\n".join(text)
    if max_chars:
        result = result[:max_chars]
    return result


def extract_pdf_images(pdf_path: Path) -> dict:
    """
    Extract images from PDF and encode as base64.

    Returns dict of page_number -> list of images
    """
    images_by_page = {}
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page_num, page in enumerate(pdf.pages, 1):
                page_images = []

                # Extract images from the page
                if hasattr(page, 'images'):
                    for idx, image in enumerate(page.images):
                        try:
                            # Get image bytes and encode to base64
                            img_bytes = image.get("stream").get_rawdata()
                            if img_bytes:
                                b64_image = base64.b64encode(img_bytes).decode("utf-8")
                                page_images.append({
                                    "index": idx,
                                    "data_base64": b64_image,
                                    "size_bytes": len(img_bytes),
                                    "bbox": image.get("x0", 0)  # Position info
                                })
                        except Exception as e:
                            pass  # Skip problematic images

                if page_images:
                    images_by_page[page_num] = page_images
                    print(f"  [OK] Extracted {len(page_images)} image(s) from page {page_num}")
    except Exception as e:
        print(f"  [X] Error extracting images: {e}")

    return images_by_page


def generate_ddr(
    inspection_text: str,
    thermal_text: str,
    reference_format: str,
    client: anthropic.Anthropic
) -> dict:
    """Generate structured DDR from inspection and thermal data."""

    system_prompt = """You are an expert property diagnostician specializing in detailed diagnostic reports (DDR).

Your task: Create a comprehensive DDR by synthesizing inspection and thermal imaging data.

DDR STRUCTURE (7 Required Sections):
1. Property Issue Summary - Concise overview of ALL identified issues
2. Area-wise Observations - Detailed findings organized by building area/room
3. Probable Root Cause - Analysis of underlying causes
4. Severity Assessment - Risk levels and urgency classification
5. Recommended Actions - Specific remediation steps with priority
6. Additional Notes - Context, constraints, or important considerations
7. Missing/Unclear Information - Explicitly state data gaps

CRITICAL REQUIREMENTS:
- ONLY report findings from source documents
- Do NOT fabricate or speculate
- Cross-reference inspection and thermal data
- Use precise technical terminology
- Flag inconsistencies between data sources
- Clearly mark sections with insufficient data"""

    user_message = f"""Generate a complete Detailed Diagnostic Report (DDR) analyzing these sources:

=== INSPECTION REPORT ===
{inspection_text[:2500]}

=== THERMAL IMAGING ===
{thermal_text[:2500]}

=== REFERENCE FORMAT ===
{reference_format[:1500]}

Create the 7-section DDR based ONLY on provided data."""

    print("  Calling Claude API (Opus 4.6)...")

    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        stream=False,
        system=system_prompt,
        messages=[
            {"role": "user", "content": user_message}
        ]
    )

    # Extract response text
    response_text = ""
    for block in response.content:
        if hasattr(block, 'text'):
            response_text += block.text

    # Parse into sections
    ddr = parse_ddr_response(response_text)
    return ddr


def parse_ddr_response(response_text: str) -> dict:
    """Parse Claude response into 7 DDR sections."""

    section_mappings = {
        "1. property issue summary": "Property Issue Summary",
        "2. area-wise observations": "Area-wise Observations",
        "3. probable root cause": "Probable Root Cause",
        "4. severity assessment": "Severity Assessment",
        "5. recommended actions": "Recommended Actions",
        "6. additional notes": "Additional Notes",
        "7. missing/unclear information": "Missing/Unclear Information",
    }

    ddr = {
        "Property Issue Summary": "",
        "Area-wise Observations": "",
        "Probable Root Cause": "",
        "Severity Assessment": "",
        "Recommended Actions": "",
        "Additional Notes": "",
        "Missing/Unclear Information": ""
    }

    current_section = None
    lines = response_text.split("\n")

    for line in lines:
        line_lower = line.lower().strip()

        for key, section_name in section_mappings.items():
            if key in line_lower:
                current_section = section_name
                continue

        if current_section:
            if line.strip():
                ddr[current_section] += line + "\n"

    for section in ddr:
        ddr[section] = ddr[section].strip()

    return ddr


def validate_ddr(ddr: dict) -> tuple[bool, list]:
    """Validate DDR has all required sections."""
    required_sections = [
        "Property Issue Summary",
        "Area-wise Observations",
        "Probable Root Cause",
        "Severity Assessment",
        "Recommended Actions",
        "Additional Notes",
        "Missing/Unclear Information"
    ]

    issues = []
    for section in required_sections:
        if section not in ddr:
            issues.append(f"Missing section: {section}")
        elif not ddr[section].strip():
            issues.append(f"Empty section: {section}")

    return len(issues) == 0, issues


def main():
    """Main execution flow."""

    parser = argparse.ArgumentParser(
        description="Enhanced DDR Generator with Image Extraction"
    )
    parser.add_argument("--api-key", help="Anthropic API key")
    parser.add_argument("--dry-run", action="store_true", help="Show extraction without API call")

    args = parser.parse_args()

    print("\n" + "=" * 70)
    print("[*] Enhanced DDR Generator with Image Extraction")
    print("=" * 70)

    # Get API key
    api_key = args.api_key or os.getenv("ANTHROPIC_API_KEY")
    if not api_key and not args.dry_run:
        print("\n[ERROR] API key not provided")
        sys.exit(1)

    # Step 1: Verify input files
    print("\n[1/6] Verifying input files...")
    files_to_check = [
        (SAMPLE_REPORT, "Sample Report"),
        (THERMAL_IMAGES, "Thermal Images"),
        (REFERENCE_DDR, "Reference DDR")
    ]

    for file_path, file_name in files_to_check:
        if file_path.exists():
            print(f"  [OK] {file_name}: Found")
        else:
            print(f"  [X] {file_name}: NOT FOUND")
            sys.exit(1)

    # Step 2: Extract images from both documents
    print("\n[2/6] Extracting images from PDFs...")
    print("  From Sample Report (Inspection)...")
    inspection_images = extract_pdf_images(SAMPLE_REPORT)

    print("  From Thermal Images...")
    thermal_images_data = extract_pdf_images(THERMAL_IMAGES)

    total_images = len(inspection_images) + len(thermal_images_data)
    print(f"  Total images extracted: {total_images}")

    # Step 3: Extract text
    print("\n[3/6] Extracting text from PDFs...")
    inspection_text = extract_pdf_text(SAMPLE_REPORT, max_chars=5000)
    thermal_text = extract_pdf_text(THERMAL_IMAGES, max_chars=5000)
    reference_format = extract_pdf_text(REFERENCE_DDR, max_chars=3000)
    print(f"  [OK] Text extracted ({len(inspection_text)} + {len(thermal_text)} chars)")

    # Dry run option
    if args.dry_run:
        print("\n[DRY RUN] Skipping API call")
        print(f"  Images found: {total_images}")
        print(f"  Text ready: {len(inspection_text)} chars")
        return

    # Step 4: Generate DDR using Claude
    print("\n[4/6] Generating DDR with Claude API...")
    client = anthropic.Anthropic(api_key=api_key)

    ddr = generate_ddr(
        inspection_text=inspection_text,
        thermal_text=thermal_text,
        reference_format=reference_format,
        client=client
    )
    print("  [OK] DDR generated")

    # Step 5: Validate
    print("\n[5/6] Validating DDR...")
    is_valid, issues = validate_ddr(ddr)
    if is_valid:
        print("  [OK] All sections present")
    else:
        for issue in issues:
            print(f"  [WARN] {issue}")

    # Step 6: Save with images included
    print("\n[6/6] Saving DDR with embedded images...")

    output_data = {
        "metadata": {
            "model": MODEL,
            "inspection_file": SAMPLE_REPORT.name,
            "thermal_file": THERMAL_IMAGES.name,
            "images_extracted": total_images,
            "inspection_images": len(inspection_images),
            "thermal_images": len(thermal_images_data)
        },
        "images": {
            "from_inspection": inspection_images,
            "from_thermal": thermal_images_data
        },
        "ddr": ddr
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)

    print(f"  [OK] Saved to: {OUTPUT_FILE}")

    # Summary
    print("\n" + "=" * 70)
    print("[SUCCESS] DDR Generation with Images Complete")
    print("=" * 70)
    print(f"\nOutput File: {OUTPUT_FILE}")
    print(f"Total Size: {os.path.getsize(OUTPUT_FILE) / 1024:.1f} KB")
    print(f"Images Embedded: {total_images}")
    print(f"  - Inspection: {len(inspection_images)}")
    print(f"  - Thermal: {len(thermal_images_data)}")


if __name__ == "__main__":
    main()
