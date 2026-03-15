"""
LLM-mentes transcript pipeline – referencia (1:1).
Nem használjuk a main PDFAI-ban; kísérlethez / forkhoz.
Lásd: TRANSCRIPT-PIPELINE-REFERENCE.md
"""
import re
import cv2
import numpy as np
import pandas as pd

from pdf2image import convert_from_path
from paddleocr import PaddleOCR
from sklearn.cluster import KMeans
from rapidfuzz import process

# -----------------------------
# CONFIG
# -----------------------------

COURSE_REGEX = r"[A-Z]{2,4}\s?\d{3,5}"
GRADE_REGEX = r"A\+|A|A-|B\+|B|B-|C\+|C|PA|CR"
CREDIT_REGEX = r"\d(\.\d)?"

EXPECTED_COLUMNS = 5

# dictionary a fuzzy javításhoz
KNOWN_COURSES = [
    "CALCULUS I",
    "INTRO TO ACCOUNTING I",
    "INTRO TO ACCOUNTING II",
    "PRINCIPLES MACROECONOMICS",
    "PRINCIPLES MICROECONOMICS",
    "INTRODUCTION TO LITERATURE",
    "AMERICAN POLITICAL SYSTEM",
    "BUSINESS STATISTICS",
]


# -----------------------------
# OCR INIT
# -----------------------------

ocr = PaddleOCR(
    use_angle_cls=True,
    lang="en"
)


# -----------------------------
# PDF → IMAGE
# -----------------------------

def pdf_to_images(pdf_path):

    images = convert_from_path(pdf_path, dpi=300)

    return [np.array(img) for img in images]


# -----------------------------
# OCR WITH BOUNDING BOX
# -----------------------------

def run_ocr(image):

    result = ocr.ocr(image)

    rows = []

    for line in result[0]:

        box = line[0]
        text = line[1][0]

        x = int(box[0][0])
        y = int(box[0][1])

        rows.append({
            "text": text.strip(),
            "x": x,
            "y": y
        })

    return pd.DataFrame(rows)


# -----------------------------
# ROW GROUPING
# -----------------------------

def group_rows(df):

    df = df.sort_values("y")

    rows = []

    current = []
    last_y = None

    for _, r in df.iterrows():

        if last_y is None:
            current.append(r)
            last_y = r.y
            continue

        if abs(r.y - last_y) < 15:
            current.append(r)
        else:
            rows.append(current)
            current = [r]

        last_y = r.y

    if current:
        rows.append(current)

    return rows


# -----------------------------
# COLUMN DETECTION
# -----------------------------

def detect_columns(df):

    xs = df["x"].values.reshape(-1, 1)

    kmeans = KMeans(n_clusters=EXPECTED_COLUMNS, random_state=0)

    df["col"] = kmeans.fit_predict(xs)

    return df


# -----------------------------
# PARSE ROW
# -----------------------------

def parse_row(row):

    texts = [r.text for r in row]

    full = " ".join(texts)

    course_code = re.search(COURSE_REGEX, full)
    grade = re.search(GRADE_REGEX, full)
    credit = re.search(CREDIT_REGEX, full)

    course_name = full

    if course_code:
        course_name = full.replace(course_code.group(), "")

    course_name = course_name.strip()

    # fuzzy cleanup
    match = process.extractOne(course_name, KNOWN_COURSES)

    if match and match[1] > 90:
        course_name = match[0]

    return {
        "course": course_name,
        "code": course_code.group() if course_code else None,
        "credit": credit.group() if credit else None,
        "grade": grade.group() if grade else None
    }


# -----------------------------
# VALIDATE ROW
# -----------------------------

def is_valid(row):

    if not row["code"]:
        return False

    if not row["credit"]:
        return False

    return True


# -----------------------------
# MAIN PIPELINE
# -----------------------------

def extract_transcript(pdf_path):

    images = pdf_to_images(pdf_path)

    records = []

    for image in images:

        df = run_ocr(image)

        rows = group_rows(df)

        for row in rows:

            parsed = parse_row(row)

            if is_valid(parsed):
                records.append(parsed)

    return pd.DataFrame(records)


# -----------------------------
# RUN
# -----------------------------

if __name__ == "__main__":

    df = extract_transcript("transcript.pdf")

    df.to_csv("transcript.csv", index=False)

    print(df)
