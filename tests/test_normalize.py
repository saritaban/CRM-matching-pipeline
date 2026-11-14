
from src.normalize import (
    normalize_text,
    normalize_company_name,
    normalize_street,
    normalize_city,
    normalize_state,
    normalize_zip
)


def test_normalization():

    print("Company name:")
    print(normalize_company_name(
        "Bellhaven Senior Living, Inc."
    ))

    print("\nStreet:")
    print(normalize_street(
        "7420 Sycamore Ridge Drive"
    ))

    print("\nCity:")
    print(normalize_city("MIAMISBURG"))

    print("\nState:")
    print(normalize_state("Ohio"))

    print("\nZIP:")
    print(normalize_zip("45342-1234"))


if __name__ == "__main__":
    test_normalization()
