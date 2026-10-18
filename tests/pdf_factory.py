"""Generatore di PDF sintetici per i test (reportlab, già in requirements.txt). Solo dati inventati."""

import io
from typing import List, Optional

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas


def make_pdf(pages: List[List[str]], user_password: Optional[str] = None, owner_password: str = "owner") -> bytes:
    """Un PDF con una riga di testo per elemento; ogni sotto-lista è una pagina (lista vuota = pagina bianca)."""
    buf = io.BytesIO()
    kwargs = {}
    if user_password is not None:
        from reportlab.lib.pdfencrypt import StandardEncryption
        kwargs["encrypt"] = StandardEncryption(userPassword=user_password, ownerPassword=owner_password)
    c = canvas.Canvas(buf, pagesize=A4, **kwargs)
    for lines in pages:
        c.setFont("Helvetica", 9)
        y = 800
        for line in lines:
            c.drawString(40, y, line)
            y -= 13
        c.showPage()
    c.save()
    return buf.getvalue()


# IBAN italiano sintetico con checksum mod-97 valido (non appartiene a nessuno)
SAMPLE_IBAN = "IT60X0542811101000000123456"
SAMPLE_IBAN_SPACED = "IT60 X054 2811 1010 0000 0123 456"
