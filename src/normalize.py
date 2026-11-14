
import re
import unicodedata


# Normalize general text
def normalize_text(value):
    if not value:
        return ""

    value = str(value).strip().lower()

    # Normalize Unicode characters
    value = unicodedata.normalize("NFKD", value)
    value = "".join(
        char for char in value
        if not unicodedata.combining(char)
    )

    # Remove punctuation
    value = re.sub(r"[^\w\s]", " ", value)

    # Remove extra spaces
    value = re.sub(r"\s+", " ", value).strip()

    return value


# Normalize company/community names
def normalize_company_name(value):
    name = normalize_text(value)

    # Remove common legal/business suffixes
    suffixes = [
        "incorporated",
        "corporation",
        "limited",
        "inc",
        "corp",
        "llc",
        "ltd"
    ]

    words = name.split()

    while words and words[-1] in suffixes:
        words.pop()

    return " ".join(words)


# Normalize street addresses
def normalize_street(value):
    street = normalize_text(value)

    replacements = {
        "street": "st",
        "avenue": "ave",
        "road": "rd",
        "drive": "dr",
        "boulevard": "blvd",
        "lane": "ln",
        "court": "ct",
        "circle": "cir",
        "highway": "hwy",
        "parkway": "pkwy",
        "suite": "ste"
    }

    words = street.split()

    words = [
        replacements.get(word, word)
        for word in words
    ]

    return " ".join(words)


# Normalize city
def normalize_city(value):
    return normalize_text(value)


# Normalize state
def normalize_state(value):
    if not value:
        return ""

    state = normalize_text(value)

    state_mapping = {
        "ohio": "oh",
        "michigan": "mi",
        "indiana": "in",
        "illinois": "il",
        "pennsylvania": "pa"
    }

    return state_mapping.get(state, state)


# Normalize ZIP code
def normalize_zip(value):
    if not value:
        return ""

    # Preserve only digits
    digits = re.sub(r"\D", "", str(value))

    # Use first 5 digits for US ZIP codes
    return digits[:5]
