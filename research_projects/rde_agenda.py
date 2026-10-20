"""LSPU 2024-2028 RDE Agenda seed, shared by migration 0016 and the tests (a TransactionTestCase flush empties
migration-seeded rows in a --keepdb test database)."""

# LSPU 2024-2028 RDE Agenda, "RDE Thrusts and Priorities" (LSPU-RDE-AGENDA-2024-2028.pdf, pp. 27-28), spelled as in the
# source. Client 2026-10-20: the System Admin maintains this list afterwards (Admin > RDE Thrusts).
RDE_AGENDA = [
    ("1", "Computing and Emerging Technologies", [
        "Game development and Immersive technologies",
        "Business Intelligence and Data Analytics",
        "Artificial Intelligence and Machine Learning",
        "Digital Systems Technology",
        "e-Government and e-Governance",
        "Smart and Emerging Technologies",
        "Biomedical Devices Engineering",
        "Robotics Technology",
        "Cyber Technologies",
    ]),
    ("2", "Natural Resources Management", [
        "Utilization and Development of Innovative Products",
        "Mechanization in Crops, Livestock, Poultry & Fisheries Production",
        "Utilization, management and Conservation of Microbial Resources",
        "Utilization and Development of Indigenous Resources",
        "Smart Farming Technologies",
        "Water Treatment and Sanitation (Including Natural Water Filtration Systems)",
        "Renewable Energy",
        "Environmental Management and Conservation",
        "Environmental Justice",
    ]),
    ("3", "Climate Change Resiliency", [
        "Vulnerability Mapping",
        "Community Resilience",
        "Climate Change Adaptation Technologies",
        "Disaster and Risk Reduction Management",
    ]),
    ("4", "Holistic Education", [
        "Teaching and Learning development Initiatives",
        "Content Knowledge, Pedagogies and Andragogy",
        "Diversity of Learning and Inclusive Education",
        "Home Schooling, Distance and Online Education",
        "Professional Development and Ethics",
        "E-Learning and Education Technology",
        "Alternative Learning delivery Modes",
        "Lifelong Learning",
        "National Competency-Based technical and Vocational Schooling",
    ]),
    ("5", "Culture and Society", [
        "Poverty Alleviation",
        "Good Governance",
        "Public Safety and Security",
        "Criminal Justice",
        "Forensic Science",
        "Constitutional and Political Law and Jurisprudence",
        "Social Legislation and Jurisprudence",
        "Civil Law and Jurisprudence",
        "Public and Private International Law and Cases",
    ]),
    ("6", "Gender and Development", [
        "Gender Equity and Equality",
        "Violence Against Women and Children",
        "Children in Conflict with the Law",
        "Gender-Based Sexual Harassment",
        "Gender Roles and Family Relations",
        "Migration",
        "Human Rights",
    ]),
    ("7", "Food, Nutrition and Health", [
        "Health and Wellness",
        "Herbal and Alternative Medicine",
        "Food Nutrition and Innovation",
        "Food Safety and Security",
        "Food Product development and Entrepreneurship",
    ]),
    ("8", "Philippine Global Competitiveness", [
        "Glocal Strategies and Connections",
        "Financial Sustainability and Risk Management",
        "Entrepreneurship and Innovation Ecosystems",
        "Business and Public Policy",
        "Sustainable Business Practices",
        "Entrepreneurship and Business Operations in Tourism and Hospitality",
        "Sustainable Tourism Destination",
        "Technology Commercialization and Technopreneurship",
        "Smart Communities and Green Computing",
    ]),
]


def seed_rde_agenda(ReiThrust):
    """Insert or refresh the agenda by code. Takes the model so the migration can pass its historical one, which
    skips CodedChoice.save(); the "code - title" name is set here."""

    def upsert(code, title, parent=None):
        row, _ = ReiThrust.objects.update_or_create(
            code=code, defaults={"title": title, "name": f"{code} - {title}", "parent": parent},
        )
        return row

    for code, title, priorities in RDE_AGENDA:
        thrust = upsert(code, title)
        for n, priority in enumerate(priorities, start=1):
            upsert(f"{code}.{n}", priority, thrust)
