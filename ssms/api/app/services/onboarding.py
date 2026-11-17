"""Defaults created for a new school, so it can be used on day one. Every value can be edited by the school.

Official values are marked VERIFY: grading scales (NECTA), class structure (Education and Training Policy 2014,
2023 edition) and term dates (Ministry school calendar circular for the year) must be checked before launch.
"""

import uuid
from datetime import date, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AcademicYear,
    AssessmentComponent,
    Department,
    Designation,
    DivisionRule,
    EducationLevel,
    FeeItem,
    FinanceCategory,
    GradeBand,
    GradingScheme,
    LedgerAccount,
    MessageTemplate,
    PublicHoliday,
    SchoolClass,
    Stream,
    Term,
)
from app.models.enums import ComponentCode
from app.models.enums import EducationLevelCode as L

DEFAULT_STREAM_CAPACITY = 45

LEVELS = {  # code: (English, Kiswahili, sort, classes [(code, English, Kiswahili)])
    L.PRE_PRIMARY: ("Pre-primary", "Elimu ya awali", 1, [("PP", "Pre-primary", "Elimu ya Awali")]),  # VERIFY 1 year
    L.PRIMARY: (
        "Primary",
        "Elimu ya msingi",
        2,
        [  # VERIFY 7 years
            (f"STD{n}", f"Standard {en}", f"Darasa la {sw}")
            for n, en, sw in (
                (1, "One", "Kwanza"),
                (2, "Two", "Pili"),
                (3, "Three", "Tatu"),
                (4, "Four", "Nne"),
                (5, "Five", "Tano"),
                (6, "Six", "Sita"),
                (7, "Seven", "Saba"),
            )
        ],
    ),
    L.O_LEVEL: (
        "Ordinary level",
        "Elimu ya sekondari ya kawaida",
        3,
        [
            ("F1", "Form One", "Kidato cha Kwanza"),
            ("F2", "Form Two", "Kidato cha Pili"),
            ("F3", "Form Three", "Kidato cha Tatu"),
            ("F4", "Form Four", "Kidato cha Nne"),
        ],
    ),
    L.A_LEVEL: (
        "Advanced level",
        "Elimu ya sekondari ya juu",
        4,
        [("F5", "Form Five", "Kidato cha Tano"), ("F6", "Form Six", "Kidato cha Sita")],
    ),
}

GRADING = {  # VERIFY against current NECTA regulations (same values as design/sql/seed.sql)
    L.PRIMARY: (
        "NECTA PSLE scale",
        None,
        [
            ("A", 81, 100, 1, "Excellent", "Bora"),
            ("B", 61, 80, 2, "Very good", "Vizuri sana"),
            ("C", 41, 60, 3, "Good", "Vizuri"),
            ("D", 21, 40, 4, "Satisfactory", "Inaridhisha"),
            ("E", 0, 20, 5, "Fail", "Hafifu"),
        ],
        [],
    ),
    L.O_LEVEL: (
        "NECTA CSEE scale",
        7,
        [
            ("A", 75, 100, 1, "Excellent", "Bora"),
            ("B", 65, 74, 2, "Very good", "Vizuri sana"),
            ("C", 45, 64, 3, "Good", "Vizuri"),
            ("D", 30, 44, 4, "Satisfactory", "Inaridhisha"),
            ("F", 0, 29, 5, "Fail", "Hafifu"),
        ],
        [("I", 7, 17), ("II", 18, 21), ("III", 22, 25), ("IV", 26, 33), ("0", 34, 35)],
    ),
    L.A_LEVEL: (
        "NECTA ACSEE scale",
        3,
        [
            ("A", 80, 100, 1, "Excellent", "Bora"),
            ("B", 70, 79, 2, "Very good", "Vizuri sana"),
            ("C", 60, 69, 3, "Good", "Vizuri"),
            ("D", 50, 59, 4, "Average", "Wastani"),
            ("E", 40, 49, 5, "Satisfactory", "Inaridhisha"),
            ("S", 35, 39, 6, "Subsidiary", "Ufaulu hafifu"),
            ("F", 0, 34, 7, "Fail", "Hafifu"),
        ],
        [("I", 3, 9), ("II", 10, 12), ("III", 13, 17), ("IV", 18, 19), ("0", 20, 21)],
    ),
}

