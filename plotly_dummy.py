import plotly.express as px
import pandas as pd

def main():
    df = pd.DataFrame({
        "x": [1, 2, 3, 4, 5],
        "y": [10, 11, 12, 13, 14],
        "category": ["A", "B", "A", "B", "A"],
    })

    fig = px.scatter(
        df,
        x="x",
        y="y",
        color="category",
        size="y",
        title="Dummy Plotly Scatter",
    )

    # Anzeige im Browser / Standard-Renderer
    fig.show()

if __name__ == "__main__":
    main()
