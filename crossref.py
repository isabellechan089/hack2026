import requests


def get_crossref_data(doi):
    clean_doi = doi.replace("https://doi.org/", "")

    url = f"https://api.crossref.org/works/{clean_doi}"

    response = requests.get(url)
    response.raise_for_status()

    data = response.json()

    return data["message"]


def get_retraction_status(doi):
    if doi is None:
        return "unknown"

    clean_doi = doi.replace("https://doi.org/", "")

    url = "https://api.crossref.org/works"

    params = {
        "filter": f"updates:{clean_doi}"
    }

    try:
        response = requests.get(url, params=params)
        response.raise_for_status()

        data = response.json()
        results = data["message"]["items"]

        for item in results:
            updates = item.get("update-to", [])

            for update in updates:
                if (
                    update.get("DOI", "").lower() == clean_doi.lower()
                    and update.get("type", "").lower() == "retraction"
                ):
                    return "retracted"

        return "not_retracted"

    except requests.RequestException:
        return "unknown"
