"""Normalise Bangla text before TTS so numbers are read as words, not digit by digit."""

import re
import unicodedata

_BN_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")

# Bengali Unicode range is 0x0980–0x09FF. A handful of characters inside that
# range (e.g. the Visarga ঃ) are common in Sanskrit but never used as script
# markers, so we exclude them when classifying a string.
_BN_SCRIPT_RANGES = ((0x0980, 0x09FF),)


def is_bangla_script(text: str) -> bool:
    """Return True when the majority of letter characters in *text* are Bengali."""
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return False
    bangla = 0
    for ch in letters:
        cp = ord(ch)
        if any(lo <= cp <= hi for lo, hi in _BN_SCRIPT_RANGES):
            bangla += 1
    return bangla / len(letters) >= 0.5


def is_latin_script(text: str) -> bool:
    """Return True when the majority of letter characters in *text* are Latin."""
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return False
    latin = sum(1 for ch in letters if "LATIN" in unicodedata.name(ch, ""))
    return latin / len(letters) >= 0.5

_BELOW_100 = (
    "শূন্য এক দুই তিন চার পাঁচ ছয় সাত আট নয় দশ "
    "এগারো বারো তেরো চৌদ্দ পনেরো ষোলো সতেরো আঠারো উনিশ "
    "বিশ একুশ বাইশ তেইশ চব্বিশ পঁচিশ ছাব্বিশ সাতাশ আটাশ ঊনত্রিশ "
    "ত্রিশ একত্রিশ বত্রিশ তেত্রিশ চৌত্রিশ পঁয়ত্রিশ ছত্রিশ সাঁইত্রিশ আটত্রিশ ঊনচল্লিশ "
    "চল্লিশ একচল্লিশ বিয়াল্লিশ তেতাল্লিশ চুয়াল্লিশ পঁয়তাল্লিশ ছেচল্লিশ সাতচল্লিশ আটচল্লিশ ঊনপঞ্চাশ "
    "পঞ্চাশ একান্ন বাহান্ন তিপ্পান্ন চুয়ান্ন পঞ্চান্ন ছাপ্পান্ন সাতান্ন আটান্ন ঊনষাট "
    "ষাট একষট্টি বাষট্টি তেষট্টি চৌষট্টি পঁয়ষট্টি ছেষট্টি সাতষট্টি আটষট্টি ঊনসত্তর "
    "সত্তর একাত্তর বাহাত্তর তিয়াত্তর চুয়াত্তর পঁচাত্তর ছিয়াত্তর সাতাত্তর আটাত্তর ঊনআশি "
    "আশি একাশি বিরাশি তিরাশি চুরাশি পঁচাশি ছিয়াশি সাতাশি অষ্টাশি ঊননব্বই "
    "নব্বই একানব্বই বিরানব্বই তিরানব্বই চুরানব্বই পঁচানব্বই ছিয়ানব্বই সাতানব্বই আটানব্বই নিরানব্বই"
).split()

assert len(_BELOW_100) == 100


def _below_1000(n: int) -> str:
    hundreds, rest = divmod(n, 100)
    parts = []
    if hundreds:
        parts.append(f"{_BELOW_100[hundreds]}শো")
    if rest:
        parts.append(_BELOW_100[rest])
    return " ".join(parts)


def number_to_bangla_words(n: int) -> str:
    if n == 0:
        return _BELOW_100[0]
    if 1100 <= n <= 9999 and n % 1000 >= 100:
        # Spoken style: 1550 -> পনেরোশো পঞ্চাশ, 2550 -> পঁচিশশো পঞ্চাশ, 1120 -> এগারোশো বিশ
        hundreds, rest = divmod(n, 100)
        head = _BELOW_100[hundreds]
        if hundreds <= 19 or rest == 0:
            head += "শো"
        return f"{head} {_BELOW_100[rest]}" if rest else head
    parts = []
    for unit, name in ((10_000_000, "কোটি"), (100_000, "লাখ"), (1_000, "হাজার")):
        count, n = divmod(n, unit)
        if count:
            parts.append(f"{number_to_bangla_words(count)} {name}")
    if n:
        parts.append(_below_1000(n))
    return " ".join(parts)


_NUMBER_RE = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{2,3})+|\d+)(?:\.(\d+))?(?![\w])")


def _replace(match: re.Match) -> str:
    whole = match.group(1).replace(",", "")
    # Long digit strings (phone numbers, IDs) stay digit-by-digit.
    if len(whole) > 9:
        return match.group(0)
    words = number_to_bangla_words(int(whole))
    if match.group(2):
        fraction = " ".join(_BELOW_100[int(d)] for d in match.group(2))
        words = f"{words} দশমিক {fraction}"
    return words


def normalize_bangla_for_tts(text: str) -> str:
    """Convert Bangla/ASCII digits to spoken Bangla words (১৫৫০ -> পনেরোশো পঞ্চাশ)."""
    text = text.translate(_BN_DIGITS)
    text = text.replace("৳", " টাকা ")
    text = re.sub(r"(\d)\s*%", r"\1 শতাংশ", text)
    text = _NUMBER_RE.sub(_replace, text)
    return re.sub(r"[ \t]{2,}", " ", text).strip()
