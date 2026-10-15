# backend/fio_utils.py
"""
Нормализация и разбор русских ФИО.

- Приводит к именительному падежу / стандартному виду (регистр, пробелы).
- Разбирает на фамилию / имя / отчество.
- Определяет пол.
- Опционально склоняет через pytrovich (на будущее для документов).

Используется при вводе full_name, responsible, engineer.
"""
from __future__ import annotations

import re
from functools import lru_cache
from typing import Optional, Dict, Any

try:
    from russiannames.parser import NamesParser
    _HAS_RUSSIANNAMES = True
except ImportError:
    _HAS_RUSSIANNAMES = False
    NamesParser = None  # type: ignore

try:
    from pytrovich.enums import NamePart, Gender, Case
    from pytrovich.maker import PetrovichDeclinationMaker
    from pytrovich.detector import PetrovichGenderDetector
    _HAS_PYTROVICH = True
except ImportError:
    _HAS_PYTROVICH = False


@lru_cache(maxsize=1)
def _get_parser() -> Optional[Any]:
    if not _HAS_RUSSIANNAMES:
        return None
    return NamesParser()


@lru_cache(maxsize=1)
def _get_declinator() -> Optional[Any]:
    if not _HAS_PYTROVICH:
        return None
    return PetrovichDeclinationMaker()


@lru_cache(maxsize=1)
def _get_gender_detector() -> Optional[Any]:
    if not _HAS_PYTROVICH:
        return None
    return PetrovichGenderDetector()


def _basic_normalize(value: str) -> str:
    """Базовая нормализация без внешних библиотек."""
    cleaned = re.sub(r"\s+", " ", value.strip())
    # убираем лишние точки в инициалах, но оставляем дефисы
    parts = []
    for part in cleaned.split():
        if "-" in part:
            sub = [p.capitalize() for p in part.split("-") if p]
            parts.append("-".join(sub))
        else:
            # инициалы вида И.И. или ИИ
            if re.fullmatch(r"[А-ЯЁA-Z]\.?", part.upper()) or re.fullmatch(r"[А-ЯЁA-Z]{1,2}", part.upper()):
                parts.append(part.upper().replace(".", "") + "." if len(part.replace(".", "")) == 1 else part.capitalize())
            else:
                parts.append(part.capitalize())
    return " ".join(parts)


def normalize_fio(value: Optional[str]) -> Optional[str]:
    """
    Главная функция: приводит ФИО к стандартному виду (именительный падеж / Title Case).

    Примеры:
        "иванов иван иванович" → "Иванов Иван Иванович"
        "ПЕТРОВА А.С." → "Петрова А.С." (или более полный разбор)
        "  сидоров   петр  " → "Сидоров Петр"
    """
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    value = value.strip()
    if not value:
        return None

    # Сначала пытаемся через russiannames (он сам нормализует текст)
    parser = _get_parser()
    if parser is not None:
        try:
            parsed = parser.parse(value)
            if parsed.get("parsed") and parsed.get("text"):
                # russiannames возвращает уже в хорошем виде
                return parsed["text"].strip()
        except Exception:
            pass

    # Fallback
    return _basic_normalize(value)


