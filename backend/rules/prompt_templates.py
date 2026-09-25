"""
Language-Pair Prompt Rules for Context-Aware Translation
Universally applicable, content-agnostic linguistic guidelines.
"""

from __future__ import annotations

TRANSLATION_RULES: dict[str, str] = {
    'Korean-English': """
1. Sentence Structure: Convert Korean's SOV (Subject-Object-Verb) structure to English's SVO (Subject-Verb-Object). Split long, verb-final Korean clauses into clear, concise English sentences, avoiding unnatural clause stacking or excessive subordination. Explicitly supply omitted subjects, objects, and pronouns where evident from context.

2. Honorifics and Formality: Map Korean speech levels to the appropriate English register:
   - 높임말 (formal / honorific) → formal, professional English register
   - 존댓말 (polite) → standard polite, neutral English
   - 반말 (casual / informal) → natural casual English
   Preserve institutional, hierarchical, or social relationships faithfully through tone and vocabulary selection.

3. Punctuation and Clarity: Use standard, clean punctuation. Avoid overusing dashes or abrupt sentence fragments for transitions. When connecting clauses or providing asides, use complete grammatical sentences, semicolons, colons, or commas.

4. Compounds and Terminology: When expressing compound concepts, prefer natural English noun compounds or standard terminology rather than awkward possessive or prepositional chains.

5. Particles and Markers: Korean grammatical markers (은/는, 이/가, 을/를, 에, 에서, etc.) should inform emphasis, topic, and sentence flow naturally without literal translation.

Format the output cleanly with original paragraph and structural breaks preserved.
""",

    'English-Korean': """
1. Sentence Structure: Convert English's SVO structure to Korean's SOV structure. Combine short English clauses into naturally coherent Korean sentences where appropriate, placing predicates at the end of clauses.

2. Honorifics and Formality: Determine the appropriate speech level (존댓말 / 하십시오체 / 해요체 / 반말) based on document context and audience:
   - Business, administrative, technical, or official texts → formal/polite register (하십시오체 / 해요체)
   - Casual or creative texts → appropriate informal register
   Use standard honorific markers and suffixes where contextually required.

3. Particles and Grammatical Markers: Apply appropriate Korean particles (은/는, 이/가, 을/를, 에, 에서, 로/으로, etc.) to maintain grammatical accuracy and smooth syntactic flow.

4. Cultural and Idiomatic Localization: Adapt English idioms, expressions, and technical metaphors to established Korean equivalents, preserving the original intent and precision.

5. Pronoun Handling: In natural Korean, repetitive pronouns (그, 그녀, 그것) are frequently omitted when context is self-evident. Rely on contextual clarity and appropriate verb endings rather than literal pronoun translation.

Format the output in natural Korean with original paragraph structures intact.
""",

    'Japanese-English': """
1. Sentence Structure: Convert Japanese's SOV structure to English's SVO. Transform topic-comment structures (marked by は) into natural English subject-predicate sentences. Reorganize complex, nested sentences into clear, coherent English structures.

2. Formality and Register: Translate Japanese keigo (敬語) into corresponding English registers:
   - 尊敬語 (respectful) & 謙譲語 (humble) → formal, respectful English
   - 丁寧語 (standard polite) → professional, standard English
   - 常体 / タメ口 (plain / casual) → casual English
   Maintain consistent tone and formality throughout the document.

3. Grammatical Markers: Japanese particles (は、が、を、に、で、へ、から、まで、より, etc.) should guide sentence emphasis, subject identification, and structural flow naturally without word-for-word translation.

4. Idiomatic and Cultural Expressions: Translate cultural idioms and domain expressions to natural English equivalents that convey exact meaning and intent.

5. Implicit Elements: Japanese frequently omits subjects and objects when understood from context. Make these elements explicit in English to guarantee clarity and grammatical completeness.

Format the translation cleanly, preserving all original paragraph and list divisions.
""",

    'English-Japanese': """
1. Sentence Structure: Convert English's SVO structure to Japanese's SOV structure. Place predicates at the end of clauses and apply natural topic-comment structures with the appropriate particles.

2. Politeness and Register: Select the appropriate register based on document context:
   - Business, legal, administrative, and technical documents → 丁寧語 (です/ます) or である/だ depending on genre standards
   - Official proclamations or formal specifications → である体 / 敬体 as appropriate
   - Casual documents → appropriate conversational tone

3. Particles: Use Japanese particles (は、が、を、に、で、へ、から、まで、より, etc.) accurately to ensure grammatical correctness and natural flow.

4. Idiomatic Localization: Adapt English idioms, figures of speech, and domain concepts into standard Japanese terminology.

5. Subject and Pronoun Management: Omit repetitive personal pronouns where context is clear, adhering to standard Japanese conventions.

Format in natural Japanese with standard punctuation (、。) and clear paragraph structure.
""",

    'Japanese-Korean': """
1. Syntactic Harmony & Natural Flow: Leverage the syntactic similarity between Japanese and Korean (both SOV, particle-based) to produce fluent, authentic Korean while avoiding unnatural word-for-word calques (e.g., avoid direct transliteration of Japanese phrasing like ~에 있어서 instead of ~에서, or ~할 것을 요한다 instead of ~해야 한다).

2. Terminology & Legal Register:
   - For employment regulations, corporate bylaws, and official manuals, employ standard Korean legal and administrative terminology (e.g., 就業規則 → 취업규칙, 採用 → 채용, 試用期間 → 수습(시용)기간, 服務規律 → 복무규율, 懲戒 → 징계, 解雇 → 해고, 休職 → 휴직).
   - For technical and embedded automotive contexts, employ industry-standard Korean automotive/SW terms (e.g., 車載ECU → 차량용/차재 ECU, 適合 → 적합/캘리브레이션, 適合性 → 적합성, 制御モデル → 제어 모델, ツールチェーン → 툴체인, 工数 → 공수).

3. Honorifics and Sentence Endings:
   - Official regulations, contracts, and company guidelines must use authoritative and objective formal endings (~한다, ~하여야 한다, ~을 원칙으로 한다, ~로 규정한다).
   - Corporate presentations and recruitment decks should use professional and courteous register (하십시오체 / 해요체, e.g., ~합니다, ~바랍니다).

4. Particles & Collocations: Map Japanese particles (は, が, を, に, で, へ, から, まで, より, と) accurately into contextually precise Korean particles (은/는, 이/가, 을/를, 에/에게, 에서, 으로/로, 부터, 까지, 보다, 와/과).

5. Numbering and Formatting: Strictly preserve Japanese numbering styles (第1条, (1), ①, etc.) into Korean equivalents (제1조, (1), ①) without missing or changing numbers.

Format in natural, polished Korean with original paragraph structures intact.
""",

    'German-Korean': """
1. Sentence Structure: Reorganize German compound sentences, passive voice constructions, and subordinate clauses (Nebensätze) into clear, natural Korean SOV sentences.

2. Commercial, Legal, and SLA Terminology:
   - Translate commercial and software maintenance terms into established Korean business standards (e.g., Wartung → 유지보수, Preisliste → 가격표/단가표, Lizenz / Serverlizenz → 라이선스 / 서버 라이선스, Grundsätzliches → 기본 원칙 / 기본 안내 사항, Vertrag → 계약).
   - Preserve monetary values, currencies (EUR, €, USD, KRW), bullet points, and percentage discount tiers without modification.

3. Formality & Register: Use formal, precise business Korean (하십시오체 or formal declarative style ~합니다, ~기준입니다).

4. Bullet Points & Multi-line Texts: Faithfully preserve bullet points, indentation, and multi-line cell formatting.

Format the output in natural Korean with business and technical clarity.
""",

    'Chinese-English': """
1. Sentence Structure: Translate to natural English SVO syntax. Resolve complex, paratactic Chinese clauses into structured, hypotactic English sentences with clear logical conjunctions.

2. Contextual Clarity: Chinese frequently leaves subjects, agents, and temporal aspects implicit. Explicitly represent omitted elements in English for grammatical precision.

3. Measure Words and Classifiers: Chinese measure words (量词) should be naturally absorbed into English noun phrases without awkward literal repetition.

4. Idiomatic Expressions (成语) & Terminology: Translate four-character idioms and classical phrasing into natural English equivalents that capture both literal meaning and communicative nuance.

5. Register and Tone: Maintain the appropriate register:
   - 书面语 (formal written Chinese) → formal, precise English
   - 口语 (colloquial Chinese) → natural, accessible English

6. Aspect and Modal Particles: Chinese aspect markers and modal particles (了、着、过、的、吗、吧、呢, etc.) should inform tense, aspect, and mood naturally in English.

Format cleanly with clear paragraph structure and consistent punctuation.
""",

    'English-Chinese': """
1. Sentence Structure: Adapt English sentences to natural Chinese flow. Reorganize complex relative clauses and passive constructions into active, topic-prominent Chinese expressions where natural.

2. Classifiers and Measure Words: Accurately apply appropriate Chinese measure words (量词) for countable and uncountable nouns.

3. Aspect and Modal Particles: Use particles (了、着、过、的、地、得) accurately to convey aspect, modification, and conditionality.

4. Register and Formality: Match the document's domain:
   - Official, academic, legal, or business texts → formal written Chinese (书面语)
   - Everyday or casual materials → accessible spoken/written Chinese (口语)

5. Idiomatic Adaptation: Employ standard Chinese terminology and appropriate idioms (成语) where they enhance natural fluency without altering meaning.

6. Contextual Economy: Omit redundant pronouns and conjunctions where context is clear, following standard Chinese stylistic practices.

Format in natural Chinese with standard punctuation (。，、；：！？) and paragraph boundaries.
""",
}

