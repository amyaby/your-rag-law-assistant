"""
test_questions.py — 15 ground-truth questions for jury demo
Each question has expected facts + correct law/article to score retrieval vs generation.
Languages: Arabic (formal), Darija (Arabic script), Darija (Arabizi), French, English

LANGUAGE NOTE ON expected_facts (a real bug that was fixed here)
---------------------------------------------------------------
`evaluate.py` grades facts with a plain lowercase substring test:

    hits = sum(1 for f in q["expected_facts"] if f.lower() in answer.lower())

The system instruction in `app/core/llm.py` tells the model to answer in
"simple Moroccan Darija or plain standard Arabic" REGARDLESS of the language the
question was asked in. So a French or English question gets an Arabic answer,
and English/French `expected_facts` could never match:

    Q7  (fr)  expected ["vol","nuit","emprisonnement"] -> answer is Arabic -> 0/3
    Q14 (en)  expected ["fraud","imprisonment","fine"] -> answer is Arabic -> 0/3

Both were scored 0% while retrieval and the citations were CORRECT — the grader
was measuring the wrong thing, and the number was meaningless.

`expected_facts` entries may therefore be a LIST of language variants for one
concept, e.g. `[["السرقة", "vol"], ["الحبس", "imprisonment"]]`. The scorer
credits a fact when ANY variant appears, and the denominator stays the number
of CONCEPTS — so adding a translation can never dilute the score. The `lang`
field still records the language of the QUESTION, which is what the
multilingual tests are probing.
"""

