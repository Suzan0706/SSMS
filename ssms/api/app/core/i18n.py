"""Kiswahili (default) and English messages for API errors and notifications."""

MESSAGES: dict[str, dict[str, str]] = {
    # generic
    "VALIDATION_ERROR": {"sw": "Taarifa ulizoweka si sahihi.", "en": "Some fields are invalid."},
    "NOT_FOUND": {"sw": "Taarifa haikupatikana.", "en": "Record not found."},
    "FORBIDDEN": {"sw": "Huna ruhusa ya kufanya kitendo hiki.", "en": "You do not have permission for this action."},
    "NOT_AUTHENTICATED": {"sw": "Tafadhali ingia kwanza.", "en": "Please log in."},
    "DUPLICATE": {"sw": "Taarifa hii tayari ipo.", "en": "This record already exists."},
    "INVALID_REFERENCE": {"sw": "Taarifa inayorejelewa haipo.", "en": "A referenced record does not exist."},
    "RULE_VIOLATION": {"sw": "Kanuni imevunjwa: {detail}", "en": "Rule violated: {detail}"},
    "FULL": {"sw": "Hakuna nafasi iliyobaki.", "en": "No places left."},
    "VENUE_CLASH": {"sw": "Ukumbi umeshawekwa kwa muda huo.", "en": "The venue is already booked at that time."},
    "NO_SMS_CREDIT": {
        "sw": "Salio la SMS halitoshi: zinahitajika {needed}, zimebaki {left}.",
        "en": "Not enough SMS credit: {needed} needed, {left} left.",
    },
    "NOT_ALLOWED": {"sw": "Kitendo hiki hakiruhusiwi sasa.", "en": "This action is not allowed now."},
    "TIMETABLE_CLASH": {"sw": "Kuna mgongano wa ratiba.", "en": "Timetable clash."},
    "RATE_LIMITED": {
        "sw": "Maombi mengi mno. Jaribu tena baada ya dakika {minutes}.",
        "en": "Too many requests. Try again in {minutes} minutes.",
    },
    "IDEMPOTENCY_MISMATCH": {
        "sw": "Idempotency-Key imetumika kwa ombi tofauti.",
        "en": "Idempotency-Key was already used for a different request.",
    },
    "IDEMPOTENCY_KEY_REQUIRED": {
        "sw": "Kichwa Idempotency-Key kinahitajika.",
        "en": "Idempotency-Key header is required.",
    },
    "INTERNAL_ERROR": {"sw": "Hitilafu ya mfumo. Jaribu tena.", "en": "System error. Please try again."},
    # auth
    "INVALID_CREDENTIALS": {"sw": "Jina la mtumiaji au nenosiri si sahihi.", "en": "Invalid username or password."},
    "ACCOUNT_LOCKED": {"sw": "Akaunti imefungwa hadi {until}.", "en": "Account locked until {until}."},
    "SCHOOL_NOT_FOUND": {"sw": "Shule haipatikani.", "en": "School not found."},
    "INVALID_TOKEN": {"sw": "Muda wa kuingia umeisha. Ingia tena.", "en": "Session expired. Please log in again."},
    "OTP_SENT": {
        "sw": "Namba ya siri imetumwa kama namba ipo kwenye mfumo.",
        "en": "A code has been sent if this number is registered.",
    },
    "OTP_INVALID": {"sw": "Namba ya siri si sahihi au imeisha muda.", "en": "The code is wrong or has expired."},
    "WEAK_PASSWORD": {
        "sw": "Nenosiri liwe na herufi 10 au zaidi, zikiwemo herufi na tarakimu.",
        "en": "Password must have at least 10 characters with letters and digits.",
    },
    "PASSWORD_CHANGE_REQUIRED": {"sw": "Badilisha nenosiri kwanza.", "en": "Please change your password first."},
    "MFA_REQUIRED": {"sw": "Weka namba ya uthibitisho (TOTP).", "en": "Enter your authenticator code."},
    "MFA_SETUP_REQUIRED": {
        "sw": "Weka kwanza uthibitisho wa hatua mbili.",
        "en": "Set up two-factor authentication first.",
    },
    # domain
    "STATUS_TRANSITION": {
        "sw": "Huwezi kubadili hali kutoka {old} kwenda {new}.",
        "en": "Cannot change status from {old} to {new}.",
    },
    "STREAM_FULL": {"sw": "Mkondo umejaa.", "en": "The stream is full."},
    "CLASS_NOT_FOUND": {"sw": "Darasa au mkondo haupo.", "en": "Class or stream not found."},
    "ONE_PRIMARY_GUARDIAN": {"sw": "Chagua mzazi mmoja mkuu.", "en": "Choose exactly one primary guardian."},
    "FILE_TYPE": {"sw": "Aina ya faili hairuhusiwi.", "en": "File type not allowed."},
    "FILE_TOO_LARGE": {"sw": "Faili ni kubwa mno (kikomo MB {mb}).", "en": "File too large (limit {mb} MB)."},
    "LEAVE_DAYS_EXCEEDED": {
        "sw": "Likizo hii inazidi siku zinazoruhusiwa mwaka huu (zimebaki {left}).",
        "en": "This leave is more than the days allowed this year ({left} left).",
    },
    "LEAVE_OVERLAP": {
        "sw": "Tayari kuna likizo iliyoidhinishwa katika tarehe hizi.",
        "en": "Leave is already approved for some of these dates.",
    },
    "YEAR_READ_ONLY": {
        "sw": "Unatazama mwaka mwingine: huwezi kubadilisha taarifa. Rudi mwaka wa sasa kwanza.",
        "en": "You are viewing another year: nothing can be changed. Switch back to the current year first.",
    },
    "FILE_INFECTED": {
        "sw": "Faili hili lina virusi na halikupokelewa.",
        "en": "This file contains a virus and was not accepted.",
    },
    "SCANNER_UNAVAILABLE": {
        "sw": "Ukaguzi wa virusi haupatikani kwa sasa; jaribu kupakia tena baada ya muda mfupi.",
        "en": "Virus scanning is unavailable right now; try the upload again shortly.",
    },
    "FILE_IN_USE": {
        "sw": "Faili hili linatumika (picha, kazi ya nyumbani, risiti au kiolezo); haliwezi kufutwa.",
        "en": "This file is in use (a photo, homework, receipt or template) and cannot be discarded.",
    },
    "FILE_TOO_LARGE_KB": {"sw": "Faili ni kubwa mno (kikomo KB {kb}).", "en": "File too large (limit {kb} KB)."},
    "IMPORT_HEADERS": {
        "sw": "Vichwa vya safu havilingani na kiolezo.",
        "en": "Column headers do not match the template.",
    },
    "INCOMPLETE_GRADES_BLOCK": {
        "sw": "Matokeo hayawezi kutolewa: matatizo {count} yanahitaji kurekebishwa.",
        "en": "Results cannot be published: {count} problem(s) must be fixed.",
    },
    # field-level validation codes
    "required": {"sw": "Sehemu hii ni lazima.", "en": "This field is required."},
    "invalid_phone": {
        "sw": "Namba ya simu si sahihi. Mfano: 0754 123 456.",
        "en": "Invalid phone number. Example: 0754 123 456.",
    },
    "invalid_email": {"sw": "Barua pepe si sahihi.", "en": "Invalid email address."},
    "future_date": {"sw": "Tarehe haiwezi kuwa ya baadaye.", "en": "Date cannot be in the future."},
    "student_age": {"sw": "Umri wa mwanafunzi uwe miaka 3 hadi 30.", "en": "Student age must be 3 to 30 years."},
    "invalid_nida": {"sw": "Namba ya NIDA iwe tarakimu 20.", "en": "NIDA number must be 20 digits."},
    "invalid_value": {"sw": "Thamani si sahihi.", "en": "Invalid value."},
    "too_long": {"sw": "Maandishi ni marefu mno.", "en": "Text is too long."},
    "duplicate_in_file": {"sw": "Imejirudia kwenye faili (safu {row}).", "en": "Duplicated in the file (row {row})."},
    "duplicate_in_school": {"sw": "Tayari ipo shuleni.", "en": "Already exists in the school."},
    "unknown_class": {"sw": "Darasa/mkondo halijulikani.", "en": "Unknown class/stream."},
    "unknown_student": {"sw": "Mwanafunzi hajulikani.", "en": "Unknown student."},
    "unknown_department": {"sw": "Idara haijulikani.", "en": "Unknown department."},
    "unknown_designation": {"sw": "Cheo hakijulikani.", "en": "Unknown designation."},
    "unknown_role": {"sw": "Jukumu halijulikani.", "en": "Unknown role."},
    "stream_full": {"sw": "Mkondo umejaa.", "en": "The stream is full."},
    "in_use": {"sw": "Bado inatumika.", "en": "Still in use."},
    "outside_year": {"sw": "Tarehe iko nje ya mwaka wa masomo.", "en": "Date is outside the academic year."},
    "bands_gap": {
        "sw": "Madaraja yafunike alama 0 hadi 100 bila pengo wala mwingiliano.",
        "en": "Grade bands must cover 0 to 100 without gaps or overlaps.",
    },
    "divisions_overlap": {"sw": "Viwango vya madaraja ya ufaulu vinaingiliana.", "en": "Division ranges overlap."},
    "scores_exceed_max": {"sw": "Kuna alama zilizozidi kiwango hiki.", "en": "Existing scores exceed this maximum."},
    "results_published": {
        "sw": "Matokeo yameshatolewa; omba marekebisho.",
        "en": "Results are published; request an amendment.",
    },
    "documents_not_valid": {
        "sw": "Nyaraka zote za lazima zihakikiwe kwanza.",
        "en": "Every required document must be validated first.",
    },
    "enrolment_closed": {"sw": "Usajili umefungwa kwa sasa.", "en": "Enrolment is closed at the moment."},
    "outside_term": {"sw": "Tarehe iko nje ya muhula.", "en": "Date is outside the term."},
    "outside_session": {"sw": "Tarehe iko nje ya kipindi cha mitihani.", "en": "Date is outside the exam session."},
    "out_of_range": {"sw": "Alama iwe kati ya 0 na {max}.", "en": "Score must be between 0 and {max}."},
    "no_fee_structure": {
        "sw": "Darasa halina muundo wa ada ulioidhinishwa.",
        "en": "The class has no approved fee structure.",
    },
    "open_bill": {
        "sw": "Ankara tayari ina namba ya malipo inayotumika.",
        "en": "The invoice already has an open control number.",
    },
    "pending_request": {"sw": "Ombi la kubatilisha linasubiri uamuzi.", "en": "A reversal request is already pending."},
    "maker_checker": {"sw": "Aliyeomba hawezi kuidhinisha.", "en": "The requester cannot approve."},
    "too_many_rows": {"sw": "Safu nyingi mno (kikomo {limit}).", "en": "Too many rows (limit {limit})."},
    "invalid_range": {
        "sw": "Tarehe ya mwisho iwe baada ya ya mwanzo (siku 366 zaidi).",
        "en": "End date must follow the start date (366 days at most).",
    },
    "not_school_day": {"sw": "Siku hii si siku ya shule.", "en": "This is not a school day."},
    "no_credit": {
        "sw": "Salio la SMS halitoshi ({needed} zinahitajika, {left} zimebaki).",
        "en": "Not enough SMS credit ({needed} needed, {left} left).",
    },
    "room_full": {"sw": "Chumba kimejaa.", "en": "The room is full."},
    "bus_full": {"sw": "Basi limejaa.", "en": "The bus is full."},
    "no_copies": {"sw": "Nakala zote zimeazimwa.", "en": "All copies are on loan."},
    "too_many_seats": {"sw": "Viti ni zaidi ya uwezo wa ukumbi.", "en": "More seats than the venue holds."},
    "wrong_gender": {
        "sw": "Bweni hili si la jinsia ya mwanafunzi.",
        "en": "This hostel is not for the student's gender.",
    },
    "not_own_child": {"sw": "Huyu si mtoto wako.", "en": "This is not your child."},
    "no_consent": {"sw": "Hakuna ridhaa ya mzazi kwa taarifa za afya.", "en": "No guardian consent for health data."},
    "card_in_use": {"sw": "Kadi hii tayari imesajiliwa.", "en": "This card is already registered."},
    "bad_placeholder": {"sw": "Kishika nafasi {name} hakiruhusiwi.", "en": "Placeholder {name} is not allowed."},
    "sms_too_long": {
        "sw": "Ujumbe ni mrefu mno (SMS {segments}, kikomo 3).",
        "en": "Message too long ({segments} SMS, limit 3).",
    },
}


def message(code: str, lang: str = "sw", **params) -> str:
    entry = MESSAGES.get(code) or MESSAGES["INTERNAL_ERROR"]
    text = entry.get(lang) or entry["en"]
    try:
        return text.format(**params)
    except (KeyError, IndexError):
        return text


def pick_language(accept_language: str | None) -> str:
    """'en' only when the client prefers English; Kiswahili is the default."""
    if not accept_language:
        return "sw"
    first = accept_language.split(",")[0].strip().lower()
    return "en" if first.startswith("en") else "sw"
