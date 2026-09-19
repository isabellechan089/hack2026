import networkx as nx
import matplotlib.pyplot as plt

from openalex import get_paper, get_citing_papers
from crossref import get_retraction_status


# --------------------------------
# 1. Get the seed paper
# --------------------------------

doi = "10.1177/1758835920922055"

paper = get_paper(doi)

print("Title:", paper["display_name"])
print("Year:", paper["publication_year"])
print("Citations:", paper["cited_by_count"])


# --------------------------------
# 2. Check retraction status
# --------------------------------

status = get_retraction_status(paper["doi"])

print("Retraction status:", status)


# --------------------------------
# 3. Create graph
# --------------------------------

G = nx.DiGraph()


# Add seed paper
G.add_node(
    paper["id"],
    title=paper["display_name"],
    year=paper["publication_year"],
    doi=paper["doi"],
    distance=0,
    retraction_status=status
)


# --------------------------------
# 4. First-hop citations
# --------------------------------

first_hop = get_citing_papers(
    paper["id"],
    limit=10
)

for citing_paper in first_hop:

    G.add_node(
        citing_paper["id"],
        title=citing_paper["display_name"],
        year=citing_paper["publication_year"],
        doi=citing_paper["doi"],
        distance=1,
        retraction_status="unknown"
    )

    G.add_edge(
        citing_paper["id"],
        paper["id"]
    )


# --------------------------------
# 5. Second-hop citations
# --------------------------------

for first_hop_paper in first_hop:

    second_hop = get_citing_papers(
        first_hop_paper["id"],
        limit=5
    )

    for second_hop_paper in second_hop:

        G.add_node(
            second_hop_paper["id"],
            title=second_hop_paper["display_name"],
            year=second_hop_paper["publication_year"],
            doi=second_hop_paper["doi"],
            distance=2,
            retraction_status="unknown"
        )

        G.add_edge(
            second_hop_paper["id"],
            first_hop_paper["id"]
        )


# --------------------------------
# 6. Print graph information
# --------------------------------

print("\nGRAPH SUMMARY")
print("Number of nodes:", G.number_of_nodes())
print("Number of edges:", G.number_of_edges())


print("\nNODES:")

for node_id, data in G.nodes(data=True):

    print(data["title"])
    print("  Year:", data["year"])
    print("  Distance:", data["distance"])
    print("  Retraction status:", data["retraction_status"])


# --------------------------------
# 7. Draw graph
# --------------------------------

pos = nx.spring_layout(G)

plt.figure(figsize=(12, 8))


# Determine node colors
node_colors = []

for node_id in G.nodes:

    node_status = G.nodes[node_id]["retraction_status"]

    if node_status == "retracted":
        node_colors.append("red")

    elif node_status == "not_retracted":
        node_colors.append("lightblue")

    else:
        node_colors.append("gray")


# Give nodes simple numeric labels
labels = {}

for i, node_id in enumerate(G.nodes):
    labels[node_id] = str(i)


# Draw nodes and edges
nx.draw(
    G,
    pos,
    with_labels=False,
    node_size=700,
    node_color=node_colors,
    arrows=True
)


# Draw labels
nx.draw_networkx_labels(
    G,
    pos,
    labels=labels,
    font_size=10
)


plt.show()