QUESTIONS = [
    {
        "id": 1,
        "question": "ما هي العقوبة الأساسية للسرقة؟",
        "lang": "ar",
        "expected_facts": ["الحبس من سنة إلى خمس سنوات", "غرامة"],
        "expected_law_contains": "الجنائي",
        "expected_articles": ["505", "506", "508", "509"],
        "category": "السرقة"
    },
    {
        "id": 2,
        "question": "ما هي عقوبة السرقة ليلا؟",
        "lang": "ar",
        "expected_facts": ["ظرف مشدد", "ليل", "الحبس"],
        "expected_law_contains": "الجنائي",
        "expected_articles": ["509", "510"],
        "category": "السرقة - ظرف مشدد"
    },
    {
        "id": 3,
        "question": "ما هي عقوبة السرقة مع استعمال السلاح؟",
        "lang": "ar",
        "expected_facts": ["سلاح", "تشديد", "عقوبة"],
        "expected_law_contains": "الجنائي",
        "expected_articles": ["510", "511"],
        "category": "السرقة - سلاح"
    },
    {
        "id": 4,
        "question": "ما هي عقوبة القتل العمد؟",
        "lang": "ar",
        "expected_facts": ["السجن المؤبد", "الإعدام", "قتل عمد"],
        "expected_law_contains": "الجنائي",
        "expected_articles": ["392", "393"],
        "category": "القتل"
    },
    {
        "id": 5,
        "question": "شنو العقوبة ديال النصب والاحتيال؟",
        "lang": "darija-ar",
        "expected_facts": ["الحبس", "النصب", "الاحتيال"],
        "expected_law_contains": "الجنائي",
        "expected_articles": ["540", "541", "542"],
        "category": "النصب"
    },
    {
        "id": 6,
        "question": "kifach nt3amel m3a chikat bla rasid?",
        "lang": "arabizi",
        "expected_facts": ["شيك", "بدون رصيد", "عقوبة"],
        "expected_law_contains": "الجنائي",
        "expected_articles": ["543", "544", "316"], # chèque = 543 Code pénal + 316 Code commerce
        "category": "الشيك بدون رصيد - Arabizi test"
    },
    {
        "id": 7,
        "question": "Quelle est la peine pour le vol de nuit?",
        "lang": "fr",
        "expected_facts": [["السرقة", "vol"], ["الليل", "nuit"],
                           ["الحبس", "emprisonnement"]],
        "expected_law_contains": "pénal",
        "expected_articles": ["509", "510"],
        "category": "Vol - Français"
    },
    {
        "id": 8,
        "question": "ما هي عقوبة التهديد؟",
        "lang": "ar",
        "expected_facts": ["التهديد", "الحبس", "غرامة"],
        "expected_law_contains": "الجنائي",
        "expected_articles": ["425", "426", "427"],
        "category": "التهديد"
    },
    {
        "id": 9,
        "question": "واش نقدر نصور شي واحد بلا علمو؟ شنو عقوبتها؟",
        "lang": "darija-ar",
        "expected_facts": [["تسجيل", "تصوير", "صورة", "التقاط"],
                           ["سرية", "خاصة", "علانية", "سري"]],
        "expected_articles": ["447-1", "303", "483"],
        "category": "الخصوصية - تصوير",
        # ------------------------------------------------------------------
        # KNOWN CORPUS GAP, not a retrieval or generation defect.
        #
        # A full-text search of the 5 254 ingested chunks for
        #   content ~ 'تصوير|صورة' AND content ~ 'رضا|إذن|علم|علانية'
        # returns 12 rows and NONE of them is an article about photographing a
        # person without consent. The closest is art. 447-1, which penalises
        # capturing/recording/disseminating information "صادرة بشكل خاص أو سري"
        # by any means including information systems — adjacent, not on point.
        #
        # The correct legal answer would cite Law 09.08 (personal data) and/or
        # the press law on image rights, neither of which is indexed at
        # article granularity in the current corpus.
        #
        # So the right system behaviour is to REFUSE to invent an article, and
        # that is what it does: "المعلومات القانونية المتاحة لا تتضمن فصلاً يحدد
        # العقوبات المتعلقة بتصوير الأشخاص بدون علمهم". `evaluate.py` scores a
        # `known_gap` question by looking for an honest refusal instead of
        # counting it as a failure, because a confident invented citation here
        # would be the far worse outcome.
        "known_gap": True,
        "refusal_markers": ["لا تتوفر", "لا تتضمن", "لا يوجد", "غير متوفر",
                            "متوفرين", "لم نعثر"],

    },
    {
        "id": 10,
        "question": "ما هي عقوبة السب والقذف؟",
        "lang": "ar",
        "expected_facts": ["السب", "القذف", "غرامة", "الحبس"],
        "expected_law_contains": "الجنائي",
        "expected_articles": ["442", "443", "444", "445"],
        "category": "السب والقذف"
    },
    {
        "id": 11,
        "question": "شنو هي عقوبة الخيانة الزوجية؟",
        "lang": "darija-ar",
        "expected_facts": ["الخيانة الزوجية", "الحبس"],
        "expected_law_contains": "الجنائي",
        "expected_articles": ["491", "492"],
        "category": "الخيانة الزوجية"
    },
    {
        "id": 12,
        "question": "ما هي عقوبة الإجهاض؟",
        "lang": "ar",
        "expected_facts": ["الإجهاض", "الحبس", "طبيب"],
        "expected_law_contains": "الجنائي",
        "expected_articles": ["449", "450", "451"],
        "category": "الإجهاض"
    },
    {
        "id": 13,
        "question": "ما هي شروط حضانة الأطفال بعد الطلاق؟",
        "lang": "ar",
        "expected_facts": ["حضانة", "الأم", "الأب", "مصلحة المحضون"],
        "expected_law_contains": "الأسرة",
        "expected_articles": ["171", "172", "173"],
        "category": "مدونة الأسرة - حضانة"
    },
    {
        "id": 14,
        "question": "What is the penalty for fraud in Morocco?",
        "lang": "en",
        "expected_facts": [["النصب", "fraud"], ["الاحتيال", "fraud"],
                           ["الحبس", "imprisonnement", "imprisonment"],
                           ["غرامة", "fine"]],
        "expected_law_contains": "penal",
        "expected_articles": ["540", "542"],
        "category": "Fraud - English"
    },
    {
        "id": 15,
        "question": "ما هي عقوبة تزوير الوثائق؟",
        "lang": "ar",
        "expected_facts": ["التزوير", "وثيقة", "السجن"],
        "expected_law_contains": "الجنائي",
        "expected_articles": ["352", "353", "354"],
        "category": "التزوير"
    },
]
