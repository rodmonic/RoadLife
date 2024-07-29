from datetime import date
from os import walk

import fiona
import geopandas as gpd
import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st
from geopy.distance import geodesic


def get_kml(file_path: str) -> gpd.GeoDataFrame:
    # set up fiona support
    fiona.drvsupport.supported_drivers["libkml"] = "rw"
    fiona.drvsupport.supported_drivers["LIBKML"] = "rw"

    gdf_road = gpd.read_file(file_path, driver="libkml")
    gdf_road.set_crs(epsg=4326, inplace=True)

    return gdf_road


# Locations
road_path = "./static/"
postcode_filepath = "./static/postcodes.csv"

# post code validation regex
postcode_regex = r"^([A-Z][A-HJ-Y]?\d[A-Z\d]? ?\d[A-Z]{2}|GIR ?0A{2})$"

# list all roads that have been downloaded
roads = next(walk(road_path), (None, None, []))[2]
exclude_files = ["UK.kml", "postcodes.csv"]
roads = [road.split(".")[0] for road in roads if road not in exclude_files]
roads.sort()

postcodes_df = pd.read_csv(postcode_filepath)

# get UK KML outline
gdf_uk = get_kml("./static/UK.kml")


def prepare_df(df: pd.DataFrame) -> pd.DataFrame:
    # remove space to make sure we can search
    df["postcode"] = df["postcode"].str.replace(" ", "")

    # Access the last row
    last_row = df.iloc[[-1]]
    # Append the last row to the DataFrame
    df = pd.concat([df, last_row], ignore_index=True)
    # replace last rows date with today's date
    df.at[df.index[-1], "from"] = date.today()
    df["from"] = pd.to_datetime(df["from"])
    # calcauted difference between all the dates
    df["days"] = (df["from"].shift(-1) - df["from"]).dt.days
    # drop final row
    df = df.drop(df.index[-1])

    # get location of postcodes
    df = pd.merge(df, postcodes_df, on="postcode", how="left")

    # drop columns
    columns_to_drop = ["postcode", "Unnamed: 0"]
    df = df.drop(columns=columns_to_drop, axis=1)

    return df


def add_points(df: pd.DataFrame) -> gpd.GeoDataFrame:
    from shapely import Point

    geometry = [Point(xy) for xy in zip(df["longitude"], df["latitude"])]

    gdf_locations = gpd.GeoDataFrame(df, geometry=geometry)

    gdf_locations.set_crs(epsg=4326, inplace=True)

    return gdf_locations


# Function to compute geodesic distance from a point to all lines
def min_geodesic_distance_to_lines(point, gdf_road: gpd.GeoDataFrame):
    point_coords = (point.y, point.x)  # (latitude, longitude)
    min_dist = float("inf")
    for line in gdf_road.geometry:
        for segment in list(line.coords):
            segment_coords = (segment[1], segment[0])  # (latitude, longitude)
            dist = geodesic(point_coords, segment_coords).meters
            if dist < min_dist:
                min_dist = dist
    return min_dist


def get_stats(
    gdf_locations: gpd.GeoDataFrame, factor: int
) -> tuple[float, float, float]:
    average = (
        gdf_locations["total_day_distance"].sum() / gdf_locations["days"].sum() / factor
    )
    min = gdf_locations["min_geodesic_distance"].min() / factor
    max = gdf_locations["min_geodesic_distance"].max() / factor

    return average, min, max


def get_map(gdf_locations: gpd.GeoDataFrame, gdf_road: gpd.GeoDataFrame) -> plt.figure:
    # Create a plot
    fig, ax = plt.subplots(figsize=(4, 4))

    plt.xlim([-8.3, 2])
    plt.ylim([50, 61])

    # Plot Uk boundary
    gdf_uk.plot(ax=ax, color="grey", linewidth=0.1, label="Lines")

    # Plot the points
    gdf_locations.plot(ax=ax, color="red", marker="x", markersize=0.1, label="Points")

    # Plot the lines
    gdf_road.plot(ax=ax, color="blue", linewidth=0.5, label="Lines")

    ax.set_xticks([])
    ax.set_yticks([])

    return fig


def get_chart(df: pd.DataFrame, selected_road: str) -> plt.figure:
    # Plot the DataFrame
    fig, ax = plt.subplots(figsize=(6, 3))

    df.plot(ax=ax, marker=None, linestyle="-", color="b")

    # Add titles and labels
    plt.xlabel("Date", fontsize=6)
    plt.ylabel(f"kms from {selected_road}", fontsize=6)

    # Customize the x-axis and y-axis
    plt.xticks(rotation=45, fontsize=6)
    plt.yticks(fontsize=6)

    # Add gridlines
    plt.grid(color="grey", linestyle="--", linewidth=0.5)

    ax.get_legend().remove()

    # Show the plot
    plt.tight_layout()

    return fig


