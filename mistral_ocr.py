from cat.log import log
from typing import List, Union, Dict
from datetime import timedelta
from cat.mad_hatter.decorators import hook
from cat.mad_hatter.decorators import endpoint
from pydantic import BaseModel
from cat.auth.permissions import AuthResource, AuthPermission, check_permissions
import json
import base64
import requests
import os
from mistralai import Mistral


class Tag(BaseModel):
    name: str
    value: str


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
