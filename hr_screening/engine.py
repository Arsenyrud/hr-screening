"""Объяснимое сопоставление подтвержденных критериев вакансии."""
from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict

ALIASES = {
    "python": ["python", "питон", "пайтон"],
    "postgresql": ["postgresql", "postgres", "постгрес", "постгресql"],
    "docker": ["docker", "докер"],
    "fastapi": ["fastapi", "fast api"],
    "django": ["django", "джанго"],
    "flask": ["flask"],
    "sql": ["sql", "эс кью эль"],
    "javascript": ["javascript", "java script", "js", "джаваскрипт"],
    "typescript": ["typescript", "type script", "ts"],
    "react": ["react", "react.js", "reactjs", "реакт"],
    "vue": ["vue", "vue.js", "vuejs"],
    "angular": ["angular"],
    "html": ["html", "html5"],
    "css": ["css", "css3"],
    "git": ["git", "гит"],
    "linux": ["linux", "линукс"],
    "kubernetes": ["kubernetes", "k8s", "кубернетес"],
    "ci/cd": ["ci/cd", "ci cd", "cicd", "continuous integration"],
    "rest": ["rest", "rest api", "restful"],
    "redis": ["redis", "редис"],
    "kafka": ["kafka", "кафка"],
    "rabbitmq": ["rabbitmq", "rabbit mq"],
    "pytest": ["pytest", "py.test"],
    "unit testing": ["unit testing", "unit tests", "юнит-тесты", "модульные тесты", "модульное тестирование"],
    "pandas": ["pandas", "пандас"],
    "numpy": ["numpy", "нампай"],
    "power bi": ["power bi", "powerbi", "пауэр би"],
    "excel": ["excel", "эксель"],
    "tableau": ["tableau", "табло"],
    "statistics": ["statistics", "статистика", "статистики", "статистический анализ", "статистике"],
    "a/b testing": ["a/b testing", "a/b tests", "a/b-тесты", "a/b-тестирование", "аб-тесты", "a/b тесты", "ab testing"],
    "airflow": ["airflow", "эйрфлоу"],
    "etl": ["etl", "elt"],
    "spark": ["spark", "pyspark", "спарк"],
    "java": ["java", "джава"],
    "spring": ["spring", "spring boot"],
    "c++": ["c++", "си++"],
    "c#": ["c#", "c sharp", "csharp"],
    ".net": [".net", "dotnet"],
    "node.js": ["node.js", "nodejs", "node js"],
    "figma": ["figma", "фигма"],
    "accessibility": ["accessibility", "wcag", "доступность интерфейсов", "веб-доступность"],
    "english": ["english", "английский", "английского"],
    "machine learning": ["machine learning", "машинное обучение", "ml"],
}
BASELINE_ID = hashlib.sha256(json.dumps({"version": "evidence-screening-v3", "aliases": ALIASES, "weights": [75, 15, 10]}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
INSTRUCTION = re.compile(r"ignore (?:all |any |previous |the )*(?:instructions|prompts)|system\s*prompt|developer\s*message|(?:set|give|assign|return|output).{0,20}(?:score|rank|100)|(?:score|rank)\s*[:=]\s*100|игнориру[йя].{0,35}(?:инструкц|правил|задан)|(?:поставь|назначь|верни|установи|выставь).{0,25}(?:балл|100|оценк)|системн.{0,10}(?:промпт|инструкц)|(?:execute|запусти|выполни).{0,20}(?:shell|curl|команд|touch|rm\s)|<\|(?:system|assistant)|\[INST\]", re.I)
PROTECTED = re.compile(r"\b(?:пол|мужчин[а-я]*|женщин[а-я]*|мужской|женский|возраст|родил[а-я]*|дата рождения|национальность|гражданство|религия|вероисповедание|семейное положение|беремен[а-я]*|инвалидность|этнич[а-я]*|gender|sex|male|female|men|women|age|date of birth|nationality|citizenship|religion|marital status|pregnan\w*|disability|ethnicity)\b", re.I)
PERSONAL_FRAGMENT = re.compile(r"\b(?:(?:возраст|age|мне)\s*[:=\u2014-]?\s*\d{1,3}\s*(?:лет|год[а]?|years?(?:\s+old)?)?|(?:пол|gender|sex)\s*[:=\u2014-]?\s*(?:мужской|женский|male|female|non[- ]?binary|не\s+указан[а-я]*|unknown)|мужчин[а-я]*|женщин[а-я]*|мужской|женский|male|female)\b", re.I)
NEGATION = re.compile(r"(?:\bне\s+(?:работал[аи]?|знаю|знал[аи]?|использовал[аи]?|владею|имею|применял[аи]?|освоил[аи]?|изучал[аи]?|знаком[а]?|умею)|\bнет\s+(?:опыта|знаний|практики)|\bбез\s+(?:опыта|знаний|практики)|\b(?:no|without)\s+(?:experience|knowledge)|\b(?:do not|don't|never)\s+(?:use|used|know|work|worked)|не\s+подтвержден[а-я]*)", re.I)


def _normalize(value):
    return re.sub(r"\s+", " ", str(value).lower().replace("ё", "е")).strip()


def _canonical(skill):
    value = _normalize(skill)
    for canonical, aliases in ALIASES.items():
        if value in aliases:
            return canonical
    return value


def _requirements(values):
    return list(dict.fromkeys(_canonical(value) for value in (values or []) if str(value).strip() and not PROTECTED.search(str(value))))


def _pattern(skill):
    aliases = ALIASES.get(skill, [skill])
    return re.compile(r"(?<![\w])(?:" + "|".join(re.escape(a) for a in sorted(aliases, key=len, reverse=True)) + r")(?![\w])", re.I)


def _vacancy_text_requirements(description):
    sections = list(re.finditer(r"(?:^|(?<=[.!?;\n]))\s*(обязательно|требования|требуется|желательно|будет плюсом|обязанности|условия|задачи|мы предлагаем|о компании)\b\s*:?\s*", description, re.I | re.M))
    must, nice = [], []
    experience_text = [description[:sections[0].start()] if sections else description]
    for index, section in enumerate(sections):
        heading = section.group(1).lower()
        if heading not in {"обязательно", "требования", "требуется", "желательно", "будет плюсом"}:
            continue
        body = description[section.end():sections[index + 1].start() if index + 1 < len(sections) else len(description)]
        target = nice if heading in {"желательно", "будет плюсом"} else must
        if target is must:
            experience_text.append(body)
        segments, _ = _safe_segments(body)
        for segment in segments:
            for clause in segment.split(";"):
                if re.search(r"\b(?:или|либо)\b|не\s+(?:требуется|обязател[а-я]*|нуж[а-я]*)", clause, re.I):
                    continue
                found = [(m.start(), skill) for skill in ALIASES for m in _pattern(skill).finditer(_normalize(clause))]
                for _, skill in sorted(found):
                    if skill not in target:
                        target.append(skill)
    safe, _ = _safe_segments("\n".join(experience_text))
    years = {float(m.group(1).replace(",", ".")) for segment in safe for m in re.finditer(r"\bопыт(?:\s+работы)?\s+от\s*(\d{1,2}(?:[.,]\d+)?)\s*(?:лет|год[а]?)\b", segment, re.I)}
    minimum = next(iter(years)) if len(years) == 1 and next(iter(years)) <= 60 else 0.0
    return must, [skill for skill in nice if skill not in must], minimum


def _sentences(text):
    return [match.group().strip() for match in re.finditer(r"[^\n.!?]+(?:\.(?!\s|$)[^\n.!?]+)*(?:[.!?]+|$)", text) if match.group().strip()]


def _safe_segments(text):
    safe, suspicious = [], False
    for line in text.splitlines():
        if INSTRUCTION.search(line):
            suspicious = True
            continue
        for sentence in _sentences(line):
            for fragment in PERSONAL_FRAGMENT.split(sentence):
                clauses = re.split(r"[,;](?!\d)", fragment) if PROTECTED.search(fragment) else [fragment]
                for clause in clauses:
                    clause = clause.strip(" ,;:()")
                    if clause and not PROTECTED.search(clause) and not re.search(r"^(?:фио|имя|фамилия|контакты|e-?mail|name)\s*:", clause, re.I) and not re.search(r"[\w.+-]+@[\w.-]+", clause):
                        safe.append(clause)
    return safe, suspicious


def _negated(sentence, match):
    normalized = _normalize(sentence)
    start = max(normalized.rfind(";", 0, match.start()), normalized.rfind("но ", 0, match.start()), normalized.rfind("but ", 0, match.start()))
    following = [p for p in [normalized.find(";", match.end()), normalized.find("но ", match.end()), normalized.find("but ", match.end())] if p >= 0]
    end = min(following) if following else len(normalized)
    clause = normalized[max(0, start):end]
    local_position = match.start() - max(0, start)
    comma_start = clause.rfind(",", 0, local_position)
    comma_end = clause.find(",", local_position)
    local = clause[comma_start + 1:comma_end if comma_end >= 0 else len(clause)]
    if NEGATION.search(local):
        return True
    affirmative = re.search(r"\b(?:знаю|использую|работал[аи]?|владею|применял[аи]?|освоил[аи]?|знаком[а]?|used|know|worked)\b", local, re.I)
    return comma_start >= 0 and not affirmative and bool(NEGATION.search(clause[:comma_start]))


def _experience(segments):
    claims, evidence = [], []
    number = r"(\d{1,2}(?:[.,]\d+)?)"
    patterns = [
        re.compile(r"(?:общий\s+)?(?:опыт(?:\s+работы)?|стаж)(?:\s+в\s+[а-яa-z -]{1,30})?\s*[:\u2014\u2013-]?\s*(?:более\s+|около\s+)?" + number + r"\s*(?:лет|год[а]?|years?)", re.I),
        re.compile(number + r"\s*(?:лет|год[а]?|years?)\s+(?:общего\s+|of\s+)?(?:опыта(?:\s+работы)?|стажа|experience)", re.I),
        re.compile(r"(?:total\s+)?(?:work\s+)?experience\s*[:\u2014\u2013-]?\s*" + number + r"\s*years?", re.I),
        re.compile(r"(?<!не )(?<!not )(?<!never )\b(?:работал[аи]?|worked)\s+[^,;.!?\d]{1,60}?\s*" + number + r"\s*(?:лет|год[а]?|years?)\b", re.I),
    ]
    for sentence in segments:
        for pattern in patterns:
            for match in pattern.finditer(sentence):
                if re.search(r"\b(?:не|not|never)\s+$", sentence[:match.start()], re.I):
                    continue
                years = float(match.group(1).replace(",", "."))
                if 0 <= years <= 60:
                    claims.append(years)
                    evidence.append(sentence)
    if claims:
        unique = sorted(set(claims))
        if len(unique) > 1 and unique[-1] - unique[0] > 1:
            return None, ["Противоречивые сведения об общем стаже; требуется уточнение."], evidence
        return min(claims), [], evidence
    intervals = []
    for sentence in segments:
        if not re.search(r"компани[яи]|работ[а-я]*|должност[а-я]*|разработчик|аналитик|инженер|employment|developer|engineer", sentence, re.I):
            continue
        for match in re.finditer(r"\b((?:19|20)\d{2})\s*[\u2014\u2013-]\s*((?:19|20)\d{2})\b", sentence):
            start, end = map(int, match.groups())
            if 1950 <= start < end <= 2100:
                intervals.append((start, end))
                evidence.append(sentence)
    if intervals:
        merged = []
        for start, end in sorted(intervals):
            if merged and start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((start, end))
        return float(sum(end - start for start, end in merged)), ["Стаж приблизительно рассчитан по закрытым годовым интервалам; месяцы не указаны."], evidence
    return None, [], []


def _duplicates(resumes):
    groups = []
    for field, reason in (("email", "Совпадает email; возможный дубль личности, записи не объединены."), ("text", "Совпадает нормализованный текст резюме; записи не объединены.")):
        buckets = defaultdict(list)
        for resume in resumes:
            value = _normalize(resume.get(field, ""))
            if value:
                key = hashlib.sha256(value.encode()).hexdigest() if field == "text" else value
                buckets[key].append(str(resume["id"]))
        for ids in buckets.values():
            if len(ids) > 1:
                groups.append({"candidate_ids": sorted(set(ids)), "reason": reason})
    return groups


def screen(vacancy: dict, resumes: list[dict], *, model_path: str | None = None) -> dict:
    """Возвращает сравнение и точные источники для проверки рекрутером."""
    must = _requirements(vacancy.get("must_have"))
    nice = [s for s in _requirements(vacancy.get("nice_to_have")) if s not in must]
    min_years = max(0.0, float(vacancy.get("min_years", 0) or 0))
    explicit = bool(vacancy.get("must_have") or vacancy.get("nice_to_have"))
    description = str(vacancy.get("description", "")).strip()
    if not explicit or not min_years:
        extracted_must, extracted_nice, extracted_years = _vacancy_text_requirements(description)
        if not explicit:
            must, nice = extracted_must, extracted_nice
        if not min_years:
            min_years = extracted_years
    top_k = max(0, min(1000, int(vacancy.get("top_k", 10) or 0)))
    normalized = {"id": str(vacancy.get("id", "")), "title": str(vacancy.get("title", "")).strip(), "description": str(vacancy.get("description", "")).strip(), "must_have": must, "nice_to_have": nice, "min_years": min_years, "top_k": top_k}
    for key in ("tenant_id", "project_id"):
        if key in vacancy:
            normalized[key] = vacancy[key]
    allowed = [r for r in resumes if all(not vacancy.get(key) or r.get(key) == vacancy[key] for key in ("tenant_id", "project_id"))]
    warnings = ["Балл отражает подтвержденные критерии вакансии; решение и проверка источников остаются за рекрутером."]
    if not explicit:
        warnings.append("Проверьте извлеченные требования: учтены только известные навыки в явных разделах; неизвестные и неоднозначные формулировки не добавлены.")
    if any(PROTECTED.search(str(s)) for s in (vacancy.get("must_have") or []) + (vacancy.get("nice_to_have") or [])):
        warnings.append("Критерии по защищенным персональным признакам исключены из сравнения.")
    if len(allowed) != len(resumes):
        warnings.append("Резюме вне tenant/project вакансии исключены из сравнения.")
    patterns = {skill: _pattern(skill) for skill in must + nice}
    candidates, semantic_documents = [], []
    for record in allowed:
        candidate_id = str(record["id"])
        text = str(record.get("text", ""))
        segments, suspicious = _safe_segments(text)
        matched, evidence, concerns, questions = [], [], [], []
        for skill, pattern in patterns.items():
            positives, negatives = [], []
            for sentence in segments:
                if re.search(r"(?:друг[а-я]*|соседн[а-я]*)\s+команд[а-я]*", sentence, re.I):
                    continue
                normalized_sentence = _normalize(sentence)
                for match in pattern.finditer(normalized_sentence):
                    (negatives if _negated(normalized_sentence, match) else positives).append(sentence)
            if positives and negatives:
                concerns.append(f"Противоречие по навыку {skill}: есть подтверждение и отрицание; не засчитан.")
                questions.append(f"Уточните практический опыт с {skill}: в резюме противоречивые утверждения.")
                for quote in list(dict.fromkeys(positives + negatives))[:2]:
                    evidence.append({"skill": skill, "quote": quote, "source": f"resume:{candidate_id}", "status": "conflicting"})
            elif positives:
                matched.append(skill)
                evidence.append({"skill": skill, "quote": positives[0], "source": f"resume:{candidate_id}", "status": "stated"})
            elif negatives:
                concerns.append(f"В резюме явно отрицается опыт с {skill}.")
                evidence.append({"skill": skill, "quote": negatives[0], "source": f"resume:{candidate_id}", "status": "negated"})
        missing = [skill for skill in must if skill not in matched]
        questions.extend(f"Расскажите о практическом использовании {skill}; подтверждение обязательного навыка отсутствует." for skill in missing if not any(skill in q for q in questions))
        years, experience_concerns, experience_quotes = _experience(segments)
        concerns.extend(experience_concerns)
        if years is None:
            concerns.append("Продолжительность профессионального опыта не подтверждена.")
            questions.append("Каков ваш общий профессиональный стаж? Уточните даты и пересекающиеся периоды работы.")
        elif min_years and years < min_years:
            concerns.append(f"Заявленный стаж {years:g} лет меньше требования {min_years:g} лет.")
            questions.append("Есть ли дополнительный релевантный опыт, не отраженный в резюме?")
        for quote in list(dict.fromkeys(experience_quotes))[:2]:
            evidence.append({"skill": "experience", "quote": quote, "source": f"resume:{candidate_id}", "status": "stated" if years is not None else "conflicting"})
        if suspicious:
            concerns.append("Найдены инструкции внутри резюме; они исключены из анализа и не исполняются.")
        professional = [f"Приведите пример реальной задачи с {skill}: каков был ваш личный вклад и как вы оценивали результат?" for skill in must if skill in matched and not any(skill in question for question in questions)][:2]
        if not questions and not professional:
            professional = ["Опишите профессиональную задачу: каков был ваш личный вклад и как вы оценивали результат?"]
        questions = list(dict.fromkeys(questions))[:8 - len(professional)] + professional
        must_ratio = sum(s in matched for s in must) / len(must) if must else 0.0
        nice_ratio = sum(s in matched for s in nice) / len(nice) if nice else 0.0
        experience_ratio = min(years / min_years, 1.0) if years is not None and min_years else 0.0
        must_weight, nice_weight, experience_weight = 75, 15 if nice else 0, 10 if min_years else 0
        must_weight += 15 - nice_weight + 10 - experience_weight
        if not must:
            if nice:
                nice_weight += must_weight
            elif min_years:
                experience_weight += must_weight
            else:
                warnings.append("Вакансия не содержит измеримых критериев; сравнение требует уточнения требований.")
            must_weight = 0
        score = must_weight * must_ratio + nice_weight * nice_ratio + experience_weight * experience_ratio
        summary = f"Подтверждено обязательных навыков: {len(must) - len(missing)}/{len(must)}; желательных: {sum(s in matched for s in nice)}/{len(nice)}. "
        summary += f"Стаж по резюме, лет: {years:g}." if years is not None else "Стаж неизвестен."
        candidates.append({"candidate_id": candidate_id, "name": str(record.get("name", "")), "score": round(score, 2), "matched_skills": matched, "missing_skills": missing, "experience_years": years, "evidence": evidence, "concerns": concerns, "questions": questions, "summary": summary, "semantic_score": None, "confidence": round((sum(s in matched for s in must + nice) + int(years is not None)) / (len(must + nice) + 1), 3), "score_components": {"must": round(must_weight * must_ratio, 2), "nice": round(nice_weight * nice_ratio, 2), "experience": round(experience_weight * experience_ratio, 2), "semantic_bonus": 0.0}})
        semantic_documents.append(" ".join(segments))
    model = {"mode": "baseline", "name": "evidence-screening-v3", "sha256": BASELINE_ID, "scoring": "must 75%, nice 15%, experience 10%; absent criteria redistribute to skills", "protected_attributes_used": False}
    if model_path and candidates:
        try:
            from .semantic import get_encoder
            encoder = get_encoder(str(model_path))
            query_segments, _ = _safe_segments(normalized["title"] + ". " + normalized["description"])
            query = " ".join(query_segments + must + nice)
            scores, clipping = encoder.compare(query, semantic_documents)
            for candidate, similarity in zip(candidates, scores):
                coverage = (len(must) - len(candidate["missing_skills"])) / len(must) if must else bool(candidate["matched_skills"])
                bonus = min(5.0 * similarity * coverage, 100 - candidate["score"])
                candidate["semantic_score"] = similarity
                candidate["score"] = round(candidate["score"] + bonus, 2)
                candidate["score_components"]["semantic_bonus"] = round(bonus, 2)
            model = dict(encoder.metadata) | {"protected_attributes_used": False, "semantic_bonus_max": 5}
            if clipping["truncated_documents"] or clipping["query_truncated"]:
                warnings.append("Достигнут лимит семантических фрагментов: 32 × 128 токенов; полный текст доступен для проверки рекрутером.")
        except (ImportError, OSError, ValueError, RuntimeError) as exc:
            warnings.append(f"Локальная семантическая модель недоступна ({type(exc).__name__}); использован базовый режим без загрузки из сети.")
    candidates.sort(key=lambda c: (-c["score"], c["candidate_id"]))
    return {"normalized_vacancy": normalized, "candidates": candidates[:top_k], "duplicates": _duplicates(allowed), "warnings": list(dict.fromkeys(warnings)), "model": model}
