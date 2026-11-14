
import requests
import json
import re
import time

from bs4 import BeautifulSoup
from urllib.parse import urljoin

BASE_URL = "https://analyst-assessment-production.up.railway.app"

COMMUNITIES_URL = f"{BASE_URL}/communities"

OUTPUT_FILE = "data/scraped_locations.json"

EXPECTED_COMMUNITY_COUNT = 34

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}

session = requests.Session()
session.headers.update(HEADERS)


# --------------------------------------------------
# 1. Get website HTML
# --------------------------------------------------

def get_soup(url):

    response = session.get(url, timeout=30)

    response.raise_for_status()

    return BeautifulSoup(response.text, "html.parser")


# --------------------------------------------------
# 2. Extract all community URLs from all pages
# --------------------------------------------------

def extract_community_urls():

    community_urls = []
    visited_pages = set()

    current_url = COMMUNITIES_URL

    while current_url:

        if current_url in visited_pages:
            print("Already visited:", current_url)
            break

        visited_pages.add(current_url)

        print("\nReading listing page:", current_url)

        soup = get_soup(current_url)

        # Find all community detail links
        for link in soup.find_all("a", href=True):

            href = link["href"]

            if re.search(r"/communities/[^/?#]+/?$", href):

                full_url = urljoin(current_url, href)

                if full_url not in community_urls:
                    community_urls.append(full_url)

        # Find the Next pagination link
        next_url = None

        for link in soup.find_all("a", href=True):

            link_text = link.get_text(
                " ",
                strip=True
            ).lower()

            rel = link.get("rel", [])

            if isinstance(rel, str):
                rel = rel.split()

            if (
                link_text.startswith("next")
                or "next" in rel
            ):

                next_url = urljoin(
                    current_url,
                    link["href"]
                )

                break

        current_url = next_url

    print("\nTotal listing pages visited:", len(visited_pages))

    print("Total unique community URLs:", len(community_urls))

    if len(community_urls) != EXPECTED_COMMUNITY_COUNT:

        print(
            "WARNING: Expected",
            EXPECTED_COMMUNITY_COUNT,
            "communities but found",
            len(community_urls)
        )

    return community_urls


# --------------------------------------------------
# 3. Extract text sections using page labels
# --------------------------------------------------

def get_page_lines(soup):

    return [
        line.strip()
        for line in soup.get_text(
            separator="\n",
            strip=True
        ).splitlines()
        if line.strip()
    ]


def extract_section(lines, start_label, end_labels):

    start_index = None

    for i, line in enumerate(lines):

        if line.lower().strip(":") == start_label.lower():

            start_index = i + 1
            break

    if start_index is None:
        return []

    result = []

    for line in lines[start_index:]:

        normalized = line.lower().strip(":")

        if normalized in [
            label.lower() for label in end_labels
        ]:
            break

        result.append(line)

    return result


# --------------------------------------------------
# 4. Extract address
# --------------------------------------------------

'''def extract_address(lines):

    address_lines = extract_section(
        lines,
        "Address",
        [
            "Care Offerings",
            "Administrator",
            "Phone"
        ]
    )

    address_text = " ".join(address_lines)

    # Match:
    # 7420 Sycamore Ridge Dr Miamisburg, OH 45342

    pattern = (
        r"^(.*?)\s+"
        r"([^,]+),\s*"
        r"([A-Z]{2})\s+"
        r"(\d{5}(?:-\d{4})?)$"
    )

    match = re.search(
        pattern,
        address_text,
        re.IGNORECASE
    )

    if match:

        return {
            "street": match.group(1).strip(),
            "city": match.group(2).strip(),
            "state": match.group(3).upper(),
            "zip": match.group(4)
        }

    return {
        "street": None,
        "city": None,
        "state": None,
        "zip": None
    }'''

def extract_address(lines):

    address_lines = extract_section(
        lines,
        "Address",
        [
            "Care Offerings",
            "Administrator",
            "Phone"
        ]
    )

    if not address_lines:
        return {
            "street": None,
            "city": None,
            "state": None,
            "zip": None
        }

    # The final address line should contain:
    # Miamisburg, OH 45342

    last_line = address_lines[-1]

    pattern = (
        r"^(.+?),\s*"
        r"([A-Z]{2})\s+"
        r"(\d{5}(?:-\d{4})?)$"
    )

    match = re.match(
        pattern,
        last_line.strip(),
        re.IGNORECASE
    )

    if not match:
        return {
            "street": None,
            "city": None,
            "state": None,
            "zip": None
        }

    return {
        "street": " ".join(address_lines[:-1]).strip() or None,
        "city": match.group(1).strip(),
        "state": match.group(2).upper(),
        "zip": match.group(3)
    }



# --------------------------------------------------
# 5. Extract care offerings
# --------------------------------------------------

def extract_care_offerings(lines):

    care_lines = extract_section(
        lines,
        "Care Offerings",
        [
            "Administrator",
            "Phone",
            "Back to all communities"
        ]
    )

    care_text = " ".join(care_lines)

    # Known care offering labels observed on the site.
    known_offerings = [
        "Short-Term Rehabilitation & Nursing",
        "Assisted Living",
        "Memory Support",
        "Rehabilitation",
        "Skilled Nursing"
    ]

    found = []

    for offering in known_offerings:

        pattern = re.escape(offering)

        if re.search(
            pattern,
            care_text,
            re.IGNORECASE
        ):

            found.append(offering)

    return found


# --------------------------------------------------
# 6. Scrape individual community
# --------------------------------------------------

def scrape_community_details(url):

    soup = get_soup(url)

    lines = get_page_lines(soup)

    # Community name
    heading = soup.find("h1")

    name = (
        heading.get_text(" ", strip=True)
        if heading
        else None
    )

    # Address
    address = extract_address(lines)

    # Care offerings
    care_offerings = extract_care_offerings(lines)

    record = {
        "name": name,
        **address,
        "care_offerings": care_offerings,
        "source_url": url
    }

    return record


# --------------------------------------------------
# 7. Scrape all communities
# --------------------------------------------------

def scrape_all_communities():

    urls = extract_community_urls()

    results = []

    failed_urls = []

    for index, url in enumerate(urls, start=1):

        print(
            f"\nScraping {index}/{len(urls)}: {url}"
        )

        try:

            record = scrape_community_details(url)

            if not record["name"]:
                raise ValueError("Community name missing")

            results.append(record)

            print("Name:", record["name"])

            print("Address:", record["city"], record["state"])

            print("Care:", record["care_offerings"])

        except Exception as error:

            print("ERROR:", error)

            failed_urls.append({
                "url": url,
                "error": str(error)
            })

        time.sleep(0.3)

    return results, failed_urls


# --------------------------------------------------
# 8. Save JSON
# --------------------------------------------------

if __name__ == "__main__":

    import os

    os.makedirs("data", exist_ok=True)

    communities, failed = scrape_all_communities()

    with open(
        OUTPUT_FILE,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            communities,
            file,
            indent=4,
            ensure_ascii=False
        )

    with open(
        "data/scraping_errors.json",
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            failed,
            file,
            indent=4
        )

    print("\n========== SCRAPING SUMMARY ==========")

    print("Total communities:", len(communities))

    print("Failed pages:", len(failed))

    print("Expected communities:", EXPECTED_COMMUNITY_COUNT)

    print("Output:", OUTPUT_FILE)

    print("Errors: data/scraping_errors.json")

    if len(communities) == EXPECTED_COMMUNITY_COUNT and not failed:

        print("\nSUCCESS: All 34 communities scraped.")

    else:

        print("\nWARNING: Scraping is incomplete. Check errors.")