# New schools start with CA 40 % + terminal exam 60 % per term and level; each school can change them.
DEFAULT_COMPONENTS = [
    (ComponentCode.CA, "Continuous assessment", "Tathmini endelevu", 40),
    (ComponentCode.TERMINAL, "Terminal exam", "Mtihani wa muhula", 60),
]

FIXED_HOLIDAYS = [  # fixed-date public holidays; Easter, Eid and other movable days are added by the school
    (1, 1, "New Year's Day", "Mwaka Mpya"),
    (1, 12, "Zanzibar Revolution Day", "Siku ya Mapinduzi ya Zanzibar"),
    (4, 7, "Karume Day", "Siku ya Karume"),
    (4, 26, "Union Day", "Siku ya Muungano"),
    (5, 1, "Workers' Day", "Mei Mosi"),
    (7, 7, "Saba Saba", "Sabasaba"),
    (8, 8, "Farmers' Day", "Nane Nane"),
    (10, 14, "Nyerere Day", "Siku ya Nyerere"),
    (12, 9, "Independence Day", "Siku ya Uhuru"),
    (12, 25, "Christmas Day", "Krismasi"),
    (12, 26, "Boxing Day", "Siku ya Kutoa Zawadi"),
]

DEPARTMENTS = [
    ("SCI", "Science", "Sayansi"),
    ("LANG", "Languages", "Lugha"),
    ("HUM", "Humanities", "Masomo ya Sanaa"),
    ("MATH", "Mathematics", "Hisabati"),
    ("ADM", "Administration", "Utawala"),
]
DESIGNATIONS = [
    ("HEAD_TEACHER", "Head teacher", "Mkuu wa shule"),
    ("ACADEMIC_MASTER", "Academic master", "Mwalimu wa taaluma"),
    ("SUBJECT_TEACHER", "Subject teacher", "Mwalimu wa somo"),
    ("BURSAR", "Bursar", "Mhasibu"),
    ("GATEKEEPER", "Gatekeeper", "Mlinzi"),
]

LEDGER = [
    ("1000", "Cash on hand", "Fedha taslimu", "ASSET"),
    ("1100", "GePG clearing", "Akaunti ya GePG", "ASSET"),
    ("1110", "Mobile money clearing", "Akaunti ya pesa za simu", "ASSET"),
    ("1200", "Bank", "Benki", "ASSET"),
    ("1300", "Fees receivable", "Ada zinazodaiwa", "ASSET"),
    ("2100", "Student credit (prepaid)", "Malipo ya ziada ya wanafunzi", "LIABILITY"),
    ("4000", "Tuition income", "Mapato ya karo", "INCOME"),
    ("4010", "Meals income", "Mapato ya chakula", "INCOME"),
    ("4020", "Examination fee income", "Mapato ya ada ya mitihani", "INCOME"),
    ("4030", "Development levy income", "Mapato ya ada ya maendeleo", "INCOME"),
    ("4040", "Transport income", "Mapato ya usafiri", "INCOME"),
    ("4050", "Boarding income", "Mapato ya bweni", "INCOME"),
    ("4060", "Fines income", "Mapato ya faini", "INCOME"),
    ("4800", "Other income", "Mapato mengine", "INCOME"),
    ("4810", "Donations", "Michango", "INCOME"),
    ("4900", "Discounts allowed", "Punguzo zilizotolewa", "EXPENSE"),
    ("5000", "Salaries and wages", "Mishahara", "EXPENSE"),
    ("5100", "Utilities", "Maji na umeme", "EXPENSE"),
    ("5200", "Supplies and stationery", "Vifaa na shajara", "EXPENSE"),
    ("5300", "Repairs and maintenance", "Matengenezo", "EXPENSE"),
    ("5900", "Other expenses", "Matumizi mengine", "EXPENSE"),
]
# Accounts that get an income or expense category of the same name (migration 0016 does the same for old schools)
CATEGORY_ACCOUNTS = ("4800", "4810", "5000", "5100", "5200", "5300", "5900")
FEE_ITEMS = [
    ("TUITION", "Tuition fee", "Karo", "4000"),
    ("MEALS", "Meals", "Chakula", "4010"),  # GFS codes: VERIFY
    ("EXAMINATION", "Examination fee", "Ada ya mitihani", "4020"),
    ("DEVELOPMENT", "Development levy", "Ada ya maendeleo", "4030"),
    ("TRANSPORT", "Transport", "Usafiri", "4040"),
    ("BOARDING", "Boarding", "Bweni", "4050"),
    ("FINE", "Late payment fine", "Faini ya kuchelewa kulipa", "4060"),
]

