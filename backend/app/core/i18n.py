"""Kiswahili / English message templates for SMS notifications."""

MESSAGES: dict[str, dict[str, str]] = {
    "account_created": {
        "sw": "{school}: Akaunti ya {name} imefunguliwa. Jina: {username}. Nenosiri la muda: {password}",
        "en": "{school}: Account for {name} created. Username: {username}. Temporary password: {password}",
    },
    "documents_to_validate": {
        "sw": "{school}: Maombi {enrolment_no} yana nyaraka {count} zinazosubiri uhakiki.",
        "en": "{school}: Application {enrolment_no} has {count} documents waiting for validation.",
    },
    "requirements_completed": {
        "sw": "{school}: Mahitaji yako yamekamilika! Maombi {enrolment_no} yanasubiri uthibitisho.",
        "en": "{school}: Your requirements are completed! Application {enrolment_no} awaits confirmation.",
    },
    "requirements_invalid": {
        "sw": "{school}: Baadhi ya mahitaji yako si sahihi. Ingia kwenye mfumo kuona maelezo.",
        "en": "{school}: Some of your requirements are invalid. Log in to see the remarks.",
    },
    "enrolment_confirmed": {
        "sw": "{school}: Usajili umekamilika. {name} amesajiliwa {level} {stream}.",
        "en": "{school}: Enrolment complete. {name} is enrolled in {level} {stream}.",
    },
    "enrolment_cancelled": {
        "sw": "{school}: Usajili {enrolment_no} umesitishwa. Sababu: {reason}",
        "en": "{school}: Enrolment {enrolment_no} has been cancelled. Reason: {reason}",
    },
    "invoice_issued": {
        "sw": "{school}: Ankara {invoice_no} ya {name}. Kiasi TZS {amount}. Namba ya malipo: {control_no}.",
        "en": "{school}: Invoice {invoice_no} for {name}. Amount TZS {amount}. Control number: {control_no}.",
    },
    "payment_received": {
        "sw": "{school}: Tumepokea TZS {amount} kwa {name} ({trans_no}). Salio: TZS {balance}.",
        "en": "{school}: Received TZS {amount} for {name} ({trans_no}). Balance: TZS {balance}.",
    },
    "status_changed": {
        "sw": "{school}: Hali ya mwanafunzi {name} imebadilika kuwa {status}. Sababu: {reason}",
        "en": "{school}: Student {name} status changed to {status}. Reason: {reason}",
    },
    "new_class_session": {
        "sw": "{school}: Kipindi kipya: {subject}, {day} {start}-{end}, chumba {room}.",
        "en": "{school}: New lesson: {subject}, {day} {start}-{end}, room {room}.",
    },
    "fee_reminder": {
        "sw": "{school}: Kumbusho: salio la ada la {name} ni TZS {balance}, mwisho {due}. Namba ya malipo {control_no}.",
        "en": "{school}: Reminder: {name}'s fee balance is TZS {balance}, due {due}. Control number {control_no}.",
    },
}

STATUS_LABELS = {
    "APPLICANT": {"sw": "Mwombaji", "en": "Applicant"},
    "ACTIVE": {"sw": "Anasoma", "en": "Active"},
    "SUSPENDED": {"sw": "Amesimamishwa", "en": "Suspended"},
    "TRANSFERRED": {"sw": "Amehamishwa", "en": "Transferred"},
    "DROPPED_OUT": {"sw": "Ameacha shule", "en": "Dropped out"},
    "GRADUATED": {"sw": "Amehitimu", "en": "Graduated"},
}

DAY_NAMES = {
    "sw": {1: "Jumatatu", 2: "Jumanne", 3: "Jumatano", 4: "Alhamisi", 5: "Ijumaa", 6: "Jumamosi"},
    "en": {1: "Monday", 2: "Tuesday", 3: "Wednesday", 4: "Thursday", 5: "Friday", 6: "Saturday"},
}


def render(key: str, lang: str, **values) -> str:
    template = MESSAGES[key].get(lang) or MESSAGES[key]["en"]
    return template.format(**values)


def tzs(amount) -> str:
    """Format money the Tanzanian way: 1,250,000."""
    return f"{amount:,.0f}"
