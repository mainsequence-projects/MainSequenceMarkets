from __future__ import annotations

import numpy as np
import pandas as pd
from numpy.linalg import LinAlgError
from numpy.typing import NDArray
from tqdm import tqdm


def rolling_pca_betas(X: pd.DataFrame, window: int, n_components: int = 5) -> np.ndarray:
    """Perform rolling PCA and return normalized principal component weights."""

    from sklearn.decomposition import PCA

    betas = []
    for i in tqdm(range(window, len(X)), desc="Performing rolling PCA"):
        x_window = X.iloc[i - window : i]
        pca = PCA(n_components=n_components)
        pca.fit(x_window)
        eigenvectors = pca.components_.T
        betas.append(eigenvectors / np.sum(np.abs(eigenvectors), axis=0))

    return np.array(betas)


def rolling_lasso_regression(
    y: pd.Series,
    X: pd.DataFrame,
    window: int,
    alpha: float = 1.0,
    **_: object,
) -> list[pd.DataFrame]:
    """Perform rolling Lasso regression and return coefficient frames."""

    from sklearn.linear_model import Lasso, LinearRegression

    betas = []
    if alpha == 0:
        lasso = LinearRegression(fit_intercept=False, positive=True)
    else:
        lasso = Lasso(alpha=alpha, fit_intercept=False, positive=True)

    for i in tqdm(range(window, len(y)), desc="Building Lasso regression"):
        null_xs = X.isnull().sum()
        null_xs = null_xs[null_xs > 0]
        symbols_to_zero = None
        x_window = X.iloc[i - window : i]
        if null_xs.shape[0] > 0:
            symbols_to_zero = null_xs.index.to_list()
            x_window = x_window[
                [column for column in x_window.columns if column not in symbols_to_zero]
            ]
        y_window = y.iloc[i - window : i]

        lasso.fit(x_window, y_window)

        round_betas = pd.DataFrame(
            lasso.coef_.reshape(1, -1),
            columns=x_window.columns,
            index=[x_window.index[-1]],
        )
        if symbols_to_zero is not None:
            round_betas.loc[:, symbols_to_zero] = 0.0
        betas.append(round_betas)

    return betas


def rolling_elastic_net(
    y: pd.Series,
    X: pd.DataFrame,
    window: int,
    alpha: float = 1.0,
    l1_ratio: float = 0.5,
) -> np.ndarray:
    """Perform rolling Elastic Net regression and return coefficients."""

    from sklearn.linear_model import ElasticNet

    betas = []
    enet = ElasticNet(alpha=alpha, l1_ratio=l1_ratio, fit_intercept=False)

    for i in tqdm(range(window, len(y)), desc="Building rolling regression"):
        x_window = X.iloc[i - window : i]
        y_window = y.iloc[i - window : i]
        enet.fit(x_window, y_window)
        betas.append(enet.coef_)

    return np.array(betas)


def do_single_regression(
    xx: NDArray,
    XTX_inv_list: list,
    rolling_window: int,
    col_name: str,
    tmp_y: NDArray,
    XTX_inv_diag: list,
) -> pd.DataFrame:
    """Perform one rolling OLS regression column for replicator experiments."""

    mean_y = tmp_y.mean(axis=1).reshape(-1, 1)
    sst = np.sum((tmp_y - mean_y) ** 2, axis=1)
    precompute_y = {"SST": sst, "mean_y": mean_y}

    results = []
    for i in tqdm(range(xx.shape[0]), desc=f"building regression {col_name}"):
        xxx = xx[i].reshape(rolling_window, xx[i].shape[-1])
        tmpy = tmp_y[i]
        x_mult = XTX_inv_list[i] @ xxx.T
        coefs = x_mult @ tmpy.T
        y_estimates = (xxx @ coefs.reshape(-1, 1)).ravel()
        residuals = tmpy - y_estimates
        ssr = np.sum((y_estimates - precompute_y["mean_y"][i]) ** 2)
        rsquared = ssr / precompute_y["SST"][i]
        residuals_var = np.sum(residuals**2) / (rolling_window - coefs.shape[0] + 1)
        standard_errors = np.sqrt(XTX_inv_diag[i] * residuals_var)
        ts = coefs / standard_errors
        results.append(
            {
                "beta": coefs[0],
                "intercept": coefs[1],
                "rsquared": rsquared,
                "t_intercept": ts[1],
                "t_beta": ts[0],
            }
        )

    return pd.concat([pd.DataFrame(results)], keys=[col_name], axis=1)


def build_rolling_regression_from_df(
    x: NDArray,
    y: NDArray,
    rolling_window: int,
    column_names: list,
    threads: int = 5,
) -> pd.DataFrame:
    """Build rolling OLS regressions for multiple variables in parallel."""

    from joblib import Parallel, delayed

    xx_base = np.concatenate([x.reshape(-1, 1), np.ones((x.shape[0], 1))], axis=1)
    xx = np.lib.stride_tricks.sliding_window_view(
        xx_base, (rolling_window, xx_base.shape[1])
    )

    XTX_inv_list = []
    XTX_inv_diag = []
    for i in tqdm(range(xx.shape[0]), desc="building x precomputes"):
        xxx = xx[i].reshape(rolling_window, xx[i].shape[-1])
        try:
            xtx_inv = np.linalg.inv(xxx.T @ xxx)
            XTX_inv_list.append(xtx_inv)
            XTX_inv_diag.append(np.diag(xtx_inv))
        except LinAlgError:
            XTX_inv_list.append(XTX_inv_list[-1] * np.nan)
            XTX_inv_diag.append(XTX_inv_diag[-1] * np.nan)

    y_views = {
        i: np.lib.stride_tricks.sliding_window_view(y[:, i], (rolling_window,))
        for i in range(y.shape[1])
    }

    reg_results = Parallel(n_jobs=threads, prefer="threads")(
        delayed(do_single_regression)(
            xx=xx,
            tmp_y=tmp_y,
            XTX_inv_list=XTX_inv_list,
            rolling_window=rolling_window,
            XTX_inv_diag=XTX_inv_diag,
            col_name=column_names[y_col],
        )
        for y_col, tmp_y in y_views.items()
    )

    results = pd.concat(reg_results, axis=1)
    results.columns = results.columns.swaplevel()
    return results
