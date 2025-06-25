from cat.log import log
from typing import List, Union, Dict
from datetime import timedelta
from cat.mad_hatter.decorators import hook
from cat.mad_hatter.decorators import endpoint
from pydantic import BaseModel
from fastapi import UploadFile, File
from cat.auth.permissions import AuthResource, AuthPermission, check_permissions
import json
import base64
import requests
import os
import tempfile
from mistralai import Mistral


class Tag(BaseModel):
    name: str
    value: List[str]


class OCRInput(BaseModel):
    image: str
    type: str
    tags: List[Tag]


@endpoint.post("/ocr")
def ocr(
    ocr_input: OCRInput,
    cat=check_permissions("CONVERSATION", "WRITE"),
) -> str:

    settings = cat.mad_hatter.get_plugin().load_settings()
    api_key = settings["mistral_api_key"]
    save_rh = settings["save_text_to_rabbit_hole"]
    client = Mistral(api_key=api_key)

    ocr_response = client.ocr.process(
        model="mistral-ocr-latest",
        document={
            "type": "image_url",
            "image_url": f"data:{ocr_input.type};base64,{ocr_input.image}",
        },
    )

    log.debug(f"OCR response: {ocr_response}")

    if save_rh:
        for page in ocr_response.pages:
            # Nome del file di output
            output_file = "ocrpage.md"
            with open(output_file, "w", encoding="utf-8") as f:
                f.write(page.markdown)
            metadata = {item.name: item.value for item in ocr_input.tags}
            cat.rabbit_hole.ingest_file(cat, output_file, 400, 100, metadata)
            os.remove(output_file)
    return ocr_response


@endpoint.post("/ocr-pdf")
async def ocr_pdf(
    file: UploadFile = File(...),
    tags: List[Tag] = [],
    cat=check_permissions("CONVERSATION", "WRITE"),
) -> str:

    original_filename = file.filename
    settings = cat.mad_hatter.get_plugin().load_settings()
    api_key = settings["mistral_api_key"]
    save_rh = settings["save_text_to_rabbit_hole"]
    client = Mistral(api_key=api_key)

    # Salviamo il file PDF temporaneamente
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_pdf:
        temp_pdf_path = temp_pdf.name
        # Leggiamo il file caricato in blocchi per gestire file di grandi dimensioni
        content = await file.read()
        temp_pdf.write(content)

    try:
        # Processare il PDF con Mistral OCR
        ocr_response = client.ocr.process(
            model="mistral-ocr-latest",
            document={
                "type": "document_url",
                "document_url": upload_pdf(temp_pdf_path),
            },
            include_image_base64=True,
        )

        log.debug(f"OCR PDF response: {ocr_response}")

        if save_rh:
            for i, page in enumerate(ocr_response.pages):
                # Nome del file di output
                output_file = f"{original_filename}_{i}.md"
                with open(output_file, "w", encoding="utf-8") as f:
                    f.write(page.markdown)
                metadata = {item.name: item.value for item in tags}
                cat.rabbit_hole.ingest_file(cat, output_file, 512, 128, metadata)
                os.remove(output_file)

        return ocr_response

    finally:
        # Pulizia: rimuovere il file temporaneo
        if os.path.exists(temp_pdf_path):
            os.remove(temp_pdf_path)


def upload_pdf(client, filename):
    uploaded_pdf = client.files.upload(
        file={
            "file_name": filename,
            "content": open(filename, "rb"),
        },
        purpose="ocr",
    )
    signed_url = client.files.get_signed_url(file_id=uploaded_pdf.id)
    return signed_url.url
