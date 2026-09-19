import requests


def get_paper(doi):
    url = f"https://api.openalex.org/works/https://doi.org/{doi}"

    response = requests.get(url)
    response.raise_for_status()

    return response.json()


def get_citing_papers(openalex_id, limit=10):
    short_id = openalex_id.split("/")[-1]

    url = "https://api.openalex.org/works"

    params = {
        "filter": f"cites:{short_id}",
        "per-page": limit
    }

    response = requests.get(url, params=params)
    response.raise_for_status()

    data = response.json()

    return data["results"]
