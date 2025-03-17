from cat.log import log
from typing import List, Union, Dict
from datetime import timedelta
from cat.mad_hatter.decorators import hook
from cat.mad_hatter.decorators import endpoint
from pydantic import BaseModel
import base64
import requests
import os
from mistralai import Mistral


class OCRInput(BaseModel):
    image: str
    type: str


@endpoint.post("/ocr")
def ocr(
    ocr_input: OCRInput,
    cat=check_permissions("CONVERSATION", "WRITE"),
) -> str:

    settings = cat.mad_hatter.get_plugin().load_settings()
    api_key = settings["mistral_api_key"]
    client = Mistral(api_key=api_key)

    ocr_response = client.ocr.process(
        model="mistral-ocr-latest",
        document={
            "type": "image_url",
            "image_url": f"data:{ocr_input.type};base64,{ocr_input.image}",
        },
    )

    debug(f"OCR response: {ocr_response}")

    return ocr_response
