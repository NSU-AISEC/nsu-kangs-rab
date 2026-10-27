"""시험용 합성 PDF 생성 함수 (모델 호출 없음, 개인 자료 없음). tests/unit/test_context.py 와 experiments/k05_pdf_extract_time.py 가 쓴다."""
import io


def build_pdf(pages: int, lines_per_page: int = 60, line: str = "The quick brown fox jumps over the lazy dog 0123456789 ") -> bytes:
    objs = []
    def add(b):
        objs.append(b)
        return len(objs)
    add(b"")  # 1: catalog 자리
    add(b"")  # 2: pages 자리
    font = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    kids = []
    for _ in range(pages):
        ops = ["BT /F1 8 Tf 10 780 Td 9 TL"]
        for i in range(lines_per_page):
            ops.append("(%s%d) Tj T*" % (line, i))
        ops.append("ET")
        stream = "\n".join(ops).encode("latin-1")
        c = add(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
        p = add(("<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents %d 0 R "
                 "/Resources << /Font << /F1 %d 0 R >> >> >>" % (c, font)).encode())
        kids.append(p)
    objs[0] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objs[1] = ("<< /Type /Pages /Kids [%s] /Count %d >>" % (" ".join("%d 0 R" % k for k in kids), pages)).encode()
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offs = []
    for i, o in enumerate(objs, 1):
        offs.append(out.tell())
        out.write(b"%d 0 obj\n" % i + o + b"\nendobj\n")
    xref = out.tell()
    out.write(b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1))
    for o in offs:
        out.write(b"%010d 00000 n \n" % o)
    out.write(b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref))
    return out.getvalue()


def build_heavy_pdf(lines: int = 55000, line: str = "The quick brown fox jumps over the lazy dog 0123456789 ") -> bytes:
    """쪽 하나에 내용 스트림을 zlib 으로 압축한 PDF. 파일은 작고 풀면 수 MiB 이다(X3: 0.15 MiB → 3.9 MiB, 추출 약 5.8초)."""
    import zlib
    ops = ["BT /F1 8 Tf 10 780 Td 9 TL"] + ["(%s%d) Tj T*" % (line, i) for i in range(lines)] + ["ET"]
    raw = "\n".join(ops).encode("latin-1")
    comp = zlib.compress(raw, 9)
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [5 0 R] /Count 1 >>",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
            b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(comp) + comp + b"\nendstream",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 3 0 R >> >> >>"]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offs = []
    for i, o in enumerate(objs, 1):
        offs.append(out.tell())
        out.write(b"%d 0 obj\n" % i + o + b"\nendobj\n")
    xref = out.tell()
    out.write(b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1))
    for o in offs:
        out.write(b"%010d 00000 n \n" % o)
    out.write(b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref))
    return out.getvalue()


def build_owner_only_pdf(text_pdf: bytes, owner: str = "owner-secret", algorithm: str = "RC4-128", user: str = "") -> bytes:
    """열기 암호는 없고 소유자 암호만 있는 PDF(기본 RC4-128). `algorithm="AES-128"` · `"AES-256"` 은 `cryptography` 가 필요하다(D-033).
    `user` 를 주면 열기 암호가 있는 PDF 가 된다."""
    from pypdf import PdfReader, PdfWriter
    w = PdfWriter(clone_from=PdfReader(io.BytesIO(text_pdf)))
    w.encrypt(user_password=user, owner_password=owner, algorithm=algorithm)
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()
