"""Built-in demo data and the demo app's answers (spec section 10).

One click on "Try the demo" must produce a GO and a NO-GO with no setup, so
everything the demo needs lives here: the 12 golden helpdesk cases (also shipped
as ``demo/helpdesk_golden.csv``), the answers the demo app returns in each mode,
and the loader that stores and approves the dataset for the signed-in user.

The demo app itself (:mod:`app.demo_server`) calls :func:`chat`, so the tests and
the running container answer identically and the verdicts are reproducible.
"""

from __future__ import annotations

import csv
import io
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Dataset, DatasetVersion, User
from app.services.datasets import (
    DatasetError,
    approve_dataset_version,
    create_dataset,
)

DEMO_DATASET_NAME = "Demo — College helpdesk"
DEMO_SOURCE_FILENAME = "helpdesk_golden.csv"

# mode -> what the demo app returns for questions it does not know.
_FALLBACK: dict[str, tuple[str, str]] = {
    "good": (
        "I am not sure about that. Ask the helpdesk in the student portal.",
        "The college helpdesk answers questions about enrolment, tuition and campus services.",
    ),
    "broken": (
        "Please consult the archived brochure in the library annex.",
        "See the website.",
    ),
}

# The 12 golden cases: question, golden answer, reference context the app should
# retrieve. The good mode returns exactly this; the broken mode returns an
# unrelated answer with almost no context, so the engine has something real to
# fail on.
DEMO_CASES: list[dict[str, str]] = [
    {
        "question": "What is the Merit Scholarship?",
        "answer": "The Merit Scholarship is a merit-based award for first-year students.",
        "context": (
            "The Merit Scholarship is a merit-based award for first-year students with strong "
            "grades."
        ),
    },
    {
        "question": "How much is the Merit Scholarship worth?",
        "answer": "It covers full tuition for four years.",
        "context": "The Merit Scholarship covers full tuition for four years of study.",
    },
    {
        "question": "Who can apply for the Merit Scholarship?",
        "answer": "Applicants need a 3.5 GPA and an admission application on file.",
        "context": (
            "Applicants need a 3.5 GPA and an admission application on file to be considered."
        ),
    },
    {
        "question": "When is the application deadline?",
        "answer": "The deadline is 1 March for autumn entry.",
        "context": "The application deadline is 1 March for autumn entry each year.",
    },
    {
        "question": "How do I apply for financial aid?",
        "answer": "Submit the FAFSA form before the priority date.",
        "context": "Submit the FAFSA form before the priority date to apply for financial aid.",
    },
    {
        "question": "Where is the registrar's office?",
        "answer": "The registrar's office is in Administration Building room 120.",
        "context": (
            "The registrar's office is in Administration Building room 120 on the ground floor."
        ),
    },
    {
        "question": "What are the office hours?",
        "answer": "Office hours are Monday to Friday, 9:00 to 17:00.",
        "context": "Office hours are Monday to Friday, 9:00 to 17:00, closed on public holidays.",
    },
    {
        "question": "How do I register for classes?",
        "answer": "Register in the student portal during your enrolment window.",
        "context": "Register for classes in the student portal during your enrolment window.",
    },
    {
        "question": "How much is tuition per semester?",
        "answer": "Tuition is 4,200 credits per semester for full-time students.",
        "context": (
            "Tuition is 4,200 credits per semester for full-time students, payable before term "
            "start."
        ),
    },
    {
        "question": "Does the college offer dormitories?",
        "answer": "Yes, there are dormitories on campus for first-year students.",
        "context": (
            "The college offers dormitories on campus for first-year students, with rooms "
            "allocated by ballot."
        ),
    },
    {
        "question": "How do I get a student ID card?",
        "answer": "Collect your student ID card from campus services with your receipt.",
        "context": "Collect your student ID card from campus services with your enrolment receipt.",
    },
    {
        "question": "What is the attendance policy?",
        "answer": "Attendance below 80 percent triggers an academic warning.",
        "context": "Attendance below 80 percent triggers an academic warning and a tutor meeting.",
    },
]

_KNOWLEDGE: dict[str, dict[str, str]] = {
    case["question"].casefold().strip(): case for case in DEMO_CASES
}


def golden_csv() -> bytes:
    """The 12 golden cases as the CSV the demo dataset is built from."""
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=["question", "answer", "context"])
    writer.writeheader()
    writer.writerows(DEMO_CASES)
    return buffer.getvalue().encode("utf-8")


def chat(question: str, mode: str = "good") -> dict[str, Any]:
    """One answer from the demo helpdesk.

    ``good`` returns the golden answer and its full context, so a correct app
    scores 1.00. ``broken`` returns an unrelated answer and a stub of context,
    so the same dataset comes out NO_GO with the weak metrics named.
    """
    normalized = (question or "").casefold().strip()
    case = _KNOWLEDGE.get(normalized)
    if case is None and normalized:
        # A single-word match keeps probes and typos on the same page.
        case = next(
            (row for key, row in _KNOWLEDGE.items() if normalized in key or key in normalized),
            None,
        )
    if mode != "good":
        # Confidently wrong, and shares no content word with any golden answer.
        return {"answer": _FALLBACK["broken"][0], "context": _FALLBACK["broken"][1]}
    if case is None:
        return {"answer": _FALLBACK["good"][0], "context": _FALLBACK["good"][1]}
    return {"answer": case["answer"], "context": case["context"]}


def find_demo_dataset(session: Session, owner_id: uuid.UUID) -> Dataset | None:
    """The demo dataset for this account, if it has already been loaded."""
    return session.scalar(
        select(Dataset).where(Dataset.owner_id == owner_id, Dataset.name == DEMO_DATASET_NAME)
    )


def load_demo_dataset(session: Session, user: User) -> tuple[Dataset, DatasetVersion]:
    """Create (or reuse) and approve the demo dataset for this account.

    Idempotent on purpose: pressing "Try the demo" twice must not fail with a
    duplicate-name error, it must run the same golden version again.
    """
    dataset = find_demo_dataset(session, user.id)
    if dataset is None:
        try:
            dataset = create_dataset(
                session,
                owner_id=user.id,
                name=DEMO_DATASET_NAME,
                source_filename=DEMO_SOURCE_FILENAME,
                raw_content=golden_csv(),
            )
            session.flush()
        except DatasetError as exc:
            if exc.code != "duplicate_name":
                raise
            dataset = find_demo_dataset(session, user.id)
            if dataset is None:
                raise
    version = next(
        (row for row in dataset.versions if row.version_no == 1),
        None,
    )
    if version is None:
        raise DatasetError("missing_version", "The demo dataset has no first version.")
    if version.approved_at is None:
        version = approve_dataset_version(session, dataset, 1, user.id)
    return dataset, version
