"""
PHI masking applied to every sample value BEFORE it is sent to an LLM.

Principle: the model needs the SHAPE of the data (is it YYYYMMDD? DD/MM/YYYY?
a code like '1'/'2'/'9'?) to understand a field, but never the real value.
So we keep format and length, and hide content.

  'SEAN'             -> 'S***'          (name)
  '+353848542679'    -> '+###########79' (phone)
  '19600110'         -> '########'      (date: format kept, value hidden)
  '10/01/1960'       -> '##/##/####'
  '400001'           -> '40##01'        (identifier: partial, still linkable)
  '87 GREEN LN'      -> '## G***'       (address)
  'H91 Y658'         -> 'H91 ****'      (Eircode: routing key only)

Short codes (M/F, 1/2/9, OP/ED, LOINC, ICD-10) are NOT masked: they are not
identifying and the agent needs them to infer code systems.
"""
import re
from collections import Counter

NAME_HINTS = re.compile(r"(^|[_.\-])(NM|NAME|FST|LST|FIRST|LAST|GIVEN|FAMILY)([_.\-]|$)|PID-5", re.I)
ADDR_HINTS = re.compile(r"ADR|ADDR|STREET|LINE", re.I)
POST_HINTS = re.compile(r"PST|POST|EIRCODE|ZIP", re.I)

PHONE = re.compile(r"^\+?\d[\d\s\-]{8,}$")
DATE_LIKE = re.compile(r"^(\d{8}|\d{12,14}|\d{4}-\d{2}-\d{2}(T[\d:]+)?|\d{2}/\d{2}/\d{4})$")
ID_LIKE = re.compile(r"^[A-Z]{0,4}-?\d{5,}$")

stats: Counter = Counter()


def mask_value(field: str, value):
    if value is None:
        return None
    s = str(value)
    if not s.strip():
        return s
    if NAME_HINTS.search(field):
        stats["name"] += 1
        return "^".join(p[:1] + "***" if p else p for p in s.split("^"))
    if POST_HINTS.search(field):
        stats["postal_code"] += 1
        return s[:3] + " ****"
    if ADDR_HINTS.search(field):
        stats["address"] += 1
        parts = s.split(" ", 1)
        return re.sub(r"\d", "#", parts[0]) + (" " + parts[1][:1] + "***" if len(parts) > 1 else "")
    if DATE_LIKE.match(s):  # check dates first: a 14-digit timestamp is not a phone
        stats["date"] += 1
        return re.sub(r"\d", "#", s)
    if PHONE.match(s):
        stats["phone"] += 1
        return s[0] + re.sub(r"\d", "#", s[1:-2]) + s[-2:]
    head = s.split("^")[0]
    if ID_LIKE.match(head):
        stats["identifier"] += 1
        return s.replace(head, _mask_id(head), 1)
    return s


def _mask_id(value: str) -> str:
    """Keep letters/punctuation and the first+last 2 digits: MBR-007919 -> MBR-00##19."""
    digit_pos = [i for i, c in enumerate(value) if c.isdigit()]
    hide = set(digit_pos[2:-2])
    return "".join("#" if i in hide else c for i, c in enumerate(value))


def summary() -> dict:
    return dict(stats)