TEMPLATES = {
    "absence_alert": (
        "{school}: {student} hakufika shuleni leo {date}. Tafadhali wasiliana na mwalimu wa darasa.",
        "{school}: {student} was absent from school today {date}. Please contact the class teacher.",
    ),
    "payment_receipt": (
        "{school}: Tumepokea TZS {amount} kwa {student}. Risiti {receipt_no}. Salio TZS {balance}.",
        "{school}: Received TZS {amount} for {student}. Receipt {receipt_no}. Balance TZS {balance}.",
    ),
    "results_ready": (
        "{school}: Matokeo ya {term} ya {student} yametoka. Ingia kwenye mfumo kuona ripoti.",
        "{school}: {student}'s {term} results are out. Log in to see the report card.",
    ),
    "invoice_issued": (
        "{school}: Ankara {invoice_no} TZS {amount}. Namba ya malipo {control_no}. Mwisho {due}.",
        "{school}: Invoice {invoice_no} TZS {amount}. Control number {control_no}. Due {due}.",
    ),
    "fee_reminder": (
        "{school}: Ada ya {student} TZS {amount} ilitakiwa {due}. Lipa kwa namba {control_no}. Asante.",
        "{school}: Fees for {student} of TZS {amount} were due on {due}. Pay with number {control_no}. Thank you.",
    ),
    "discipline_notice": (
        "{school}: {student} amehusika na tukio la nidhamu ({category}) tarehe {date}. Tafadhali wasiliana na shule.",
        "{school}: {student} was involved in a discipline incident ({category}) on {date}. Please contact the school.",
    ),
    "library_overdue": (
        '{school}: Kitabu "{title}" alichoazima {borrower} kilitakiwa kurudishwa {due}. Tafadhali kirudishe.',
        '{school}: The book "{title}" borrowed by {borrower} was due on {due}. Please return it.',
    ),
    "account_created": (
        "{school}: Akaunti yako ya SSMS imefunguliwa. Jina: {username}. Nenosiri la muda: {password}",
        "{school}: Your SSMS account is ready. Username: {username}. Temporary password: {password}",
    ),
}


def _weekday_on_or_after(day: date, weekday: int) -> date:
    return day + timedelta(days=(weekday - day.weekday()) % 7)


def default_terms(year: int) -> list[tuple[int, str, str, date, date]]:
    """Two terms: second Monday of January to first Friday of June, first Monday of July to first Friday of
    December. VERIFY with the Ministry calendar circular for the year; schools edit the dates."""
    return [
        (
            1,
            "Term One",
            "Muhula wa Kwanza",
            _weekday_on_or_after(date(year, 1, 8), 0),
            _weekday_on_or_after(date(year, 6, 1), 4),
        ),
        (
            2,
            "Term Two",
            "Muhula wa Pili",
            _weekday_on_or_after(date(year, 7, 1), 0),
            _weekday_on_or_after(date(year, 12, 1), 4),
        ),
    ]


