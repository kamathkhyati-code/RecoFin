"""Render the compiled graph to a PNG for visual inspection."""

from recon_platform.graph.build import build_graph

graph = build_graph()
png_bytes = graph.get_graph().draw_mermaid_png()

with open("docs/graph/recon_graph.png", "wb") as f:
    f.write(png_bytes)

print("Graph PNG written to docs/graph/recon_graph.png")
