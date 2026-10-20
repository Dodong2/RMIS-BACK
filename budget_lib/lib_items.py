"""Starting LIB Item list (client 2026-10-20): object codes from the DBM UACS Manual Appendices, COA-DBM-DOF Joint
Circular 2013-1, Sections C.5.1 (PS), C.5.2 (MOOE) and C.5.6 (Capital Outlays). The System Admin edits, deactivates or
adds items afterwards (Admin > LIB Items). Shared by migration 0009 and the tests."""

LIB_ITEMS = [
    ("ps", "Honoraria", "5010210000"),
    ("ps", "Salaries and Wages - Casual/Contractual", "5010102000"),
    ("ps", "Overtime Pay", "5010213001"),
    ("mooe", "Traveling Expenses - Local", "5020101000"),
    ("mooe", "Traveling Expenses - Foreign", "5020102000"),
    ("mooe", "Training Expenses", "5020201000"),
    ("mooe", "Office Supplies Expenses", "5020301000"),
    ("mooe", "Medical, Dental and Laboratory Supplies Expenses", "5020308000"),
    ("mooe", "Fuel, Oil and Lubricants Expenses", "5020309000"),
    ("mooe", "Agricultural and Marine Supplies Expenses", "5020310000"),
    ("mooe", "Chemical and Filtering Supplies Expenses", "5020313000"),
    ("mooe", "Other Supplies and Materials Expenses", "5020399000"),
    ("mooe", "Postage and Courier Services", "5020501000"),
    ("mooe", "Internet Subscription Expenses", "5020503000"),
    ("mooe", "Survey Expenses", "5020701000"),
    ("mooe", "Research, Exploration and Development Expenses", "5020702000"),
    ("mooe", "Consultancy Services", "5021103000"),
    ("mooe", "Other Professional Services", "5021199000"),
    ("mooe", "Printing and Publication Expenses", "5029902000"),
    ("mooe", "Representation Expenses", "5029903000"),
    ("mooe", "Transportation and Delivery Expenses", "5029904000"),
    ("mooe", "Rents - Motor Vehicles", "5029905003"),
    ("mooe", "Rents - Equipment", "5029905004"),
    ("mooe", "Subscription Expenses", "5029907000"),
    ("co", "Office Equipment", "5060405002"),
    ("co", "Information and Communication Technology Equipment", "5060405003"),
    ("co", "Agricultural and Forestry Equipment", "5060405004"),
    ("co", "Technical and Scientific Equipment", "5060405014"),
    ("co", "Other Machinery and Equipment", "5060405099"),
]


def seed_lib_items(LibItem):
    """Insert the starting list; existing rows (matched by class + name) are left as the admin set them."""
    for category, name, uacs_code in LIB_ITEMS:
        LibItem.objects.get_or_create(category=category, name=name, defaults={"uacs_code": uacs_code})
