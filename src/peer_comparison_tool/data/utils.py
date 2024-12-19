import pandas as pd
from sklearn.cluster import DBSCAN
import numpy as np
from typing import List

DEFAULT_LABEL = 'Not cluster member'


def create_valuation_clusters(df: pd.DataFrame, cols: List[str], eps: float=0.25, min_samples: int=4):
    df_clusters = df.dropna(subset=['ticker'] + cols, how='any').copy()
    df_clusters = apply_dbscan(df_clusters, cols, eps, min_samples)
    # add in any missing data companies with the default cluster:
    df = pd.merge(df, df_clusters[['ticker', 'label']], on=['ticker'], how='left')
    df['cluster_membership'] = df['label'].fillna(value=DEFAULT_LABEL)

    return df[['ticker', 'cluster_membership']]


def apply_dbscan(df: pd.DataFrame, cols: List[str], eps: float = 0.25, min_samples: int = 4):
    """
    Apply DBSCAN clustering to a DataFrame and return the DataFrame with cluster labels and colors.

    Parameters:
    - df: DataFrame containing 'x' and 'y' columns for clustering.
    - eps: The maximum distance between two points for them to be considered as in the same neighborhood.
    - min_samples: The minimum number of points required to form a dense region.

    Returns:
    - df: DataFrame with 'cluster' labels and 'color' for each point.
    """
    dbscan = DBSCAN(eps=eps, min_samples=min_samples)
    array_list = []
    for col in cols:
        x_normalised = (df[col].values - df[col].min()) / (df[col].max() - df[col].min() + 0.0001)
        array_list.append(x_normalised)
    # TODO if none/one rows then dont go into dbscan.fit_predict
    if len(df.index) <= 1:
        df['label'] = DEFAULT_LABEL
        return df
    df['cluster'] = dbscan.fit_predict(X=np.column_stack(array_list))
    # set red as outlier:
    df['label'] = df['cluster'].apply(lambda row: 'Cluster member' if row != -1 else DEFAULT_LABEL)
    return df