def parse_fio(value: Optional[str]) -> Dict[str, Any]:
    """
    Разбор ФИО + определение пола.

    Возвращает:
    {
        "full": str | None,          # нормализованная строка
        "surname": str | None,       # фамилия (sn)
        "name": str | None,          # имя (fn)
        "patronymic": str | None,    # отчество (mn)
        "gender": str | None,        # 'm' | 'f' | None
        "parsed": bool,
        "format": str | None,        # sfm / sFM / ...
        "raw": str | None,
    }
    """
    result: Dict[str, Any] = {
        "full": None,
        "surname": None,
        "name": None,
        "patronymic": None,
        "gender": None,
        "parsed": False,
        "format": None,
        "raw": value,
    }

    if not value or not isinstance(value, str) or not value.strip():
        return result

    raw = value.strip()
    result["full"] = normalize_fio(raw)

    parser = _get_parser()
    if parser is not None:
        try:
            p = parser.parse(raw)
            result["parsed"] = bool(p.get("parsed"))
            result["format"] = p.get("format")
            result["surname"] = p.get("sn") or p.get("surname")
            result["name"] = p.get("fn") or p.get("name")
            result["patronymic"] = p.get("mn") or p.get("middlename") or p.get("midname")
            # инициалы
            if not result["name"] and p.get("fn_s"):
                result["name"] = p.get("fn_s")
            if not result["patronymic"] and p.get("mn_s"):
                result["patronymic"] = p.get("mn_s")
            g = p.get("gender")
            if g in ("m", "f", "male", "female"):
                result["gender"] = "m" if g.startswith("m") else "f"
            if result["full"] is None and p.get("text"):
                result["full"] = p["text"]
            return result
        except Exception:
            pass

    # Простой fallback-разбор
    parts = (result["full"] or raw).split()
    if len(parts) >= 1:
        result["surname"] = parts[0]
    if len(parts) >= 2:
        result["name"] = parts[1]
    if len(parts) >= 3:
        result["patronymic"] = parts[2]
        # грубый пол по окончанию отчества
        pat = result["patronymic"].lower()
        if pat.endswith(("ич", "ыч", "оглы", "улы")):
            result["gender"] = "m"
        elif pat.endswith(("на", "кызы", "гызы", "уулу")):
            result["gender"] = "f"
    result["parsed"] = len(parts) >= 2
    return result


def decline_fio(
    value: Optional[str],
    case: str = "nominative",
    gender: Optional[str] = None,
) -> Optional[str]:
    """
    Склонение ФИО в нужный падеж (pytrovich).

    case: nominative | genitive | dative | accusative | instrumental | prepositional
    gender: 'm' | 'f' | None (автоопределение)

    Если pytrovich недоступен или ошибка — возвращает normalize_fio(value).
    """
    if not value:
        return value

    normalized = normalize_fio(value)
    if not normalized or not _HAS_PYTROVICH:
        return normalized

    case_map = {
        "nominative": Case.NOMINATIVE,
        "genitive": Case.GENITIVE,
        "dative": Case.DATIVE,
        "accusative": Case.ACCUSATIVE,
        "instrumental": Case.INSTRUMENTAL,
        "prepositional": Case.PREPOSITIONAL,
    }
    target_case = case_map.get(case.lower(), Case.NOMINATIVE)

    # Если уже номинатив — ничего не делаем
    if target_case == Case.NOMINATIVE:
        return normalized

    parsed = parse_fio(normalized)
    g = gender or parsed.get("gender")
    gender_enum = None
    if g == "m":
        gender_enum = Gender.MALE
    elif g == "f":
        gender_enum = Gender.FEMALE

    # Если пол не определён — пробуем detector
    if gender_enum is None and _get_gender_detector() is not None:
        try:
            det = _get_gender_detector()
            detected = det.detect(
                firstname=parsed.get("name"),
                middlename=parsed.get("patronymic"),
                lastname=parsed.get("surname"),
            )
            gender_enum = detected
        except Exception:
            gender_enum = Gender.ANDROGYNOUS

    if gender_enum is None:
        gender_enum = Gender.ANDROGYNOUS

    maker = _get_declinator()
    if maker is None:
        return normalized

    parts = []
    try:
        if parsed.get("surname"):
            parts.append(
                maker.make(NamePart.LASTNAME, gender_enum, target_case, parsed["surname"])
            )
        if parsed.get("name"):
            parts.append(
                maker.make(NamePart.FIRSTNAME, gender_enum, target_case, parsed["name"])
            )
        if parsed.get("patronymic"):
            parts.append(
                maker.make(NamePart.MIDDLENAME, gender_enum, target_case, parsed["patronymic"])
            )
        if parts:
            return " ".join(parts)
    except Exception:
        pass

    return normalized