GENERIC_RULES: str = """
1. Natural Expression: The translation must read as an authentic, high-quality document originally authored in the target language, avoiding unnatural word-for-word phrasing.

2. Semantic & Intent Fidelity: Faithfully preserve the core meaning, logical progression, nuance, and intent of the source text. Balance grammatical accuracy with natural readability.

3. Cultural & Idiomatic Adaptation: Adapt idioms, figures of speech, and domain expressions to target language equivalents where appropriate. Maintain original meaning when cultural specificity is essential.

4. Syntax & Structural Coherence: Reorganize clauses and sentences to conform to the target language's natural syntax and grammatical conventions for maximum clarity.

5. Register & Tone Fidelity: Faithfully match the register, formality level, and domain tone (e.g., formal, administrative, legal, technical, academic, business, or conversational) of the source document.

6. Terminology Consistency: Ensure consistent and precise translation of specialized terminology, proper nouns, titles, and technical concepts throughout the entire document.

7. Structural & Numbering Integrity: Strictly preserve all original numbering systems (articles, sections, clauses, items, lists). Do not renumber continuous sequences or restart numbering at 1 unless explicitly restarted in the source. Keep each distinct item on its own line.

8. Inline Formatting & Style Tags Preservation:
   - When the input text contains inline style tags such as `<span color="..." size="..." bold="...">...</span>` or `<c color="..." bold="...">...</c>`, you MUST preserve these exact tags wrapped around the corresponding translated words or phrases in the target language.
   - Do NOT delete, alter, or omit any attribute (`color`, `size`, `bold`, `italic`).
   - Ensure the translated terms corresponding to the original highlighted/colored tokens are enclosed inside their respective tags.

Format the translation with appropriate paragraph breaks, typographical conventions, and punctuation for the target language.
"""


def get_rules(source_lang: str = "", target_lang: str = "English") -> str:
    """
    Retrieves language-pair specific rules or falls back to universal generic rules.
    Guarantees document-agnostic, content-agnostic, and language-independent behavior.
    """
    if source_lang and target_lang:
        pair_key = f"{source_lang.strip().title()}-{target_lang.strip().title()}"
        if pair_key in TRANSLATION_RULES:
            return TRANSLATION_RULES[pair_key]

    return GENERIC_RULES

