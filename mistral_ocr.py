from cat.log import log
from typing import List, Union, Dict
from datetime import timedelta
from cat.mad_hatter.decorators import hook
from cat.mad_hatter.decorators import endpoint
from pydantic import BaseModel
from fastapi import UploadFile, File, Form
from cat.auth.permissions import AuthResource, AuthPermission, check_permissions
import json
import base64
import requests
import os
import tempfile

# from mistralai import Mistral


class Tag(BaseModel):
    name: str
    value: Union[str, List[str]]


class OCRInput(BaseModel):
    image: str
    type: str
    tags: List[Tag]


class OCRPDFInput(BaseModel):
    pdf: str
    filename: str
    tags: List[Tag]


@endpoint.post("/ocr")
def ocr(
    ocr_input: OCRInput,
    cat=check_permissions("CONVERSATION", "WRITE"),
) -> str:

    settings = cat.mad_hatter.get_plugin().load_settings()
    api_key = settings["mistral_api_key"]
    save_rh = settings["save_text_to_rabbit_hole"]

    api_url = "https://api.mistral.ai/v1/ocr"  # Replace with the actual OCR endpoint

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    data = {
        "model": "mistral-ocr-latest",
        "document": {
            "type": "image_url",
            "image_url": f"data:{ocr_input.type};base64,{ocr_input.image}",
        },
    }

    try:
        response = requests.post(api_url, headers=headers, json=data)
        response.raise_for_status()  # Raise HTTPError for bad responses (4xx or 5xx)
        ocr_response = response.json()

        log.debug(f"OCR response: {ocr_response}")

        if save_rh:
            if cat is None:
                raise ValueError("`cat` must be provided if `save_rh` is True.")

            for page in ocr_response.get(
                "pages", []
            ):  # Added .get to handle case where pages doesn't exist
                # Nome del file di output
                output_file = "ocrpage.md"
                markdown_content = page.get("markdown", "")  # Access markdown safely
                with open(output_file, "w", encoding="utf-8") as f:
                    f.write(markdown_content)

                metadata = {item.name: item.value for item in ocr_input.tags}
                cat.rabbit_hole.ingest_file(cat, output_file, 400, 100, metadata)
                os.remove(output_file)

        return ocr_response

    except requests.exceptions.RequestException as e:
        log.debug(f"Error during OCR request: {e}")
        return None
    except json.JSONDecodeError as e:
        log.debug(
            f"Error decoding JSON response: {e}. Response text: {response.text if 'response' in locals() else 'No response'}"
        )
        return None
    except Exception as e:
        log.debug(f"An unexpected error occurred: {e}")
        return None


@endpoint.post("/ocr-pdf")
async def ocr_pdf(
    ocr_input: OCRPDFInput,
    cat=check_permissions("CONVERSATION", "WRITE"),
) -> str:

    original_filename = ocr_input.filename
    settings = cat.mad_hatter.get_plugin().load_settings()
    api_key = settings["mistral_api_key"]
    save_rh = settings["save_text_to_rabbit_hole"]

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_pdf:
        temp_pdf_path = temp_pdf.name
        content = base64.b64decode(ocr_input.pdf)
        temp_pdf.write(content)
    try:
        document_url = upload_pdf(api_key, temp_pdf_path)
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": "mistral-ocr-latest",
            "document": {"type": "document_url", "document_url": document_url},
            "include_image_base64": True,
        }
        response = requests.post(
            "https://api.mistral.ai/v1/ocr", headers=headers, json=payload
        )
        response.raise_for_status()
        ocr_response = response.json()
        log.debug(f"OCR PDF response: {ocr_response}")

        if save_rh:
            for i, page in enumerate(ocr_response.get("pages", [])):
                output_file = f"{original_filename}_{i}.md"
                with open(output_file, "w", encoding="utf-8") as f:
                    f.write(page.get("markdown", ""))

                metadata = {item.name: item.value for item in ocr_input.tags}
                cat.rabbit_hole.ingest_file(cat, output_file, 512, 128, metadata)
                os.remove(output_file)
        return ocr_response
    finally:
        if os.path.exists(temp_pdf_path):
            os.remove(temp_pdf_path)


def upload_pdf(api_key, filename):
    files = {"file": open(filename, "rb")}
    data = {"purpose": "ocr"}
    headers = {"Authorization": f"Bearer {api_key}"}
    response = requests.post(
        "https://api.mistral.ai/v1/files", headers=headers, files=files, data=data
    )
    response.raise_for_status()
    uploaded = response.json()
    file_id = uploaded["id"]

    # Richiedi l'URL firmato
    response = requests.get(
        f"https://api.mistral.ai/v1/files/{file_id}/url?expiry=24", headers=headers
    )
    response.raise_for_status()
    return response.json()["url"]
