import io
import re
import base64
from typing import List, Dict, Any, Optional

from fastapi import FastAPI, UploadFile, File, HTTPException, Query
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pdfminer.high_level import extract_text
from pypdf import PdfReader, PdfWriter

app = FastAPI(title="PDF to JSON API", version="1.3")

# CORS (ajuste os domínios em produção)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],           # ex.: ["http://localhost:5173", "http://127.0.0.1:5173"]
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Regex compatíveis com holerite (ajuste conforme seu layout)
cpf_re = re.compile(r"CPF:\s*([\d.\-]+)", re.I)
nome_re = re.compile(r"Nome do (?:Colaborador|Funcion[aá]rio)\s*\n?([^\n\r]+)", re.I)
liq_re = re.compile(r"SAL[ÁA]RIO L[ÍI]QUIDO\s*R\$\s*([\d.\,]+)", re.I)

def to_number_br(s: Optional[str]):
    if not s:
        return None
    s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except Exception:
        return None

def extract_fields_from_text(text: str) -> Dict[str, Any]:
    nome = (nome_re.search(text).group(1).strip()) if nome_re.search(text) else ""
    cpf = (cpf_re.search(text).group(1).strip()) if cpf_re.search(text) else ""
    liq = (liq_re.search(text).group(1).strip()) if liq_re.search(text) else ""
    valor_liquido = to_number_br(liq)
    return {"nome": nome, "cpf": cpf, "valor_liquido": valor_liquido}

def page_to_pdf_bytes(pdf_bytes: bytes, page_index: int) -> bytes:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    if page_index < 0 or page_index >= len(reader.pages):
        raise IndexError("Página inválida")
    writer = PdfWriter()
    writer.add_page(reader.pages[page_index])
    out = io.BytesIO()
    writer.write(out)
    writer.close()
    return out.getvalue()

def _is_pdf_content_type(ct: Optional[str]) -> bool:
    if not ct:
        return True  # alguns browsers mandam vazio; vamos aceitar
    ct = ct.lower()
    return ct in ("application/pdf", "application/octet-stream")

@app.get("/health")
def health():
    return {"ok": True}

@app.post("/extract")
async def extract(file: UploadFile = File(...)):
    """
    Retorna JSON com um item por página:
    [
      {
        "page": 1,
        "nome": "...",
        "cpf": "...",
        "valor_liquido": 2987.32,
        "page_pdf_base64": "<binário da página (PDF 1 página) em Base64>"
      },
      ...
    ]
    """
    if not _is_pdf_content_type(file.content_type):
        raise HTTPException(status_code=400, detail="Envie um PDF.")

    data = await file.read()
    try:
        reader = PdfReader(io.BytesIO(data))
    except Exception:
        raise HTTPException(status_code=400, detail="PDF inválido.")

    results: List[Dict[str, Any]] = []
    num_pages = len(reader.pages)

    for i in range(num_pages):
        # Texto apenas da página i
        try:
            page_text = extract_text(io.BytesIO(data), page_numbers=[i]) or ""
        except Exception:
            page_text = ""

        fields = extract_fields_from_text(page_text)

        # Binário exato da página i (PDF de 1 página)
        try:
            page_pdf = page_to_pdf_bytes(data, i)
            page_pdf_b64 = base64.b64encode(page_pdf).decode("utf-8")
        except Exception:
            page_pdf_b64 = ""

        results.append({
            "page": i + 1,
            **fields,
            "page_pdf_base64": page_pdf_b64
        })

    if all((not r["nome"] and not r["cpf"] and r["valor_liquido"] is None) for r in results):
        raise HTTPException(status_code=422, detail="Não foi possível extrair os campos.")

    return JSONResponse(results)

@app.post("/extract/page")
async def extract_single_page(
    index: int = Query(..., ge=1, description="Número da página (1-based)"),
    file: UploadFile = File(...)
):
    """
    Retorna o binário (application/pdf) contendo apenas a página solicitada.
    """
    if not _is_pdf_content_type(file.content_type):
        raise HTTPException(status_code=400, detail="Envie um PDF.")

    data = await file.read()
    try:
        page_pdf = page_to_pdf_bytes(data, index - 1)
    except IndexError:
        raise HTTPException(status_code=404, detail="Página não encontrada.")
    except Exception:
        raise HTTPException(status_code=400, detail="Falha ao processar PDF.")

    return StreamingResponse(io.BytesIO(page_pdf), media_type="application/pdf")
