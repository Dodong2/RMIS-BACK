"""Official LIB Item list (client 2026-10-21): the PS, MOOE and Capital Outlay rows of 2027-LIB-proposed.xlsx (LSPU
Siniloan, sheet "Research") with their account codes, spelled as in the file. Left out: the group headings under Capital
Outlay, the uncoded "Life and Retirement Insurance Premium" breakdown row under Retirement and Life Insurance Premium, and
Loan Amortization / Mandatory Reserve Fund (outside PS/MOOE/CO). The System Admin edits, deactivates or adds items
afterwards (Admin > LIB Items). Shared by migrations 0009/0011 and the tests."""

LIB_ITEMS = [
    ("ps", "Salaries and Wages", "50101010"),
    ("ps", "Retirement and Life Insurance Premium", "50103010"),
    ("ps", "Honoraria", "50102100"),
    ("ps", "Overtime and Night Pay", "50102130"),
    ("mooe", "Traveling Expenses - Local", "50201010"),
    ("mooe", "Traveling Expenses - Foreign", "50201020"),
    ("mooe", "Training Expenses", "50202010"),
    ("mooe", "Scholarship Grants/Expenses", "50202020"),
    ("mooe", "Office Supplies Expenses", "50203010"),
    ("mooe", "Accountable Forms", "50203020"),
    ("mooe", "Drugs and Medicines Expenses", "50203070"),
    ("mooe", "Medical, Dental & Lab. Supplies Expenses", "50203080"),
    ("mooe", "Fuel, Oil, & Lubricants Expenses", "50203090"),
    ("mooe", "Agricultural & Fisheries Expenses", "50203100"),
    ("mooe", "Textbooks and Instructional Materials Expenses", "50203110"),
    ("mooe", "Semi-expendable Machinery and Equipment", "50203210"),
    ("mooe", "Semi-Expendable Furniture, Fixtures and Books Expenses", "50203220"),
    ("mooe", "Other Supplies and Materials Expenses", "50203990"),
    ("mooe", "Water Expenses", "50204010"),
    ("mooe", "Electricity Expenses", "50204020"),
    ("mooe", "Gas/Heating Expenses", "50204030"),
    ("mooe", "Postage and Courier Expenses", "50205010"),
    ("mooe", "Telephone Expenses", "50205020"),
    ("mooe", "Internet Subscription Expenses", "50205030"),
    ("mooe", "Cable, Satellite, Telegraph and Radio Expenses", "50205040"),
    ("mooe", "Awards/Rewards Expenses", "50206010"),
    ("mooe", "Prizes", "50206020"),
    ("mooe", "Legal Services", "50211010"),
    ("mooe", "Auditing Services", "50211020"),
    ("mooe", "Other Professional Services", "50211990"),
    ("mooe", "Security Services", "50212030"),
    ("mooe", "Other General Services", "50212990"),
    ("mooe", "Repairs and Maintenance-Land Improvement", "50213020"),
    ("mooe", "Repairs and Maintenance-Infrastucture Assets", "50213030"),
    ("mooe", "Repairs & Maintenance - Buildings & Other Structures", "50213040"),
    ("mooe", "Repairs & Maintenance - Machinery & Equipment", "50213050"),
    ("mooe", "Repairs & Maintenance - Motor Vehicles", "50213060"),
    ("mooe", "Repairs & Maintenance -Furniture & Fixtures", "50213070"),
    ("mooe", "Repairs & Maintenance - Semi-expendable Machinery & Equipment", "50213210"),
    ("mooe", "Repairs & Maintenance - Semi expendable Furniture & Fixtures and Books", "50213220"),
    ("mooe", "Repairs & Maintenance - Other Property, Plant & Equipment", "50213990"),
    ("mooe", "Subsidies-Others", "50214990"),
    ("mooe", "Fidelity Bond Premium", "50215020"),
    ("mooe", "Insurance Expenses", "50215030"),
    ("mooe", "Labor & Wages", "50216010"),
    ("mooe", "Advertising Expenses", "50299010"),
    ("mooe", "Printing & Publication Expenses", "50299020"),
    ("mooe", "Representation Expenses", "50299030"),
    ("mooe", "Transportation and Delivery Expenses", "50299040"),
    ("mooe", "Rent Expenses", "50299050"),
    ("mooe", "Membership Dues & Contribution to Organizations", "50299060"),
    ("mooe", "Subscription Expenses", "50299070"),
    ("mooe", "Other Maintenance and Operating Expenses", "50299990"),
    ("mooe", "Cost of Sales", "50402010"),
    ("co", "Land and Buildings Outlay", "50603010"),
    ("co", "Other Land Improvement", "10602990"),
    ("co", "Water Supply System", "10603040"),
    ("co", "Power Supply System", "10603050"),
    ("co", "School Buildings", "10604020"),
    ("co", "Other Structures", "10604990"),
    ("co", "Office Equipment", "10605020"),
    ("co", "Information and Communication Technology Equipment", "10605030"),
    ("co", "Medical Equipment", "10605110"),
    ("co", "Printing Equipment", ""),
    ("co", "Sports Equipment", "10605130"),
    ("co", "Technical and Scientific Equipment", "10605140"),
    ("co", "Other Machineries & Equipment", "10605990"),
    ("co", "Motor Vehicles", "10606010"),
    ("co", "Purchase of Speedboat", ""),
    ("co", "Furniture and Fixtures", "10607010"),
    ("co", "Books", "10607020"),
    ("co", "Other Leased Assets", ""),
    ("co", "Other Property, Plant and Equipment", "10698990"),
    ("co", "Computer Software", "10801020"),
]


def seed_lib_items(LibItem):
    """Insert the official list; existing rows (matched by class + name, any case) get the file's code and are active."""
    for category, name, uacs_code in LIB_ITEMS:
        item = LibItem.objects.filter(category=category, name__iexact=name).first()
        if item is None:
            LibItem.objects.create(category=category, name=name, uacs_code=uacs_code)
        else:
            item.name, item.uacs_code, item.is_active = name, uacs_code, True
            item.save(update_fields=["name", "uacs_code", "is_active"])
