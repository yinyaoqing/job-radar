import pytest

from job_radar.classify import (
    CATEGORIES,
    classify,
    is_general_application,
    work_mode_from_text,
)


@pytest.mark.parametrize(
    ("title", "department", "expected"),
    [
        ("Software engineer", "Development", "engineering"),
        ("Senior Frontend Developer", None, "engineering"),
        ("IT support technician", "Administration", "engineering"),
        ("Data Engineer", None, "data"),
        ("Data Analyst", None, "data"),
        ("Principal Product Manager", "Product", "product"),
        ("(Senior) Product Owner", "Product", "product"),
        ("Product Designer", None, "design"),
        ("Product Marketing Manager", None, "marketing"),
        ("Agentic Operator, Growth Marketing", "Marketing", "marketing"),
        ("Director, Demand Generation", "Marketing", "marketing"),
        ("Growth Engineer", None, "engineering"),
        ("Account Executive", "Revenue", "sales"),
        ("Solutions Engineer", None, "sales"),
        ("Senior Customer Success Manager", "Customer Success", "customer"),
        ("Recruiter, GTM", "Talent Acquisition", "people"),
        ("US IT Recruiter - Emerging AI Roles", "Others", "people"),
        ("Lead Accountant", "Accounting", "finance"),
        ("Deputy AML Manager - Belgium", None, "legal"),
        ("Technical Writer", None, "content"),
        ("Community Manager", None, "content"),
        ("Senior GTM Strategy & Operations Manager", "Revenue", "operations"),
        ("Executive Assistant", None, "operations"),
        ("Senior Client Manager", "Client Management", "customer"),
        ("Strategic Project Lead - Healthcare", "Applied AI & Research", "operations"),
        ("Strategic Sourcing Lead - Fulfillment - Brazil", "Corporate", "operations"),
        # Title says nothing, the department decides.
        ("Transaction Review Lead", "Growth", "marketing"),
        ("Production staff", "Factory", "other"),
    ],
)
def test_classify(title, department, expected):
    assert classify(title, department) == expected
    assert expected in CATEGORIES


@pytest.mark.parametrize(
    ("texts", "expected"),
    [
        (("Remote (USA)",), "remote"),
        (("Remote, United States",), "remote"),
        (("Anywhere",), "remote"),
        (("San Francisco (hybrid)",), "hybrid"),
        (("San Francisco",), "onsite"),
        (("Berlin", "Remote - EU"), "remote"),
        ((None, ""), "unknown"),
    ],
)
def test_work_mode_from_text(texts, expected):
    assert work_mode_from_text(*texts) == expected


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Don’t see what you’re looking for?", True),
        ("General Application", True),
        ("Join our Talent Community", True),
        ("Talent Acquisition Partner", False),
        ("Software engineer", False),
    ],
)
def test_is_general_application(title, expected):
    assert is_general_application(title) is expected