async def apply_defaults(
    session: AsyncSession, school_id: uuid.UUID, admin_id: uuid.UUID, levels: list[L], year: int
) -> dict[str, int]:
    """Insert the defaults for a new school (no RLS context needed on the console; created_by = school admin)."""
    common = {"school_id": school_id, "created_by": admin_id}
    counts: dict[str, int] = {}

    async def add(kind: str, rows: list) -> list:
        """Insert one group and flush, so the next group's composite foreign keys find these rows."""
        session.add_all(rows)
        await session.flush()
        counts[kind] = counts.get(kind, 0) + len(rows)
        return rows

    academic_year = (
        await add(
            "academic_years",
            [
                AcademicYear(
                    name=str(year), start_date=date(year, 1, 1), end_date=date(year, 12, 31), is_current=True, **common
                )
            ],
        )
    )[0]
    terms = await add(
        "terms",
        [
            Term(
                academic_year_id=academic_year.id,
                term_no=n,
                name_en=en,
                name_sw=sw,
                start_date=start,
                end_date=end,
                **common,
            )
            for n, en, sw, start, end in default_terms(year)
        ],
    )
    await add(
        "public_holidays",
        [
            PublicHoliday(holiday_date=date(year, m, d), name_en=en, name_sw=sw, kind="NATIONAL", **common)
            for m, d, en, sw in FIXED_HOLIDAYS
        ],
    )

    for code in sorted(set(levels), key=lambda c: LEVELS[c][2]):
        name_en, name_sw, sort, classes = LEVELS[code]
        level = (
            await add(
                "education_levels",
                [EducationLevel(code=code, name_en=name_en, name_sw=name_sw, sort_order=sort, **common)],
            )
        )[0]
        await add(
            "assessment_components",
            [
                AssessmentComponent(
                    term_id=term.id,
                    education_level_id=level.id,
                    code=component,
                    name_en=en,
                    name_sw=sw,
                    max_score=100,
                    weight=weight,
                    **common,
                )
                for term in terms
                for component, en, sw, weight in DEFAULT_COMPONENTS
            ],
        )
        made = await add(
            "classes",
            [
                SchoolClass(
                    education_level_id=level.id, code=c, name_en=en, name_sw=sw, sort_order=sort * 10 + i, **common
                )
                for i, (c, en, sw) in enumerate(classes, start=1)
            ],
        )
        for current, following in zip(made, made[1:], strict=False):
            current.next_class_id = following.id  # UPDATE once both classes exist
        await add(
            "streams", [Stream(class_id=c.id, name="A", capacity=DEFAULT_STREAM_CAPACITY, **common) for c in made]
        )
        if code in GRADING:
            name, best_n, bands, divisions = GRADING[code]
            scheme = (
                await add(
                    "grading_schemes",
                    [
                        GradingScheme(
                            education_level_id=level.id,
                            academic_year_id=academic_year.id,
                            name=name,
                            best_n_subjects=best_n,
                            **common,
                        )
                    ],
                )
            )[0]
            await add(
                "grade_bands",
                [
                    GradeBand(
                        grading_scheme_id=scheme.id,
                        letter=g,
                        min_score=lo,
                        max_score=hi,
                        points=p,
                        remark_en=en,
                        remark_sw=sw,
                        **common,
                    )
                    for g, lo, hi, p, en, sw in bands
                ],
            )
            await add(
                "division_rules",
                [
                    DivisionRule(grading_scheme_id=scheme.id, division=d, min_points=lo, max_points=hi, **common)
                    for d, lo, hi in divisions
                ],
            )

    await add("departments", [Department(code=c, name_en=en, name_sw=sw, **common) for c, en, sw in DEPARTMENTS])
    await add("designations", [Designation(code=c, name_en=en, name_sw=sw, **common) for c, en, sw in DESIGNATIONS])
    accounts = {
        c: a
        for c, a in (
            (row[0], LedgerAccount(code=row[0], name_en=row[1], name_sw=row[2], kind=row[3], **common))
            for row in LEDGER
        )
    }
    await add("ledger_accounts", list(accounts.values()))
    await add(
        "fee_items",
        [
            FeeItem(code=c, name_en=en, name_sw=sw, income_account_id=accounts[acct].id, **common)
            for c, en, sw, acct in FEE_ITEMS
        ],
    )
    await add(
        "finance_categories",
        [
            FinanceCategory(
                kind=accounts[code].kind,
                name_en=accounts[code].name_en,
                name_sw=accounts[code].name_sw,
                ledger_account_id=accounts[code].id,
                **common,
            )
            for code in CATEGORY_ACCOUNTS
        ],
    )
    await add(
        "message_templates",
        [
            MessageTemplate(key=key, language=lang, body=body, **common)
            for key, (sw, en) in TEMPLATES.items()
            for lang, body in (("sw", sw), ("en", en))
        ],
    )
    await session.flush()
    return counts