def get_line_chart_df(gdf: gpd.GeoDataFrame, factor: int) -> pd.DataFrame:
    columns_to_drop = [
        "longitude",
        "latitude",
        "days",
        "geometry",
        "total_day_distance",
    ]
    df = gdf.drop(columns=columns_to_drop)

    # Access the last row
    last_row = df.iloc[[-1]]
    # Append the last row to the DataFrame
    df = pd.concat([df, last_row], ignore_index=True)
    # replace last rows date with today's date
    df.at[df.index[-1], "from"] = date.today()

    df["from"] = pd.to_datetime(df["from"])

    df = df.reset_index(drop=True).set_index("from")
    # Create a complete date range from the start to the end of the DataFrame's dates
    full_date_range = pd.date_range(start=df.index.min(), end=df.index.max())

    # Reindex the DataFrame to include the full date range
    df = df.reindex(full_date_range)

    # forward fill
    df["min_geodesic_distance"] = df["min_geodesic_distance"].fillna(method="ffill")
    df["distance"] = df["min_geodesic_distance"] / factor

    df = df.drop(columns=["min_geodesic_distance"])

    return df


def prepare_gdf(df: pd.DataFrame, selected_road: str) -> gpd.GeoDataFrame:
    gdf_locations = add_points(df)
    road_file_path = f"./static/{selected_road}.kml"
    gdf_road = get_kml(road_file_path)
    gdf_locations["min_geodesic_distance"] = gdf_locations["geometry"].apply(
        min_geodesic_distance_to_lines, gdf_road=gdf_road
    )
    gdf_locations["total_day_distance"] = (
        gdf_locations["min_geodesic_distance"] * gdf_locations["days"]
    )

    return gdf_road, gdf_locations


def road_life():
    st.set_page_config(
        page_title="Road Life Checker", page_icon=":motorway:", layout="wide"
    )

    df = pd.DataFrame(columns=["postcode", "from"])

    config = {
        "postcode": st.column_config.TextColumn(
            validate=postcode_regex, width="small", required=True
        ),
        "from": st.column_config.DateColumn(
            format="DD/MM/YYYY", width="small", required=True
        ),
    }

    st.sidebar.write("Please select a british road to compare against")
    selected_road = st.sidebar.selectbox(
        options=roads, label=":car:", label_visibility="collapsed"
    )

    selected_road_human_readable = selected_road.replace("_", " ")

    st.sidebar.markdown(
        "Please fill out the table below with postcodes, capitalised including spaces, and the date you started living at that postcode"
    )

    df = st.sidebar.data_editor(
        data=df,
        column_config=config,
        num_rows="dynamic",
        hide_index=True,
        use_container_width=True,
    )

    st.sidebar.write("Then click 'Submit'")
    submitted = st.sidebar.button("Submit")

    st.write("Please use the sidebar to the left to enter where you've lived and what road you're interested in checking")

    if submitted:
        # do some preparation to the dataframes

        if not df["from"].is_unique:
            st.info("please check your dates are unique.")
            return

        if not df["from"].is_monotonic_increasing:
            st.info("Please check your dates are in chronalogical order.")
            return

        if df.isnull().values.any():
            st.info(
                "Please delete any empty rows and make sure all columns are filled out."
            )
            return

        df = prepare_df(df)

        gdf_road, gdf_locations = prepare_gdf(df, selected_road)
        line_chart_df = get_line_chart_df(gdf_locations, 1000)

        # get the data
        average_km, min_km, max_km = get_stats(gdf_locations, 1000)
        map_chart = get_map(gdf_locations=gdf_locations, gdf_road=gdf_road)
        line_chart = get_chart(line_chart_df, selected_road_human_readable)

        st.markdown(f"""## Distance lived from {selected_road_human_readable}""")

        st.write("\n" * 3)  # Adjust the number of newlines for more or less space

        # first column
        chart_row = st.columns([0.3, 0.7])
        chart_row[0].pyplot(map_chart, use_container_width=True)

        # second column
        chart_row[1].write("\n")
        metric_row = chart_row[1].columns([1, 1, 1])

        metric_row[0].metric(
            f"Average distance lived from {selected_road_human_readable}",
            f"{average_km: .2f} km",
        )
        metric_row[1].metric(
            f"Maximum distance lived from {selected_road_human_readable}",
            f"{max_km: .2f} km",
        )
        metric_row[2].metric(
            f"Minimum distance lived from {selected_road_human_readable}",
            f"{min_km: .2f} km",
        )

        chart_row[1].write("\n" * 10)
        chart_row[1].pyplot(line_chart, use_container_width=True)


def main():
    road_life()


if __name__ == "__main__":
    main()
